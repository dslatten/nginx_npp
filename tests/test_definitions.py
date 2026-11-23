"""Release regressions for the actual XML files installed by users."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generate", ROOT / "tools" / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


class DefinitionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.languages = [ET.parse(ROOT / filename).getroot().find("UserLang") for filename in (
            "userDefineLang_nginx.xml", "userDefineLang_nginx_dark.xml")]

    def lists(self, language):
        return {node.get("name"): node.text or "" for node in language.find("KeywordLists")}

    def test_canonical_downloads_have_matching_rules(self):
        light, dark = self.languages
        self.assertEqual((light.get("name"), dark.get("name")), ("Nginx", "Nginx-Dark"))
        for language in self.languages:
            self.assertEqual(language.get("udlVersion"), "2.1")
            self.assertEqual(language.get("ext"), "conf")
        self.assertEqual(ET.tostring(light.find("Settings")), ET.tostring(dark.find("Settings")))
        self.assertEqual(self.lists(light), self.lists(dark))

    def test_new_features_and_existing_keywords_are_available(self):
        expected = {
            "http2", "http3", "quic_retry", "grpc_pass", "stream", "ssl_preread",
            "load_module", "ssl_certificate_cache", "ssl_ech_file", "early_hints",
            "add_header_inherit", "json_set", "json_max_depth", "tunnel_pass",
            "client_body_early_read", "proxy_pass_trailers", "proxy_cookie_flags",
            "uwsgi_pass", "scgi_pass", "fastcgi_pass", "proxy_pass", "try_files",
            "ssl", "spdy", "fastcgi_cache_purge",
        }
        for language in self.languages:
            lists = self.lists(language)
            words = set((lists["Keywords3"] + " " + lists["Keywords4"]).split())
            self.assertFalse(expected - words, expected - words)
            self.assertEqual(language.find("Settings/Global").get("caseIgnored"), "no")
            self.assertEqual(language.find("Settings/Prefix").get("Keywords4"), "no")

    def test_catalog_directives_reach_both_downloads(self):
        expected = set()
        for filename in ("nginx-index.json", "community-2024.json", "openresty.json"):
            catalog = json.loads((ROOT / "src" / "module-catalogs" / filename).read_text(encoding="utf-8"))
            expected.update(catalog["directives"])
            expected.update(catalog.get("retired_directives", []))
        for language in self.languages:
            lists = self.lists(language)
            actual = set(" ".join(lists[f"Keywords{i}"] for i in range(1, 9)).split())
            prefixes = tuple((lists["Keywords1"] + " " + lists["Keywords2"]).split())
            missing = {word for word in expected - actual if not word.startswith(prefixes)}
            self.assertFalse(missing, missing)
            for number in (4, 6, 7, 8):
                self.assertEqual(language.find("Settings/Prefix").get(f"Keywords{number}"), "no")

    def test_strings_comments_and_braced_variables_do_not_create_folds(self):
        for language in self.languages:
            lists = self.lists(language)
            self.assertEqual(lists["Comments"], "00# 01 02 03 04")
            self.assertTrue(lists["Delimiters"].startswith("00' 01\\ 02' 03\" 04\\ 05\" 06${ 07 08}"))
            self.assertEqual(lists["Folders in code1, open"], "{")
            self.assertEqual(lists["Folders in code1, close"], "}")
            for token in ("{", "}", "'", '"'):
                self.assertNotIn(token, lists["Operators1"].split())
            styles = {node.get("name"): node for node in language.find("Styles")}
            for name in ("LINE COMMENTS", "DELIMITERS1", "DELIMITERS2", "DELIMITERS3"):
                self.assertEqual(styles[name].get("nesting"), "0")
            self.assertEqual(styles["DELIMITERS3"].get("fgColor"), styles["KEYWORDS1"].get("fgColor"))

    def test_variable_and_named_location_prefixes_survive(self):
        for language in self.languages:
            lists = self.lists(language)
            self.assertIn("$", lists["Keywords1"].split())
            self.assertIn("HTTP_", lists["Keywords1"].split())
            self.assertEqual(lists["Keywords2"], "@")
            prefix = language.find("Settings/Prefix")
            self.assertEqual(prefix.get("Keywords1"), "yes")
            self.assertEqual(prefix.get("Keywords2"), "yes")

    def test_long_operators_take_precedence(self):
        for language in self.languages:
            ops = self.lists(language)["Operators1"].split()
            self.assertIn("!=", ops)
            for index, op in enumerate(ops):
                for later in ops[index + 1:]:
                    self.assertFalse(later.startswith(op), f"{op} shadows {later}")

    def test_generated_files_are_current(self):
        for name, expected in generate.build_outputs(ROOT).items():
            self.assertEqual((ROOT / name).read_bytes(), expected, name)

    def test_duplicate_and_overlong_keyword_groups_are_rejected(self):
        vocabulary = generate.read_json(ROOT, "keywords.json")
        duplicate = copy.deepcopy(vocabulary)
        duplicate["legacy"] = sorted(duplicate["legacy"] + [vocabulary["directives"][0]])
        with self.assertRaisesRegex(ValueError, "multiple groups"):
            generate.keyword_groups(duplicate)
        overlong = copy.deepcopy(vocabulary)
        overlong["parameters"] = ["a" * 30000]
        with self.assertRaisesRegex(ValueError, "editor limit"):
            generate.keyword_groups(overlong)


if __name__ == "__main__":
    unittest.main()
