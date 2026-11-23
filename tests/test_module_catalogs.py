"""Additive module coverage and Notepad++ keyword-buffer regressions."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generate", ROOT / "tools" / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


def small_vocabulary():
    return {
        "variable_prefixes": ["$", "HTTP_"],
        "named_location_prefixes": ["@"],
        "structural": ["http"],
        "directives": ["proxy_pass"],
        "legacy": ["ssl"],
        "parameters": ["on"],
    }


class ModuleCatalogsTest(unittest.TestCase):
    def test_catalog_union_preserves_case_and_existing_styles(self):
        vocabulary = small_vocabulary()
        original = copy.deepcopy(vocabulary)
        catalogs = {
            "one.json": ["HTTP_HEADER", "MixedCase", "http", "on", "proxy_pass"],
            "two.json": ["MixedCase", "mixedcase", "ssl"],
        }
        groups = generate.keyword_groups(vocabulary, catalogs)
        self.assertEqual(groups[0:3], [["$", "HTTP_"], ["@"], ["http"]])
        self.assertEqual(groups[4], ["on"])
        self.assertEqual(groups[3], ["MixedCase", "mixedcase", "proxy_pass", "ssl"])
        self.assertEqual(groups[5:], [[], [], []])
        self.assertEqual(vocabulary, original)

    def test_keyword_packing_counts_spaces_and_utf8_bytes(self):
        vocabulary = {name: [] for name in generate.GROUPS}
        # First pair takes exactly 20 bytes including its separator. The last
        # name has 12 characters but 24 bytes, so it must occupy another group.
        vocabulary["directives"] = ["a" * 9, "b" * 10, "c" * 20, "\u00e9" * 12]
        with patch.object(generate, "MAX_KEYWORD_BYTES", 24):
            groups = generate.keyword_groups(vocabulary)
        self.assertEqual(groups[3], ["a" * 9, "b" * 10])
        self.assertEqual(groups[5], ["c" * 20])
        self.assertEqual(groups[6], ["\u00e9" * 12])
        self.assertEqual(groups[7], [])
        self.assertEqual(groups[4], [])

    def test_overlong_tokens_and_exhausted_groups_fail_instead_of_truncating(self):
        vocabulary = {name: [] for name in generate.GROUPS}
        with patch.object(generate, "MAX_KEYWORD_BYTES", 10):
            vocabulary["directives"] = ["a" * 11]
            with self.assertRaisesRegex(ValueError, "editor limit"):
                generate.keyword_groups(vocabulary)
            vocabulary["directives"] = [letter * 10 for letter in "abcde"]
            with self.assertRaisesRegex(ValueError, "four available"):
                generate.keyword_groups(vocabulary)
            vocabulary["directives"] = []
            vocabulary["parameters"] = ["\u00e9" * 6]
            with self.assertRaisesRegex(ValueError, "editor limit"):
                generate.keyword_groups(vocabulary)

    def test_spilled_directives_keep_identical_exact_matching_styles(self):
        vocabulary = {name: [] for name in generate.GROUPS}
        vocabulary["directives"] = [letter * 10 for letter in "abcd"]
        with patch.object(generate, "MAX_KEYWORD_BYTES", 10):
            groups = generate.keyword_groups(vocabulary)
        lexer = generate.read_json(ROOT, "lexer.json")
        for theme in generate.read_json(ROOT, "themes.json").values():
            language = ET.fromstring(generate.make_udl(groups, lexer, theme, "test")).find("UserLang")
            styles = {node.get("name"): dict(node.attrib) for node in language.find("Styles")}
            expected = styles["KEYWORDS4"].copy()
            expected.pop("name")
            for number in (4, 6, 7, 8):
                self.assertEqual(language.find("Settings/Prefix").get(f"Keywords{number}"), "no")
                actual = styles[f"KEYWORDS{number}"].copy()
                actual.pop("name")
                self.assertEqual(actual, expected)
            self.assertEqual(language.find("Settings/Global").get("caseIgnored"), "no")

    def test_all_sources_survive_in_both_themes_and_reference_files(self):
        vocabulary = generate.read_json(ROOT, "keywords.json")
        # Build the expected union independently of the generator's loader.
        expected = set().union(*map(set, vocabulary.values()))
        for path in (ROOT / "src" / "module-catalogs").glob("*.json"):
            catalog = json.loads(path.read_text(encoding="utf-8"))
            expected.update(catalog["directives"])
            expected.update(catalog.get("retired_directives", []))
        outputs = generate.build_outputs(ROOT)
        self.assertEqual(set(outputs), {
            "userDefineLang_nginx.xml", "userDefineLang_nginx_dark.xml",
            "src/Words1.txt", "src/Words2.txt", "src/Words3.txt", "src/Words4.txt",
            "src/Words5.txt",
        })
        themes = []
        for filename in ("userDefineLang_nginx.xml", "userDefineLang_nginx_dark.xml"):
            language = ET.fromstring(outputs[filename]).find("UserLang")
            lists = {node.get("name"): node.text or "" for node in language.find("KeywordLists")}
            themes.append(lists)
            actual = []
            for number in range(1, 9):
                words = lists[f"Keywords{number}"]
                self.assertLess(len(words.encode("utf-8")), 30 * 1024)
                actual.extend(words.split())
            for number in range(1, 6):
                reference = outputs[f"src/Words{number}.txt"].decode("utf-8")
                space_separated = reference.split("Space-separated:\n", 1)[1].split("\n\n", 1)[0]
                if number == 4:
                    words = " ".join(lists[f"Keywords{i}"] for i in (4, 6, 7, 8) if lists[f"Keywords{i}"])
                else:
                    words = lists[f"Keywords{number}"]
                self.assertEqual(space_separated, words)
            self.assertEqual(len(actual), len(set(actual)))
            prefixes = tuple(vocabulary["variable_prefixes"] + vocabulary["named_location_prefixes"])
            self.assertFalse({word for word in expected - set(actual) if not word.startswith(prefixes)})
        self.assertEqual(themes[0], themes[1])

    def test_required_catalogs_cannot_silently_disappear(self):
        required = ("nginx-index.json", "community-2024.json", "openresty.json")
        self.assertTrue(set(required).issubset(generate.module_catalogs(ROOT)))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "src" / "module-catalogs"
            with self.assertRaisesRegex(ValueError, "Missing required"):
                generate.module_catalogs(root)
            directory.mkdir(parents=True)
            for name in required:
                (directory / name).write_text('{"directives": []}', encoding="utf-8")
            for name in required:
                path = directory / name
                path.unlink()
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                    generate.module_catalogs(root)
                path.write_text('{"directives": []}', encoding="utf-8")

    def test_catalog_retired_names_survive_with_original_case(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "src" / "module-catalogs"
            directory.mkdir(parents=True)
            for name in ("nginx-index.json", "community-2024.json", "openresty.json"):
                (directory / name).write_text('{"directives": []}', encoding="utf-8")
            path = directory / "openresty.json"
            path.write_text(json.dumps({"directives": ["Current"], "retired_directives": ["Old"]}), encoding="utf-8")
            self.assertEqual(generate.module_catalogs(root)["openresty.json"], ["Current", "Old"])
            path.write_text(json.dumps({"directives": ["Current"], "retired_directives": ["two words"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "retired_directives"):
                generate.module_catalogs(root)

    def test_malformed_catalog_tokens_are_rejected(self):
        vocabulary = small_vocabulary()
        for words in (["z", "a"], ["duplicate", "duplicate"], ["two words"], [""]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                generate.keyword_groups(vocabulary, {"invalid.json": words})


if __name__ == "__main__":
    unittest.main()
