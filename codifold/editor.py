"""Write support for workspace views.

编辑只作用于工作区里的 ``*.blocks.json`` 和 ``codifold.json``：先走
``block_config.validate`` 的结构校验，再原子写入，最后用
``checks.report`` 做整项目复检；复检失败会回滚到写入前的文件。
草稿允许尚未接通的视图；契约与引用错误仍然阻止保存。

所有写接口都要求目录里存在 ``codifold.json``；单文件 ``?config=`` 模式保持只读。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import block_config, checks, flat, flat_ops, project_config, workspace_registry
from .fsutil import atomic_write_bytes as _atomic_write_bytes
from .fsutil import atomic_write_text as _atomic_write_text
from .fsutil import data_revision, file_revision
from .locking import workspace_write

MANIFEST_NAME = project_config.MANIFEST_NAME
_UNSET = object()


class RevisionConflict(ValueError):
    """The file changed after the client read it."""

    def __init__(self, message: str, current: str | None = None):
        super().__init__(message)
        self.current = current



def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _workspace_directory(path) -> Path:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺少工作区路径")
    directory = Path(path).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区目录：{directory}")
    if not directory.is_dir():
        raise ValueError("编辑只支持工作区目录，不能写入单个视图文件")
    directory = directory.resolve()
    if not (directory / MANIFEST_NAME).is_file():
        raise ValueError(f"缺少 {MANIFEST_NAME}，不能编辑该项目")
    return directory


def _workspace(path) -> Path:
    directory = _workspace_directory(path)
    if project_config.load_manifest(directory) is None:
        raise ValueError(f"缺少 {MANIFEST_NAME}，不能编辑该项目")
    return directory


def _view_text(config: dict, *, flat_format: bool = False) -> str:
    if flat_format:
        payload = {"view": config["view"], "containers": config["containers"],
                   "blocks": config["blocks"]}
    else:
        payload = {"view": config["view"], "blocks": config["blocks"]}
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if len(data.encode("utf-8")) > block_config.MAX_BYTES:
        raise ValueError("视图配置超过 2 MB")
    return data


def _checked_view(config: dict) -> tuple[dict, dict | None, bool]:
    """Return nested projection, canonical flat form, and whether input was flat."""
    if flat.is_flat(config):
        nested = flat.validate_flat(config)
        return nested, flat.from_nested(nested), True
    nested = block_config.validate(config)
    return nested, None, False


def _target_is_flat(manifest: dict, target: Path, created: bool) -> bool:
    if manifest.get("format") == "flat":
        return True
    if created:
        return False
    try:
        return flat.is_flat(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def _view_target(directory: Path, manifest: dict, index: dict,
                 view_id: str) -> tuple[Path, bool]:
    for view in index["views"]:
        if view["view_id"] != view_id:
            continue
        file = view["file"]
        if Path(file).name != file or "/" in file or "\\" in file:
            raise ValueError(f"视图文件名不合法：{file}")
        target = (directory / file).resolve()
        if target.parent != directory:
            raise ValueError(f"视图文件不在工作区目录内：{file}")
        if not target.is_file():
            raise FileNotFoundError(f"视图文件不存在：{file}")
        return target, False
    target = (directory / f"{view_id}{manifest['suffix']}").resolve()
    if target.parent != directory:
        raise ValueError(f"视图文件不在工作区目录内：{target.name}")
    if target.exists():
        raise ValueError(f"视图文件已存在但不在视图索引中：{target.name}")
    return target, True


def _check_revision(data: bytes | None, expected) -> str | None:
    current = data_revision(data) if data is not None else None
    if expected is _UNSET:
        return current
    if expected is not None and not isinstance(expected, str):
        raise ValueError("revision 必须是字符串或 null")
    if expected != current:
        raise RevisionConflict("文件已被其他编辑修改，请重新加载后再保存", current)
    return current


def _manifest_raw(directory: Path) -> tuple[dict, str]:
    target = directory / MANIFEST_NAME
    raw = target.read_bytes()
    if len(raw) > project_config.MAX_MANIFEST_BYTES:
        raise ValueError(f"{MANIFEST_NAME} 超过 {project_config.MAX_MANIFEST_BYTES // 1024} KB")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_NAME} 必须是 JSON 对象")
    return data, data_revision(raw)


def _restore(target: Path, previous: bytes | None, created: bool) -> None:
    if created:
        try:
            target.unlink()
        except FileNotFoundError:
            pass
    elif previous is not None:
        _atomic_write_bytes(target, previous)


def _set_entry(directory: Path, entry: str | None) -> None:
    manifest_path = directory / MANIFEST_NAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_NAME} 必须是 JSON 对象")
    views = data.setdefault("views", {})
    if not isinstance(views, dict):
        raise ValueError(f"{MANIFEST_NAME} 的 views 必须是对象")
    if entry is None:
        views.pop("entry", None)
    else:
        views["entry"] = entry
    _atomic_write_text(manifest_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _project_report(directory: Path, *, strict: bool = False) -> dict:
    return checks.report(str(directory), draft=not strict)


def _report_error(report: dict) -> str:
    return "保存后项目校验失败：" + "；".join(report["errors"])


def _iter_blocks(blocks):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


@workspace_write
def save_view(path, config, revision=_UNSET) -> dict:
    """Create or update one view, validating the whole workspace afterwards."""
    directory = _workspace(path)
    checked, flat_config, _ = _checked_view(config)
    view_id = checked["view"]["id"]
    manifest = project_config.load_manifest(directory)
    if manifest is None:
        raise ValueError(f"缺少 {MANIFEST_NAME}，不能编辑该项目")
    index = block_config.load_index(str(directory))
    target, created = _view_target(directory, manifest, index, view_id)
    previous = None if created else target.read_bytes()
    _check_revision(previous, revision)
    if created and target.exists():
        raise RevisionConflict("视图文件已被其他编辑创建", file_revision(target))
    flat_format = _target_is_flat(manifest, target, created)
    out = (flat_config or flat.from_nested(checked)) if flat_format else checked
    _atomic_write_text(target, _view_text(out, flat_format=flat_format))
    try:
        report = _project_report(directory)
        if not report["ok"]:
            raise ValueError(_report_error(report))
        payload = block_config.load(str(directory), view_id)
        updated = block_config.load_index(str(directory))
    except Exception:
        _restore(target, previous, created)
        raise
    return {
        "payload": payload,
        "index": updated,
        "warnings": report["warnings"],
        "created": created,
        "revision": payload["revision"],
        "manifest_revision": payload.get("manifest_revision"),
    }


@workspace_write
def save_views(path, configs, *, strict: bool = False) -> dict:
    """Create or update a batch of views, validating the workspace once.

    Batch mode exists for the conversion workbench: a new entry view may jump
    to a detail view created in the same batch, so all files must be visible
    before the whole-project check runs.
    """
    directory = _workspace(path)
    if not isinstance(configs, list) or not configs:
        raise ValueError("configs 必须是非空数组")
    checked_entries = [_checked_view(config) for config in configs]
    checked = [entry[0] for entry in checked_entries]
    view_ids = [config["view"]["id"] for config in checked]
    if len(set(view_ids)) != len(view_ids):
        raise ValueError("同一批次里 view.id 不能重复")
    manifest = project_config.load_manifest(directory)
    if manifest is None:
        raise ValueError(f"缺少 {MANIFEST_NAME}，不能编辑该项目")
    index = block_config.load_index(str(directory))
    plans = []
    targets: set[Path] = set()
    for nested, flat_config, _ in checked_entries:
        target, created = _view_target(directory, manifest, index,
                                       nested["view"]["id"])
        if target in targets:
            raise ValueError(f"多个视图指向同一文件：{target.name}")
        targets.add(target)
        previous = None if created else target.read_bytes()
        flat_format = _target_is_flat(manifest, target, created)
        out = (flat_config or flat.from_nested(nested)) if flat_format else nested
        plans.append({"config": out, "view_id": nested["view"]["id"],
                      "flat_format": flat_format, "target": target,
                      "created": created, "previous": previous})
    written = []
    try:
        for plan in plans:
            _atomic_write_text(plan["target"],
                               _view_text(plan["config"],
                                          flat_format=plan["flat_format"]))
            written.append(plan)
        report = _project_report(directory, strict=strict)
        if not report["ok"]:
            raise ValueError(_report_error(report))
        if strict and report["warnings"]:
            raise ValueError("保存后项目有警告：" + "；".join(report["warnings"][:5]))
        payloads = {
            config["view"]["id"]: block_config.load(str(directory),
                                                     config["view"]["id"])
            for config in checked
        }
        updated = block_config.load_index(str(directory))
    except Exception:
        for plan in reversed(written):
            _restore(plan["target"], plan["previous"], plan["created"])
        raise
    return {
        "payloads": payloads,
        "index": updated,
        "warnings": report["warnings"],
        "report": report,
        "created": [plan["view_id"] for plan in plans if plan["created"]],
        "updated": [plan["view_id"] for plan in plans if not plan["created"]],
    }


@workspace_write
def apply_drafts(path, specs, *, strict: bool = False) -> dict:
    """Allocate IDs and write drafts under the same workspace lock."""
    from . import draft
    configs = draft.compile_drafts(path, specs)
    return save_views(path, configs, strict=strict)


@workspace_write
def mutate_view(path, view_id, action: str, *, revision=_UNSET, **payload) -> dict:
    """Apply one block/container operation to a flat view and revalidate."""
    directory = _workspace(path)
    if not isinstance(view_id, str) or not view_id.strip():
        raise ValueError("缺少视图 id")
    index = block_config.load_index(str(directory))
    chosen = next((view for view in index["views"]
                   if view["view_id"] == view_id), None)
    if chosen is None:
        raise ValueError(f"找不到视图：{view_id}")
    file = chosen["file"]
    target = (directory / file).resolve()
    if target.parent != directory:
        raise ValueError(f"视图文件不在工作区目录内：{file}")
    previous = target.read_bytes()
    _check_revision(previous, revision)
    raw = json.loads(previous.decode("utf-8"))
    if not flat.is_flat(raw):
        raise ValueError("块操作只支持 flat 视图；旧嵌套视图请先转换")
    current = flat.from_nested(flat.validate_flat(raw))
    result: dict = {}
    if action == "add_block":
        current, ident = flat_ops.add_block(
            current, payload.get("container", "root"),
            after_id=payload.get("after_id"),
            name=payload.get("name") or "新块",
            description=payload.get("description") or "新步骤。")
        result["block_id"] = ident
    elif action == "add_branch_block":
        current, ident = flat_ops.add_branch_block(
            current, payload.get("container", "root"),
            after_id=payload.get("after_id"),
            name=payload.get("name") or "新分支",
            description=payload.get("description") or "按条件分支。",
            kind=payload.get("kind") or "single")
        result["block_id"] = ident
    elif action == "delete_block":
        current = flat_ops.delete_block(
            current, payload.get("block_id"),
            cascade=bool(payload.get("cascade")))
    elif action == "add_branch":
        current, cid, child = flat_ops.add_branch(
            current, payload.get("block_id"),
            condition=payload.get("condition"),
            role=payload.get("role"))
        result.update({"container_id": cid, "block_id": child})
    elif action == "add_finally":
        current, cid, child = flat_ops.add_finally(
            current, payload.get("block_id"))
        result.update({"container_id": cid, "block_id": child})
    elif action == "delete_container":
        current = flat_ops.delete_container(
            current, payload.get("container_id"))
    elif action == "update_container":
        current = flat_ops.update_container(
            current, payload.get("container_id"),
            condition=(payload["condition"] if "condition" in payload
                       else flat_ops._UNSET),
            role=(payload["role"] if "role" in payload
                  else flat_ops._UNSET))
    else:
        raise ValueError(f"未知块操作：{action}")
    text = _view_text(current, flat_format=True)
    _atomic_write_text(target, text)
    try:
        report = _project_report(directory)
        if not report["ok"]:
            raise ValueError(_report_error(report))
        updated = block_config.load(str(directory), view_id)
    except Exception:
        _restore(target, previous, False)
        raise
    return {
        "payload": updated,
        "index": block_config.load_index(str(directory)),
        "warnings": report["warnings"],
        "result": result,
        "revision": updated["revision"],
        "manifest_revision": updated.get("manifest_revision"),
    }


def _external_references(directory: Path, index: dict, view_id: str) -> list[str]:
    references = []
    for view in index["views"]:
        if view["view_id"] == view_id:
            continue
        payload = block_config.load(str(directory), view["view_id"])
        for block in _iter_blocks(payload["config"]["blocks"]):
            jump = block.get("jump")
            if jump and jump.get("view") == view_id:
                references.append(f"视图 {view['view_id']} 的块 {block['id']}（jump）")
            flow = block.get("flow")
            if flow and flow.get("view") == view_id:
                references.append(f"视图 {view['view_id']} 的块 {block['id']}（flow）")
            for target in block.get("emit", []):
                if target.get("view") == view_id:
                    references.append(f"视图 {view['view_id']} 的块 {block['id']}（emit）")
    return references


def event_names(path) -> dict:
    """Collect existing ``on`` names so the editor can offer them as choices."""
    directory = _workspace(path)
    index = block_config.load_index(str(directory))
    names = set()
    for view in index["views"]:
        payload = block_config.load(str(directory), view["view_id"])
        for block in _iter_blocks(payload["config"]["blocks"]):
            name = block.get("on")
            if name:
                names.add(name)
    return {"events": sorted(names)}


@workspace_write
def delete_view(path, view_id, revision=_UNSET, manifest_revision=_UNSET) -> dict:
    """Delete one view; refuse the last view or a view referenced from elsewhere."""
    directory = _workspace(path)
    if not isinstance(view_id, str) or not view_id.strip():
        raise ValueError("缺少视图 id")
    view_id = view_id.strip()
    index = block_config.load_index(str(directory))
    chosen = next((view for view in index["views"] if view["view_id"] == view_id), None)
    if chosen is None:
        available = "、".join(view["view_id"] for view in index["views"])
        raise ValueError(f"找不到视图：{view_id}（可用：{available}）")
    if len(index["views"]) <= 1:
        raise ValueError("至少保留一个视图，不能删除最后一个视图")
    references = _external_references(directory, index, view_id)
    if references:
        raise ValueError("视图仍被其他视图引用，不能删除：" + "；".join(references))
    target = (directory / chosen["file"]).resolve()
    if target.parent != directory:
        raise ValueError(f"视图文件不在工作区目录内：{chosen['file']}")
    manifest_path = directory / MANIFEST_NAME
    previous = target.read_bytes()
    manifest_previous = manifest_path.read_bytes()
    _check_revision(previous, revision)
    _check_revision(manifest_previous, manifest_revision)
    manifest = project_config.load_manifest(directory)
    entry_changed = manifest is not None and manifest["entry"] == view_id
    target.unlink()
    try:
        if entry_changed:
            remaining = [view["view_id"] for view in index["views"]
                         if view["view_id"] != view_id]
            _set_entry(directory, remaining[0])
        report = _project_report(directory)
        if not report["ok"]:
            raise ValueError(_report_error(report))
        updated = block_config.load_index(str(directory))
    except Exception:
        _atomic_write_bytes(target, previous)
        if manifest_previous is not None:
            _atomic_write_bytes(manifest_path, manifest_previous)
        raise
    return {
        "index": updated,
        "entry": updated["entry"],
        "manifest_revision": updated.get("manifest_revision"),
    }


def project_settings(path) -> dict:
    """Return the raw manifest plus the current index and revision."""
    directory = _workspace(path)
    manifest, revision = _manifest_raw(directory)
    index = block_config.load_index(str(directory))
    return {
        "manifest": manifest,
        "revision": revision,
        "index": index,
    }


@workspace_write
def save_project(path, config, revision=_UNSET) -> dict:
    """Update editable manifest fields and revalidate the whole workspace.

    Only ``project.name`` / ``project.description`` / ``project.root``,
    ``files`` and ``views.entry`` are editable. ``views.suffix`` is preserved
    because changing it would require renaming every view file.
    """
    directory = _workspace(path)
    if not isinstance(config, dict):
        raise ValueError("项目配置必须是 JSON 对象")
    manifest_path = directory / MANIFEST_NAME
    previous = manifest_path.read_bytes()
    _check_revision(previous, revision)
    data = json.loads(previous.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_NAME} 必须是 JSON 对象")
    candidate = json.loads(json.dumps(data))
    project = candidate.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{MANIFEST_NAME} 缺少 project")

    incoming_project = config.get("project")
    if incoming_project is not None:
        if not isinstance(incoming_project, dict):
            raise ValueError("project 必须是对象")
        if "name" in incoming_project:
            project["name"] = _text(incoming_project["name"], "project.name")
        if "description" in incoming_project:
            project["description"] = _text(incoming_project["description"],
                                           "project.description")
        if "root" in incoming_project:
            root = incoming_project["root"]
            if not isinstance(root, str) or not root.strip():
                raise ValueError("project.root 必须是非空字符串")
            project["root"] = root.strip()

    if "files" in config:
        files = config["files"]
        if not isinstance(files, list):
            raise ValueError("files 必须是数组")
        cleaned = []
        for item_index, item in enumerate(files):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"files[{item_index}] 必须是非空字符串")
            cleaned.append(item.strip())
        candidate["files"] = cleaned

    incoming_views = config.get("views")
    if incoming_views is not None:
        if not isinstance(incoming_views, dict):
            raise ValueError("views 必须是对象")
        views = candidate.get("views")
        if not isinstance(views, dict):
            views = candidate["views"] = {}
        if "suffix" in incoming_views:
            current = views.get("suffix", project_config.DEFAULT_SUFFIX)
            if incoming_views["suffix"] != current:
                raise ValueError("views.suffix 暂不支持修改")
        if "entry" in incoming_views:
            entry = incoming_views["entry"]
            if entry is None:
                views.pop("entry", None)
            elif isinstance(entry, str) and entry.strip():
                views["entry"] = entry.strip()
            else:
                raise ValueError("views.entry 必须是非空字符串或 null")

    checked = project_config.validate_manifest(directory, candidate)
    index = block_config.load_index(str(directory))
    if checked["entry"] is not None:
        known = {view["view_id"] for view in index["views"]}
        if checked["entry"] not in known:
            available = "、".join(view["view_id"] for view in index["views"])
            raise ValueError(f"views.entry 指向不存在的视图：{checked['entry']}"
                             f"（可用：{available}）")

    text = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) > project_config.MAX_MANIFEST_BYTES:
        raise ValueError(f"{MANIFEST_NAME} 超过 "
                         f"{project_config.MAX_MANIFEST_BYTES // 1024} KB")
    _atomic_write_text(manifest_path, text)
    try:
        report = _project_report(directory)
        if not report["ok"]:
            raise ValueError(_report_error(report))
        updated = block_config.load_index(str(directory))
    except Exception:
        _atomic_write_bytes(manifest_path, previous)
        raise
    return {
        "manifest": candidate,
        "index": updated,
        "revision": file_revision(manifest_path),
        "manifest_revision": updated.get("manifest_revision"),
    }


def open_workspace(path) -> dict:
    """Validate a workspace, record it as recently opened, and return its index."""
    directory = _workspace(path)
    index = block_config.load_index(str(directory))
    manifest, _ = _manifest_raw(directory)
    try:
        workspace_registry.remember(directory)
    except (OSError, ValueError):
        pass
    return {"index": index, "manifest": manifest}


def remember_workspace(path) -> None:
    directory = _workspace(path)
    workspace_registry.remember(directory)


def recent_workspaces() -> dict:
    return {"recent": workspace_registry.recent()}


def forget_workspace(path) -> dict:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("缺少工作区路径")
    workspace_registry.forget(path)
    return {"recent": workspace_registry.recent()}


def delete_workspace(path, confirm) -> dict:
    """Reject legacy whole-directory deletion, which could erase source code."""
    raise ValueError("Demo 不提供整目录删除，请使用“移除最近记录”；源码和工作区文件请自行管理")


@workspace_write
def create_workspace(directory, name, description, view_id="main",
                     view_name="主流程", view_description=None) -> dict:
    """Create a new workspace directory with a manifest and one starter view."""
    view_description = view_description or "新建工作区"
    name = _text(name, "项目名称")
    description = _text(description, "项目描述")
    view_name = _text(view_name, "视图名称")
    view_description = _text(view_description, "视图描述")
    checked = block_config.validate({
        "view": {"id": view_id, "name": view_name, "description": view_description},
        "blocks": [{
            "id": 1, "type": "normal", "name": "开始",
            "description": "流程起点。", "next": None,
        }],
    })
    view_id = checked["view"]["id"]
    flat_config = flat.from_nested(checked)
    raw = directory.strip() if isinstance(directory, str) else ""
    if not raw:
        raise ValueError("缺少工作区目录")
    target = Path(raw).expanduser()
    if not target.is_absolute():
        raise ValueError("工作区目录必须是绝对路径（可以用 ~ 开头）")
    target = target.resolve()
    created_dir = not target.exists()
    if target.exists():
        if not target.is_dir():
            raise ValueError("工作区路径不是目录")
        if any(target.iterdir()):
            raise ValueError("工作区目录不是空的，拒绝覆盖")
    else:
        target.mkdir(parents=True)
    manifest = {
        "project": {"name": name, "description": description, "root": "."},
        "files": [],
        "views": {"suffix": project_config.DEFAULT_SUFFIX, "entry": view_id,
                  "format": "flat"},
    }
    manifest_path = target / MANIFEST_NAME
    view_path = target / f"{view_id}{project_config.DEFAULT_SUFFIX}"
    try:
        _atomic_write_text(manifest_path,
                           json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        _atomic_write_text(view_path, _view_text(flat_config, flat_format=True))
        index = block_config.load_index(str(target))
        payload = block_config.load(str(target), view_id)
    except Exception:
        for path in (manifest_path, view_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if created_dir:
            try:
                target.rmdir()
            except OSError:
                pass
        raise
    return {"index": index, "payload": payload, "manifest": manifest}
