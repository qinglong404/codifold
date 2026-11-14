"""Workspace-level checks for static contract views.

Contract blocks describe types and HTTP endpoints. They do not carry
``code_mapping``; they point at existing flow/struct blocks through
``evidence`` and ``handler``. A single view file cannot check the
workspace-level references, so this module checks duplicate type names,
duplicate endpoints, unresolved type references and missing evidence.
"""
from __future__ import annotations

from pathlib import Path

from . import block_config

HANDLER_KINDS = {"function", "entry", "flow"}


def _iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


def _where(view_id: str, block: dict) -> str:
    return f"{view_id}:{block['id']}"


def _check_evidence(ref: dict, source_view: str, block: dict,
                    views: dict[str, dict], blocks_by_view: dict[str, dict],
                    errors: list[str], warnings: list[str]) -> None:
    where = _where(source_view, block)
    target_view = ref["view"]
    target = views.get(target_view)
    if target is None:
        errors.append(f"契约块 {where} 的 evidence 指向不存在的视图：{target_view}")
        return
    if target["kind"] == "contract":
        errors.append(f"契约块 {where} 的 evidence 不能指向契约视图：{target_view}")
        return
    target_blocks = blocks_by_view.get(target_view)
    if target_blocks is None:
        return
    target_block = target_blocks.get(ref["id"])
    if target_block is None:
        errors.append(
            f"契约块 {where} 的 evidence 指向 {target_view} 里不存在的 id：{ref['id']}")
        return
    if not target_block.get("code_mapping"):
        warnings.append(
            f"契约块 {where} 的 evidence 目标 {target_view}:{ref['id']} "
            "没有 code_mapping")


def _check_handler(endpoint: dict, views: dict[str, dict],
                   blocks_by_view: dict[str, dict],
                   errors: list[str]) -> None:
    view_id = endpoint["view"]
    block = endpoint["block"]
    payload = block["contract"]
    where = f"{view_id}:{block['id']}（{payload['method']} {payload['path']}）"
    if payload.get("external"):
        if payload.get("handler") is not None:
            errors.append(f"外部接口 {where} 不能写 handler")
        return
    handler = payload.get("handler")
    if handler is None:
        errors.append(f"接口 {where} 缺少 handler，或写 external: true")
        return
    target_view = views.get(handler["view"])
    if target_view is None:
        errors.append(
            f"接口 {where} 的 handler 指向不存在的视图：{handler['view']}")
        return
    if target_view["kind"] not in HANDLER_KINDS:
        errors.append(
            f"接口 {where} 的 handler 目标必须是 function/entry/flow："
            f"{handler['view']} 是 {target_view['kind']}")
        return
    target_blocks = blocks_by_view.get(handler["view"])
    if target_blocks is None:
        return
    if handler["id"] not in target_blocks:
        errors.append(
            f"接口 {where} 的 handler 指向 {handler['view']} 里不存在的 id："
            f"{handler['id']}")


def report(path: str | Path) -> dict:
    directory = Path(path).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区：{directory}")
    directory = directory.resolve()
    index = block_config.load_index(str(directory))
    views = {view["view_id"]: view for view in index["views"]}
    contract_views = [view for view in index["views"]
                      if view["kind"] == "contract"]
    result = {
        "ok": True,
        "errors": [],
        "warnings": [],
        "views": [],
        "types": [],
        "endpoints": [],
    }
    if not contract_views:
        return result

    configs: dict[str, dict] = {}
    blocks_by_view: dict[str, dict[int, dict]] = {}
    for view in index["views"]:
        try:
            payload = block_config.load(str(directory), view["view_id"])
        except (OSError, ValueError):
            continue
        configs[view["view_id"]] = payload["config"]
        blocks_by_view[view["view_id"]] = {
            block["id"]: block for block in _iter_blocks(payload["config"]["blocks"])
        }

    errors: list[str] = []
    warnings: list[str] = []
    types: dict[str, dict] = {}
    endpoints: list[dict] = []
    summaries: list[dict] = []

    for view in contract_views:
        view_id = view["view_id"]
        config = configs.get(view_id)
        if config is None:
            summaries.append({
                "view_id": view_id, "name": view["name"],
                "types": 0, "endpoints": 0, "error": "读取失败",
            })
            continue
        type_count = 0
        endpoint_count = 0
        for block in _iter_blocks(config["blocks"]):
            payload = block.get("contract")
            if not isinstance(payload, dict):
                continue
            for ref in block.get("evidence", []):
                _check_evidence(ref, view_id, block, views, blocks_by_view,
                                errors, warnings)
            if payload.get("kind") == "type":
                type_count += 1
                name = block["name"]
                if name in types:
                    previous = types[name]
                    errors.append(
                        f"类型名重复：{name}（{previous['view']}:{previous['id']} "
                        f"与 {_where(view_id, block)}）")
                else:
                    types[name] = {
                        "name": name, "view": view_id, "id": block["id"],
                    }
                if not block.get("evidence"):
                    warnings.append(
                        f"契约块 {_where(view_id, block)}（类型 {name}）"
                        "没有 evidence，无法定位代码")
            elif payload.get("kind") == "endpoint":
                endpoint_count += 1
                endpoints.append({
                    "view": view_id,
                    "id": block["id"],
                    "method": payload["method"],
                    "path": payload["path"],
                    "block": block,
                })
        summaries.append({
            "view_id": view_id, "name": view["name"],
            "types": type_count, "endpoints": endpoint_count, "error": None,
        })

    seen_endpoints: dict[tuple[str, str], str] = {}
    for endpoint in endpoints:
        payload = endpoint["block"]["contract"]
        where = f"{endpoint['view']}:{endpoint['id']}（{endpoint['method']} {endpoint['path']}）"
        key = (endpoint["method"], endpoint["path"])
        if key in seen_endpoints:
            errors.append(
                f"接口重复：{endpoint['method']} {endpoint['path']}"
                f"（{seen_endpoints[key]} 与 {where}）")
        else:
            seen_endpoints[key] = where
        for name_key in ("request", "response"):
            type_name = payload.get(name_key)
            if type_name is not None and type_name not in types:
                errors.append(
                    f"接口 {where} 的 {name_key} 类型不存在：{type_name}")
        _check_handler(endpoint, views, blocks_by_view, errors)

    entry = views.get(index["entry"])
    if entry is not None and entry["kind"] == "contract":
        warnings.append(
            f"入口视图 {index['entry']} 是契约视图，建议改为 main/flow/entry")

    result.update({
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "views": summaries,
        "types": [types[name] for name in sorted(types)],
        "endpoints": [{
            "view": item["view"],
            "id": item["id"],
            "method": item["method"],
            "path": item["path"],
        } for item in sorted(endpoints,
                             key=lambda item: (item["path"], item["method"],
                                               item["view"], item["id"]))],
    })
    return result
