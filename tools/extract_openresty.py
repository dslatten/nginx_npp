#!/usr/bin/env python3
"""Extract configuration vocabulary from an official OpenResty source archive.

The archive is read as data, never extracted or executed. Module selection comes
from configure's literal module list, including disabled-by-default modules.
Test and example directories are excluded. This is vocabulary coverage; embedded
Lua and custom module block grammars are not parsed by the generated highlighter.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

if __package__:
    from . import update_keywords as core
    from .catalog_history import preserve_retired_directives
else:
    import update_keywords as core
    from catalog_history import preserve_retired_directives


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "src/module-catalogs/openresty.json"
NAME = re.compile(r'\s*ngx_string\s*\(\s*"([A-Za-z_][A-Za-z0-9_-]*)"\s*\)\s*,')
EXCLUDED_DIRS = {"test", "tests", "t", "example", "examples"}


def archive_sources(archive, version):
    """Read regular text sources only, rejecting ambiguous or unsafe members."""
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("version must have four numeric components")
    prefix = "openresty-" + version
    result = {}
    seen = set()
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or not path.parts or path.parts[0] != prefix):
                raise ValueError("unexpected archive path: " + member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("nonregular archive member: " + member.name)
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative in seen:
                raise ValueError("duplicate archive member: " + relative)
            seen.add(relative)
            if relative != "configure" and path.suffix not in {".c", ".h", ".inc"}:
                continue
            if member.size > 16 * 1024 * 1024:
                raise ValueError("unexpectedly large source file: " + relative)
            result[relative] = bundle.extractfile(member).read()
    if "configure" not in result:
        raise ValueError("archive lacks OpenResty's configure manifest")
    return result


def module_manifest(configure, available):
    """Read the literal Perl module manifest without evaluating Perl or shell."""
    match = re.search(r"my @modules = \((.*?)\n\);", configure, re.DOTALL)
    if match is None:
        raise ValueError("unsupported OpenResty module manifest")
    components = sorted({p.split("/")[1] for p in available if p.startswith("bundle/")})
    nginx = [name for name in components if re.fullmatch(r"nginx-\d+\.\d+\.\d+", name)]
    if len(nginx) != 1:
        raise ValueError("expected one bundled Nginx source tree")
    modules = [{"configure_name": "nginx", "component": nginx[0], "default_enabled": True}]
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = re.fullmatch(r"\[([a-z0-9_]+)\s*=>\s*'([^']+)'(?:,\s*'(disabled)')?\],", line)
        if entry is None:
            raise ValueError("unsupported manifest entry: " + line)
        name, package, disabled = entry.groups()
        candidates = [value for value in components if value.startswith(package + "-")]
        if len(candidates) != 1:
            raise ValueError("expected one source directory for " + package)
        modules.append({"configure_name": name, "component": candidates[0],
                        "default_enabled": disabled is None})
    if len({module["configure_name"] for module in modules}) != len(modules):
        raise ValueError("duplicate module manifest entry")
    if len(modules) == 1:
        raise ValueError("OpenResty's module manifest contains no addons")
    return modules


def expand_command_headers(body, component, sources):
    """Resolve NDK's command header while rejecting unrecognized includes.

    NDK deliberately includes one header inside its command array with a selector
    macro. Its other branch contains C type declarations, not directives.
    """
    used = set()
    pattern = re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]\s*$', re.MULTILINE)

    def expand(match):
        filename = match.group(1)
        if not component.startswith("ngx_devel_kit-") or filename != "ndk_upstream_list.h":
            raise ValueError("unsupported include in command array: " + filename)
        if not re.search(r"#define\s+NDK_UPSTREAM_LIST_CMDS\s+1\b", body[:match.start()]):
            raise ValueError("NDK command-header selector was not enabled")
        path = "bundle/" + component + "/src/" + filename
        if path not in sources:
            raise ValueError("missing NDK command header")
        header = core.strip_comments(sources[path].decode("utf-8"))
        selected = re.fullmatch(
            r"\s*#if\s*\(NDK_UPSTREAM_LIST_CMDS\)\s*(.*?)#else\b.*?#endif\s*",
            header, re.DOTALL,
        )
        if selected is None:
            raise ValueError("NDK command-header layout changed; review extraction")
        used.add(path)
        return selected.group(1)

    return pattern.sub(expand, body), used


def command_names(body, label):
    """Read only literal command-name fields, preserving case and hyphens."""
    if re.search(r"^\s*#include\b", body, re.MULTILINE):
        raise ValueError("unresolved command-header include in " + label)
    body = re.sub(r"^\s*#[^\n]*", "", body, flags=re.MULTILINE)
    names = set()
    index = 0
    sentinel_seen = False
    while index < len(body):
        if body[index].isspace() or body[index] == ",":
            index += 1
            continue
        sentinel = re.match(r"ngx_null_command\b", body[index:])
        if sentinel:
            sentinel_seen = True
            index += sentinel.end()
            continue
        if body[index] != "{" or sentinel_seen:
            raise ValueError("unsupported command initializer in " + label)
        end = core.closing_brace(body, index)
        match = NAME.match(body[index + 1:end])
        if match is None:
            raise ValueError("unsupported command-name expression in " + label)
        names.add(match.group(1))
        index = end + 1
    if not sentinel_seen:
        raise ValueError("missing command-array sentinel in " + label)
    return names


def source_arrays(path, content, component, sources):
    clean = core.strip_comments(content.decode("utf-8"))
    declarations = core.mask_literals(clean)
    matches = list(core.ARRAY_START.finditer(declarations))
    # Do not silently skip new declaration forms, such as sized arrays.
    possible = re.findall(r"\bngx_command_t\s+\w+\s*\[[^\]]*\]\s*=", declarations)
    if len(possible) != len(matches):
        raise ValueError("unsupported command-array declaration in " + path)
    arrays = {}
    included = set()
    for match in matches:
        start = match.end() - 1
        end = core.closing_brace(clean, start)
        if not re.match(r"\s*;", clean[end + 1:]):
            raise ValueError("invalid command-array ending in " + path)
        body, headers = expand_command_headers(clean[start + 1:end], component, sources)
        name = match.group("name")
        if name in arrays:
            raise ValueError("duplicate command array in " + path)
        arrays[name] = command_names(body, path + ":" + name)
        included.update(headers)
    return arrays, included


def build_catalog(archive, version):
    sources = archive_sources(archive, version)
    modules = module_manifest(sources["configure"].decode("utf-8"), sources)
    all_names = set()
    source_evidence = {}
    source_evidence["configure"] = hashlib.sha256(sources["configure"]).hexdigest()
    total_arrays = 0
    for module in modules:
        component = module["component"]
        prefix = "bundle/" + component + "/"
        names = set()
        array_count = 0
        paths = set()
        for path in sorted(sources):
            if not path.startswith(prefix):
                continue
            if EXCLUDED_DIRS.intersection(PurePosixPath(path).parts[2:-1]):
                continue
            arrays, included = source_arrays(path, sources[path], component, sources)
            if not arrays:
                continue
            paths.add(path)
            paths.update(included)
            for values in arrays.values():
                names.update(values)
            array_count += len(arrays)
        # This module intentionally exposes a Lua API and registers NULL commands.
        if not array_count and not component.startswith("ngx_lua_upstream-"):
            raise ValueError("no command arrays found for bundled module " + component)
        if component.startswith("ngx_lua_upstream-"):
            module["note"] = "Provides a Lua API and registers no Nginx configuration directives."
        module["command_arrays"] = array_count
        module["directive_count"] = len(names)
        module["directives"] = sorted(names)
        module["source_files"] = sorted(paths)
        for path in paths:
            source_evidence[path] = hashlib.sha256(sources[path]).hexdigest()
        all_names.update(names)
        total_arrays += array_count
    if not all_names:
        raise ValueError("empty directive vocabulary")
    return {
        "description": "Nginx configuration directive names from every addon module listed in the official OpenResty bundle and its bundled Nginx source. Includes optional modules and platform branches. Test/example modules and Lua API function names are excluded; embedded Lua syntax is outside this vocabulary catalog.",
        "version": version,
        "source_url": "https://openresty.org/download/openresty-" + version + ".tar.gz",
        "archive_sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
        "directives": sorted(all_names),
        "module_count": len(modules),
        "command_array_count": total_arrays,
        "modules": modules,
        "source_sha256": dict(sorted(source_evidence.items())),
        "extraction_notes": [
            "Module membership and default-enabled flags are read from configure's literal @modules list without executing it.",
            "Names come from ngx_command_t initializers. NDK's upstream_list command is resolved from its selector-controlled included header.",
            "The NDK demonstration directives set_concat2 and set_prepend_hello are excluded because their example module is not in the bundle's configure module list.",
            "All conditional platform/feature branches are included. Highlighting a name does not assert that a module is enabled or that an obsolete directive is accepted.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        catalog = build_catalog(args.archive, args.version)
        catalog = preserve_retired_directives(catalog, args.output)
        content = json.dumps(catalog, ensure_ascii=True, indent=2) + "\n"
        if args.check:
            if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
                raise ValueError("OpenResty catalog is missing or out of date")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8", newline="\n") as output:
                output.write(content)
        print("OpenResty {}: {} distinct directives, {} bundled module components, {} command arrays.{}".format(
            args.version, len(catalog["directives"]), catalog["module_count"], catalog["command_array_count"],
            " Verified." if args.check else " Catalog written.",
        ))
        return 0
    except (OSError, ValueError, tarfile.TarError) as error:
        print("extract_openresty: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
