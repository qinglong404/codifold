"""Local directory browsing for the workspace picker.

只列目录，不读文件内容；服务本身只监听 127.0.0.1，并沿用 server 的 Host 校验。
浏览结果只用于选择工作区目录，不参与校验（真正的校验在 open_workspace）。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import block_config
from .project_config import MANIFEST_NAME, load_manifest

ROOT = Path(__file__).resolve().parent.parent
MAX_ENTRIES = 400
# 常见的大目录/工具目录，浏览时不显示，避免淹没项目目录。
NOISE = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
}


def _shortcuts() -> list[dict]:
    home = Path.home()
    return [
        {"name": "主目录", "path": str(home)},
        {"name": "Codifold 仓库", "path": str(ROOT)},
        {"name": "示例", "path": str(ROOT / "examples")},
    ]


def list_directory(path: str | None = None) -> dict:
    """List immediate subdirectories of ``path`` (defaults to the home directory)."""
    raw = (path or "").strip()
    target = Path(raw).expanduser() if raw else Path.home()
    if not target.is_absolute():
        raise ValueError("目录必须是绝对路径")
    if not target.exists():
        raise FileNotFoundError(f"目录不存在：{target}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录：{target}")
    target = target.resolve()

    entries = []
    truncated = False
    try:
        children = list(target.iterdir())
    except PermissionError as error:
        raise PermissionError(f"没有权限读取目录：{target}") from error
    for child in children:
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            break
        name = child.name
        if name in NOISE:
            continue
        try:
            if not child.is_dir():
                continue
            entries.append({
                "name": name,
                "path": str(child),
                "is_workspace": (child / MANIFEST_NAME).is_file(),
            })
        except OSError:
            continue

    entries.sort(key=lambda item: (not item["is_workspace"], item["name"].lower()))
    parent = target.parent
    return {
        "path": str(target),
        "parent": str(parent) if parent != target else None,
        "is_workspace": (target / MANIFEST_NAME).is_file(),
        "entries": entries,
        "truncated": truncated,
        "shortcuts": _shortcuts(),
    }


def example_workspaces() -> list[dict]:
    """Return valid workspaces under the repository's ``examples/`` directory."""
    base = ROOT / "examples"
    if not base.is_dir():
        return []
    result = []
    for directory in sorted(base.iterdir(), key=lambda item: item.name.lower()):
        if not directory.is_dir():
            continue
        try:
            manifest = load_manifest(directory)
            if not manifest:
                continue
            index = block_config.load_index(str(directory))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        result.append({
            "path": str(directory.resolve()),
            "name": index["project"]["name"],
            "description": index["project"]["description"],
            "views": len(index["views"]),
            "entry": index["entry"],
        })
    return result
