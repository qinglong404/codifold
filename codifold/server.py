"""Local-only static server and JSON APIs.

Serves the Codifold block reader/editor at / and its JSON APIs. The server never
imports or executes the analysed project; it validates and stores the JSON that
an external AI (or a human) writes.
"""
from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import block_config, browse, editor, mapping_report

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
MAX_BODY_BYTES = block_config.MAX_BYTES * 2


def create_server(port=5190):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(DIST), **kwargs)

        def log_message(self, format, *args):
            # Avoid printing user source or local import paths.
            pass

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def send_json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get("Host", "").split(":")[0] in {"127.0.0.1", "localhost"}

        def do_GET(self):
            if not self.valid_host():
                return self.send_json({"error": "仅支持本机访问"}, 403)
            route = urlsplit(self.path).path
            if route in {"/", "/index.html"}:
                self.path = "/index.html"
                return super().do_GET()
            if route in {"/blocks", "/blocks/"}:
                # 旧地址继续可用，但统一加载新的单页应用。
                self.path = "/index.html"
                return super().do_GET()
            if route in {"/gradebook", "/gradebook/", "/demo", "/demo/"}:
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if route == "/api/views":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                try:
                    return self.send_json(block_config.load_index(path))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/coverage":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                try:
                    return self.send_json(mapping_report.report(path))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/events":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                try:
                    return self.send_json(editor.event_names(path))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/project":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                try:
                    return self.send_json(editor.project_settings(path))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/workspaces":
                try:
                    result = editor.recent_workspaces()
                    result["examples"] = browse.example_workspaces()
                    return self.send_json(result)
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/browse":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                try:
                    return self.send_json(browse.list_directory(path))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if route == "/api/blocks-config":
                query = parse_qs(urlsplit(self.path).query)
                path = query.get("path", [None])[0]
                view = query.get("view", [None])[0]
                try:
                    return self.send_json(block_config.load(path, view))
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    return self.send_json({"error": str(error)}, 400)
            if self.path.startswith("/api/"):
                return self.send_json({"error": "接口不存在"}, 404)
            return super().do_GET()

        def do_POST(self):
            # Reject cross-site writes and DNS rebinding. No permissive CORS.
            origin = self.headers.get("Origin")
            if not self.valid_host() or (origin and origin != "http://" + self.headers.get("Host")):
                return self.send_json({"error": "仅接受当前本地页面的请求"}, 403)
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise ValueError("请求体积超过限制")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求必须是 JSON 对象")
                route = urlsplit(self.path).path
                if route == "/api/views":
                    options = {}
                    if "revision" in body:
                        options["revision"] = body["revision"]
                    return self.send_json(editor.save_view(
                        body.get("path"), body.get("config"), **options))
                if route == "/api/project":
                    options = {}
                    if "revision" in body:
                        options["revision"] = body["revision"]
                    return self.send_json(editor.save_project(
                        body.get("path"), body.get("config"), **options))
                if route == "/api/blocks":
                    options = {key: value for key, value in body.items()
                               if key not in {"path", "view", "action", "revision"}}
                    if "revision" in body:
                        options["revision"] = body["revision"]
                    return self.send_json(editor.mutate_view(
                        body.get("path"), body.get("view"),
                        body.get("action"), **options))
                if route == "/api/workspaces/open":
                    return self.send_json(editor.open_workspace(body.get("path")))
                if route == "/api/workspaces":
                    result = editor.create_workspace(
                        body.get("directory"), body.get("name"), body.get("description"),
                        body.get("view_id", "main"), body.get("view_name", "主流程"),
                        body.get("view_description"))
                    try:
                        editor.remember_workspace(result["index"]["source"]["path"])
                    except (OSError, ValueError):
                        pass
                    return self.send_json(result)
                return self.send_json({"error": "接口不存在"}, 404)
            except editor.RevisionConflict as error:
                return self.send_json({
                    "error": str(error),
                    "code": "revision_conflict",
                    "current_revision": error.current,
                }, 409)
            except (ValueError, TypeError, OSError, json.JSONDecodeError) as error:
                return self.send_json({"error": str(error)}, 400)

        def do_DELETE(self):
            origin = self.headers.get("Origin")
            if not self.valid_host() or (origin and origin != "http://" + self.headers.get("Host")):
                return self.send_json({"error": "仅接受当前本地页面的请求"}, 403)
            route = urlsplit(self.path).path
            query = parse_qs(urlsplit(self.path).query)
            try:
                if route == "/api/views":
                    options = {}
                    if "revision" in query:
                        options["revision"] = query["revision"][0]
                    if "manifest_revision" in query:
                        options["manifest_revision"] = query["manifest_revision"][0]
                    return self.send_json(editor.delete_view(
                        query.get("path", [None])[0], query.get("view", [None])[0],
                        **options))
                if route == "/api/workspaces":
                    return self.send_json(editor.delete_workspace(
                        query.get("path", [None])[0], query.get("confirm", [None])[0]))
                if route == "/api/workspaces/recent":
                    return self.send_json(editor.forget_workspace(
                        query.get("path", [None])[0]))
                return self.send_json({"error": "接口不存在"}, 404)
            except editor.RevisionConflict as error:
                return self.send_json({
                    "error": str(error),
                    "code": "revision_conflict",
                    "current_revision": error.current,
                }, 409)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                return self.send_json({"error": str(error)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server
