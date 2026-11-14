import json
import tempfile
import unittest
from pathlib import Path

from codifold import block_config, editor, flat, flat_ops, workbench


def normal(ident, name="步骤", **extra):
    block = {"id": ident, "type": "normal", "name": name, "description": "描述"}
    block.update(extra)
    return block


def nested_view():
    return {
        "view": {"id": "main", "name": "主流程", "description": "测试",
                 "kind": "main"},
        "blocks": [
            normal(1, "开始", next=2),
            {
                "id": 2, "type": "branch", "name": "选择", "description": "分支",
                "select": "single",
                "branches": [
                    {"condition": "A", "steps": [normal(3, "A 步", next=None)]},
                    {"condition": "B", "steps": [normal(4, "B 步", next=None)]},
                ],
            },
            {
                "id": 5, "type": "branch", "kind": "try", "name": "尝试",
                "description": "try", "select": "single",
                "branches": [
                    {"role": "body", "steps": [normal(6, "主体", next=None)]},
                    {"role": "except", "condition": "ValueError",
                     "steps": [normal(7, "异常", next=None)]},
                ],
                "finally": [normal(8, "收尾", next=None)],
            },
        ],
    }


class FlatSchemaTests(unittest.TestCase):
    def test_round_trip_preserves_nested_view(self):
        nested = block_config.validate(nested_view())
        flat_config = flat.from_nested(nested)
        self.assertEqual(flat_config["containers"][0]["id"], "root")
        self.assertIn("c2-0", [item["id"] for item in flat_config["containers"]])
        self.assertIn("f5", [item["id"] for item in flat_config["containers"]])
        self.assertEqual(flat.validate_flat(flat_config), nested)

    def test_duplicate_membership_is_rejected(self):
        nested = block_config.validate(nested_view())
        flat_config = flat.from_nested(nested)
        flat_config["containers"][0]["blocks"].append(3)
        with self.assertRaisesRegex(ValueError, "同时属于"):
            flat.validate_flat(flat_config)

    def test_wrong_container_parent_is_rejected(self):
        nested = block_config.validate(nested_view())
        flat_config = flat.from_nested(nested)
        container = next(item for item in flat_config["containers"]
                         if item["id"] == "c2-0")
        container["parent"] = 5
        with self.assertRaisesRegex(ValueError, "parent=2"):
            flat.validate_flat(flat_config)

    def test_container_cycle_is_rejected(self):
        config = {
            "view": {"id": "main", "name": "主流程", "description": "测试"},
            "containers": [
                {"id": "root", "kind": "root", "blocks": [1]},
                {"id": "c2-0", "kind": "branch", "parent": 2, "blocks": [2]},
            ],
            "blocks": [
                normal(1),
                {"id": 2, "type": "branch", "name": "循环", "description": "循环",
                 "select": "single", "branches": ["c2-0"]},
            ],
        }
        with self.assertRaisesRegex(ValueError, "形成环"):
            flat.validate_flat(config)


class FlatEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_create_workspace_writes_flat_view(self):
        target = self.base / "project"
        editor.create_workspace(str(target), "项目", "描述")
        raw = json.loads((target / "main.blocks.json").read_text(encoding="utf-8"))
        self.assertIn("containers", raw)
        manifest = json.loads((target / "codifold.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["views"]["format"], "flat")

    def test_save_nested_update_keeps_flat_format(self):
        target = self.base / "project"
        result = editor.create_workspace(str(target), "项目", "描述")
        config = result["payload"]["config"]
        config["blocks"][0]["name"] = "新开始"
        editor.save_view(str(target), config)
        raw = json.loads((target / "main.blocks.json").read_text(encoding="utf-8"))
        self.assertIn("containers", raw)
        self.assertEqual(raw["blocks"][0]["name"], "新开始")

    def test_mutate_add_and_delete_block(self):
        target = self.base / "project"
        editor.create_workspace(str(target), "项目", "描述")
        result = editor.mutate_view(str(target), "main", "add_block",
                                     container="root", name="新块",
                                     description="新步骤")
        new_id = result["result"]["block_id"]
        self.assertEqual(result["payload"]["schema"], "flat")
        self.assertEqual(result["payload"]["order"], [1, new_id])
        result = editor.mutate_view(str(target), "main", "delete_block",
                                     block_id=new_id)
        self.assertEqual(result["payload"]["order"], [1])

    def test_mutate_add_branch_and_finally(self):
        target = self.base / "project"
        editor.create_workspace(str(target), "项目", "描述")
        config = {
            "view": {"id": "main", "name": "主流程", "description": "描述"},
            "containers": [{"id": "root", "kind": "root", "blocks": [1, 2]}],
            "blocks": [{"id": 1, "type": "normal", "name": "开始",
                        "description": "开始"}],
        }
        branch = {
            "id": 2, "type": "branch", "name": "分支", "description": "分支",
            "select": "single",
            "branches": ["c2-0"],
        }
        config["blocks"].append(branch)
        config["containers"].append({"id": "c2-0", "kind": "branch",
                                     "parent": 2, "blocks": [3]})
        config["blocks"].append({"id": 3, "type": "normal", "name": "子",
                                 "description": "子"})
        (target / "main.blocks.json").write_text(
            json.dumps(flat.from_nested(flat.validate_flat(config)),
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        result = editor.mutate_view(str(target), "main", "add_branch",
                                     block_id=2, condition="C")
        cid = result["result"]["container_id"]
        self.assertIn(cid, [item["id"] for item in result["payload"]["flat"]["containers"]])
        result = editor.mutate_view(str(target), "main", "delete_container",
                                     container_id=cid)
        self.assertNotIn(cid, [item["id"] for item in result["payload"]["flat"]["containers"]])

    def test_workbench_dry_run_prints_flat(self):
        target = self.base / "project"
        editor.create_workspace(str(target), "项目", "描述")
        draft = {
            "view": {"id": "extra", "name": "额外", "description": "额外"},
            "blocks": [{"name": "开始", "description": "开始"}],
        }
        draft_path = self.base / "draft.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False),
                              encoding="utf-8")
        output = __import__("io").StringIO()
        import contextlib
        with contextlib.redirect_stdout(output):
            self.assertEqual(workbench.main(
                ["apply", str(target), str(draft_path), "--dry-run"]), 0)
        data = json.loads(output.getvalue())
        self.assertIn("containers", data)
        self.assertEqual(data["containers"][0]["kind"], "root")

    def test_workbench_apply_writes_flat_for_flat_workspace(self):
        target = self.base / "project"
        editor.create_workspace(str(target), "项目", "描述")
        draft = {
            "view": {"id": "extra", "name": "额外", "description": "额外"},
            "file": "app.py",
            "blocks": [{"name": "开始", "description": "开始", "map": 1}],
        }
        (target / "app.py").write_text("x = 1\n", encoding="utf-8")
        manifest = json.loads((target / "codifold.json").read_text(encoding="utf-8"))
        manifest["files"] = ["app.py"]
        (target / "codifold.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        draft_path = self.base / "draft.json"
        draft_path.write_text(json.dumps(draft, ensure_ascii=False),
                              encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workbench.main(
                ["apply", str(target), str(draft_path)]), 0)
        raw = json.loads((target / "extra.blocks.json").read_text(encoding="utf-8"))
        self.assertIn("containers", raw)


if __name__ == "__main__":
    unittest.main()
