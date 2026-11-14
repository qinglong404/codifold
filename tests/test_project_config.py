import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codifold import mapping_report, validate
from codifold.project_config import load_manifest


SOURCE = """x = 1
# comment
y = 2

print(x + y)
"""


def write_project(directory: Path, mappings, *, manifest=True):
    (directory / "sample.py").write_text(SOURCE, encoding="utf-8")
    if manifest:
        (directory / "codifold.json").write_text(json.dumps({
            "project": {"name": "测试项目", "description": "测试描述", "root": "."},
            "files": ["sample.py"],
            "views": {"suffix": ".blocks.json", "entry": "main"},
        }), encoding="utf-8")
    blocks = []
    for index, lines in enumerate(mappings, 1):
        blocks.append({
            "id": index, "type": "normal", "name": f"块 {index}", "description": "描述",
            "code_mapping": {"file": "sample.py", "lines": lines},
        })
    (directory / "main.blocks.json").write_text(json.dumps({
        "view": {"id": "main", "name": "主视图", "description": "主视图描述"},
        "blocks": blocks,
    }), encoding="utf-8")


def write_views(directory: Path, views, *, entry=None, files=None):
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": files or [],
        "views": {"suffix": ".blocks.json"},
    }
    if entry:
        manifest["views"]["entry"] = entry
    (directory / "codifold.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                             encoding="utf-8")
    for view in views:
        (directory / f"{view['view']['id']}.blocks.json").write_text(
            json.dumps(view, ensure_ascii=False), encoding="utf-8")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_manifest_resolves_root_and_files(self):
        (self.directory / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.directory / "codifold.json").write_text(json.dumps({
            "project": {"name": "项目", "description": "项目描述", "root": "."},
            "files": ["a.py"],
        }), encoding="utf-8")
        manifest = load_manifest(self.directory)
        self.assertEqual(manifest["name"], "项目")
        self.assertEqual(manifest["description"], "项目描述")
        self.assertEqual(manifest["files"], ["a.py"])
        self.assertEqual(manifest["suffix"], ".blocks.json")
        self.assertIsNone(manifest["entry"])
        self.assertEqual(manifest["paths"]["a.py"], (self.directory / "a.py").resolve())

    def test_manifest_is_optional(self):
        self.assertIsNone(load_manifest(self.directory))

    def test_manifest_rejects_missing_file(self):
        (self.directory / "codifold.json").write_text(json.dumps({
            "project": {"name": "项目", "description": "描述", "root": "."},
            "files": ["missing.py"],
        }), encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            load_manifest(self.directory)

    def test_manifest_rejects_duplicates_and_escapes(self):
        (self.directory / "a.py").write_text("x = 1\n", encoding="utf-8")
        for files in (["a.py", "a.py"], ["../a.py"], ["/etc/passwd"]):
            (self.directory / "codifold.json").write_text(json.dumps({
                "project": {"name": "项目", "description": "描述", "root": "."},
                "files": files,
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manifest(self.directory)

    def test_manifest_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.py"
            outside.write_text("x = 1\n", encoding="utf-8")
            (self.directory / "link.py").symlink_to(outside)
            (self.directory / "codifold.json").write_text(json.dumps({
                "project": {"name": "项目", "description": "描述", "root": "."},
                "files": ["link.py"],
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_manifest(self.directory)
            self.assertIn("root", str(error.exception))


class MappingReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_report_computes_coverage_and_overlaps(self):
        write_project(self.directory, [[1, 3], [3, 5]])
        data = mapping_report.report(str(self.directory))
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])
        item = data["files"][0]
        self.assertEqual(item["total"], 3)
        self.assertEqual(item["covered"], 3)
        self.assertEqual(item["ratio"], 1.0)
        self.assertEqual(item["uncovered"], [])
        self.assertEqual(item["overlaps"], [{"start": 3, "end": 3, "blocks": [1, 2]}])

    def test_report_lists_uncovered_and_non_code_mappings(self):
        write_project(self.directory, [[1, 2]])
        data = mapping_report.report(str(self.directory))
        item = data["files"][0]
        self.assertEqual(item["covered"], 1)
        self.assertEqual(item["uncovered"], [{"start": 3, "end": 3}, {"start": 5, "end": 5}])
        self.assertEqual(item["outside"], [{"start": 2, "end": 2}])
        self.assertTrue(data["warnings"])

    def test_report_requires_manifest(self):
        write_project(self.directory, [[1]], manifest=False)
        with self.assertRaises(ValueError) as error:
            mapping_report.report(str(self.directory))
        self.assertIn("codifold.json", str(error.exception))

    def test_report_flags_unreachable_blocks(self):
        write_views(self.directory, [{
            "view": {"id": "main", "name": "主视图", "description": "描述"},
            "blocks": [
                {"id": 1, "type": "normal", "name": "终止", "description": "描述", "next": None},
                {"id": 2, "type": "normal", "name": "死代码", "description": "描述"},
            ],
        }], entry="main")
        data = mapping_report.report(str(self.directory))
        self.assertTrue(any("不可达" in warning for warning in data["warnings"]))
        self.assertEqual([item["id"] for item in data["views"][0]["unreachable"]], [2])

    def test_report_flags_cross_view_jump_missing_id(self):
        write_views(self.directory, [
            {"view": {"id": "main", "name": "主视图", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "跳转", "description": "描述",
                         "jump": {"view": "other", "id": 99}}]},
            {"view": {"id": "other", "name": "辅助", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "目标", "description": "描述"}]},
        ], entry="main")
        data = mapping_report.report(str(self.directory))
        self.assertFalse(data["ok"])
        self.assertTrue(any("jump" in error and "99" in error for error in data["errors"]))

    def test_report_accepts_cross_view_jump_existing_id(self):
        write_views(self.directory, [
            {"view": {"id": "main", "name": "主视图", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "跳转", "description": "描述",
                         "jump": {"view": "other", "id": 1}}]},
            {"view": {"id": "other", "name": "辅助", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "目标", "description": "描述"}]},
        ], entry="main")
        data = mapping_report.report(str(self.directory))
        self.assertTrue(data["ok"])
        self.assertEqual(data["errors"], [])

    def test_cli_fails_on_cross_view_jump_error(self):
        write_views(self.directory, [
            {"view": {"id": "main", "name": "主视图", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "跳转", "description": "描述",
                         "jump": {"view": "other", "id": 99}}]},
            {"view": {"id": "other", "name": "辅助", "description": "描述"},
             "blocks": [{"id": 1, "type": "normal", "name": "目标", "description": "描述"}]},
        ], entry="main")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main([str(self.directory)]), 1)

    def test_cli_json_and_strict(self):
        write_project(self.directory, [[1, 3], [3, 5]])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = validate.main([str(self.directory), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["files"][0]["ratio"], 1.0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main([str(self.directory)]), 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main([str(self.directory), "--strict"]), 1)


if __name__ == "__main__":
    unittest.main()
