"""Codifold workbench MCP server (stdio, JSON-RPC 2.0).

MCP clients launch it as a local process:

    python3 -m codifold.mcp_server
    python3 -m codifold.workbench mcp

The server exposes the workbench operations as MCP tools (brief / apply /
check / coherence / export-md) and the project guides as MCP resources.
Nothing is executed: only workspace JSON is read or written.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import checks, draft, editor, export_md, flat, narrative, project_config
from .brief import collect_brief

SERVER_NAME = "codifold-workbench"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = PROTOCOL_VERSIONS[0]
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

INSTRUCTIONS = """Codifold 转换工作台。工作区必须是含 codifold.json 的目录；工具只读写工作区 JSON，不分析、不执行被讲解的源码。

推荐顺序：
1. codifold_brief：读取覆盖率、视图清单和一个视图的块结构；
2. 写局部草稿：块用短 key 互相引用，map 写行号或行号区间；
3. codifold_apply：默认 dry_run=true 只返回编译结果，确认后传 dry_run=false 才写入；
4. codifold_check：strict=true 时覆盖率警告也算失败；
5. codifold_export_md：导出只含名称和描述的文字稿，供人工审核。

视图角色、草稿格式和验收门禁见 codifold://guide/workbench 与 codifold://guide/conversion。"""

TOOLS = [
    {
        "name": "codifold_brief",
        "title": "读取工作区简报",
        "description": (
            "读取工作区简报：项目元数据、文件覆盖率、未覆盖行、视图清单、"
            "指定视图的块结构、下一个可用 id、错误/警告、叙事和连贯性。"
            "写草稿前先调用。只读，不改任何文件。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "工作区目录（含 codifold.json）；相对路径按服务器当前目录解析。",
                },
                "view": {
                    "type": "string",
                    "description": "要展开块结构的视图 id；省略时用入口视图。",
                },
                "snippets": {
                    "type": "boolean",
                    "default": False,
                    "description": "附带未覆盖源码行（最多 200 行）。",
                },
            },
            "required": ["workspace"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "codifold_apply",
        "title": "编译并写入视图草稿",
        "description": (
            "把局部视图草稿编译成最终 JSON。块用 key 互相引用，map 写行号或行号区间；"
            "工具负责分配数字 id 并补全 next/jump/flow/emit。"
            "默认 dry_run=true，只返回编译结果、不写文件；确认后传 dry_run=false 才写入。"
            "写入后跑整项目复检，失败自动回滚。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "工作区目录（含 codifold.json）。",
                },
                "draft": {
                    "description": (
                        "视图草稿：单个视图对象、视图数组、{views: [...]}，"
                        "或上述内容的 JSON 字符串。"
                    ),
                    "oneOf": [
                        {"type": "object"},
                        {"type": "array"},
                        {"type": "string"},
                    ],
                },
                "dry_run": {
                    "type": "boolean",
                    "default": True,
                    "description": "true 只返回编译结果；false 才写入工作区。",
                },
                "strict": {
                    "type": "boolean",
                    "default": False,
                    "description": "写入时若有覆盖率/可达性警告，回滚并报错。",
                },
            },
            "required": ["workspace", "draft"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    },
    {
        "name": "codifold_check",
        "title": "整项目门禁检查",
        "description": (
            "检查结构、代码覆盖率、重复映射、跨视图引用、叙事和连贯性。"
            "返回 JSON；ok=false 表示不通过，isError=true 同时置位。"
            "strict=true 时警告也算失败。只读。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "工作区目录（含 codifold.json）。",
                },
                "strict": {
                    "type": "boolean",
                    "default": False,
                    "description": "警告也算失败。",
                },
            },
            "required": ["workspace"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "codifold_coherence",
        "title": "检查视图连贯性",
        "description": (
            "只查连贯性：从 main 视图出发，沿 jump/flow/emit 能到达多少视图。"
            "score 必须是 1.0，否则 isError=true。只读。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "工作区目录（含 codifold.json）。",
                },
            },
            "required": ["workspace"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "codifold_export_md",
        "title": "导出审核用文字稿",
        "description": (
            "把工作区投影成只含名称和描述的文字稿（Markdown），供人工或 AI 审核。"
            "默认返回文档文本；传 out 时写入文件并返回摘要。"
            "with_code=true 会追加附录 C 代码证据。只读工作区。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "工作区目录（含 codifold.json）。",
                },
                "views": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "只导出指定视图 id，可多选。",
                },
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(export_md.KIND_ORDER)},
                    "description": "只导出指定视图角色，可多选。",
                },
                "with_code": {
                    "type": "boolean",
                    "default": False,
                    "description": "文末附加代码证据附录。",
                },
                "max_code_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 20,
                    "description": "附录 C 每个块最多列出多少行代码。",
                },
                "out": {
                    "type": "string",
                    "description": "写入文件路径；省略时直接把文档文本作为结果返回。",
                },
            },
            "required": ["workspace"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]

RESOURCES = [
    {
        "uri": "codifold://guide/conversion",
        "name": "conversion-guide",
        "title": "项目转换指南",
        "description": "从真实项目到视图的转换规则、入口链路画法和验收门禁。",
        "mimeType": "text/markdown",
    },
    {
        "uri": "codifold://guide/workbench",
        "name": "workbench",
        "title": "转换工作台",
        "description": "brief/apply/check/coherence/export-md 的用法、草稿格式和引用规则。",
        "mimeType": "text/markdown",
    },
    {
        "uri": "codifold://guide/flat-schema",
        "name": "flat-schema",
        "title": "Flat 视图规范",
        "description": "blocks + containers 的平面视图格式，新工作区默认格式。",
        "mimeType": "text/markdown",
    },
    {
        "uri": "codifold://guide/blocks-schema",
        "name": "blocks-schema",
        "title": "旧嵌套格式与工作区配置",
        "description": "codifold.json 字段和旧嵌套视图格式。",
        "mimeType": "text/markdown",
    },
]

_RESOURCE_FILES = {
    "codifold://guide/conversion": "conversion-guide.md",
    "codifold://guide/workbench": "workbench.md",
    "codifold://guide/flat-schema": "flat-schema.md",
    "codifold://guide/blocks-schema": "blocks-schema.md",
}


class RpcError(Exception):
    """Protocol-level JSON-RPC error (not a tool execution error)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _error_response(request_id, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _json_result(payload, *, is_error: bool = False) -> dict:
    return _text_result(
        json.dumps(payload, ensure_ascii=False, indent=2), is_error=is_error)


def _unknown_args(args: dict, allowed: set[str]) -> None:
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise ValueError(f"未知参数：{', '.join(unknown)}")


def _str_arg(args: dict, name: str, *, required: bool = False,
             default: str | None = None) -> str | None:
    value = args.get(name, default)
    if value is None:
        if required:
            raise ValueError(f"缺少 {name}（{name} 必须是非空字符串）")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value.strip()


def _bool_arg(args: dict, name: str, default: bool) -> bool:
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} 必须是布尔值")
    return value


def _int_arg(args: dict, name: str, default: int,
             *, minimum: int | None = None) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须是整数")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}")
    return value


def _list_arg(args: dict, name: str) -> list[str]:
    value = args.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{name} 必须是非空字符串数组")
    return [item.strip() for item in value]


def _workspace(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.exists():
        raise ValueError(f"找不到工作区：{path}")
    if not path.is_dir():
        raise ValueError(f"工作区不是目录：{path}")
    path = path.resolve()
    manifest = path / project_config.MANIFEST_NAME
    if not manifest.is_file():
        raise ValueError(
            f"不是 Codifold 工作区（缺少 {project_config.MANIFEST_NAME}）：{path}")
    return path


def _tool_brief(args: dict) -> dict:
    _unknown_args(args, {"workspace", "view", "snippets"})
    workspace = _workspace(_str_arg(args, "workspace", required=True))
    view = _str_arg(args, "view")
    snippets = _bool_arg(args, "snippets", False)
    return _json_result(collect_brief(str(workspace), view, snippets))


def _draft_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"draft 不是合法 JSON：{error}") from error
    if isinstance(value, (dict, list)):
        return value
    raise ValueError("draft 必须是视图对象、视图数组、{views: [...]} 或 JSON 字符串")


def _tool_apply(args: dict) -> dict:
    _unknown_args(args, {"workspace", "draft", "dry_run", "strict"})
    workspace = _workspace(_str_arg(args, "workspace", required=True))
    if "draft" not in args:
        raise ValueError("缺少 draft（视图草稿）")
    specs = draft.normalize_drafts(_draft_value(args["draft"]))
    configs = draft.compile_drafts(str(workspace), specs)
    dry_run = _bool_arg(args, "dry_run", True)
    if dry_run:
        manifest = project_config.load_manifest(workspace)
        if manifest is not None and manifest.get("format") == "flat":
            configs = [flat.from_nested(config) for config in configs]
        payload = configs[0] if len(configs) == 1 else {"views": configs}
        return _json_result({"dry_run": True, "payload": payload})
    result = editor.save_views(
        str(workspace), configs, strict=_bool_arg(args, "strict", False))
    return _json_result({
        "dry_run": False,
        "created": result["created"],
        "updated": result["updated"],
        "warnings": result["warnings"],
        "files": result["report"]["files"],
    })


def _tool_check(args: dict) -> dict:
    _unknown_args(args, {"workspace", "strict"})
    workspace = _workspace(_str_arg(args, "workspace", required=True))
    data = checks.report(str(workspace),
                         strict=_bool_arg(args, "strict", False))
    return _json_result(data, is_error=not data["ok"])


def _tool_coherence(args: dict) -> dict:
    _unknown_args(args, {"workspace"})
    workspace = _workspace(_str_arg(args, "workspace", required=True))
    data = narrative.report(str(workspace))
    coherence = data.get("coherence") or {
        "score": 0.0, "reachable": 0, "total": 0,
        "root": "", "depths": {}, "orphans": [],
    }
    return _json_result(coherence, is_error=coherence.get("score") != 1.0)


def _tool_export_md(args: dict) -> dict:
    _unknown_args(args, {"workspace", "views", "kinds", "with_code",
                         "max_code_lines", "out"})
    workspace = _workspace(_str_arg(args, "workspace", required=True))
    views = _list_arg(args, "views")
    kinds = _list_arg(args, "kinds")
    unknown = [kind for kind in kinds if kind not in export_md.KIND_ORDER]
    if unknown:
        raise ValueError(
            f"未知视图角色：{'、'.join(unknown)}"
            f"（可用：{'、'.join(export_md.KIND_ORDER)}）")
    text, summary = export_md.build(
        str(workspace),
        views=views or None,
        kinds=kinds or None,
        with_code=_bool_arg(args, "with_code", False),
        max_code_lines=_int_arg(args, "max_code_lines", 20, minimum=1),
    )
    out = _str_arg(args, "out")
    if out and out != "-":
        target = export_md.write(text, out)
        return _json_result({
            "out": str(target),
            "views": summary["views"],
            "blocks": summary["blocks"],
            "errors": summary["errors"],
            "warnings": summary["warnings"],
        }, is_error=bool(summary["errors"]))
    return _text_result(text, is_error=bool(summary["errors"]))


_TOOL_HANDLERS = {
    "codifold_brief": _tool_brief,
    "codifold_apply": _tool_apply,
    "codifold_check": _tool_check,
    "codifold_coherence": _tool_coherence,
    "codifold_export_md": _tool_export_md,
}


class McpServer:
    """Protocol dispatcher; transport is handled by :func:`serve`."""

    def handle(self, message):
        """Return a JSON-RPC response dict, or None for notifications."""
        if isinstance(message, list):
            return _error_response(None, -32600, "不支持 JSON-RPC 批量请求")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error_response(None, -32600, "Invalid Request")
        method = message.get("method")
        if not isinstance(method, str):
            return _error_response(message.get("id"), -32600, "Invalid Request")
        notification = "id" not in message
        request_id = message.get("id")
        params = message.get("params")
        if params is None:
            params = {}
        try:
            if not isinstance(params, dict):
                raise RpcError(-32602, "params 必须是对象")
            result = self._dispatch(method, params)
        except RpcError as error:
            return None if notification else _error_response(
                request_id, error.code, error.message)
        except Exception as error:  # keep the loop alive on unexpected bugs
            traceback.print_exc(file=sys.stderr)
            return None if notification else _error_response(
                request_id, -32603, f"内部错误：{error}")
        if notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = (requested if requested in PROTOCOL_VERSIONS
                       else DEFAULT_PROTOCOL)
            return {
                "protocolVersion": version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "resources/list":
            return {"resources": RESOURCES}
        if method == "resources/read":
            return self._read_resource(params)
        raise RpcError(-32601, f"不支持的方法：{method}")

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RpcError(-32602, "tools/call 缺少 name")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "arguments 必须是对象")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            raise RpcError(-32602, f"未知工具：{name}")
        try:
            return handler(arguments)
        except (OSError, ValueError) as error:
            return _text_result(f"错误：{error}", is_error=True)
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            return _text_result(f"内部错误：{error}", is_error=True)

    def _read_resource(self, params: dict) -> dict:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise RpcError(-32602, "resources/read 缺少 uri")
        filename = _RESOURCE_FILES.get(uri.strip())
        if filename is None:
            raise RpcError(-32002, f"找不到资源：{uri}")
        try:
            text = (DOCS_DIR / filename).read_text(encoding="utf-8")
        except OSError as error:
            raise RpcError(-32603, f"读取资源失败：{error}") from error
        return {"contents": [{
            "uri": uri.strip(),
            "mimeType": "text/markdown",
            "text": text,
        }]}


def _read_message(stream) -> bytes | None:
    """Read one newline-delimited message; tolerate Content-Length framing."""
    line = stream.readline()
    while line and not line.strip():
        line = stream.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        try:
            length = int(line.split(b":", 1)[1].strip())
        except (IndexError, ValueError) as error:
            raise ValueError(f"无效的 Content-Length：{line!r}") from error
        while True:
            header = stream.readline()
            if header in (b"", b"\r\n", b"\n"):
                break
        body = stream.read(length)
        if len(body) != length:
            raise ValueError("消息体长度不足")
        return body
    return line.strip()


def _send(stream, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    stream.write((data + "\n").encode("utf-8"))
    stream.flush()


def serve(instream=None, outstream=None) -> int:
    """Run the stdio loop until EOF. Returns a process exit code."""
    instream = sys.stdin.buffer if instream is None else instream
    outstream = sys.stdout.buffer if outstream is None else outstream
    server = McpServer()
    while True:
        try:
            raw = _read_message(instream)
        except (OSError, ValueError) as error:
            print(f"codifold mcp: 读取失败：{error}", file=sys.stderr)
            return 1
        if raw is None:
            return 0
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _send(outstream, _error_response(None, -32700, f"Parse error: {error}"))
            continue
        response = server.handle(message)
        if response is not None:
            _send(outstream, response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="codifold.mcp_server",
        description="Codifold 工作台 MCP 服务器（stdio）："
                    "提供 brief / apply / check / coherence / export-md。",
    )
    parser.add_argument("--version", action="version",
                        version=f"{SERVER_NAME} {SERVER_VERSION}")
    parser.parse_args(argv)
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
