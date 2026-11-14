"""Maintenance steps that keep the job table small."""
from __future__ import annotations

from typing import Any

from taskflow.registry import step


@step("maintenance.prune", retries=0)
def prune(context: dict[str, Any]) -> dict[str, Any]:
    storage = context["storage"]
    if storage is None:
        raise RuntimeError("maintenance step requires storage")
    raw = context["payload"].get("retention_seconds", 3600)
    retention = float(raw)
    if retention < 0:
        raise ValueError("retention_seconds 不能为负")
    removed = storage.prune(retention)
    return {"removed": removed, "retention_seconds": retention}
