"""Narrative checks for a converted workspace.

Coverage says every line has a block. These checks say whether a reader can
follow the story: the main view must continue into entry views, every entry
must be reachable from the mainline, and flow views must not end on a detail
jump with no way forward.
"""
from __future__ import annotations

from pathlib import Path

from . import block_config

FLOW_KINDS = {"main", "flow", "entry"}


def _iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


def _execution_edges(blocks: list[dict]) -> dict[int, set[int]]:
    edges: dict[int, set[int]] = {}

    def walk(steps: list[dict], continuation: int | None) -> None:
        for index, block in enumerate(steps):
            next_id = steps[index + 1]["id"] if index + 1 < len(steps) else continuation
            ident = block["id"]
            if block["type"] == "normal":
                if "next" in block:
                    if block["next"] is not None:
                        edges.setdefault(ident, set()).add(block["next"])
                elif next_id is not None:
                    edges.setdefault(ident, set()).add(next_id)
                continue
            for branch in block["branches"]:
                edges.setdefault(ident, set()).add(branch["steps"][0]["id"])
                branch_continuation = next_id
                if block.get("kind") == "try" and block.get("finally"):
                    branch_continuation = block["finally"][0]["id"]
                walk(branch["steps"], branch_continuation)
            if block.get("kind") == "try" and block.get("finally"):
                walk(block["finally"], next_id)

    walk(blocks, None)
    return edges


def _reachable(blocks: list[dict], edges: dict[int, set[int]]) -> set[int]:
    seen: set[int] = set()
    stack = [blocks[0]["id"]]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edges.get(current, ()))
    return seen


def report(path: str | Path) -> dict:
    directory = Path(path).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区：{directory}")
    directory = directory.resolve()
    index = block_config.load_index(str(directory))
    views = index["views"]
    configs: dict[str, dict] = {}
    for view in views:
        try:
            configs[view["view_id"]] = block_config.load(
                str(directory), view["view_id"]
            )["config"]
        except (OSError, ValueError):
            continue
    explicit = any("kind" in config["view"] for config in configs.values())
    has_flow = any(
        block.get("flow")
        for config in configs.values()
        for block in _iter_blocks(config["blocks"])
    )
    ids_by_view = {
        view_id: {block["id"] for block in _iter_blocks(config["blocks"])}
        for view_id, config in configs.items()
    }
    kinds = {view["view_id"]: view["kind"] for view in views}
    errors: list[str] = []
    warnings: list[str] = []
    flow_out: dict[str, set[str]] = {view["view_id"]: set() for view in views}
    nav_out: dict[str, set[str]] = {view["view_id"]: set() for view in views}
    for view_id, config in configs.items():
        for block in _iter_blocks(config["blocks"]):
            flow = block.get("flow")
            if flow:
                target = flow["view"]
                if target not in kinds:
                    errors.append(
                        f"视图 {view_id} 的块 {block['id']} flow 指向不存在的视图：{target}"
                    )
                else:
                    if target in ids_by_view and flow["id"] not in ids_by_view[target]:
                        errors.append(
                            f"视图 {view_id} 的块 {block['id']} flow 指向 {target} 里不存在的 id：{flow['id']}"
                        )
                    if kinds[target] not in FLOW_KINDS:
                        errors.append(
                            f"视图 {view_id} 的块 {block['id']} flow 目标不是主线/流程/入口：{target}"
                        )
                    flow_out[view_id].add(target)
                    nav_out[view_id].add(target)
            jump = block.get("jump")
            if jump and jump.get("view"):
                nav_out[view_id].add(jump["view"])
            for ref in block.get("emit", []):
                if ref.get("view"):
                    nav_out[view_id].add(ref["view"])

    main_id = next((view["view_id"] for view in views
                    if view["kind"] == "main"), index["entry"])
    depths: dict[str, int] = {main_id: 0}
    queue = [main_id]
    while queue:
        current = queue.pop(0)
        for target in nav_out.get(current, ()):
            if target in kinds and target not in depths:
                depths[target] = depths[current] + 1
                queue.append(target)
    total = len(views)
    score = round(len(depths) / total, 4) if total else 1.0
    orphans = sorted(set(kinds) - set(depths))
    coherence = {
        "score": score,
        "reachable": len(depths),
        "total": total,
        "root": main_id,
        "depths": {view["view_id"]: depths[view["view_id"]]
                   for view in views if view["view_id"] in depths},
        "orphans": orphans,
    }
    if orphans:
        names = "、".join(orphans[:8])
        more = "…" if len(orphans) > 8 else ""
        errors.append(
            f"连贯性 {score:.4f} < 1：{len(orphans)} 个视图无法从 "
            f"{main_id} 到达（{names}{more}）"
        )
    if not explicit and not has_flow:
        return {"ok": not errors, "skipped": True, "errors": errors,
                "warnings": warnings, "coherence": coherence, "views": []}

    reachable = set(depths)
    entry_views = [view for view in views if view["kind"] in {"entry", "flow"}]
    for view in entry_views:
        if view["view_id"] not in reachable:
            warnings.append(
                f"入口视图 {view['view_id']} 无法从 {main_id} 通过 flow/jump 到达"
            )
    if entry_views and not flow_out.get(main_id):
        warnings.append(f"主线视图 {main_id} 没有任何 flow 出口")

    for view in views:
        if view["kind"] not in FLOW_KINDS:
            continue
        view_id = view["view_id"]
        config = configs.get(view_id)
        if config is None:
            continue
        edges = _execution_edges(config["blocks"])
        seen = _reachable(config["blocks"], edges)
        for block in _iter_blocks(config["blocks"]):
            if block["id"] not in seen:
                continue
            if edges.get(block["id"]):
                continue
            if block.get("flow"):
                continue
            if "next" in block and block["next"] is None:
                if view["kind"] in {"main", "flow"} and block.get("jump"):
                    warnings.append(
                        f"视图 {view_id} 的块 {block['id']} “{block['name']}” "
                        "只有实现跳转，没有主线出口"
                    )
                continue
            if block.get("jump"):
                warnings.append(
                    f"视图 {view_id} 的块 {block['id']} “{block['name']}” "
                    "只有实现跳转，没有主线出口"
                )
            else:
                warnings.append(
                    f"视图 {view_id} 的块 {block['id']} “{block['name']}” "
                    "没有明确出口（next:null 或 flow）"
                )

    view_summary = [{
        "view_id": view["view_id"],
        "kind": view["kind"],
        "reachable": view["view_id"] in reachable,
        "depth": depths.get(view["view_id"]),
    } for view in views]
    return {"ok": not errors, "skipped": False, "errors": errors,
            "warnings": warnings, "main": main_id, "coherence": coherence,
            "views": view_summary}
