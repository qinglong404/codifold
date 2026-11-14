"""Recently opened workspaces, persisted in the per-user state directory."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import project_config
from .fsutil import atomic_write_text
from .paths import state_dir
from .locking import resource_lock

ROOT = Path(__file__).resolve().parent.parent
MAX_RECENT = 20


def _state_dir() -> Path:
    return state_dir()


def _registry_path() -> Path:
    return _state_dir() / "workspaces.json"


def _normalize(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _read() -> list[dict]:
    target = _registry_path()
    if not target.exists() and not os.environ.get("CODIFOLD_STATE_DIR"):
        # Read existing source-checkout records; the next write migrates them.
        target = ROOT / ".codifold" / "workspaces.json"
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("recent") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("path")
        if not isinstance(raw, str) or not raw.strip():
            continue
        directory = _normalize(raw)
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        name = item.get("name")
        description = item.get("description")
        opened_at = item.get("opened_at")
        result.append({
            "path": key,
            "name": name if isinstance(name, str) else "",
            "description": description if isinstance(description, str) else "",
            "opened_at": opened_at if isinstance(opened_at, str) else None,
        })
        if len(result) >= MAX_RECENT:
            break
    return result


def _write(items: list[dict]) -> None:
    target = _registry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps({"recent": items}, ensure_ascii=False, indent=2) + "\n")


def recent() -> list[dict]:
    """Return recent entries, using live manifest names when the workspace exists."""
    items = _read()
    for item in items:
        directory = Path(item["path"])
        try:
            manifest = project_config.load_manifest(directory)
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = None
        if manifest:
            item["name"] = manifest["name"]
            item["description"] = manifest["description"]
            item["exists"] = True
        else:
            item["exists"] = False
    return items


def remember(directory) -> None:
    with resource_lock("recent:" + str(_registry_path().resolve())):
        _remember(directory)


def _remember(directory) -> None:
    """Move a workspace to the front of the recent list."""
    target = _normalize(str(directory))
    manifest = project_config.load_manifest(target)
    if manifest is None:
        raise ValueError(f"缺少 {project_config.MANIFEST_NAME}，不能记录工作区")
    items = [item for item in _read() if item["path"] != str(target)]
    items.insert(0, {
        "path": str(target),
        "name": manifest["name"],
        "description": manifest["description"],
        "opened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    _write(items[:MAX_RECENT])


def forget(path) -> bool:
    """Remove one workspace from the recent list without touching the directory."""
    with resource_lock("recent:" + str(_registry_path().resolve())):
        return _forget(path)


def _forget(path) -> bool:
    target = _normalize(str(path))
    items = _read()
    remaining = [item for item in items if item["path"] != str(target)]
    if len(remaining) == len(items):
        return False
    _write(remaining)
    return True
