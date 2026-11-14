import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config


def view(view_id="alpha", name="视图", description="描述"):
    data = {"name": name, "description": description}
    if view_id is not None:
        data["id"] = view_id
    return {"view": data, "blocks": [
        {"id": 1, "type": "normal", "name": "开始", "description": "入口"},
    ]}


class ViewIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.write_manifest()

    def write_manifest(self, files=None, entry=None, suffix=".blocks.json"):
        manifest = {
            "project": {"name": "测试项目", "description": "测试描述", "root": "."},
            "files": files or [],
            "views": {"suffix": suffix},
        }
        if entry:
            manifest["views"]["entry"] = entry
        (self.directory / "codifold.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def write(self, name, config):
        if not name.endswith(".blocks.json"):
            name = name.removesuffix(".json") + ".blocks.json"
        target = self.directory / name
        target.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return target

    def test_index_puts_entry_first(self):
        self.write_manifest(entry="beta")
        self.write("a.json", view("alpha"))
        self.write("b.json", view("beta"))
        index = block_config.load_index(str(self.directory))
        self.assertEqual(index["source"]["kind"], "project")
        self.assertEqual(index["entry"], "beta")
        self.assertEqual([item["view_id"] for item in index["views"]], ["beta", "alpha"])
        self.assertEqual([item["file"] for item in index["views"]],
                         ["b.blocks.json", "a.blocks.json"])

    def test_index_falls_back_to_first_file(self):
        self.write("a.json", view("alpha"))
        self.write("b.json", view("beta"))
        index = block_config.load_index(str(self.directory))
        self.assertEqual(index["entry"], "alpha")
        self.assertEqual([item["view_id"] for item in index["views"]], ["alpha", "beta"])

    def test_index_rejects_duplicate_view_id(self):
        self.write("a.json", view("same"))
        self.write("b.json", view("same"))
        with self.assertRaises(ValueError) as error:
            block_config.load_index(str(self.directory))
        self.assertIn("重复", str(error.exception))

    def test_index_ignores_non_suffix_json(self):
        self.write("a.json", view("alpha"))
        (self.directory / "legacy.json").write_text('{"blocks": []}', encoding="utf-8")
        index = block_config.load_index(str(self.directory))
        self.assertEqual([item["view_id"] for item in index["views"]], ["alpha"])

    def test_index_rejects_view_file_without_view(self):
        (self.directory / "bad.blocks.json").write_text(
            '{"blocks": [{"id": 1, "type": "normal", "name": "x", "description": "y"}]}',
            encoding="utf-8")
        with self.assertRaises(ValueError) as error:
            block_config.load_index(str(self.directory))
        self.assertIn("view", str(error.exception))

    def test_index_rejects_invalid_view_id(self):
        self.write("a.json", view("Bad ID"))
        with self.assertRaises(ValueError) as error:
            block_config.load_index(str(self.directory))
        self.assertIn("view.id", str(error.exception))

    def test_index_rejects_unknown_entry(self):
        self.write_manifest(entry="missing")
        self.write("a.json", view("alpha"))
        with self.assertRaises(ValueError) as error:
            block_config.load_index(str(self.directory))
        self.assertIn("views.entry", str(error.exception))

    def test_index_does_not_validate_blocks(self):
        broken = view("broken")
        broken["blocks"][0].pop("name")
        self.write("broken.json", broken)
        index = block_config.load_index(str(self.directory))
        self.assertEqual(index["entry"], "broken")
        with self.assertRaises(ValueError):
            block_config.load(str(self.directory), "broken")

    def test_load_by_view_id(self):
        self.write("a.json", view("alpha", name="甲"))
        self.write("b.json", view("beta", name="乙"))
        data = block_config.load(str(self.directory), "beta")
        self.assertEqual(data["view"]["view_id"], "beta")
        self.assertEqual(data["source"]["kind"], "project")
        self.assertEqual(data["order"], [1])
        self.assertEqual(data["config"]["view"]["name"], "乙")

    def test_load_uses_entry_when_view_missing(self):
        self.write_manifest(entry="beta")
        self.write("a.json", view("alpha"))
        self.write("b.json", view("beta"))
        data = block_config.load(str(self.directory))
        self.assertEqual(data["view"]["view_id"], "beta")

    def test_unknown_view_is_rejected(self):
        self.write("a.json", view("alpha"))
        with self.assertRaises(ValueError) as error:
            block_config.load(str(self.directory), "missing")
        self.assertIn("找不到视图", str(error.exception))

    def test_single_file_index(self):
        target = self.write("solo.json", view("solo"))
        index = block_config.load_index(str(target))
        self.assertEqual(index["entry"], "solo")
        self.assertEqual(len(index["views"]), 1)
        data = block_config.load(str(target))
        self.assertEqual(data["view"]["view_id"], "solo")
        self.assertEqual(data["source"]["kind"], "file")

    def test_single_file_rejects_unknown_view(self):
        target = self.write("solo.json", view("solo"))
        with self.assertRaises(ValueError):
            block_config.load(str(target), "other")

    def handler(self, view_id="handler", entry=True):
        block = {"id": 1, "type": "normal", "name": "入口", "description": "描述"}
        if entry:
            block["on"] = "device.click"
        return {"view": {"id": view_id, "name": view_id, "description": "描述"},
                "blocks": [block]}

    def source(self, emit):
        return {"view": {"id": "source", "name": "source", "description": "描述"},
                "blocks": [{"id": 1, "type": "normal", "name": "发出",
                            "description": "描述", "emit": emit}]}

    def test_cross_view_emit_accepts_event_entry(self):
        self.write("handler.json", self.handler())
        self.write("source.json", self.source([{"view": "handler", "id": 1}]))
        data = block_config.load(str(self.directory), "source")
        self.assertEqual(data["config"]["blocks"][0]["emit"], [{"view": "handler", "id": 1}])

    def test_cross_view_emit_rejects_non_entry(self):
        self.write("handler.json", self.handler(entry=False))
        self.write("source.json", self.source([{"view": "handler", "id": 1}]))
        with self.assertRaises(ValueError) as error:
            block_config.load(str(self.directory), "source")
        self.assertIn("不是事件入口", str(error.exception))

    def test_cross_view_emit_rejects_missing_target(self):
        self.write("handler.json", self.handler())
        self.write("source.json", self.source([{"view": "handler", "id": 99}]))
        with self.assertRaises(ValueError) as error:
            block_config.load(str(self.directory), "source")
        self.assertIn("不存在的 id", str(error.exception))

    def test_cross_view_emit_rejects_unknown_view(self):
        self.write("source.json", self.source([{"view": "missing", "id": 1}]))
        with self.assertRaises(ValueError) as error:
            block_config.load(str(self.directory), "source")
        self.assertIn("不存在的视图", str(error.exception))

    def test_default_project_lists_all_views(self):
        index = block_config.load_index()
        self.assertEqual(index["source"]["kind"], "project")
        self.assertEqual(index["entry"], "gradebook")
        self.assertEqual(index["project"]["name"], "学生成绩管理")
        self.assertEqual([item["view_id"] for item in index["views"]], ["gradebook"])


if __name__ == "__main__":
    unittest.main()
