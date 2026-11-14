"""Cooperative locks shared by the HTTP, CLI and MCP writers.

Lock files stay in the user state directory: unlinking an active lock file
would allow another process to lock a different inode. OS locks are released
on process exit. External editors do not participate in this protocol.
"""
from __future__ import annotations

import errno
import hashlib
import inspect
import os
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .paths import state_dir

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_held = threading.local()
LOCK_TIMEOUT = 10.0


@contextmanager
def resource_lock(key: str):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    target = (state_dir() / "locks" / f"{digest}.lock").resolve()
    name = str(target)
    with _guard:
        local_lock = _locks.setdefault(name, threading.RLock())
    if not local_lock.acquire(timeout=LOCK_TIMEOUT):
        raise ValueError("工作区正由其他 Codifold 请求写入，请稍后重试")
    try:
        held = getattr(_held, "names", None)
        if held is None:
            held = _held.names = set()
        if name in held:
            yield
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                if target.stat().st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
            else:
                import fcntl
            deadline = time.monotonic() + LOCK_TIMEOUT
            while True:
                try:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if time.monotonic() >= deadline:
                        raise ValueError("工作区正由其他 Codifold 进程写入，请稍后重试") from error
                    time.sleep(0.05)
            held.add(name)
            try:
                yield
            finally:
                held.remove(name)
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    finally:
        local_lock.release()


def workspace_write(function):
    """Serialize a complete mutation, including validation and rollback."""
    parameter = next(iter(inspect.signature(function).parameters))

    @wraps(function)
    def serialized(*args, **kwargs):
        path = args[0] if args else kwargs.get(parameter)
        if not isinstance(path, str) or not path.strip():
            return function(*args, **kwargs)
        directory = Path(path).expanduser().resolve()
        with resource_lock("workspace:" + str(directory)):
            return function(*args, **kwargs)

    return serialized
