"""Small filesystem helpers shared by the writer and the workspace registry.

写文件统一走同目录临时文件 + ``replace``，避免半截 JSON；修订值用文件内容的
SHA-256，前端拿它做“我读到的那一版”检查。
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def atomic_write_text(target: Path, text: str) -> None:
    atomic_write_bytes(target, text.encode("utf-8"))


def data_revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_revision(target: Path) -> str:
    return data_revision(target.read_bytes())
