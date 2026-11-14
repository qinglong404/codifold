import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codifold import mcp_server, workbench

ROOT = Path(__file__).resolve().parent.parent
SOURCE = '"""Demo."""\nVALUE = 1\ndef start():\n    return VALUE\n'


def normal(ident, *, mapping=None, name="步骤", description="描述", **extra):
    block = {"id": ident, "type": "normal", "name": name,
             "description": description}
    if mapping is not None:
        lines = mapping if isinstance(mapping, list) else [mapping]
        block["code_mapping"] = {"file": "app.py", "lines": lines}
    block.update(extra)
    return block


def write_view(directory: Path, view_id: str, blocks: list,
               *, kind=None, name=None, description="视图说明"):
    view = {"id": view_id, "name": name or view_id,
            "description": description}
    if kind:
        view["kind"] = kind
    data = {"view": view, "blocks": blocks}
    (directory / f"{view_id}.blocks.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def write_workspace(directory: Path, views=None):
    (directory / "app.py").write_text(SOURCE, encoding="utf-8")
    manifest = {
        "project": {"name": "测试项目", "description": "测试描述", "root": "."},
        "files": ["app.py"],
        "views": {"suffix": ".blocks.json", "entry": "main"},
    }
    (directory / "codifold.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    for config in views or [base_view()]:
        write_view(directory, config["view"]["id"], config["blocks"],
                   kind=config["view"].get("kind"),
                   name=config["view"]["name"])


def base_view(mapping="1-4"):
    return {
        "view": {"id": "main", "name": "主流程",
                 "description": "从启动到结束。", "kind": "main"},
        "blocks": [normal(1, mapping=mapping, name="启动",
                          description="启动。", next=None)],
    }


def draft_bundle():
    return {"views": [
        {
            "view": {"id": "main", "name": "主流程",
                     "description": "主线。", "kind": "main"},
            "file": "app.py",
            "blocks": [
                {"key": "start", "name": "启动", "description": "启动。",
                 "map": 1, "jump": "detail:start"},
                {"key": "finish", "name": "结束", "description": "结束。",
                 "map": 2, "next": "end"},
            ],
        },
        {
            "view": {"id": "detail", "name": "细节",
                     "description": "细节视图。", "kind": "function"},
            "file": "app.py",
            "blocks": [
                {"key": "start", "name": "读取", "description": "读取常量。",
                 "map": "3-4", "next": "end"},
            ],
        },
    ]}


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        write_workspace(self.directory)
        self.server = mcp_server.McpServer()

    def request(self, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.server.handle(message)

    def call(self, name, arguments):
        response = self.request("tools/call",
                                {"name": name, "arguments": arguments})
        self.assertIn("result", response, response)
        return response["result"]

    def payload(self, result):
        return json.loads(result["content"][0]["text"])

    def test_initialize_and_tools_list(self):
        response = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        })
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["serverInfo"]["name"], "codifold-workbench")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])
        self.assertIn("Codifold", result["instructions"])

        response = self.request("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(response["result"]["protocolVersion"],
                         mcp_server.DEFAULT_PROTOCOL)

        tools = self.request("tools/list")["result"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            ["codifold_brief", "codifold_apply", "codifold_check",
             "codifold_coherence", "codifold_export_md"])
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])
            self.assertIn(tool["name"], mcp_server._TOOL_HANDLERS)

    def test_brief_tool_returns_json(self):
        result = self.call("codifold_brief",
                           {"workspace": str(self.directory)})
        self.assertFalse(result["isError"])
        data = self.payload(result)
        self.assertEqual(data["entry"], "main")
        self.assertEqual(data["view"]["view_id"], "main")
        self.assertEqual(data["view"]["next_id"], 2)
        self.assertEqual(data["errors"], [])

    def test_apply_defaults_to_dry_run_and_writes_when_asked(self):
        result = self.call("codifold_apply", {
            "workspace": str(self.directory), "draft": draft_bundle()})
        self.assertFalse(result["isError"])
        dry = self.payload(result)
        self.assertTrue(dry["dry_run"])
        self.assertEqual([item["view"]["id"] for item in dry["payload"]["views"]],
                         ["main", "detail"])
        self.assertFalse((self.directory / "detail.blocks.json").exists())

        result = self.call("codifold_apply", {
            "workspace": str(self.directory),
            "draft": draft_bundle(), "dry_run": False})
        self.assertFalse(result["isError"])
        written = self.payload(result)
        self.assertIn("detail", written["created"])
        self.assertIn("main", written["updated"])
        self.assertTrue((self.directory / "detail.blocks.json").exists())

        result = self.call("codifold_check",
                           {"workspace": str(self.directory), "strict": True})
        self.assertFalse(result["isError"])
        checked = self.payload(result)
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["narrative"]["coherence"]["score"], 1.0)

    def test_apply_accepts_json_string(self):
        result = self.call("codifold_apply", {
            "workspace": str(self.directory),
            "draft": json.dumps(draft_bundle(), ensure_ascii=False)})
        self.assertFalse(result["isError"])
        self.assertTrue(self.payload(result)["dry_run"])

    def test_apply_invalid_draft_is_error_result(self):
        result = self.call("codifold_apply", {
            "workspace": str(self.directory),
            "draft": {"view": {"id": "main", "name": "主流程",
                               "description": "主线。"},
                      "blocks": []},
        })
        self.assertTrue(result["isError"])
        self.assertIn("错误", result["content"][0]["text"])
        self.assertFalse((self.directory / "detail.blocks.json").exists())

    def test_check_strict_treats_warnings_as_failure(self):
        write_view(self.directory, "main",
                   [normal(1, mapping=[1], name="启动", next=None)],
                   kind="main", name="主流程")
        result = self.call("codifold_check", {"workspace": str(self.directory)})
        self.assertFalse(result["isError"])
        loose = self.payload(result)
        self.assertTrue(loose["ok"])
        self.assertTrue(loose["warnings"])

        result = self.call("codifold_check", {
            "workspace": str(self.directory), "strict": True})
        self.assertTrue(result["isError"])
        strict = self.payload(result)
        self.assertFalse(strict["ok"])
        self.assertTrue(strict["warnings"])

    def test_coherence_tool_reports_orphans(self):
        result = self.call("codifold_coherence",
                           {"workspace": str(self.directory)})
        self.assertFalse(result["isError"])
        self.assertEqual(self.payload(result)["score"], 1.0)

        write_view(self.directory, "detail",
                   [normal(1, name="孤立", next=None)],
                   kind="function", name="细节")
        result = self.call("codifold_coherence",
                           {"workspace": str(self.directory)})
        self.assertTrue(result["isError"])
        data = self.payload(result)
        self.assertEqual(data["orphans"], ["detail"])
        self.assertLess(data["score"], 1.0)

    def test_export_md_tool_text_file_and_code(self):
        result = self.call("codifold_export_md",
                           {"workspace": str(self.directory)})
        self.assertFalse(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("# 测试项目 流程图文字稿", text)
        self.assertIn("## 1. main", text)
        self.assertNotIn("VALUE = 1", text)

        out = self.directory / "exports" / "flow.md"
        result = self.call("codifold_export_md", {
            "workspace": str(self.directory), "out": str(out)})
        self.assertFalse(result["isError"])
        summary = self.payload(result)
        self.assertEqual(summary["views"], 1)
        self.assertTrue(out.exists())

        result = self.call("codifold_export_md", {
            "workspace": str(self.directory), "with_code": True})
        text = result["content"][0]["text"]
        self.assertIn("## 附录 C. 代码证据", text)
        self.assertIn("VALUE = 1", text)

        result = self.call("codifold_export_md", {
            "workspace": str(self.directory), "kinds": ["nope"]})
        self.assertTrue(result["isError"])
        self.assertIn("未知视图角色", result["content"][0]["text"])

    def test_tool_argument_errors_are_results(self):
        result = self.call("codifold_brief", {})
        self.assertTrue(result["isError"])
        self.assertIn("workspace", result["content"][0]["text"])

        result = self.call("codifold_check", {
            "workspace": str(self.directory), "bogus": True})
        self.assertTrue(result["isError"])
        self.assertIn("未知参数", result["content"][0]["text"])

        result = self.call("codifold_check", {
            "workspace": str(self.directory / "missing")})
        self.assertTrue(result["isError"])
        self.assertIn("找不到工作区", result["content"][0]["text"])

    def test_protocol_errors_and_notifications(self):
        response = self.request("tools/call",
                                {"name": "nope", "arguments": {}})
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("未知工具", response["error"]["message"])

        response = self.request("unknown/method")
        self.assertEqual(response["error"]["code"], -32601)

        response = self.request("tools/list", params=[])
        self.assertEqual(response["error"]["code"], -32602)

        response = self.server.handle([])
        self.assertEqual(response["error"]["code"], -32600)

        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        response = self.server.handle(
            {"jsonrpc": "1.0", "id": 1, "method": "ping"})
        self.assertEqual(response["error"]["code"], -32600)

    def test_resources_list_and_read(self):
        resources = self.request("resources/list")["result"]["resources"]
        self.assertEqual(len(resources), 4)
        self.assertEqual(
            {item["uri"] for item in resources},
            {"codifold://guide/conversion", "codifold://guide/workbench",
             "codifold://guide/flat-schema",
             "codifold://guide/blocks-schema"})

        response = self.request("resources/read",
                                {"uri": "codifold://guide/workbench"})
        text = response["result"]["contents"][0]["text"]
        self.assertIn("export-md", text)
        self.assertEqual(response["result"]["contents"][0]["mimeType"],
                         "text/markdown")

        response = self.request("resources/read",
                                {"uri": "codifold://guide/missing"})
        self.assertEqual(response["error"]["code"], -32002)

    def test_stdio_loop_recovers_from_parse_error(self):
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {}}),
            "{not json",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        ]
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        out = io.BytesIO()
        self.assertEqual(mcp_server.serve(io.BytesIO(raw), out), 0)
        output = [json.loads(line) for line in
                  out.getvalue().decode("utf-8").splitlines()]
        self.assertEqual(len(output), 3)
        self.assertEqual(output[0]["id"], 1)
        self.assertEqual(output[1]["error"]["code"], -32700)
        self.assertIsNone(output[1]["id"])
        self.assertEqual(output[2]["result"], {})

    def test_content_length_framing(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 9,
                           "method": "ping"}).encode("utf-8")
        raw = (b"Content-Length: " + str(len(body)).encode("ascii")
               + b"\r\n\r\n" + body)
        out = io.BytesIO()
        self.assertEqual(mcp_server.serve(io.BytesIO(raw), out), 0)
        response = json.loads(out.getvalue().decode("utf-8"))
        self.assertEqual(response["id"], 9)
        self.assertEqual(response["result"], {})

    def test_workbench_mcp_subcommand_delegates(self):
        with mock.patch("codifold.mcp_server.serve", return_value=0) as serve:
            self.assertEqual(workbench.main(["mcp"]), 0)
        serve.assert_called_once_with()

    def test_module_entrypoint_over_stdio(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "codifold_brief",
                        "arguments": {"workspace": str(self.directory)}}},
        ]
        payload = "\n".join(json.dumps(item, ensure_ascii=False)
                            for item in messages) + "\n"
        process = subprocess.run(
            [sys.executable, "-m", "codifold.mcp_server"],
            input=payload.encode("utf-8"), capture_output=True,
            cwd=ROOT, timeout=30)
        self.assertEqual(process.returncode, 0,
                         process.stderr.decode("utf-8", "replace"))
        output = process.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(output), 2, output)
        init = json.loads(output[0])
        self.assertEqual(init["result"]["serverInfo"]["name"],
                         "codifold-workbench")
        call = json.loads(output[1])
        self.assertFalse(call["result"]["isError"])
        data = json.loads(call["result"]["content"][0]["text"])
        self.assertEqual(data["view"]["view_id"], "main")


if __name__ == "__main__":
    unittest.main()
