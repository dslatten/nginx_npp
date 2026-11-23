"""Coverage checks for saved index extraction and the community snapshot."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import extract_directive_index as INDEX

ROOT = Path(__file__).resolve().parents[1]


class DirectiveIndexTests(unittest.TestCase):
    def test_scope_context_deduplication_and_exact_spelling(self):
        html = """
        <nav><a href="news.html#item">news</a></nav>
        <h2>Other section</h2><p><a href="other.html#no">not_a_directive</a></p>
        <h2>Alphabetical index of directives</h2>
        <p><a href="http.html#access_log">access_log</a> (http)<br>
           <a href="stream.html#access_log">access_log</a> (stream)<br>
           <a href="module.html#mixed"><code>MixedCase_name</code></a><br>
           <a href="module.html#hyphen">module-option</a><br>
           <a href="module.html#entity">entity&#95;name</a></p>
        <footer><a href="footer.html#copyright">copyright</a></footer>
        """
        names, count = INDEX.extract_directives(html)
        self.assertEqual(count, 5)
        self.assertEqual(names, ["MixedCase_name", "access_log", "entity_name", "module-option"])

    def test_rejects_wrong_or_incomplete_pages(self):
        bad_pages = (
            "<html><h2>Access denied</h2><p>Try again.</p></html>",
            "<h2>Alphabetical index of directives</h2><p></p>",
            '<h2>Alphabetical index of directives</h2><p><a href="x#d">d</a>',
            '<h2>Alphabetical index of directives</h2><p><a href="x">d</a></p>',
            '<h2>Alphabetical index of directives</h2><p><a href="x#d">two words</a></p>',
        )
        for html in bad_pages:
            with self.subTest(html=html), self.assertRaises(ValueError):
                INDEX.extract_directives(html)

    def test_snapshot_is_reproducible_without_current_date(self):
        source = b'<h2>Alphabetical index of directives</h2><p><a href="m#d">d</a></p>'
        self.assertEqual(INDEX.build_catalog(source), INDEX.build_catalog(source))
        self.assertNotIn("retrieved", INDEX.build_catalog(source))
        self.assertEqual(INDEX.build_catalog(source, "2026-11-23")["retrieved"], "2026-11-23")
        with self.assertRaises(ValueError):
            INDEX.build_catalog(source, "2026-02-31")

    def test_catalog_snapshots_preserve_recorded_coverage(self):
        index = json.loads((ROOT / "src/module-catalogs/nginx-index.json").read_text(encoding="utf-8"))
        community = json.loads((ROOT / "src/module-catalogs/community-2024.json").read_text(encoding="utf-8"))
        for catalog in (index, community):
            self.assertEqual(catalog["directives"], sorted(set(catalog["directives"])))
            self.assertEqual(catalog["unique_directives"], len(catalog["directives"]))
            self.assertTrue(catalog["source_url"].startswith("https://"))
        self.assertEqual(len(community["directives"]), 702)
        self.assertEqual(len(community["sources"]), 2)
        for name in ("http2", "http3", "stream", "grpc_pass", "js_import", "otel_trace",
                     "connect_timeout", "read_timeout", "ssl_name", "ssl_server_name",
                     "sticky_cookie_insert", "uuid_file"):
            self.assertIn(name, community["directives"])
        for name in ("http2", "acme_certificate", "auth_jwt", "js_import", "otel_trace"):
            self.assertIn(name, index["directives"])

    def test_refresh_retains_removed_names_and_restores_returning_names(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / "index.html"
            output = folder / "catalog.json"
            arguments = ["--input", str(source), "--output", str(output)]

            def set_source(names):
                links = "".join('<a href="module#{}">{}</a>'.format(name, name) for name in names)
                source.write_text(
                    "<h2>Alphabetical index of directives</h2><p>" + links + "</p>",
                    encoding="utf-8",
                )

            def run(extra=()):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    return INDEX.main(arguments + list(extra))

            set_source(["alpha", "beta"])
            self.assertEqual(run(), 0)
            self.assertNotIn("retired_directives", json.loads(output.read_text()))

            set_source(["beta", "gamma"])
            original = output.read_bytes()
            self.assertEqual(run(["--check"]), 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(run(), 0)
            catalog = json.loads(output.read_text())
            self.assertEqual(catalog["directives"], ["beta", "gamma"])
            self.assertEqual(catalog["retired_directives"], ["alpha"])
            self.assertEqual(run(["--check"]), 0)

            set_source(["gamma"])
            self.assertEqual(run(), 0)
            catalog = json.loads(output.read_text())
            self.assertEqual(catalog["retired_directives"], ["alpha", "beta"])

            set_source(["alpha", "gamma"])
            self.assertEqual(run(), 0)
            catalog = json.loads(output.read_text())
            self.assertEqual(catalog["directives"], ["alpha", "gamma"])
            self.assertEqual(catalog["retired_directives"], ["beta"])

            set_source(["alpha", "beta", "gamma"])
            self.assertEqual(run(), 0)
            self.assertNotIn("retired_directives", json.loads(output.read_text()))
            self.assertEqual(run(["--check"]), 0)

    def test_invalid_prior_catalog_is_not_overwritten(self):
        invalid_catalogs = (
            "not JSON", "[]", "{}", '{"directives":null}',
            '{"directives":["alpha","alpha"]}',
            '{"directives":["beta","alpha"]}',
            '{"directives":["two words"]}',
            '{"directives":["alpha"],"retired_directives":"beta"}',
            '{"directives":["alpha"],"retired_directives":["alpha"]}',
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.json"
            for invalid in invalid_catalogs:
                with self.subTest(invalid=invalid):
                    output.write_text(invalid, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        INDEX.preserve_retired_directives({"directives": ["fresh"]}, output)
                    self.assertEqual(output.read_text(encoding="utf-8"), invalid)

    def test_direct_script_execution_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "index.html"
            output = Path(directory) / "catalog.json"
            source.write_text(
                '<h2>Alphabetical index of directives</h2><p><a href="m#d">d</a></p>',
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/extract_directive_index.py"),
                 "--input", str(source), "--output", str(output)],
                cwd=directory, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(output.read_text())["directives"], ["d"])


if __name__ == "__main__":
    unittest.main()
