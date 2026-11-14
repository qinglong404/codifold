"""JSON HTTP API and route decorators for taskflow."""
from __future__ import annotations

import json
import logging
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .events import EventBus
from .pipeline import Pipeline, UnknownPipeline
from .storage import Job, Storage

log = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024


@dataclass(slots=True)
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"请求体不是合法 JSON：{error}") from error
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def query_one(self, key: str, default: str | None = None) -> str | None:
        values = self.query.get(key) or []
        return values[0] if values else default


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    pattern: re.Pattern[str]
    handler: str
    requires_auth: bool = True


ROUTES: list[Route] = []


def route(method: str, path: str, *,
          auth: bool = True) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    pattern = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$")

    def decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        ROUTES.append(Route(method.upper(), pattern, handler.__name__, auth))
        return handler

    return decorate


def _json_job(job: Job) -> dict[str, Any]:
    return job.to_dict()


class Api:
    def __init__(self, settings: Settings, storage: Storage,
                 pipeline: Pipeline, bus: EventBus,
                 token: str | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.pipeline = pipeline
        self.bus = bus
        self.token = token

    def dispatch(self, request: Request) -> tuple[int, dict[str, Any]]:
        matched: tuple[Route, dict[str, str]] | None = None
        for spec in ROUTES:
            if spec.method != request.method:
                continue
            match = spec.pattern.match(request.path)
            if match is not None:
                matched = (spec, match.groupdict())
                break
        if matched is None:
            return 404, {"error": "route not found"}
        spec, params = matched
        if spec.requires_auth and self.token and not self._authorized(request):
            return 401, {"error": "unauthorized"}
        handler = getattr(self, spec.handler)
        try:
            return handler(request, **params)
        except ValueError as error:
            return 400, {"error": str(error)}
        except KeyError:
            return 404, {"error": "job not found"}
        except Exception:
            log.exception("request failed: %s %s", request.method, request.path)
            return 500, {"error": "internal error"}

    def _authorized(self, request: Request) -> bool:
        token = request.headers.get("X-API-Token")
        if token:
            return secrets.compare_digest(token, self.token or "")
        header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return secrets.compare_digest(header[len(prefix):], self.token or "")

    @route("GET", "/health", auth=False)
    def health(self, request: Request) -> tuple[int, dict[str, Any]]:
        return 200, {
            "ok": True,
            "stats": self.storage.stats(),
            "steps": sorted(self.pipeline.steps),
        }

    @route("POST", "/api/jobs")
    def create_job(self, request: Request) -> tuple[int, dict[str, Any]]:
        data = request.json()
        kind = data.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("kind 必须是非空字符串")
        try:
            self.pipeline.plan_for(kind)
        except UnknownPipeline as error:
            raise ValueError(str(error)) from error
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 JSON 对象")
        max_attempts = data.get("max_attempts", 3)
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise ValueError("max_attempts 必须是整数")
        job = self.storage.create_job(kind, payload, max_attempts)
        self.bus.publish("job.created", {"job_id": job.id, "kind": job.kind})
        return 201, {"job": _json_job(job)}

    @route("GET", "/api/jobs")
    def list_jobs(self, request: Request) -> tuple[int, dict[str, Any]]:
        state = request.query_one("state")
        limit_text = request.query_one("limit", "50") or "50"
        try:
            limit = int(limit_text)
        except ValueError:
            raise ValueError("limit 必须是整数") from None
        jobs = self.storage.list_jobs(state, limit)
        return 200, {"jobs": [_json_job(job) for job in jobs]}

    @route("GET", "/api/jobs/{job_id}")
    def get_job(self, request: Request, job_id: str) -> tuple[int, dict[str, Any]]:
        job = self.storage.get_job(self._job_id(job_id))
        if job is None:
            raise KeyError(job_id)
        return 200, {"job": _json_job(job)}

    @route("DELETE", "/api/jobs/{job_id}")
    def cancel_job(self, request: Request, job_id: str) -> tuple[int, dict[str, Any]]:
        parsed = self._job_id(job_id)
        if self.storage.get_job(parsed) is None:
            raise KeyError(job_id)
        if not self.storage.cancel_job(parsed):
            return 409, {"error": "job cannot be canceled"}
        self.bus.publish("job.canceled", {"job_id": parsed})
        return 200, {"canceled": True}

    @route("POST", "/api/maintenance")
    def create_maintenance(self, request: Request) -> tuple[int, dict[str, Any]]:
        job = self.storage.create_job("maintenance", {}, max_attempts=2)
        self.bus.publish("job.created", {"job_id": job.id, "kind": job.kind})
        return 202, {"job": _json_job(job)}

    @staticmethod
    def _job_id(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("job_id 必须是整数") from None
        if value <= 0:
            raise ValueError("job_id 必须是正整数")
        return value


class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], api: Api) -> None:
        self.api = api
        super().__init__(address, _Handler)


class _Handler(BaseHTTPRequestHandler):
    server_version = "Taskflow/0.1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        header = self.headers.get("Content-Length", "0")
        try:
            length = int(header)
        except ValueError:
            self._send(400, {"error": "invalid Content-Length"})
            return
        if length < 0:
            self._send(400, {"error": "invalid Content-Length"})
            return
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": "request body too large"})
            return
        body = self.rfile.read(length) if length else b""
        request = Request(method, parsed.path, parse_qs(parsed.query),
                          self.headers, body)
        status, payload = self.server.api.dispatch(request)
        self._send(status, payload)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            log.debug("client disconnected before response")

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("%s - %s", self.address_string(), format % args)
