import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config, draft, editor, mapping_report, narrative, workbench


def normal(ident, name="步骤", **extra):
    block = {"id": ident, "type": "normal", "name": name, "description": "描述"}
    block.update(extra)
    return block


def view(view_id, blocks, kind=None, name=None, description="视图描述"):
    data = {"id": view_id, "name": name or view_id, "description": description}
    if kind:
        data["kind"] = kind
    return {"view": data, "blocks": blocks}


def write_workspace(directory: Path, views):
    (directory / "app.py").write_text("x = 1\n", encoding="utf-8")
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": ["app.py"],
        "views": {"suffix": ".blocks.json", "entry": "main"},
    }
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for config in views:
        (directory / f"{config['view']['id']}.blocks.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class KindAndFlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_index_infers_view_kind(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("entry-run", [normal(1)]),
            view("fn-load", [normal(1)]),
            view("mod-config", [normal(1)]),
            view("struct", [normal(1)]),
            view("toolbox", [normal(1)]),
        ])
        index = block_config.load_index(str(self.directory))
        kinds = {item["view_id"]: item["kind"] for item in index["views"]}
        self.assertEqual(kinds["main"], "main")
        self.assertEqual(kinds["entry-run"], "entry")
        self.assertEqual(kinds["fn-load"], "function")
        self.assertEqual(kinds["mod-config"], "struct")
        self.assertEqual(kinds["struct"], "struct")
        self.assertEqual(kinds["toolbox"], "toolbox")

    def test_flow_requires_external_allowed_target(self):
        write_workspace(self.directory, [
            view("main", [normal(1, flow={"view": "entry-run", "id": 1})],
                 kind="main"),
            view("entry-run", [normal(1, next=None)], kind="entry"),
            view("fn-load", [normal(1, next=None)], kind="function"),
        ])
        payload = block_config.load(str(self.directory), "main")
        self.assertEqual(payload["config"]["blocks"][0]["flow"]["view"],
                         "entry-run")

        invalid = {
            "view": {"id": "main", "name": "主线", "description": "描述",
                     "kind": "main"},
            "blocks": [normal(1, flow={"view": "fn-load", "id": 1})],
        }
        (self.directory / "main.blocks.json").write_text(
            json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "主线/流程/入口"):
            block_config.load(str(self.directory), "main")

    def test_flow_requires_view_field(self):
        config = {
            "view": {"id": "main", "name": "主线", "description": "描述"},
            "blocks": [normal(1, flow={"id": 1})],
        }
        with self.assertRaisesRegex(ValueError, "flow 必须指向"):
            block_config.validate(config)

    def test_narrative_flags_unreachable_entry(self):
        write_workspace(self.directory, [
            view("main", [normal(1, next=None)], kind="main"),
            view("entry-run", [normal(1, next=None)], kind="entry"),
        ])
        data = narrative.report(self.directory)
        self.assertFalse(data["skipped"])
        self.assertIn("无法从 main", "；".join(data["warnings"]))
        self.assertIn("没有任何 flow", "；".join(data["warnings"]))
        self.assertEqual(data["coherence"]["score"], 0.5)
        self.assertIn("连贯性", "；".join(data["errors"]))

    def test_narrative_flags_detail_only_dead_end(self):
        write_workspace(self.directory, [
            view("main", [normal(1, jump={"view": "fn-load", "id": 1},
                               next=None)], kind="main"),
            view("fn-load", [normal(1, next=None)], kind="function"),
        ])
        data = narrative.report(self.directory)
        self.assertIn("只有实现跳转", "；".join(data["warnings"]))

    def test_flow_makes_entry_reachable(self):
        write_workspace(self.directory, [
            view("main", [normal(1, flow={"view": "entry-run", "id": 1},
                               next=None)], kind="main"),
            view("entry-run", [normal(1, next=None)], kind="entry"),
        ])
        data = narrative.report(self.directory)
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["warnings"], [])
        self.assertEqual(data["coherence"]["score"], 1.0)

    def test_entry_reachable_through_jump_and_flow(self):
        write_workspace(self.directory, [
            view("main", [
                normal(1, flow={"view": "entry-main", "id": 1}),
                normal(2, jump={"view": "fn-worker", "id": 1}),
            ], kind="main"),
            view("entry-main", [normal(1, next=None)], kind="entry"),
            view("fn-worker", [normal(1, flow={"view": "entry-side", "id": 1},
                               next=None)], kind="function"),
            view("entry-side", [normal(1, next=None)], kind="entry"),
        ])
        data = narrative.report(self.directory)
        self.assertEqual(data["errors"], [])
        self.assertNotIn("entry-side", "；".join(data["warnings"]))

    def test_function_collection_allows_independent_blocks(self):
        write_workspace(self.directory, [
            view("main", [normal(1, next=None)], kind="main"),
            view("fn-collection", [
                normal(1, next=None), normal(2, next=None),
            ], kind="function"),
        ])
        report = mapping_report.report(str(self.directory))
        self.assertFalse(any("不可达" in warning for warning in report["warnings"]))

    def test_workbench_draft_supports_kind_and_flow(self):
        write_workspace(self.directory, [
            view("main", [normal(1, next=None)]),
        ])
        bundle = {"views": [
            {
                "view": {"id": "main", "name": "主线", "kind": "main",
                         "description": "入口主线"},
                "blocks": [{"key": "go", "name": "运行", "description": "进入入口",
                            "next": "end", "flow": "entry-run:start"}],
            },
            {
                "view": {"id": "entry-run", "name": "运行入口", "kind": "entry",
                         "description": "事件入口"},
                "blocks": [{"key": "start", "name": "开始", "description": "开始",
                            "next": "end"}],
            },
        ]}
        configs = draft.compile_drafts(self.directory, bundle["views"])
        self.assertEqual(configs[0]["view"]["kind"], "main")
        self.assertEqual(configs[0]["blocks"][0]["flow"],
                         {"view": "entry-run", "id": 1})
        result = editor.save_views(str(self.directory), configs)
        self.assertEqual(result["updated"], ["main"])
        self.assertEqual(result["created"], ["entry-run"])
        loaded = block_config.load(str(self.directory), "main")
        self.assertEqual(loaded["config"]["blocks"][0]["flow"],
                         {"view": "entry-run", "id": 1})


if __name__ == "__main__":
    unittest.main()
