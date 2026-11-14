"""Command line entry point for the taskflow demo service."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from .api import Api, ApiServer
from .config import Settings, load_settings, validate_settings
from .events import EventBus
from .pipeline import Pipeline
from .registry import load_plugins, registered_steps
from .storage import Storage
from .worker import Scheduler, Worker

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Runtime:
    settings: Settings
    storage: Storage
    bus: EventBus
    pipeline: Pipeline
    workers: list[Worker]
    scheduler: Scheduler | None
    server: ApiServer | None


def _build_runtime(settings: Settings, stop_event: threading.Event, *,
                   with_http: bool, with_scheduler: bool,
                   worker_count: int | None = None) -> Runtime:
    storage = Storage(settings.database)
    try:
        bus = EventBus()
        load_plugins(settings.plugin_package, bus)
        pipeline = Pipeline(registered_steps(), storage)
        count = settings.workers if worker_count is None else worker_count
        workers = [
            Worker(f"worker-{index + 1}", storage, pipeline, bus, stop_event,
                   settings.poll_seconds, settings.lease_seconds)
            for index in range(count)
        ]
        scheduler = None
        if with_scheduler:
            scheduler = Scheduler(storage, bus, stop_event,
                                  settings.scheduler_seconds,
                                  settings.retention_seconds)
        server = None
        if with_http:
            api = Api(settings, storage, pipeline, bus, settings.api_token)
            server = ApiServer((settings.host, settings.port), api)
    except Exception:
        storage.close()
        raise
    return Runtime(settings, storage, bus, pipeline, workers, scheduler, server)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    if threading.current_thread() is not threading.main_thread():
        return

    def handle(signum: int, frame: object) -> None:
        log.info("received signal %s, shutting down", signum)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle)


def _wait_for_stop(stop_event: threading.Event) -> None:
    while not stop_event.wait(1.0):
        pass


def _shutdown(runtime: Runtime, stop_event: threading.Event,
              server_thread: threading.Thread | None = None) -> None:
    stop_event.set()
    if runtime.server is not None:
        runtime.server.shutdown()
        runtime.server.server_close()
    if server_thread is not None:
        server_thread.join(timeout=3)
    if runtime.scheduler is not None and runtime.scheduler.ident is not None:
        runtime.scheduler.join(timeout=5)
    for worker in runtime.workers:
        if worker.ident is not None:
            worker.join(timeout=10)
    runtime.storage.close()
    log.info("shutdown complete")


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    runtime = _build_runtime(settings, stop_event,
                             with_http=True, with_scheduler=True)
    if runtime.server is None or runtime.scheduler is None:
        raise RuntimeError("serve runtime is incomplete")
    for worker in runtime.workers:
        worker.start()
    runtime.scheduler.start()
    server_thread = threading.Thread(
        target=runtime.server.serve_forever, name="http-server", daemon=True
    )
    server_thread.start()
    log.info("taskflow listening on http://%s:%d", settings.host, settings.port)
    try:
        _wait_for_stop(stop_event)
    finally:
        _shutdown(runtime, stop_event, server_thread)
    return 0


def cmd_worker(settings: Settings, args: argparse.Namespace) -> int:
    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    runtime = _build_runtime(settings, stop_event,
                             with_http=False, with_scheduler=False)
    for worker in runtime.workers:
        worker.start()
    log.info("started %d worker(s)", len(runtime.workers))
    try:
        _wait_for_stop(stop_event)
    finally:
        _shutdown(runtime, stop_event)
    return 0


def cmd_enqueue(settings: Settings, args: argparse.Namespace) -> int:
    storage = Storage(settings.database)
    try:
        bus = EventBus()
        load_plugins(settings.plugin_package, bus)
        pipeline = Pipeline(registered_steps(), storage)
        pipeline.plan_for(args.kind)
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError as error:
            raise ValueError(f"payload 不是合法 JSON：{error}") from error
        if not isinstance(payload, dict):
            raise ValueError("payload 必须是 JSON 对象")
        job = storage.create_job(args.kind, payload, args.max_attempts)
        bus.publish("job.created", {"job_id": job.id, "kind": job.kind})
        print(json.dumps({"job": job.to_dict()}, ensure_ascii=False, indent=2))
    finally:
        storage.close()
    return 0


def cmd_status(settings: Settings, args: argparse.Namespace) -> int:
    storage = Storage(settings.database)
    try:
        if args.job is not None:
            job = storage.get_job(args.job)
            if job is None:
                print(f"任务不存在：{args.job}", file=sys.stderr)
                return 1
            payload = {"job": job.to_dict()}
        else:
            jobs = storage.list_jobs(args.state, args.limit)
            payload = {
                "stats": storage.stats(),
                "jobs": [job.to_dict() for job in jobs],
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        storage.close()
    return 0


def cmd_run_once(settings: Settings, args: argparse.Namespace) -> int:
    stop_event = threading.Event()
    runtime = _build_runtime(settings, stop_event, with_http=False,
                             with_scheduler=False, worker_count=1)
    try:
        processed = runtime.workers[0].run_once()
        print(json.dumps({"processed": processed, "stats": runtime.storage.stats()},
                         ensure_ascii=False))
    finally:
        _shutdown(runtime, stop_event)
    return 0


COMMANDS = {
    "serve": cmd_serve,
    "worker": cmd_worker,
    "enqueue": cmd_enqueue,
    "status": cmd_status,
    "run-once": cmd_run_once,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskflow", description="A small SQLite-backed workflow engine."
    )
    parser.add_argument("--config", help="JSON 配置文件路径")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动 HTTP API、worker 和调度器")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--workers", type=int)
    serve.add_argument("--token")
    serve.add_argument("--db", dest="database")

    worker = sub.add_parser("worker", help="只启动 worker 线程")
    worker.add_argument("--workers", type=int)
    worker.add_argument("--db", dest="database")

    enqueue = sub.add_parser("enqueue", help="创建一条任务")
    enqueue.add_argument("kind")
    enqueue.add_argument("--payload", default="{}")
    enqueue.add_argument("--max-attempts", type=int, default=3)
    enqueue.add_argument("--db", dest="database")

    status = sub.add_parser("status", help="查看任务与计数")
    status.add_argument("--job", type=int)
    status.add_argument("--state")
    status.add_argument("--limit", type=int, default=20)
    status.add_argument("--db", dest="database")

    once = sub.add_parser("run-once", help="领取并执行一条任务后退出")
    once.add_argument("--db", dest="database")
    return parser


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    updates = {}
    for field in ("host", "port", "workers"):
        value = getattr(args, field, None)
        if value is not None:
            updates[field] = value
    token = getattr(args, "token", None)
    if token is not None:
        updates["api_token"] = token or None
    database = getattr(args, "database", None)
    if database:
        updates["database"] = Path(database).expanduser()
    if args.log_level:
        updates["log_level"] = args.log_level
    return replace(settings, **updates)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = validate_settings(_apply_overrides(load_settings(args.config), args))
    except (OSError, ValueError) as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    command = COMMANDS[args.command]
    try:
        return command(settings, args)
    except KeyboardInterrupt:
        log.info("interrupted")
        return 130
    except (OSError, ValueError, ImportError) as error:
        log.error("%s", error)
        return 2
