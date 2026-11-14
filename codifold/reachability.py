"""Static execution reachability for a validated view.

只把执行边算作可达：普通块的默认后继 / next、分支扇出、列表尾汇合、
try 的 finally 汇合。jump 和 emit 是导航/事件关联，不算执行边。
"""
from __future__ import annotations


def _walk(blocks):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _walk(branch["steps"])
        if block.get("finally"):
            yield from _walk(block["finally"])


def _edges(steps, continuation, edges):
    for index, block in enumerate(steps):
        next_id = steps[index + 1]["id"] if index + 1 < len(steps) else continuation
        if block["type"] == "normal":
            if "next" in block:
                if block["next"] is not None:
                    edges.setdefault(block["id"], set()).add(block["next"])
            elif next_id is not None:
                edges.setdefault(block["id"], set()).add(next_id)
            continue
        for branch in block["branches"]:
            edges.setdefault(block["id"], set()).add(branch["steps"][0]["id"])
            branch_continuation = next_id
            if block.get("kind") == "try" and block.get("finally"):
                branch_continuation = block["finally"][0]["id"]
            _edges(branch["steps"], branch_continuation, edges)
        if block.get("kind") == "try" and block.get("finally"):
            _edges(block["finally"], next_id, edges)


def unreachable(blocks: list[dict], jump_targets=None) -> list[dict]:
    """Return blocks with no execution path from the view's first top-level block.

    ``jump_targets`` are ids intentionally reachable by navigation; they are
    excluded from the warning to avoid flagging standalone detail blocks.
    """
    jump_targets = jump_targets or set()
    edges: dict[int, set[int]] = {}
    _edges(blocks, None, edges)
    seen = set()
    stack = [blocks[0]["id"]]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(edges.get(current, ()))
    return [{"id": block["id"], "name": block["name"]}
            for block in _walk(blocks)
            if block["id"] not in seen and block["id"] not in jump_targets]
