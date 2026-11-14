"""SQLite-backed job storage with one connection per thread."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(slots=True)
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    state: JobState
    attempts: int
    max_attempts: int
    worker_id: str | None
    lease_until: float | None
    last_error: str | None
    result: dict[str, Any]
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": self.payload,
            "state": self.state.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "worker_id": self.worker_id,
            "lease_until": self.lease_until,
            "last_error": self.last_error,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    worker_id TEXT,
    lease_until REAL,
    last_error TEXT,
    result TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state, created_at);
"""


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=int(row["id"]),
        kind=str(row["kind"]),
        payload=json.loads(row["payload"]),
        state=JobState(row["state"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        worker_id=row["worker_id"],
        lease_until=row["lease_until"],
        last_error=row["last_error"],
        result=json.loads(row["result"] or "{}"),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


class Storage:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.Lock()
        self._ready = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._ready:
                return
            conn = sqlite3.connect(self.path)
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()
            self._ready = True

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def create_job(self, kind: str, payload: dict[str, Any],
                   max_attempts: int = 3) -> Job:
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts 必须在 1–10 之间")
        now = time.time()
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs (kind, payload, state, max_attempts, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False),
                 JobState.QUEUED.value, max_attempts, now, now),
            )
            job_id = int(cursor.lastrowid)
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("新建任务后无法读取记录")
        return job

    def get_job(self, job_id: int) -> Job | None:
        row = self._connect().execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row is not None else None

    def list_jobs(self, state: str | None = None, limit: int = 50) -> list[Job]:
        if not 1 <= limit <= 200:
            raise ValueError("limit 必须在 1–200 之间")
        conn = self._connect()
        if state is None:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            try:
                value = JobState(state).value
            except ValueError:
                raise ValueError(f"未知任务状态：{state}") from None
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state = ? ORDER BY id DESC LIMIT ?",
                (value, limit),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def claim_next(self, worker_id: str, lease_seconds: float) -> Job | None:
        """Atomically take a queued or expired job, incrementing its attempt count."""
        now = time.time()
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE attempts < max_attempts AND ("
                "state = ? OR (state = ? AND lease_until IS NOT NULL AND lease_until < ?)"
                ") ORDER BY created_at, id LIMIT 1",
                (JobState.QUEUED.value, JobState.RUNNING.value, now),
            ).fetchone()
            if row is None:
                return None
            attempts = int(row["attempts"]) + 1
            conn.execute(
                "UPDATE jobs SET state = ?, attempts = ?, worker_id = ?, "
                "lease_until = ?, updated_at = ? WHERE id = ?",
                (JobState.RUNNING.value, attempts, worker_id,
                 now + lease_seconds, now, int(row["id"])),
            )
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (int(row["id"]),)
            ).fetchone()
        return _row_to_job(row) if row is not None else None

    def heartbeat(self, job_id: int, worker_id: str, lease_seconds: float) -> bool:
        now = time.time()
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_until = ?, updated_at = ? "
                "WHERE id = ? AND state = ? AND worker_id = ?",
                (now + lease_seconds, now, job_id, JobState.RUNNING.value, worker_id),
            )
        return cursor.rowcount == 1

    def finish_job(self, job_id: int, worker_id: str, state: JobState,
                   result: dict[str, Any] | None = None,
                   error: str | None = None) -> bool:
        if state not in (JobState.SUCCEEDED, JobState.FAILED):
            raise ValueError("finish_job 只接受 succeeded/failed")
        now = time.time()
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state = ?, result = ?, last_error = ?, "
                "worker_id = NULL, lease_until = NULL, updated_at = ? "
                "WHERE id = ? AND state = ? AND worker_id = ?",
                (state.value, json.dumps(result or {}, ensure_ascii=False),
                 error, now, job_id, JobState.RUNNING.value, worker_id),
            )
        return cursor.rowcount == 1

    def cancel_job(self, job_id: int) -> bool:
        now = time.time()
        with self._write() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? "
                "WHERE id = ? AND state IN (?, ?)",
                (JobState.CANCELED.value, now, job_id,
                 JobState.QUEUED.value, JobState.FAILED.value),
            )
        return cursor.rowcount == 1

    def requeue_expired(self, now: float | None = None) -> list[int]:
        moment = time.time() if now is None else now
        with self._write() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE state = ? AND lease_until IS NOT NULL "
                "AND lease_until < ? AND attempts < max_attempts",
                (JobState.RUNNING.value, moment),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if ids:
                conn.executemany(
                    "UPDATE jobs SET state = ?, worker_id = NULL, lease_until = NULL, "
                    "updated_at = ? WHERE id = ?",
                    [(JobState.QUEUED.value, moment, job_id) for job_id in ids],
                )
        return ids

    def fail_exhausted(self, now: float | None = None) -> list[int]:
        moment = time.time() if now is None else now
        with self._write() as conn:
            rows = conn.execute(
                "SELECT id, attempts FROM jobs WHERE state = ? "
                "AND lease_until IS NOT NULL AND lease_until < ? "
                "AND attempts >= max_attempts",
                (JobState.RUNNING.value, moment),
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            if ids:
                conn.executemany(
                    "UPDATE jobs SET state = ?, last_error = ?, worker_id = NULL, "
                    "lease_until = NULL, updated_at = ? WHERE id = ?",
                    [(JobState.FAILED.value,
                      f"租约过期，已用完 {int(row['attempts'])} 次尝试",
                      moment, int(row["id"])) for row in rows],
                )
        return ids

    def prune(self, retention_seconds: float, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        cutoff = moment - max(0.0, retention_seconds)
        with self._write() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE state IN (?, ?) AND updated_at < ?",
                (JobState.SUCCEEDED.value, JobState.CANCELED.value, cutoff),
            )
        return int(cursor.rowcount)

    def stats(self) -> dict[str, int]:
        counts = {state.value: 0 for state in JobState}
        rows = self._connect().execute(
            "SELECT state, COUNT(*) AS count FROM jobs GROUP BY state"
        ).fetchall()
        for row in rows:
            counts[str(row["state"])] = int(row["count"])
        return counts

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
