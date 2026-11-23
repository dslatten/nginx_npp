"""Extraction boundaries and coverage of the pinned OpenResty source catalog."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools import extract_openresty as extractor


ROOT = Path(__file__).resolve().parents[1]


class CommandExtractionTests(unittest.TestCase):
    def test_first_fields_only_and_case_preserved(self):
        source = br'''
            // ngx_command_t fake[] = { ngx_null_command };
            char *text = "ngx_command_t fake[] = { }";
            static ngx_command_t actual[] = {
                { ngx_string("MixedCase"), ngx_string("not_a_name"), 0 },
                #if PLATFORM
                { ngx_string("name-with-hyphen"), 0 },
                #else
                { ngx_string("other_platform"), 0 },
                #endif
                ngx_null_command
            };
        '''
        arrays, includes = extractor.source_arrays("test.c", source, "test-1", {})
        self.assertEqual(arrays, {"actual": {"MixedCase", "name-with-hyphen", "other_platform"}})
        self.assertEqual(includes, set())

    def test_unknown_name_macros_and_missing_sentinels_fail(self):
        for source in (
            '{ NAME_MACRO("unknown"), 0 }, ngx_null_command',
            '{ ngx_string("incomplete"), 0 }',
            'ngx_null_command, { ngx_string("after_end"), 0 }',
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                extractor.command_names(source, "test")

    def test_unsupported_array_declarations_fail(self):
        with self.assertRaisesRegex(ValueError, "unsupported command-array declaration"):
            extractor.source_arrays(
                "sized.c", b"ngx_command_t sized[1] = { ngx_null_command };", "test-1", {},
            )

    def test_ndk_command_header_selects_command_branch(self):
        header_path = "bundle/ngx_devel_kit-0.3.6/src/ndk_upstream_list.h"
        sources = {header_path: b'''
            #if (NDK_UPSTREAM_LIST_CMDS)
            { ngx_string ("upstream_list"), 0 },
            #else
            typedef struct { int not_a_command; } example_t;
            #endif
        '''}
        source = b'''
            ngx_command_t ndk_http_commands[] = {
            #define NDK_UPSTREAM_LIST_CMDS 1
            #include <ndk_upstream_list.h>
            #undef NDK_UPSTREAM_LIST_CMDS
            ngx_null_command
            };
        '''
        arrays, includes = extractor.source_arrays(
            "ndk.c", source, "ngx_devel_kit-0.3.6", sources,
        )
        self.assertEqual(arrays, {"ndk_http_commands": {"upstream_list"}})
        self.assertEqual(includes, {header_path})
        with self.assertRaisesRegex(ValueError, "selector was not enabled"):
            extractor.source_arrays(
                "ndk.c", source.replace(b"#define NDK_UPSTREAM_LIST_CMDS 1", b""),
                "ngx_devel_kit-0.3.6", sources,
            )

    def test_new_command_header_requires_review(self):
        with self.assertRaisesRegex(ValueError, "unsupported include"):
            extractor.expand_command_headers('#include "new_commands.h"', "module-1", {})


class ManifestAndArchiveTests(unittest.TestCase):
    def test_manifest_keeps_optional_modules_and_ignores_commented_entries(self):
        manifest = """my @modules = (
            [http_lua => 'ngx_lua'],
            [http_iconv => 'iconv-nginx-module', 'disabled'],
            #[http_example => 'example-module'],
);
"""
        sources = ["bundle/nginx-1.31.8/core.c", "bundle/ngx_lua-0.10/test.c",
                   "bundle/iconv-nginx-module-0.14/module.c"]
        modules = extractor.module_manifest(manifest, sources)
        self.assertEqual([item["configure_name"] for item in modules],
                         ["nginx", "http_lua", "http_iconv"])
        self.assertFalse(modules[-1]["default_enabled"])
        with self.assertRaisesRegex(ValueError, "no addons"):
            extractor.module_manifest("my @modules = (\n);", sources)
        with self.assertRaisesRegex(ValueError, "expected one source directory"):
            extractor.module_manifest(manifest, sources[:-1])

    def archive(self, directory, members):
        path = Path(directory) / "source.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, content, kind in members:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        return path

    def test_archive_reads_source_as_data_without_unpacking(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.archive(directory, [
                ("openresty-1.2.3.4/configure", b"manifest", tarfile.REGTYPE),
                ("openresty-1.2.3.4/bundle/module-1/src.c", b"source", tarfile.REGTYPE),
                ("openresty-1.2.3.4/executable", b"ignored", tarfile.REGTYPE),
            ])
            sources = extractor.archive_sources(archive, "1.2.3.4")
            self.assertEqual(sources, {"configure": b"manifest", "bundle/module-1/src.c": b"source"})
            self.assertEqual(list(Path(directory).iterdir()), [archive])

    def test_archive_rejects_traversal_links_and_duplicate_sources(self):
        normal = ("openresty-1.2.3.4/configure", b"data", tarfile.REGTYPE)
        for malformed in (
            ("openresty-1.2.3.4/../escape.c", b"", tarfile.REGTYPE),
            ("other-root/source.c", b"", tarfile.REGTYPE),
            ("openresty-1.2.3.4/link.c", b"", tarfile.SYMTYPE),
            normal,
        ):
            with self.subTest(member=malformed), tempfile.TemporaryDirectory() as directory:
                archive = self.archive(directory, [normal, malformed])
                with self.assertRaises(ValueError):
                    extractor.archive_sources(archive, "1.2.3.4")


class CatalogSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "src/module-catalogs/openresty.json").read_text(encoding="utf-8"))

    def test_release_coverage_matches_module_union(self):
        catalog = self.catalog
        self.assertEqual(catalog["module_count"], len(catalog["modules"]))
        self.assertTrue(catalog["directives"])
        union = {name for module in catalog["modules"] for name in module["directives"]}
        self.assertEqual(catalog["directives"], sorted(union))
        self.assertEqual(sum(m["command_arrays"] for m in catalog["modules"]),
                         catalog["command_array_count"])
        for module in catalog["modules"]:
            self.assertEqual(module["directive_count"], len(module["directives"]))
            self.assertEqual(module["directives"], sorted(set(module["directives"])))
            self.assertTrue(set(module["source_files"]).issubset(catalog["source_sha256"]))

    def test_optional_modules_and_ndk_command_are_included(self):
        if self.catalog["version"] != "1.31.8.1":
            self.skipTest("Pinned source coverage applies to OpenResty 1.31.8.1")
        self.assertEqual(self.catalog["module_count"], 22)
        self.assertEqual(self.catalog["command_array_count"], 128)
        self.assertEqual(len(self.catalog["directives"]), 914)
        disabled = {m["configure_name"] for m in self.catalog["modules"] if not m["default_enabled"]}
        self.assertEqual(disabled, {"http_iconv", "http_drizzle", "http_postgres"})
        expected = {"drizzle_query", "postgres_query", "set_iconv", "upstream_list",
                    "http", "stream", "http2", "content_by_lua_block", "lua_shared_dict",
                    "more_set_headers"}
        self.assertTrue(expected.issubset(self.catalog["directives"]))
        self.assertTrue({"set_concat2", "set_prepend_hello"}.isdisjoint(self.catalog["directives"]))


if __name__ == "__main__":
    unittest.main()
