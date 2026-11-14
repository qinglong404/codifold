import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from codifold import block_config
from codifold.server import create_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.original_state_dir = os.environ.get("CODIFOLD_STATE_DIR")
        os.environ["CODIFOLD_STATE_DIR"] = str(Path(cls.temporary.name) / "state")
        cls.server = create_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        if cls.original_state_dir is None:
            os.environ.pop("CODIFOLD_STATE_DIR", None)
        else:
            os.environ["CODIFOLD_STATE_DIR"] = cls.original_state_dir
        cls.temporary.cleanup()

    def setUp(self):
        registry = Path(self.temporary.name) / "state" / "workspaces.json"
        if registry.exists():
            registry.unlink()

    def request_json(self, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(self.url + path, data=data,
                          headers={"Content-Type": "application/json", **(headers or {})},
                          method=method)
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def write_workspace(self, directory, views, entry="main"):
        manifest = {
            "project": {"name": "测试项目", "description": "测试描述", "root": "."},
            "files": [],
            "views": {"suffix": ".blocks.json", "entry": entry},
        }
        (directory / "codifold.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        for config in views:
            (directory / f"{config['view']['id']}.blocks.json").write_text(
                json.dumps(config, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def view(view_id, blocks):
        return {
            "view": {"id": view_id, "name": view_id, "description": "描述"},
            "blocks": blocks,
        }

    def test_rebinding_host_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/views", headers={"Host": "malicious.example"})
        self.assertEqual(error.exception.code, 403)

    def test_unknown_api_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/unknown")
        self.assertEqual(error.exception.code, 404)

    def test_legacy_pages_redirect_to_reader(self):
        for route in ("/gradebook", "/demo"):
            with urlopen(self.url + route, timeout=5) as response:
                self.assertTrue(response.geturl().endswith("/"))

    def test_reader_page_is_served_if_built(self):
        page = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"
        if not page.is_file():
            self.skipTest("frontend not built")
        for route in ("/", "/blocks"):
            with urlopen(self.url + route, timeout=5) as response:
                html = response.read().decode("utf-8")
            self.assertIn('id="root"', html)
            self.assertIn("Codifold", html)

    def test_blocks_config_is_exposed(self):
        result = self.request_json("/api/blocks-config")
        self.assertEqual(result["source"]["kind"], "default")
        self.assertEqual(result["order"], [1, 2, 3, 14, 15])
        branch = result["config"]["blocks"][2]
        self.assertEqual(branch["type"], "branch")
        self.assertEqual(branch["select"], "single")
        self.assertEqual(len(branch["branches"]), 6)
        self.assertEqual(result["config"]["blocks"][3]["next"], 2)
        self.assertIn("ranges", result["codes"]["1"])

    def test_blocks_config_bad_path_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/blocks-config?path=/no/such.json")
        self.assertEqual(error.exception.code, 400)

    def test_views_index_is_exposed(self):
        result = self.request_json("/api/views")
        self.assertEqual(result["source"]["kind"], "project")
        self.assertEqual(result["entry"], "gradebook")
        self.assertEqual([item["view_id"] for item in result["views"]], ["gradebook"])

    def test_blocks_config_selects_view_in_project(self):
        path = quote(str(block_config.DEFAULT_PROJECT))
        result = self.request_json(f"/api/blocks-config?path={path}&view=gradebook")
        self.assertEqual(result["view"]["view_id"], "gradebook")
        self.assertEqual(result["source"]["kind"], "project")
        self.assertEqual(result["order"], [1, 2, 3, 14, 15])

    def test_blocks_config_rejects_unknown_view(self):
        path = quote(str(block_config.DEFAULT_PROJECT))
        with self.assertRaises(HTTPError) as error:
            self.request_json(f"/api/blocks-config?path={path}&view=missing")
        self.assertEqual(error.exception.code, 400)

    def test_post_view_saves_workspace_view(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            config = self.view("main", [
                {"id": 1, "type": "normal", "name": "新块",
                 "description": "新描述", "next": None},
            ])
            result = self.request_json("/api/views", {
                "path": str(directory), "config": config,
            })
            self.assertEqual(result["payload"]["config"]["blocks"][0]["name"], "新块")
            self.assertEqual([item["view_id"] for item in result["index"]["views"]],
                             ["main"])
            data = json.loads((directory / "main.blocks.json").read_text(encoding="utf-8"))
            self.assertEqual(data["blocks"][0]["name"], "新块")

    def test_post_view_rejects_cross_site_origin(self):
        config = self.view("main", [
            {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
        ])
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/views", {"path": "/tmp/none", "config": config},
                              {"Origin": "https://example.com"})
        self.assertEqual(error.exception.code, 403)

    def test_events_are_exposed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "入口",
                 "description": "描述", "on": "device.click"},
            ])])
            result = self.request_json(
                f"/api/events?path={quote(str(directory))}")
            self.assertEqual(result["events"], ["device.click"])

    def test_delete_view_route_updates_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [
                self.view("main", [{"id": 1, "type": "normal",
                                    "name": "开始", "description": "描述"}]),
                self.view("other", [{"id": 1, "type": "normal",
                                     "name": "其他", "description": "描述"}]),
            ])
            result = self.request_json(
                f"/api/views?path={quote(str(directory))}&view=main", method="DELETE")
            self.assertEqual(result["entry"], "other")
            self.assertFalse((directory / "main.blocks.json").exists())

    def test_create_workspace_route(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new-project"
            result = self.request_json("/api/workspaces", {
                "directory": str(target), "name": "新项目", "description": "项目描述",
            })
            self.assertEqual(result["index"]["entry"], "main")
            self.assertEqual(result["payload"]["order"], [1])
            self.assertTrue((target / "codifold.json").is_file())
            self.assertTrue((target / "main.blocks.json").is_file())

    def test_blocks_mutation_route(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "flat-project"
            self.request_json("/api/workspaces", {
                "directory": str(target), "name": "扁平项目",
                "description": "测试",
            })
            result = self.request_json("/api/blocks", {
                "path": str(target), "view": "main", "action": "add_block",
                "container": "root", "name": "新块", "description": "新步骤",
            })
            self.assertEqual(result["payload"]["schema"], "flat")
            new_id = result["result"]["block_id"]
            self.assertIn(new_id, result["payload"]["order"])
            deleted = self.request_json("/api/blocks", {
                "path": str(target), "view": "main", "action": "delete_block",
                "block_id": new_id,
            })
            self.assertNotIn(new_id, deleted["payload"]["order"])

    def test_views_index_exposes_revisions(self):
        result = self.request_json("/api/views")
        self.assertEqual(len(result["manifest_revision"]), 64)
        self.assertTrue(all(len(item["revision"]) == 64 for item in result["views"]))

    def test_post_view_revision_conflict_returns_409(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            config = self.view("main", [
                {"id": 1, "type": "normal", "name": "新块", "description": "新描述"},
            ])
            with self.assertRaises(HTTPError) as error:
                self.request_json("/api/views", {
                    "path": str(directory), "config": config, "revision": "stale",
                })
            self.assertEqual(error.exception.code, 409)
            body = json.loads(error.exception.read().decode("utf-8"))
            self.assertEqual(body["code"], "revision_conflict")
            self.assertEqual(len(body["current_revision"]), 64)

    def test_project_settings_route(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "app.py").write_text("x = 1\n", encoding="utf-8")
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            current = self.request_json(f"/api/project?path={quote(str(directory))}")
            self.assertEqual(current["manifest"]["project"]["name"], "测试项目")
            result = self.request_json("/api/project", {
                "path": str(directory),
                "revision": current["revision"],
                "config": {
                    "project": {"name": "改名", "description": "新描述", "root": "."},
                    "files": ["app.py"],
                },
            })
            self.assertEqual(result["index"]["project"]["files"], ["app.py"])
            self.assertEqual(result["index"]["project"]["name"], "改名")
            manifest = json.loads((directory / "codifold.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["files"], ["app.py"])
            self.assertEqual(manifest["views"]["entry"], "main")

    def test_workspaces_open_recent_and_forget(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            opened = self.request_json("/api/workspaces/open", {"path": str(directory)})
            self.assertEqual(opened["index"]["entry"], "main")
            recent = self.request_json("/api/workspaces")["recent"]
            self.assertEqual([item["path"] for item in recent], [str(directory.resolve())])
            self.assertEqual(recent[0]["name"], "测试项目")
            self.assertTrue(recent[0]["exists"])

            forgotten = self.request_json(
                f"/api/workspaces/recent?path={quote(str(directory))}", method="DELETE")
            self.assertEqual(forgotten["recent"], [])

    def test_browse_route_lists_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            workspace = directory / "alpha"
            workspace.mkdir()
            self.write_workspace(workspace, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            (directory / "beta").mkdir()
            result = self.request_json(f"/api/browse?path={quote(str(directory))}")
            self.assertEqual(result["path"], str(directory.resolve()))
            self.assertEqual(result["parent"], str(directory.resolve().parent))
            self.assertFalse(result["is_workspace"])
            entries = {item["name"]: item for item in result["entries"]}
            self.assertTrue(entries["alpha"]["is_workspace"])
            self.assertFalse(entries["beta"]["is_workspace"])
            self.assertTrue(result["shortcuts"])

    def test_browse_rejects_relative_path(self):
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/browse?path=relative/dir")
        self.assertEqual(error.exception.code, 400)

    def test_workspaces_expose_examples(self):
        result = self.request_json("/api/workspaces")
        names = {item["name"] for item in result["examples"]}
        self.assertIn("学生成绩管理", names)
        self.assertIn("学生成绩管理（链路版）", names)
        base = Path(__file__).resolve().parent.parent / "examples"
        self.assertTrue(all(Path(item["path"]).is_relative_to(base)
                            for item in result["examples"]))

    def test_delete_workspace_route(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "workspace"
            target.mkdir()
            self.write_workspace(target, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            with self.assertRaises(HTTPError) as error:
                self.request_json(
                    f"/api/workspaces?path={quote(str(target))}&confirm=wrong",
                    method="DELETE")
            self.assertEqual(error.exception.code, 400)
            self.assertTrue(target.is_dir())
            source = target / "app.py"
            source.write_text("keep me", encoding="utf-8")
            with self.assertRaises(HTTPError) as error:
                self.request_json(
                    f"/api/workspaces?path={quote(str(target))}"
                    f"&confirm={quote(str(target.resolve()))}", method="DELETE")
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(source.read_text(encoding="utf-8"), "keep me")

    def test_project_settings_reject_unknown_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.write_workspace(directory, [self.view("main", [
                {"id": 1, "type": "normal", "name": "开始", "description": "描述"},
            ])])
            current = self.request_json(f"/api/project?path={quote(str(directory))}")
            with self.assertRaises(HTTPError) as error:
                self.request_json("/api/project", {
                    "path": str(directory),
                    "revision": current["revision"],
                    "config": {"views": {"entry": "missing"}},
                })
            self.assertEqual(error.exception.code, 400)

    def test_unknown_delete_is_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request_json("/api/unknown", method="DELETE")
        self.assertEqual(error.exception.code, 404)

    def test_coverage_report_is_exposed(self):
        result = self.request_json("/api/coverage")
        self.assertTrue(result["ok"])
        self.assertEqual(result["project"]["files"], ["gradebook.py"])
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["file"], "gradebook.py")
        self.assertGreater(result["files"][0]["total"], 0)

if __name__ == "__main__":
    unittest.main()
