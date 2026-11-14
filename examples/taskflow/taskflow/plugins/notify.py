"""Forward a finished report to an optional webhook."""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from taskflow.registry import on, step

log = logging.getLogger(__name__)


@step("notify.webhook", retries=2, backoff=0.25)
def notify(context: dict[str, Any]) -> dict[str, Any]:
    payload = context["payload"]
    url = payload.get("webhook")
    if not url:
        return {"skipped": True, "reason": "payload.webhook is empty"}
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("payload.webhook 必须是 http(s) 地址")
    summary = context["outputs"].get("report.summarize", {})
    body = json.dumps({"job": context["job"].id, "summary": summary},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return {"status": response.status,
                "body": response.read(200).decode("utf-8", "replace")}


@on("job.lost")
def warn_lost_job(topic: str, payload: dict[str, Any]) -> None:
    log.warning("job %s lost its lease on worker %s",
                payload.get("job_id"), payload.get("worker"))
