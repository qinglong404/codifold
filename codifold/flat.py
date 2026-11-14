"""Flat view schema: a block table plus explicit containers.

New workspaces store views as:

    {
      "view": {"id": "main", "name": "...", "description": "...", "kind": "main"},
      "containers": [
        {"id": "root", "kind": "root", "blocks": [1, 2]},
        {"id": "c2-0", "kind": "branch", "parent": 2, "condition": "yes", "blocks": [3]},
        {"id": "f2", "kind": "finally", "parent": 2, "blocks": [4]}
      ],
      "blocks": [
        {"id": 1, "type": "normal", "...": "..."},
        {"id": 2, "type": "branch", "branches": ["c2-0"], "finally": "f2"}
      ]
    }

Every block belongs to exactly one container. Branch blocks reference
container ids, not embedded step arrays. The reader converts the flat form to
the nested form for layout; the editor operates on single blocks/containers.
"""
from __future__ import annotations

import re
from typing import Any

from . import block_config

ROOT_ID = "root"
CONTAINER_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
CONTAINER_KINDS = {"root", "branch", "finally"}
MAX_CONTAINERS = block_config.MAX_BLOCKS


def is_flat(config: Any) -> bool:
    return isinstance(config, dict) and isinstance(config.get("containers"), list)


def _check_keys(value: dict, allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} 有未知字段：{', '.join(unknown)}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} 必须是正整数")
    return value


def _nested_branch(container: dict, block_by_id: dict[int, dict],
                   build_block) -> dict:
    branch: dict[str, Any] = {
        "steps": [build_block(ident) for ident in container["blocks"]],
    }
    if container.get("condition") is not None:
        branch["condition"] = container["condition"]
    if container.get("role") is not None:
        branch["role"] = container["role"]
    return branch


def validate_flat(config: dict) -> dict:
    """Validate a flat view and return the nested projection used by rendering."""
    if not is_flat(config):
        raise ValueError("不是 flat 视图（缺少 containers）")
    view = block_config._view(config.get("view"))
    blocks_value = config.get("blocks")
    containers_value = config.get("containers")
    if not isinstance(blocks_value, list) or not blocks_value:
        raise ValueError("flat 视图的 blocks 必须是非空数组")
    if not isinstance(containers_value, list) or not containers_value:
        raise ValueError("flat 视图的 containers 必须是非空数组")
    if len(blocks_value) > block_config.MAX_BLOCKS:
        raise ValueError(f"块过多，最多 {block_config.MAX_BLOCKS} 个")
    if len(containers_value) > MAX_CONTAINERS:
        raise ValueError(f"容器过多，最多 {MAX_CONTAINERS} 个")

    block_by_id: dict[int, dict] = {}
    for index, block in enumerate(blocks_value):
        field = f"blocks[{index}]"
        if not isinstance(block, dict):
            raise ValueError(f"{field} 必须是对象")
        ident = _int(block.get("id"), f"{field}.id")
        if ident in block_by_id:
            raise ValueError(f"块 id 重复：{ident}")
        block_by_id[ident] = block

    containers: list[dict] = []
    container_by_id: dict[str, dict] = {}
    root = None
    for index, container in enumerate(containers_value):
        field = f"containers[{index}]"
        if not isinstance(container, dict):
            raise ValueError(f"{field} 必须是对象")
        _check_keys(container, {"id", "kind", "parent", "condition",
                                "role", "blocks"}, field)
        cid = _text(container.get("id"), f"{field}.id")
        if not CONTAINER_ID.fullmatch(cid):
            raise ValueError(f"{field}.id 只能是小写字母开头的 [a-z0-9_-]")
        if cid in container_by_id:
            raise ValueError(f"容器 id 重复：{cid}")
        kind = container.get("kind")
        if kind not in CONTAINER_KINDS:
            raise ValueError(f"{field}.kind 只能是 root / branch / finally")
        items = container.get("blocks")
        if not isinstance(items, list) or not items:
            raise ValueError(f"{field}.blocks 必须是非空数组")
        checked_items = []
        for item_index, item in enumerate(items):
            ident = _int(item, f"{field}.blocks[{item_index}]")
            if ident not in block_by_id:
                raise ValueError(f"{field}.blocks[{item_index}] 指向不存在的块：{ident}")
            checked_items.append(ident)
        result = {"id": cid, "kind": kind, "blocks": checked_items}
        if kind == "root":
            if cid != ROOT_ID:
                raise ValueError(f"root 容器 id 必须是 {ROOT_ID}")
            if root is not None:
                raise ValueError("只能有一个 root 容器")
            if container.get("parent") is not None:
                raise ValueError(f"{field} 是 root，不能写 parent")
            if container.get("condition") is not None or container.get("role") is not None:
                raise ValueError(f"{field} 是 root，不能写 condition/role")
            root = result
        else:
            parent = _int(container.get("parent"), f"{field}.parent")
            if parent not in block_by_id:
                raise ValueError(f"{field}.parent 指向不存在的块：{parent}")
            result["parent"] = parent
            if kind == "branch":
                if container.get("condition") is not None:
                    result["condition"] = _text(container["condition"],
                                                f"{field}.condition")
                if container.get("role") is not None:
                    role = _text(container["role"], f"{field}.role")
                    if role not in {"body", "except"}:
                        raise ValueError(f"{field}.role 只能是 body 或 except")
                    result["role"] = role
            else:
                if container.get("condition") is not None:
                    raise ValueError(f"{field} 是 finally，不能写 condition")
                if container.get("role") is not None:
                    raise ValueError(f"{field} 是 finally，不能写 role")
        container_by_id[cid] = result
        containers.append(result)
    if root is None:
        raise ValueError(f"缺少 id={ROOT_ID} 的 root 容器")

    membership: dict[int, str] = {}
    for container in containers:
        for ident in container["blocks"]:
            if ident in membership:
                raise ValueError(
                    f"块 {ident} 同时属于容器 {membership[ident]} 和 {container['id']}"
                )
            membership[ident] = container["id"]
    missing = sorted(set(block_by_id) - set(membership))
    if missing:
        raise ValueError(f"块没有归属容器：{', '.join(str(i) for i in missing)}")

    for block in block_by_id.values():
        if block.get("type") not in {"normal", "branch"}:
            raise ValueError(f"块 {block.get('id')} 的 type 只能是 normal 或 branch")
        if block["type"] == "branch":
            branches = block.get("branches")
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"分支块 {block['id']} 的 branches 必须是非空容器 id 数组")
            if len(set(branches)) != len(branches):
                raise ValueError(f"分支块 {block['id']} 的 branches 有重复容器")
            for cid in branches:
                if not isinstance(cid, str) or cid not in container_by_id:
                    raise ValueError(f"分支块 {block['id']} 引用了不存在的容器：{cid}")
                container = container_by_id[cid]
                if container["kind"] != "branch" or container.get("parent") != block["id"]:
                    raise ValueError(f"分支块 {block['id']} 的容器 {cid} 必须是 parent={block['id']} 的 branch 容器")
            finally_id = block.get("finally")
            if finally_id is not None:
                if not isinstance(finally_id, str) or finally_id not in container_by_id:
                    raise ValueError(f"分支块 {block['id']} 的 finally 容器不存在：{finally_id}")
                finally_container = container_by_id[finally_id]
                if (finally_container["kind"] != "finally"
                        or finally_container.get("parent") != block["id"]):
                    raise ValueError(f"分支块 {block['id']} 的 finally 必须是 parent={block['id']} 的 finally 容器")
        else:
            if block.get("branches") is not None or block.get("finally") is not None:
                raise ValueError(f"普通块 {block['id']} 不能引用容器")

    referenced = set()
    for block in block_by_id.values():
        if block["type"] != "branch":
            continue
        for cid in block["branches"]:
            referenced.add(cid)
        if block.get("finally") is not None:
            referenced.add(block["finally"])
    for container in containers:
        if container["kind"] == "root":
            continue
        parent = block_by_id[container["parent"]]
        if parent["type"] != "branch":
            raise ValueError(f"容器 {container['id']} 的 parent 不是分支块：{container['parent']}")
        if container["id"] not in referenced:
            raise ValueError(f"容器 {container['id']} 没有被父分支块引用")

    # Container depth and cycles. A top-level block lives at depth 1.
    depths: dict[str, int] = {ROOT_ID: 1}
    visiting: set[str] = set()

    def depth_of(cid: str) -> int:
        if cid in depths:
            return depths[cid]
        if cid in visiting:
            raise ValueError(f"容器引用形成环：{cid}")
        visiting.add(cid)
        container = container_by_id[cid]
        parent_block = container["parent"]
        parent_container = membership[parent_block]
        depth = depth_of(parent_container) + 1
        if depth > block_config.MAX_DEPTH:
            raise ValueError(f"容器 {cid} 嵌套过深，最多 {block_config.MAX_DEPTH} 层")
        visiting.remove(cid)
        depths[cid] = depth
        return depth

    for container in containers:
        depth_of(container["id"])

    def build_block(ident: int) -> dict:
        block = dict(block_by_id[ident])
        if block["type"] == "branch":
            block["branches"] = [
                _nested_branch(container_by_id[cid], block_by_id, build_block)
                for cid in block["branches"]
            ]
            finally_id = block.get("finally")
            if finally_id is not None:
                block["finally"] = [
                    build_block(item) for item in container_by_id[finally_id]["blocks"]
                ]
        return block

    nested = {
        "view": view,
        "blocks": [build_block(ident) for ident in root["blocks"]],
    }
    return block_config.validate(nested)


def from_nested(config: dict) -> dict:
    """Convert a validated nested view to the flat canonical form."""
    checked = block_config.validate(config)
    view = checked["view"]
    containers: list[dict] = [{
        "id": ROOT_ID,
        "kind": "root",
        "blocks": [block["id"] for block in checked["blocks"]],
    }]
    blocks: list[dict] = []

    def add_block(block: dict) -> None:
        record = {key: value for key, value in block.items()
                  if key not in {"branches", "finally"}}
        blocks.append(record)
        if block["type"] != "branch":
            return
        branch_ids = []
        for index, branch in enumerate(block["branches"]):
            cid = f"c{block['id']}-{index}"
            container = {
                "id": cid,
                "kind": "branch",
                "parent": block["id"],
                "blocks": [step["id"] for step in branch["steps"]],
            }
            if branch.get("condition") is not None:
                container["condition"] = branch["condition"]
            if branch.get("role") is not None:
                container["role"] = branch["role"]
            containers.append(container)
            branch_ids.append(cid)
            for step in branch["steps"]:
                add_block(step)
        record["branches"] = branch_ids
        finally_blocks = block.get("finally")
        if finally_blocks:
            fid = f"f{block['id']}"
            containers.append({
                "id": fid,
                "kind": "finally",
                "parent": block["id"],
                "blocks": [step["id"] for step in finally_blocks],
            })
            record["finally"] = fid
            for step in finally_blocks:
                add_block(step)

    for block in checked["blocks"]:
        add_block(block)
    return {"view": view, "containers": containers, "blocks": blocks}
