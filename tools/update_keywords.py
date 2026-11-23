#!/usr/bin/env python3
"""Refresh Nginx command names from an unpacked official release (Python 3.9+).

This reads source files; it does not compile or execute Nginx. All shipped
modules and platform branches are included. Parameters and prefix groups are
curated separately in src/keywords.json. Previously highlighted command names
remain available in the compatibility group when absent from a newer release.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
GROUPS = (
    "structural", "directives", "legacy", "parameters",
    "variable_prefixes", "named_location_prefixes",
)
EXPECTED_ARRAYS = {
    "ngx_core_commands", "ngx_conf_commands", "ngx_events_commands",
    "ngx_http_commands", "ngx_http_core_commands", "ngx_http_proxy_commands",
    "ngx_mail_commands", "ngx_stream_commands", "ngx_stream_core_commands",
}
ARRAY_START = re.compile(
    r"\bngx_command_t\s+(?P<name>[A-Za-z_]\w*)\s*\[\s*\]\s*=\s*\{"
)
COMMAND_NAME = re.compile(r'\s*ngx_string\s*\(\s*"([a-z][a-z0-9_]*)"\s*\)\s*,')
TOKEN = re.compile(r"^[a-z][a-z0-9_]*$")
# Match string/character literals before comments, so strings such as URLs and
# escaped quote characters are retained exactly while comments are discarded.
C_LITERAL_OR_COMMENT = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*',
    re.DOTALL,
)


def strip_comments(text):
    def replace(match):
        value = match.group(0)
        if value.startswith(("/*", "//")):
            return "".join("\n" if ch == "\n" else " " for ch in value)
        return value
    return C_LITERAL_OR_COMMENT.sub(replace, text)


def mask_literals(text):
    """Hide string contents when searching for C declarations."""
    return C_LITERAL_OR_COMMENT.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group(0)),
        text,
    )


def closing_brace(text, start):
    """Find the end of an initializer without counting braces in literals."""
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("unterminated command-array initializer")


def extract_array(body, label):
    """Read only each command struct's first field, never unrelated strings."""
    # Keep entries from every platform/feature branch, irrespective of the host.
    body = re.sub(r"^\s*#[^\n]*(?:\\\n[^\n]*)*", "", body, flags=re.MULTILINE)
    names = set()
    index = 0
    saw_sentinel = False
    while index < len(body):
        if body[index].isspace() or body[index] == ",":
            index += 1
            continue
        sentinel = re.match(r"ngx_null_command\b", body[index:])
        if sentinel:
            saw_sentinel = True
            index += sentinel.end()
            continue
        if body[index] != "{" or saw_sentinel:
            raise ValueError("unsupported command initializer in " + label)
        end = closing_brace(body, index)
        name = COMMAND_NAME.match(body[index + 1:end])
        if name is None:
            raise ValueError("unsupported command-name field in " + label)
        names.add(name.group(1))
        index = end + 1
    if not saw_sentinel:
        raise ValueError("missing ngx_null_command sentinel in " + label)
    return names


def extract_commands(source_dir, version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("version must have the form 1.31.9")
    header = source_dir / "src/core/nginx.h"
    text = header.read_text(encoding="utf-8")
    match = re.search(r'^#define\s+NGINX_VERSION\s+"([^"]+)"', text, re.MULTILINE)
    if match is None or match.group(1) != version:
        raise ValueError("--version does not match src/core/nginx.h")
    names = set()
    arrays = set()
    sources = {}
    for path in sorted((source_dir / "src").rglob("*.c")):
        original = path.read_bytes()
        clean = strip_comments(original.decode("utf-8"))
        matches = list(ARRAY_START.finditer(mask_literals(clean)))
        if not matches:
            continue
        relative = path.relative_to(source_dir).as_posix()
        sources[relative] = hashlib.sha256(original).hexdigest()
        for match in matches:
            name = match.group("name")
            if name in arrays:
                raise ValueError("duplicate command array: " + name)
            start = match.end() - 1
            end = closing_brace(clean, start)
            if not re.match(r"\s*;", clean[end + 1:]):
                raise ValueError("invalid end of command array: " + name)
            names.update(extract_array(clean[start + 1:end], relative + ":" + name))
            arrays.add(name)
    expected = set(EXPECTED_ARRAYS)
    # The stream module first appeared in 1.9.0. Historical source trees must
    # still provide the core, configuration, events, HTTP, proxy, and mail arrays.
    if tuple(map(int, version.split("."))) < (1, 9, 0):
        expected -= {"ngx_stream_commands", "ngx_stream_core_commands"}
    missing = expected - arrays
    if missing:
        raise ValueError("incomplete source tree; missing arrays: " + ", ".join(sorted(missing)))
    if len(names) < 300:
        raise ValueError("unexpectedly few commands; refusing to replace the vocabulary")
    digest_input = "".join(name + "\n" + sources[name] + "\n" for name in sorted(sources))
    return names, {
        "version": version,
        "source_url": "https://nginx.org/download/nginx-" + version + ".tar.gz",
        "command_sources_sha256": hashlib.sha256(digest_input.encode("utf-8")).hexdigest(),
        "command_arrays": len(arrays),
        "source_files": len(sources),
        "unique_directives": len(names),
    }


def validate_keywords(data):
    if not isinstance(data, dict) or set(data) != set(GROUPS):
        raise ValueError("keywords.json must contain exactly: " + ", ".join(GROUPS))
    seen = set()
    for name in GROUPS:
        values = data[name]
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise ValueError(name + " must be an array of nonempty strings")
        if values != sorted(set(values)):
            raise ValueError(name + " must be sorted and unique")
        if any(any(char.isspace() for char in value) for value in values):
            raise ValueError(name + " contains whitespace inside a keyword")
        overlap = seen.intersection(values)
        if overlap:
            raise ValueError("keywords occur in multiple groups: " + ", ".join(sorted(overlap)))
        if name in GROUPS[:4] and any(not TOKEN.fullmatch(v) for v in values):
            raise ValueError(name + " contains an invalid keyword")
        seen.update(values)


def load_keywords(path):
    if not path.is_file():
        raise ValueError("src/keywords.json is missing; restore the canonical vocabulary before updating")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_keywords(data)
    return data


def update_keywords(existing, commands, extra_legacy=()):
    structural = set(existing["structural"])
    # Every old command remains highlighted, even if absent from the next release.
    previous = set(existing["directives"]) | set(existing["legacy"]) | set(extra_legacy)
    legacy = previous - commands - structural
    directives = commands - structural
    occupied = structural | directives | legacy
    result = {
        "structural": sorted(structural),
        "directives": sorted(directives),
        "legacy": sorted(legacy),
        "parameters": sorted(set(existing["parameters"]) - occupied),
        "variable_prefixes": existing["variable_prefixes"],
        "named_location_prefixes": existing["named_location_prefixes"],
    }
    validate_keywords(result)
    return result


def load_sources(path):
    if not path.exists():
        return {
            "schema_version": 1,
            "scope": "Command names from all modules shipped in the official open-source Nginx release, including optional modules and every platform branch. Recognition does not imply that a module is enabled or a directive is valid in every context.",
            "compatibility": {
                "description": "Names from both original light and dark themes that are absent from the selected source release are retained in legacy, as are names removed in later updates. Historical coverage is the union of the listed official release snapshots and the bundled Vim core deprecated list. The original third-party fastcgi_cache_purge keyword is also retained.",
                "baseline_repository": "https://github.com/dslatten/nginx_npp",
                "baseline_revision": "c5f8bc33897a340bf56654a397bc88887e47cfb7",
            },
            "parameters": {
                "description": "A curated selection of values and block/listen parameters. Command names take precedence when a token is used in both roles.",
                "references": [
                    "https://nginx.org/en/docs/http/ngx_http_core_module.html#listen",
                    "https://nginx.org/en/docs/http/ngx_http_headers_module.html",
                    "https://nginx.org/en/docs/http/ngx_http_map_module.html",
                    "https://nginx.org/en/docs/http/ngx_http_upstream_module.html",
                ],
            },
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported sources.json schema; metadata was not changed")
    for key in ("nginx", "compatibility"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError("sources.json " + key + " metadata must be an object")
    return data


def vim_deprecated(source_dir):
    """Read only the official core deprecated group, excluding third parties."""
    path = source_dir / "contrib/vim/syntax/nginx.vim"
    if not path.is_file():
        return set(), None
    content = path.read_bytes()
    names = set(re.findall(
        r"^syn keyword ngxDirectiveDeprecated contained ([a-z][a-z0-9_]*)\s*$",
        content.decode("utf-8"), re.MULTILINE,
    ))
    return names, {"path": "contrib/vim/syntax/nginx.vim",
                   "sha256": hashlib.sha256(content).hexdigest(),
                   "keywords": sorted(names)}


def add_archive_digest(metadata, source_dir, archive=None):
    if archive is None:
        archive = source_dir.parent / ("nginx-" + metadata["version"] + ".tar.gz")
        if not archive.is_file():
            return
    metadata["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()


def json_text(data):
    return json.dumps(data, ensure_ascii=True, indent=2) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="unpacked official nginx release directory")
    parser.add_argument("--version", required=True, help="release version, e.g. 1.31.9")
    parser.add_argument("--archive", type=Path, help="optional original release archive for SHA-256 provenance")
    parser.add_argument("--legacy-source", action="append", nargs=2, default=[],
                        metavar=("VERSION", "DIRECTORY"),
                        help="also retain commands from this historical official release; repeatable")
    parser.add_argument("--check", action="store_true", help="verify the checked-in vocabulary and provenance without writing")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
            raise ValueError("--version must have the form 1.31.9")
        source_dir = args.source_dir.resolve()
        commands, extracted = extract_commands(source_dir, args.version)
        keyword_path = ROOT / "src/keywords.json"
        source_path = ROOT / "src/sources.json"
        sources = load_sources(source_path)
        compatibility = sources.setdefault("compatibility", {})
        extra_legacy, vim_source = vim_deprecated(source_dir)
        if vim_source is not None:
            vim_source.update({"version": args.version, "source_url": extracted["source_url"]})
            prior_vim = compatibility.setdefault("vim_deprecated", {})
            if not isinstance(prior_vim, dict):
                raise ValueError("vim_deprecated metadata must be an object")
            prior_vim.update(vim_source)
        for version, directory in args.legacy_source:
            legacy_dir = Path(directory).resolve()
            historical, evidence = extract_commands(legacy_dir, version)
            extra_legacy.update(historical)
            add_archive_digest(evidence, legacy_dir)
            evidence["compared_with_version"] = args.version
            evidence["legacy_names"] = sorted(historical - commands)
            history = compatibility.setdefault("historical_releases", {})
            if not isinstance(history, dict) or not isinstance(history.get(version, {}), dict):
                raise ValueError("historical_releases metadata must map versions to objects")
            history.setdefault(version, {}).update(evidence)
        keywords = update_keywords(load_keywords(keyword_path), commands, extra_legacy)
        # Preserve unknown metadata fields, including additions by maintainers.
        metadata = dict(sources.get("nginx", {}))
        metadata.update(extracted)
        if sources.get("nginx", {}).get("version") != args.version:
            metadata.pop("archive_sha256", None)
        add_archive_digest(metadata, source_dir, args.archive)
        sources["nginx"] = metadata
        outputs = {keyword_path: json_text(keywords), source_path: json_text(sources)}
        if args.check:
            stale = [str(path.relative_to(ROOT)) for path, content in outputs.items()
                     if not path.exists() or path.read_text(encoding="utf-8") != content]
            if stale:
                raise ValueError("outdated generated data: " + ", ".join(stale))
        else:
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", encoding="utf-8", newline="\n") as output:
                    output.write(content)
        print("Nginx {}: {} commands in {} arrays; {} compatibility names.{}".format(
            args.version, len(commands), extracted["command_arrays"], len(keywords["legacy"]),
            " Verified." if args.check else " Run tools/generate.py to rebuild the UDL files.",
        ))
        return 0
    except (OSError, ValueError) as error:
        print("update_keywords: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
