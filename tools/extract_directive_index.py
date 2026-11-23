#!/usr/bin/env python3
"""Extract a directive catalog from a saved official Nginx index (Python 3.9+).

Download https://nginx.org/en/docs/dirindex.html separately, then run:
    python tools/extract_directive_index.py --input PATH --retrieved YYYY-MM-DD

This tool is offline. It reads link display names only from the directive
index's paragraph, preserves their spelling, and deduplicates module contexts.
"""

import argparse
from datetime import date
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

if __package__:
    from .catalog_history import preserve_retired_directives
else:
    from catalog_history import preserve_retired_directives

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://nginx.org/en/docs/dirindex.html"
DESCRIPTION = (
    "Names listed in the official Nginx alphabetical directive index, including "
    "open-source, commercial, and separately distributed modules. Repeated "
    "HTTP, stream, mail, and other contexts are deduplicated. This catalog "
    "recognizes names; it does not assert availability in a particular build."
)


class DirectiveIndexParser(HTMLParser):
    """Read the first paragraph after the exact directive-index heading."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading_parts = None
        self.found_heading = False
        self.in_list = False
        self.finished = False
        self.anchor_parts = None
        self.anchor_href = None
        self.entries = []

    def handle_starttag(self, tag, attrs):
        if self.finished:
            return
        if tag == "h2":
            self.heading_parts = []
        elif tag == "p" and self.found_heading:
            if self.in_list:
                raise ValueError("unexpected nested directive-index paragraph")
            self.in_list = True
        elif tag == "a" and self.in_list:
            if self.anchor_parts is not None:
                raise ValueError("unexpected nested directive link")
            self.anchor_parts = []
            self.anchor_href = dict(attrs).get("href", "")

    def handle_data(self, data):
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.anchor_parts is not None:
            self.anchor_parts.append(data)

    def handle_endtag(self, tag):
        if self.finished:
            return
        if tag == "h2" and self.heading_parts is not None:
            heading = " ".join("".join(self.heading_parts).split())
            self.heading_parts = None
            if heading == "Alphabetical index of directives":
                self.found_heading = True
        elif tag == "a" and self.anchor_parts is not None:
            name = "".join(self.anchor_parts).strip()
            if not name or any(character.isspace() for character in name):
                raise ValueError("invalid directive link display name: " + repr(name))
            if not urlsplit(self.anchor_href).fragment:
                raise ValueError("directive link is missing its documentation anchor")
            self.entries.append(name)
            self.anchor_parts = None
            self.anchor_href = None
        elif tag == "p" and self.in_list:
            if self.anchor_parts is not None:
                raise ValueError("unclosed directive link")
            self.in_list = False
            self.finished = True


def extract_directives(html_text):
    parser = DirectiveIndexParser()
    parser.feed(html_text)
    parser.close()
    if not parser.found_heading:
        raise ValueError("official directive-index heading was not found")
    if not parser.finished:
        raise ValueError("directive-index paragraph is missing or incomplete")
    if not parser.entries:
        raise ValueError("directive index contains no directive links")
    return sorted(set(parser.entries)), len(parser.entries)


def build_catalog(html_bytes, retrieved=None):
    directives, entry_count = extract_directives(html_bytes.decode("utf-8-sig"))
    catalog = {
        "schema_version": 1,
        "source_url": SOURCE_URL,
        "description": DESCRIPTION,
        "source_html_sha256": hashlib.sha256(html_bytes).hexdigest(),
        "entry_count": entry_count,
        "unique_directives": len(directives),
    }
    if retrieved is not None:
        # Validate an explicitly supplied retrieval date without reading the clock.
        catalog["retrieved"] = date.fromisoformat(retrieved).isoformat()
    catalog["directives"] = directives
    return catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="saved official directive-index HTML")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "src/module-catalogs/nginx-index.json",
        help="destination catalog JSON",
    )
    parser.add_argument("--retrieved", help="optional explicit retrieval date, YYYY-MM-DD")
    parser.add_argument("--check", action="store_true", help="compare output without writing")
    args = parser.parse_args(argv)
    try:
        catalog = preserve_retired_directives(
            build_catalog(args.input.read_bytes(), args.retrieved), args.output
        )
        expected = (json.dumps(catalog, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != expected:
                raise ValueError("catalog is stale: " + str(args.output))
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(expected)
        print("{} {} directive names from {} index entries.".format(
            "Checked" if args.check else "Extracted",
            catalog["unique_directives"], catalog["entry_count"],
        ))
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        print("extract_directive_index: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
