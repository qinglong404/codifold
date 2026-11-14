import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codifold import block_config, editor
from codifold.fsutil import file_revision


def normal(ident, name="步骤", **extra):
    block = {"id": ident, "type": "normal", "name": name, "description": "描述"}
    block.update(extra)
    return block


def view(view_id, blocks, name=None, description="视图描述"):
    return {
        "view": {"id": view_id, "name": name or view_id, "description": description},
        "blocks": blocks,
    }


def write_workspace(directory: Path, views, *, entry=None, files=None):
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": files or [],
        "views": {"suffix": ".blocks.json"},
    }
    if entry:
        manifest["views"]["entry"] = entry
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for config in views:
        (directory / f"{config['view']['id']}.blocks.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def read_view(self, name="main.blocks.json"):
        return json.loads((self.directory / name).read_text(encoding="utf-8"))

    def test_save_updates_existing_view(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        result = editor.save_view(str(self.directory), view(
            "main", [normal(1, "新块"), normal(2)], name="新名称"))
        self.assertFalse(result["created"])
        self.assertEqual(result["payload"]["order"], [1, 2])
        self.assertEqual(result["index"]["views"][0]["name"], "新名称")
        data = self.read_view()
        self.assertEqual([block["name"] for block in data["blocks"]], ["新块", "步骤"])
        self.assertEqual(list(self.directory.glob(".*.tmp")), [])

    def test_save_creates_new_view(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        result = editor.save_view(str(self.directory), view("extra", [normal(1)]))
        self.assertTrue(result["created"])
        self.assertTrue((self.directory / "extra.blocks.json").is_file())
        self.assertEqual([item["view_id"] for item in result["index"]["views"]],
                         ["main", "extra"])

    def test_save_rejects_invalid_config_without_writing(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        before = (self.directory / "main.blocks.json").read_bytes()
        with self.assertRaises(ValueError):
            editor.save_view(str(self.directory), view("main", [normal(1, next=99)]))
        self.assertEqual((self.directory / "main.blocks.json").read_bytes(), before)
        self.assertEqual(list(self.directory.glob(".*.tmp")), [])

    def test_save_rolls_back_when_cross_view_jump_breaks(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("other", [normal(1, jump={"view": "main", "id": 1})]),
        ], entry="main")
        before = (self.directory / "main.blocks.json").read_bytes()
        with self.assertRaises(ValueError) as error:
            editor.save_view(str(self.directory), view("main", [normal(2)]))
        self.assertIn("jump", str(error.exception))
        self.assertEqual((self.directory / "main.blocks.json").read_bytes(), before)

    def test_save_rejects_single_file(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        with self.assertRaises(ValueError):
            editor.save_view(str(self.directory / "main.blocks.json"),
                             view("main", [normal(1)]))

    def test_save_requires_manifest(self):
        config = view("main", [normal(1)])
        (self.directory / "main.blocks.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError) as error:
            editor.save_view(str(self.directory), config)
        self.assertIn("codifold.json", str(error.exception))

    def test_save_rejects_view_file_outside_workspace(self):
        outside = self.directory / "outside" / "main.blocks.json"
        outside.parent.mkdir()
        write_workspace(self.directory, [], entry="main")
        outside.write_text(json.dumps(view("main", [normal(1)]), ensure_ascii=False),
                           encoding="utf-8")
        (self.directory / "main.blocks.json").symlink_to(outside)
        with self.assertRaises(ValueError) as error:
            editor.save_view(str(self.directory), view("main", [normal(2)]))
        self.assertIn("工作区目录", str(error.exception))

    def test_event_names_are_collected(self):
        write_workspace(self.directory, [
            view("main", [normal(1, on="device.click"), normal(2)]),
            view("other", [normal(1, on="timer.tick")]),
        ], entry="main")
        self.assertEqual(editor.event_names(str(self.directory))["events"],
                         ["device.click", "timer.tick"])

    def test_delete_view_updates_entry(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("other", [normal(1)]),
        ], entry="main")
        result = editor.delete_view(str(self.directory), "main")
        self.assertFalse((self.directory / "main.blocks.json").exists())
        self.assertEqual(result["entry"], "other")
        manifest = json.loads((self.directory / "codifold.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["views"]["entry"], "other")

    def test_delete_view_refuses_references(self):
        write_workspace(self.directory, [
            view("main", [normal(1, on="device.click")]),
            view("other", [normal(1, emit=[{"view": "main", "id": 1}])]),
        ], entry="main")
        with self.assertRaises(ValueError) as error:
            editor.delete_view(str(self.directory), "main")
        self.assertIn("引用", str(error.exception))
        self.assertTrue((self.directory / "main.blocks.json").is_file())

    def test_delete_last_view_is_refused(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        with self.assertRaises(ValueError) as error:
            editor.delete_view(str(self.directory), "main")
        self.assertIn("最后一个", str(error.exception))
        self.assertTrue((self.directory / "main.blocks.json").is_file())

    def test_create_workspace(self):
        target = self.directory / "new-project"
        result = editor.create_workspace(str(target), "新项目", "项目描述")
        self.assertEqual(result["index"]["entry"], "main")
        self.assertEqual(result["payload"]["order"], [1])
        self.assertTrue((target / "codifold.json").is_file())
        self.assertTrue((target / "main.blocks.json").is_file())
        manifest = json.loads((target / "codifold.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"], [])
        self.assertEqual(manifest["views"]["entry"], "main")
        self.assertEqual(list(target.glob(".*.tmp")), [])

    def test_create_workspace_rejects_non_empty_directory(self):
        target = self.directory / "occupied"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError) as error:
            editor.create_workspace(str(target), "新项目", "项目描述")
        self.assertIn("不是空", str(error.exception))
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_create_workspace_requires_absolute_directory(self):
        with self.assertRaises(ValueError) as error:
            editor.create_workspace("relative-project", "新项目", "项目描述")
        self.assertIn("绝对路径", str(error.exception))


    def test_index_and_payload_expose_revisions(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        index = block_config.load_index(str(self.directory))
        payload = block_config.load(str(self.directory), "main")
        self.assertEqual(index["views"][0]["revision"],
                         file_revision(self.directory / "main.blocks.json"))
        self.assertEqual(index["manifest_revision"],
                         file_revision(self.directory / "codifold.json"))
        self.assertEqual(payload["revision"],
                         file_revision(self.directory / "main.blocks.json"))
        self.assertEqual(payload["manifest_revision"], index["manifest_revision"])

    def test_save_view_with_matching_revision(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        index = block_config.load_index(str(self.directory))
        revision = index["views"][0]["revision"]
        result = editor.save_view(str(self.directory),
                                  view("main", [normal(1, "新块")]),
                                  revision=revision)
        self.assertNotEqual(result["revision"], revision)
        self.assertEqual(result["revision"],
                         file_revision(self.directory / "main.blocks.json"))

    def test_save_view_rejects_stale_revision(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        stale = block_config.load_index(str(self.directory))["views"][0]["revision"]
        path = self.directory / "main.blocks.json"
        path.write_text(json.dumps(view("main", [normal(2)]), ensure_ascii=False),
                        encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaises(editor.RevisionConflict) as error:
            editor.save_view(str(self.directory), view("main", [normal(3)]),
                             revision=stale)
        self.assertEqual(error.exception.current, file_revision(path))
        self.assertEqual(path.read_bytes(), before)

    def test_save_new_view_accepts_null_and_rejects_existing(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        result = editor.save_view(str(self.directory), view("extra", [normal(1)]),
                                  revision=None)
        self.assertTrue(result["created"])
        before = (self.directory / "extra.blocks.json").read_bytes()
        with self.assertRaises(editor.RevisionConflict):
            editor.save_view(str(self.directory), view("extra", [normal(2)]),
                             revision=None)
        self.assertEqual((self.directory / "extra.blocks.json").read_bytes(), before)

    def test_delete_view_rejects_stale_revision(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("other", [normal(1)]),
        ], entry="main")
        index = block_config.load_index(str(self.directory))
        stale = next(item for item in index["views"]
                     if item["view_id"] == "other")["revision"]
        path = self.directory / "other.blocks.json"
        path.write_text(json.dumps(view("other", [normal(2)]), ensure_ascii=False),
                        encoding="utf-8")
        with self.assertRaises(editor.RevisionConflict):
            editor.delete_view(str(self.directory), "other", revision=stale)
        self.assertTrue(path.is_file())

    def test_delete_view_rejects_stale_manifest_revision(self):
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("other", [normal(1)]),
        ], entry="main")
        index = block_config.load_index(str(self.directory))
        manifest = self.directory / "codifold.json"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n",
                            encoding="utf-8")
        with self.assertRaises(editor.RevisionConflict):
            editor.delete_view(str(self.directory), "other",
                               revision=next(item["revision"] for item in index["views"]
                                             if item["view_id"] == "other"),
                               manifest_revision=index["manifest_revision"])
        self.assertTrue((self.directory / "other.blocks.json").is_file())

    def test_project_settings_round_trip_preserves_unknown_fields(self):
        self.write_source()
        write_workspace(self.directory, [
            view("main", [normal(1)]),
            view("other", [normal(1)]),
        ], entry="main")
        manifest_path = self.directory / "codifold.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["project"]["custom"] = "keep"
        manifest["views"]["custom"] = "keep"
        manifest["extra"] = {"keep": True}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        current = editor.project_settings(str(self.directory))
        self.assertEqual(current["manifest"]["extra"], {"keep": True})
        result = editor.save_project(str(self.directory), {
            "project": {"name": "改名项目", "description": "新描述", "root": "."},
            "files": ["app.py"],
            "views": {"suffix": ".blocks.json", "entry": "other"},
        }, revision=current["revision"])
        self.assertEqual(result["index"]["entry"], "other")
        self.assertEqual(result["index"]["project"]["files"], ["app.py"])
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["name"], "改名项目")
        self.assertEqual(data["project"]["custom"], "keep")
        self.assertEqual(data["files"], ["app.py"])
        self.assertEqual(data["views"]["entry"], "other")
        self.assertEqual(data["views"]["custom"], "keep")
        self.assertEqual(data["extra"], {"keep": True})
        self.assertEqual(result["revision"], file_revision(manifest_path))

    def test_project_settings_rolls_back_when_mapped_file_is_removed(self):
        self.write_source()
        write_workspace(self.directory, [view("main", [normal(
            1, code_mapping={"file": "app.py", "lines": [1]})])], entry="main",
            files=["app.py"])
        manifest = self.directory / "codifold.json"
        before = manifest.read_bytes()
        with self.assertRaises(ValueError) as error:
            editor.save_project(str(self.directory), {"files": []})
        self.assertIn("app.py", str(error.exception))
        self.assertEqual(manifest.read_bytes(), before)

    def test_project_settings_rejects_missing_file_and_bad_entry(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        before = (self.directory / "codifold.json").read_bytes()
        with self.assertRaises(FileNotFoundError):
            editor.save_project(str(self.directory), {"files": ["missing.py"]})
        with self.assertRaises(ValueError):
            editor.save_project(str(self.directory), {"views": {"entry": "missing"}})
        with self.assertRaises(ValueError):
            editor.save_project(str(self.directory), {"views": {"suffix": ".other.json"}})
        self.assertEqual((self.directory / "codifold.json").read_bytes(), before)

    def test_project_settings_rejects_stale_revision(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        manifest = self.directory / "codifold.json"
        stale = editor.project_settings(str(self.directory))["revision"]
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        before = manifest.read_bytes()
        with self.assertRaises(editor.RevisionConflict) as error:
            editor.save_project(str(self.directory), {"files": []}, revision=stale)
        self.assertEqual(error.exception.current, file_revision(manifest))
        self.assertEqual(manifest.read_bytes(), before)

    def test_open_workspace_records_recent_list(self):
        write_workspace(self.directory, [view("main", [normal(1)])], entry="main")
        state = self.directory / "state"
        with mock.patch.dict(os.environ, {"CODIFOLD_STATE_DIR": str(state)}):
            editor.open_workspace(str(self.directory))
            recent = editor.recent_workspaces()["recent"]
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["path"], str(self.directory.resolve()))
            self.assertEqual(recent[0]["name"], "测试项目")
            self.assertTrue(recent[0]["exists"])

            second = self.directory / "second"
            editor.create_workspace(str(second), "第二项目", "第二描述")
            editor.open_workspace(str(second))
            recent = editor.recent_workspaces()["recent"]
            self.assertEqual([item["name"] for item in recent], ["第二项目", "测试项目"])

            editor.forget_workspace(str(second))
            recent = editor.recent_workspaces()["recent"]
            self.assertEqual([item["name"] for item in recent], ["测试项目"])

    def test_delete_workspace_requires_confirmation_and_removes_recent(self):
        target = self.directory / "to-delete"
        editor.create_workspace(str(target), "待删项目", "描述")
        state = self.directory / "state"
        with mock.patch.dict(os.environ, {"CODIFOLD_STATE_DIR": str(state)}):
            editor.open_workspace(str(target))
            with self.assertRaises(ValueError):
                editor.delete_workspace(str(target), str(self.directory))
            self.assertTrue(target.is_dir())
            result = editor.delete_workspace(str(target), str(target.resolve()))
            self.assertEqual(result["deleted"], str(target.resolve()))
            self.assertFalse(target.exists())
            self.assertEqual(editor.recent_workspaces()["recent"], [])

    def test_delete_workspace_allows_broken_manifest(self):
        target = self.directory / "broken"
        target.mkdir()
        (target / "codifold.json").write_text(json.dumps({
            "project": {"name": "坏项目", "description": "描述", "root": "."},
            "files": ["missing.py"],
            "views": {},
        }), encoding="utf-8")
        state = self.directory / "state"
        with mock.patch.dict(os.environ, {"CODIFOLD_STATE_DIR": str(state)}):
            result = editor.delete_workspace(str(target), str(target.resolve()))
        self.assertEqual(result["deleted"], str(target.resolve()))
        self.assertFalse(target.exists())

    def test_delete_workspace_refuses_git_and_non_workspace(self):
        target = self.directory / "git-project"
        editor.create_workspace(str(target), "Git 项目", "描述")
        (target / ".git").mkdir()
        with self.assertRaises(ValueError) as error:
            editor.delete_workspace(str(target), str(target.resolve()))
        self.assertIn(".git", str(error.exception))
        self.assertTrue(target.is_dir())
        with self.assertRaises(ValueError):
            editor.delete_workspace(str(self.directory), str(self.directory.resolve()))

    def test_delete_workspace_guard_rejects_repo_and_top_level(self):
        with self.assertRaises(ValueError):
            editor._guard_delete(block_config.ROOT)
        with self.assertRaises(ValueError):
            editor._guard_delete(Path("/tmp"))
        with self.assertRaises(ValueError):
            editor._guard_delete(Path.home().resolve())

    def write_source(self, name="app.py"):
        (self.directory / name).write_text(
            "x = 1\n# comment\ny = 2\nprint(x + y)\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
