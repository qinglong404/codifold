"""Aggregate imported rows into a small per-person report."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from taskflow.registry import on, step

log = logging.getLogger(__name__)


@step("report.summarize", retries=1, backoff=0.2)
def summarize(context: dict[str, Any]) -> dict[str, Any]:
    rows = context["outputs"].get("csv.import", {}).get("rows", [])
    if not rows:
        raise ValueError("没有可汇总的数据行")
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        name = str(row["name"])
        totals[name] += float(row["amount"])
        counts[name] += 1
    ranking = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return {
        "total": round(sum(totals.values()), 2),
        "people": len(totals),
        "ranking": [
            {"name": name, "total": round(total, 2), "count": counts[name]}
            for name, total in ranking
        ],
    }


@on("job.succeeded")
def log_summary(topic: str, payload: dict[str, Any]) -> None:
    merged = (payload.get("output") or {}).get("merged", {})
    if "total" in merged:
        log.info("report for job %s: total=%s", payload.get("job_id"), merged["total"])
