import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config, draft, editor, workbench

SOURCE = '''"""Demo source."""
import json

DATA = "x"


def load():
    """Load."""
    if not DATA:
        return []
    return json.loads(DATA)
'''


def normal(ident, name="步骤", **extra):
    block = {"id": ident, "type": "normal", "name": name, "description": "描述"}
    block.update(extra)
    return block


def view(view_id, blocks, name=None, description="视图描述"):
    return {
        "view": {"id": view_id, "name": name or view_id, "description": description},
        "blocks": blocks,
    }


def write_workspace(directory: Path, views, *, entry=None, files=("app.py",)):
    (directory / "app.py").write_text(SOURCE, encoding="utf-8")
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": list(files),
        "views": {"suffix": ".blocks.json"},
    }
    if entry:
        manifest["views"]["entry"] = entry
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for config in views:
        (directory / f"{config['view']['id']}.blocks.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_draft(directory: Path, name: str, data) -> Path:
    target = directory / name
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


class WorkbenchDraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_compile_allocates_ids_and_resolves_keys(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-load", "name": "读取", "description": "读取细节"},
            "file": "app.py",
            "blocks": [
                {"key": "entry", "name": "入口", "description": "进入函数",
                 "map": "7-8"},
                {"key": "check", "type": "branch", "name": "判断",
                 "description": "检查数据", "map": "9", "select": "single",
                 "branches": [
                     {"condition": "空", "steps": [
                         {"key": "empty", "name": "返回空", "description": "返回空列表",
                          "map": "10", "next": "end"},
                     ]},
                     {"condition": "有值", "steps": [
                         {"key": "read", "name": "解析", "description": "解析 JSON",
                          "map": "11", "next": "entry"},
                     ]},
                 ]},
            ],
        }
        config = draft.compile_drafts(self.directory, [spec])[0]
        blocks = config["blocks"]
        self.assertEqual([block["id"] for block in blocks], [1, 2])
        self.assertEqual([step["id"] for step in blocks[1]["branches"][0]["steps"]], [3])
        self.assertEqual([step["id"] for step in blocks[1]["branches"][1]["steps"]], [4])
        self.assertIsNone(blocks[1]["branches"][0]["steps"][0]["next"])
        self.assertEqual(blocks[1]["branches"][1]["steps"][0]["next"], 1)
        self.assertEqual(blocks[0]["code_mapping"]["lines"], ["7-8"])

    def test_compile_try_draft(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-try", "name": "尝试", "description": "try 细节"},
            "file": "app.py",
            "blocks": [{
                "key": "try", "type": "branch", "kind": "try", "name": "尝试",
                "description": "读取并处理错误", "map": "9",
                "branches": [
                    {"role": "body", "steps": [
                        {"key": "read", "name": "读取", "description": "读取数据",
                         "map": "10", "next": "end"},
                    ]},
                    {"role": "except", "condition": "ValueError", "steps": [
                        {"key": "fallback", "name": "回退", "description": "返回空",
                         "map": "11", "next": "end"},
                    ]},
                ],
            }],
        }
        config = draft.compile_drafts(self.directory, [spec])[0]
        block = config["blocks"][0]
        self.assertEqual(block["kind"], "try")
        self.assertEqual([branch["role"] for branch in block["branches"]],
                         ["body", "except"])

    def test_duplicate_key_is_rejected(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-dup", "name": "重复", "description": "重复 key"},
            "file": "app.py",
            "blocks": [
                {"key": "same", "name": "一", "description": "一", "map": 7},
                {"key": "same", "name": "二", "description": "二", "map": 8},
            ],
        }
        with self.assertRaisesRegex(ValueError, "key 重复"):
            draft.compile_drafts(self.directory, [spec])

    def test_null_mapping_means_no_mapping(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-nomap", "name": "无映射", "description": "无映射"},
            "blocks": [{"name": "开始", "description": "开始", "map": None}],
        }
        config = draft.compile_drafts(self.directory, [spec])[0]
        self.assertNotIn("code_mapping", config["blocks"][0])

    def test_bundle_resolves_cross_view_keys(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        bundle = {"views": [
            {"view": {"id": "detail", "name": "细节", "description": "细节视图"},
             "file": "app.py",
             "blocks": [{"key": "start", "name": "开始", "description": "开始",
                         "map": "7-8"}]},
            {"view": {"id": "entry", "name": "入口", "description": "入口视图"},
             "file": "app.py",
             "blocks": [{"key": "go", "name": "打开", "description": "打开细节",
                         "map": "1-2", "jump": "detail:start"}]},
        ]}
        path = write_draft(self.directory, "bundle.json", bundle)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workbench.main(["apply", str(self.directory), str(path)]), 0)
        entry_data = json.loads((self.directory / "entry.blocks.json").read_text(encoding="utf-8"))
        self.assertEqual(entry_data["blocks"][0]["jump"], {"view": "detail", "id": 1})
        detail_data = json.loads((self.directory / "detail.blocks.json").read_text(encoding="utf-8"))
        self.assertEqual(detail_data["blocks"][0]["id"], 1)

    def test_dry_run_does_not_write(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-dry", "name": "干跑", "description": "干跑视图"},
            "file": "app.py",
            "blocks": [{"name": "开始", "description": "开始", "map": 7}],
        }
        path = write_draft(self.directory, "dry.json", spec)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["apply", str(self.directory), str(path), "--dry-run"]), 0)
        self.assertFalse((self.directory / "fn-dry.blocks.json").exists())
        self.assertIn('"id": 1', output.getvalue())

    def test_strict_apply_rolls_back_uncovered_view(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        spec = {
            "view": {"id": "fn-strict", "name": "严格", "description": "严格视图"},
            "file": "app.py",
            "blocks": [{"name": "开始", "description": "开始", "map": 7}],
        }
        path = write_draft(self.directory, "strict.json", spec)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(workbench.main(
                ["apply", str(self.directory), str(path), "--strict"]), 1)
        self.assertFalse((self.directory / "fn-strict.blocks.json").exists())

    def test_external_jump_break_rolls_back(self):
        write_workspace(self.directory, [
            view("main", [normal(1, jump={"view": "detail", "id": 5})]),
            view("detail", [normal(5, "开始", code_mapping={
                "file": "app.py", "lines": ["7-8"]})]),
        ], entry="main")
        before = (self.directory / "detail.blocks.json").read_bytes()
        spec = {
            "view": {"id": "detail", "description": "更新细节"},
            "file": "app.py",
            "blocks": [{"name": "新开始", "description": "新开始", "map": "7-8"}],
        }
        path = write_draft(self.directory, "update.json", spec)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(workbench.main(
                ["apply", str(self.directory), str(path)]), 1)
        self.assertIn("detail", stderr.getvalue())
        self.assertEqual((self.directory / "detail.blocks.json").read_bytes(), before)

    def test_update_with_explicit_id_keeps_external_jump(self):
        write_workspace(self.directory, [
            view("main", [normal(1, jump={"view": "detail", "id": 5})]),
            view("detail", [normal(5, "开始", code_mapping={
                "file": "app.py", "lines": ["7-8"]})]),
        ], entry="main")
        spec = {
            "view": {"id": "detail", "description": "更新细节"},
            "file": "app.py",
            "blocks": [{"id": 5, "name": "新开始", "description": "新开始",
                        "map": "7-8"}],
        }
        path = write_draft(self.directory, "update-keep.json", spec)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workbench.main(
                ["apply", str(self.directory), str(path)]), 0)
        payload = block_config.load(str(self.directory), "main")
        self.assertEqual(payload["config"]["blocks"][0]["jump"],
                         {"view": "detail", "id": 5})
        detail_data = json.loads((self.directory / "detail.blocks.json").read_text(encoding="utf-8"))
        self.assertEqual(detail_data["blocks"][0]["id"], 5)

    def test_update_existing_flat_view_with_branch(self):
        write_workspace(self.directory, [
            view("main", [normal(1, code_mapping={"file": "app.py", "lines": [1]})]),
        ], entry="main")
        flat_view = {
            "view": {"id": "flow", "name": "流程", "description": "流程描述"},
            "containers": [
                {"id": "root", "kind": "root", "blocks": [1]},
                {"id": "c1-0", "kind": "branch", "parent": 1, "blocks": [2]},
            ],
            "blocks": [
                normal(1, "判断", type="branch", select="single", branches=["c1-0"]),
                normal(2, "执行", code_mapping={"file": "app.py", "lines": [3]}),
            ],
        }
        (self.directory / "flow.blocks.json").write_text(
            json.dumps(flat_view, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        spec = {
            "view": {"id": "flow", "description": "更新 flat 视图"},
            "file": "app.py",
            "blocks": [
                {"id": 1, "type": "branch", "select": "single", "name": "判断",
                 "description": "判断条件", "map": [3], "branches": [
                     {"condition": "成立", "steps": [
                         {"id": 2, "name": "执行", "description": "执行步骤",
                          "map": [4], "next": "end"},
                     ]},
                 ]},
            ],
        }
        path = write_draft(self.directory, "update-flat.json", spec)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workbench.main(
                ["apply", str(self.directory), str(path)]), 0)
        payload = block_config.load(str(self.directory), "flow")
        self.assertEqual(payload["schema"], "flat")
        self.assertEqual(payload["config"]["blocks"][0]["name"], "判断")

    def test_brief_json_reports_uncovered_and_next_id(self):
        write_workspace(self.directory, [
            view("main", [normal(1, code_mapping={"file": "app.py", "lines": [1]})]),
        ], entry="main")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["brief", str(self.directory), "--view", "main", "--json"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["view"]["next_id"], 2)
        self.assertTrue(data["files"][0]["uncovered"])
        self.assertEqual(data["view"]["config"]["blocks"][0]["id"], 1)

    def test_brief_snippets_include_source_text(self):
        write_workspace(self.directory, [
            view("main", [normal(1, code_mapping={"file": "app.py", "lines": [1]})]),
        ], entry="main")
        data = workbench.collect_brief(str(self.directory), "main", snippets=True)
        texts = [item["text"] for item in data["snippets"]["lines"]]
        self.assertIn("import json", texts)

    def test_check_reports_coherence_and_strict_fails(self):
        main = view("main", [normal(1, next=None)], name="主线")
        main["view"]["kind"] = "main"
        entry = view("entry-run", [normal(1, next=None)], name="入口")
        entry["view"]["kind"] = "entry"
        write_workspace(self.directory, [main, entry], entry="main")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["check", str(self.directory), "--json"]), 1)
        data = json.loads(output.getvalue())
        self.assertLess(data["narrative"]["coherence"]["score"], 1)
        self.assertTrue(data["narrative"]["coherence"]["orphans"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workbench.main(
                ["check", str(self.directory), "--strict"]), 1)

    def test_coherence_command_passes_for_linked_views(self):
        main = view("main", [normal(1, flow={"view": "entry-run", "id": 1})])
        main["view"]["kind"] = "main"
        entry = view("entry-run", [normal(1, next=None)])
        entry["view"]["kind"] = "entry"
        write_workspace(self.directory, [main, entry], entry="main")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["coherence", str(self.directory), "--json"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["score"], 1.0)
        self.assertEqual(data["reachable"], 2)

    def test_coherence_command_reports_orphan(self):
        main = view("main", [normal(1, next=None)])
        main["view"]["kind"] = "main"
        entry = view("entry-run", [normal(1, next=None)])
        entry["view"]["kind"] = "entry"
        write_workspace(self.directory, [main, entry], entry="main")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["coherence", str(self.directory), "--json"]), 1)
        data = json.loads(output.getvalue())
        self.assertEqual(data["orphans"], ["entry-run"])

    def test_batch_save_updates_two_views(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("detail", [normal(1)]),
        ], entry="main")
        result = editor.save_views(str(self.directory), [
            view("main", [normal(1, "入口")]),
            view("detail", [normal(1, "细节")]),
        ])
        self.assertEqual(result["updated"], ["main", "detail"])
        self.assertEqual(result["created"], [])


if __name__ == "__main__":
    unittest.main()
