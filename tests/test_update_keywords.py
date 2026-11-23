"""Regression checks for safe, reproducible source vocabulary extraction."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/update_keywords.py"
SPEC = importlib.util.spec_from_file_location("update_keywords", MODULE_PATH)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def vocabulary():
    return {
        "structural": ["http"],
        "directives": ["old_command", "retained_command"],
        "legacy": ["third_party_command"],
        "parameters": ["new_command", "on"],
        "variable_prefixes": ["$", "HTTP_"],
        "named_location_prefixes": ["@"],
    }


class CommandParsingTests(unittest.TestCase):
    def test_only_first_command_fields_are_names(self):
        body = r'''
            /* { ngx_string("comment_is_not_a_command"), 0 }, */
            { ngx_string("first"), ngx_string("value_is_not_a_command"),
              0, { 1, 2 }, "literal } brace", 0, NULL },
            #if (NGX_LINUX)
            { ngx_string("linux_only"), 0, NULL, 0, 0, NULL },
            #else
            { ngx_string("other_platform"), 0, NULL, 0, 0, NULL },
            #endif
            ngx_null_command
        '''
        self.assertEqual(
            updater.extract_array(updater.strip_comments(body), "test"),
            {"first", "linux_only", "other_platform"},
        )

    def test_comments_inside_string_literals_are_preserved(self):
        source = '"https://example.org/*literal*/" /* erase */ // erase too\n'
        cleaned = updater.strip_comments(source)
        self.assertIn('"https://example.org/*literal*/"', cleaned)
        self.assertNotIn("erase", cleaned)

    def test_rejects_unknown_initializer_and_missing_sentinel(self):
        for body in (
            '{ SOME_MACRO("unknown"), 0 }, ngx_null_command',
            '{ ngx_string("valid"), 0 },',
            'ngx_null_command, { ngx_string("after_sentinel"), 0 }',
            '{ ngx_string("invalid-name"), 0 }, ngx_null_command',
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    updater.extract_array(body, "test")

    def test_source_extraction_ignores_unrelated_strings_and_fake_declarations(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "src/core").mkdir(parents=True)
            (source / "src/core/nginx.h").write_text(
                '#define NGINX_VERSION "1.31.9"\n', encoding="utf-8"
            )
            commands = ',\n'.join(
                '{ ngx_string("command_%03d"), 0, NULL, 0, 0, NULL }' % index
                for index in range(300)
            )
            text = r'''
                static ngx_str_t unrelated = ngx_string("not_a_command");
                static char *description = "ngx_command_t fake[] = { bad }";
                /* ngx_command_t commented[] = { bad }; */
                static ngx_command_t test_commands[] = {
            ''' + commands + ',\nngx_null_command\n};\n'
            (source / "src/core/module.c").write_text(text, encoding="utf-8")
            with mock.patch.object(updater, "EXPECTED_ARRAYS", {"test_commands"}):
                names, provenance = updater.extract_commands(source, "1.31.9")
                self.assertEqual(len(names), 300)
                self.assertEqual(provenance["command_arrays"], 1)
                self.assertEqual(provenance["source_files"], 1)
                self.assertNotIn("not_a_command", names)
                with self.assertRaisesRegex(ValueError, "version"):
                    updater.extract_commands(source, "1.31.8")
            with self.assertRaisesRegex(ValueError, "missing arrays"):
                updater.extract_commands(source, "1.31.9")


class VocabularyTests(unittest.TestCase):
    def test_missing_canonical_data_is_not_rebuilt_from_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "canonical vocabulary"):
                updater.load_keywords(root / "src/keywords.json")

    def test_historical_keywords_are_retained_without_duplicating_current_commands(self):
        result = updater.update_keywords(
            vocabulary(), {"http", "retained_command"},
            {"http", "spdy_chunk_size", "spdy_headers_comp"},
        )
        self.assertEqual(result["legacy"], [
            "old_command", "spdy_chunk_size", "spdy_headers_comp", "third_party_command",
        ])
        self.assertEqual(result["structural"], ["http"])

    def test_vim_reader_excludes_third_party_and_non_deprecated_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            path = source / "contrib/vim/syntax/nginx.vim"
            path.parent.mkdir(parents=True)
            path.write_text(
                'syn keyword ngxDirectiveDeprecated contained proxy_downstream_buffer\n'
                'syn keyword ngxDirectiveDeprecated contained proxy_upstream_buffer\n'
                'syn keyword ngxDirective contained js_access\n'
                'syn keyword ngxDirectiveThirdPartyDeprecated contained third_party\n',
                encoding="utf-8",
            )
            names, evidence = updater.vim_deprecated(source)
            self.assertEqual(names, {"proxy_downstream_buffer", "proxy_upstream_buffer"})
            self.assertEqual(evidence["keywords"], sorted(names))
            self.assertEqual(len(evidence["sha256"]), 64)

    def test_checked_in_legacy_contains_verified_historical_names(self):
        data = updater.load_keywords(MODULE_PATH.parents[1] / "src/keywords.json")
        self.assertTrue({"spdy", "spdy_chunk_size", "spdy_headers_comp", "spdy_recv_timeout",
                         "connections", "imap", "worker_threads"}.issubset(data["legacy"]))
        # Some obsolete handlers remain registered in current source commands.
        self.assertTrue({"proxy_downstream_buffer", "proxy_upstream_buffer"}
                        .issubset(set(data["directives"]) | set(data["legacy"])))

    def test_removed_and_third_party_names_are_preserved(self):
        previous = vocabulary()
        result = updater.update_keywords(previous, {"http", "retained_command", "new_command"})
        self.assertEqual(result["directives"], ["new_command", "retained_command"])
        self.assertEqual(result["legacy"], ["old_command", "third_party_command"])
        self.assertEqual(result["parameters"], ["on"])
        self.assertEqual(result["variable_prefixes"], ["$", "HTTP_"])
        self.assertEqual(previous["parameters"], ["new_command", "on"])
        # A former compatibility name can become a source command without loss.
        restored = updater.update_keywords(result, {"http", "old_command"})
        self.assertEqual(restored["directives"], ["old_command"])
        self.assertEqual(restored["legacy"], ["new_command", "retained_command", "third_party_command"])

    def test_invalid_groups_fail_instead_of_silently_normalizing(self):
        cases = []
        duplicate = vocabulary()
        duplicate["parameters"] = ["http", "on"]
        cases.append(duplicate)
        unsorted = vocabulary()
        unsorted["directives"].reverse()
        cases.append(unsorted)
        invalid = vocabulary()
        invalid["directives"] = ["two words"]
        cases.append(invalid)
        unknown = vocabulary()
        unknown["custom"] = []
        cases.append(unknown)
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    updater.validate_keywords(data)

    def test_refresh_preserves_custom_metadata_and_check_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            keywords = root / "src/keywords.json"
            sources = root / "src/sources.json"
            keywords.write_text(updater.json_text(vocabulary()), encoding="utf-8")
            sources.write_text(updater.json_text({
                "schema_version": 1,
                "maintainer_note": "keep this",
                "nginx": {"version": "1.30.0", "archive_sha256": "old hash", "custom": "keep too"},
            }), encoding="utf-8")
            extracted = {
                "version": "1.31.9", "command_arrays": 1,
                "unique_directives": 2, "command_sources_sha256": "new hash",
            }
            args = ["--source-dir", str(root / "upstream"), "--version", "1.31.9"]
            with mock.patch.object(updater, "ROOT", root), \
                    mock.patch.object(updater, "extract_commands", return_value=({"http", "retained_command"}, extracted)), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(updater.main(args), 0)
                metadata = json.loads(sources.read_text(encoding="utf-8"))
                self.assertEqual(metadata["maintainer_note"], "keep this")
                self.assertEqual(metadata["nginx"]["custom"], "keep too")
                self.assertNotIn("archive_sha256", metadata["nginx"])
                self.assertEqual(updater.main(args + ["--check"]), 0)
                data = json.loads(keywords.read_text(encoding="utf-8"))
                data["directives"] = []
                keywords.write_text(updater.json_text(data), encoding="utf-8")
                self.assertEqual(updater.main(args + ["--check"]), 1)

    def test_failed_extraction_leaves_files_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            keywords = root / "src/keywords.json"
            before = updater.json_text(vocabulary())
            keywords.write_text(before, encoding="utf-8")
            with mock.patch.object(updater, "ROOT", root), \
                    mock.patch.object(updater, "extract_commands", side_effect=ValueError("bad source")), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(updater.main(["--source-dir", str(root), "--version", "1.31.9"]), 1)
            self.assertEqual(keywords.read_text(encoding="utf-8"), before)
            self.assertFalse((root / "src/sources.json").exists())


if __name__ == "__main__":
    unittest.main()
