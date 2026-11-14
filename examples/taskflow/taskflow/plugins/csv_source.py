"""Read a CSV file and expose its rows to later pipeline steps."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from taskflow.registry import on, step

log = logging.getLogger(__name__)


@step("csv.import", retries=2, backoff=0.1)
def import_csv(context: dict[str, Any]) -> dict[str, Any]:
    """Read payload.path and return parsed rows plus the discovered columns."""
    payload = context["payload"]
    raw_path = payload.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("payload.path 必须是非空字符串")
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"CSV 文件不存在：{path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        if "name" not in columns or "amount" not in columns:
            raise ValueError("CSV 必须包含 name 和 amount 列")
        rows = []
        for index, row in enumerate(reader, start=2):
            try:
                rows.append({
                    "name": row["name"],
                    "amount": float(row["amount"]),
                    "line": index,
                })
            except (TypeError, ValueError) as error:
                raise ValueError(f"第 {index} 行 amount 不是数字") from error
    return {"columns": columns, "rows": rows, "source": str(path)}


@on("job.failed")
def remember_failure(topic: str, payload: dict[str, Any]) -> None:
    log.warning("job %s failed: %s", payload.get("job_id"), payload.get("error"))
