"""Workspace manifest: ``codifold.json``.

工作区配置负责项目级元数据、源码绑定和视图发现规则；视图文件按后缀加载。

    {
      "project": {"name": "...", "description": "...", "root": "."},
      "files": ["app.py"],
      "views": {"suffix": ".blocks.json", "entry": "main"}
    }
"""
from __future__ import annotations

import json
from pathlib import Path

from .fsutil import data_revision

MANIFEST_NAME = "codifold.json"
DEFAULT_SUFFIX = ".blocks.json"
MAX_MANIFEST_BYTES = 256 * 1024


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{MANIFEST_NAME} 的 {field} 必须是非空字符串")
    return value.strip()


def validate_manifest(directory: Path, data) -> dict:
    """Validate a manifest object against ``directory`` without reading the file."""
    directory = directory.resolve()
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_NAME} 必须是 JSON 对象")
    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{MANIFEST_NAME} 缺少 project")
    name = _text(project.get("name"), "project.name")
    description = _text(project.get("description"), "project.description")

    root_value = project.get("root", ".")
    if not isinstance(root_value, str) or not root_value.strip():
        raise ValueError(f"{MANIFEST_NAME} 的 project.root 必须是非空字符串")
    root = Path(root_value.strip()).expanduser()
    if not root.is_absolute():
        root = directory / root
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"{MANIFEST_NAME} 的 project.root 不是目录：{root}")

    files_value = data.get("files", [])
    if not isinstance(files_value, list):
        raise ValueError(f"{MANIFEST_NAME} 的 files 必须是数组")
    files = []
    paths: dict[str, Path] = {}
    for index, item in enumerate(files_value):
        field = f"files[{index}]"
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{MANIFEST_NAME} 的 {field} 必须是非空字符串")
        relative = Path(item.strip())
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{MANIFEST_NAME} 的 {field} 只能是 root 内的相对路径")
        file = relative.as_posix()
        if file in paths:
            raise ValueError(f"{MANIFEST_NAME} 的 {field} 重复：{file}")
        source = (root / relative).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"{MANIFEST_NAME} 的 {field} 解析后不在 root 内：{file}")
        if not source.is_file():
            raise FileNotFoundError(f"{MANIFEST_NAME} 声明的文件不存在：{file}")
        files.append(file)
        paths[file] = source

    views = data.get("views", {})
    if not isinstance(views, dict):
        raise ValueError(f"{MANIFEST_NAME} 的 views 必须是对象")
    suffix = views.get("suffix", DEFAULT_SUFFIX)
    if not isinstance(suffix, str) or not suffix.strip():
        raise ValueError(f"{MANIFEST_NAME} 的 views.suffix 必须是非空字符串")
    suffix = suffix.strip()
    if not suffix.startswith(".") or not suffix.endswith(".json") or suffix == ".json" \
            or "/" in suffix or "\\" in suffix:
        raise ValueError(f"{MANIFEST_NAME} 的 views.suffix 必须是 .xxx.json 形式的文件后缀")
    entry = views.get("entry")
    if entry is not None:
        entry = _text(entry, "views.entry")
    view_format = views.get("format", "nested")
    if view_format not in {"nested", "flat"}:
        raise ValueError(f"{MANIFEST_NAME} 的 views.format 只能是 nested 或 flat")

    return {
        "path": str(directory / MANIFEST_NAME),
        "directory": str(directory),
        "name": name,
        "description": description,
        "root": str(root),
        "files": files,
        "paths": paths,
        "suffix": suffix,
        "entry": entry,
        "format": view_format,
    }


def load_manifest(directory: Path) -> dict | None:
    directory = directory.resolve()
    target = directory / MANIFEST_NAME
    if not target.is_file():
        return None
    if target.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError(f"{MANIFEST_NAME} 超过 {MAX_MANIFEST_BYTES // 1024} KB")
    raw = target.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    checked = validate_manifest(directory, data)
    checked["revision"] = data_revision(raw)
    return checked
