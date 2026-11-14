"""Single-block/container operations for flat views."""
from __future__ import annotations

from typing import Any

from . import block_config, flat

_MISSING = object()


def canonical(config: dict) -> dict:
    return flat.from_nested(flat.validate_flat(config))


def _blocks(config: dict) -> dict[int, dict]:
    return {block["id"]: block for block in config["blocks"]}


def _containers(config: dict) -> dict[str, dict]:
    return {container["id"]: container for container in config["containers"]}


def _container_of(config: dict, block_id: int) -> dict:
    for container in config["containers"]:
        if block_id in container["blocks"]:
            return container
    raise ValueError(f"块没有归属容器：{block_id}")


def _new_block_id(config: dict) -> int:
    return max((block["id"] for block in config["blocks"]), default=0) + 1


def _branch_container_id(config: dict, block_id: int) -> str:
    existing = {container["id"] for container in config["containers"]}
    index = 0
    while f"c{block_id}-{index}" in existing:
        index += 1
    return f"c{block_id}-{index}"


def _normal_block(ident: int, name: str = "新块", description: str = "新步骤。") -> dict:
    return {"id": ident, "type": "normal", "name": name,
            "description": description}


def _descendant_ids(config: dict, block_id: int) -> set[int]:
    block = _blocks(config)[block_id]
    if block["type"] != "branch":
        return set()
    containers = _containers(config)
    result: set[int] = set()
    stack: list[str] = []
    for cid in block.get("branches", []):
        stack.append(cid)
    if block.get("finally"):
        stack.append(block["finally"])
    while stack:
        container = containers[stack.pop()]
        for child in container["blocks"]:
            if child in result:
                continue
            result.add(child)
            result.update(_descendant_ids(config, child))
    return result


def _containers_under_blocks(config: dict, block_ids: set[int]) -> set[str]:
    containers = _containers(config)
    blocks = _blocks(config)
    result: set[str] = set()
    stack = list(block_ids)
    seen_blocks: set[int] = set()
    while stack:
        ident = stack.pop()
        if ident in seen_blocks:
            continue
        seen_blocks.add(ident)
        block = blocks[ident]
        if block["type"] != "branch":
            continue
        for cid in list(block.get("branches", [])) + (
                [block["finally"]] if block.get("finally") else []):
            if cid in result:
                continue
            result.add(cid)
            stack.extend(containers[cid]["blocks"])
    return result


def _check_references(config: dict, removed: set[int]) -> None:
    view_id = config["view"]["id"]
    by_id = _blocks(config)
    # next 是执行顺序：删除目标时顺手接上目标的 next，避免留下悬空边。
    for _ in range(len(removed) + 1):
        changed = False
        for block in config["blocks"]:
            if block["id"] in removed:
                continue
            next_id = block.get("next", _MISSING)
            if not isinstance(next_id, int) or next_id not in removed:
                continue
            target = by_id.get(next_id)
            if target is not None and target["type"] == "normal":
                following = target.get("next", _MISSING)
                if following is _MISSING:
                    block.pop("next", None)
                elif following in removed:
                    block["next"] = following
                    changed = True
                else:
                    block["next"] = following
            else:
                block.pop("next", None)
        if not changed:
            break
    for block in config["blocks"]:
        if block["id"] in removed:
            continue
        refs = []
        for key in ("jump", "flow"):
            ref = block.get(key)
            if ref:
                refs.append((key, ref))
        refs.extend(("emit", ref) for ref in block.get("emit", []))
        for key, ref in refs:
            if ref.get("view") not in (None, view_id):
                continue
            if ref["id"] in removed:
                raise ValueError(f"块 {block['id']} 的 {key} 仍指向被删除的块 {ref['id']}")


def _insert_position(config: dict, container: dict, after_id: int | None) -> int:
    if after_id is None:
        return len(container["blocks"])
    if after_id not in container["blocks"]:
        raise ValueError(f"块 {after_id} 不在容器 {container['id']} 里")
    return container["blocks"].index(after_id) + 1


def _rewire_next(config: dict, target: dict, new_id: int) -> None:
    if target["type"] != "normal":
        return
    next_value = target.get("next", _MISSING)
    if next_value is _MISSING:
        return
    target["next"] = new_id
    new_block = _blocks(config)[new_id]
    if next_value is None:
        new_block["next"] = None
    else:
        new_block["next"] = next_value


def add_block(config: dict, container_id: str, *, after_id: int | None = None,
              name: str = "新块", description: str = "新步骤。") -> tuple[dict, int]:
    config = canonical(config)
    containers = _containers(config)
    container = containers.get(container_id)
    if container is None:
        raise ValueError(f"容器不存在：{container_id}")
    ident = _new_block_id(config)
    block = _normal_block(ident, name, description)
    previous = after_id if after_id is not None else (
        container["blocks"][-1] if container["blocks"] else None)
    position = _insert_position(config, container, after_id)
    container["blocks"].insert(position, ident)
    config["blocks"].append(block)
    if previous is not None:
        _rewire_next(config, _blocks(config)[previous], ident)
    return canonical(config), ident


def add_branch_block(config: dict, container_id: str, *, after_id: int | None = None,
                     name: str = "新分支", description: str = "按条件分支。",
                     kind: str = "single") -> tuple[dict, int]:
    config = canonical(config)
    containers = _containers(config)
    container = containers.get(container_id)
    if container is None:
        raise ValueError(f"容器不存在：{container_id}")
    if kind not in {"single", "multi", "try"}:
        raise ValueError("kind 只能是 single / multi / try")
    ident = _new_block_id(config)
    branch = {
        "id": ident,
        "type": "branch",
        "name": name,
        "description": description,
        "select": "single" if kind == "try" else ("multi" if kind == "multi" else "single"),
        "branches": [],
    }
    if kind == "try":
        branch["kind"] = "try"
    child_ids = []
    branch_count = 2
    for index in range(branch_count):
        child = _normal_block(ident + 1 + index, "主体步骤" if kind == "try" and index == 0
                              else ("异常处理" if kind == "try" else "分支步骤"))
        config["blocks"].append(child)
        cid = _branch_container_id(config, ident)
        cdata = {"id": cid, "kind": "branch", "parent": ident,
                 "blocks": [child["id"]]}
        if kind == "try":
            cdata["role"] = "body" if index == 0 else "except"
        config["containers"].append(cdata)
        branch["branches"].append(cid)
        child_ids.append(child["id"])
    config["blocks"].append(branch)
    previous = after_id if after_id is not None else (
        container["blocks"][-1] if container["blocks"] else None)
    position = _insert_position(config, container, after_id)
    container["blocks"].insert(position, ident)
    if previous is not None:
        _rewire_next(config, _blocks(config)[previous], ident)
    return canonical(config), ident


def delete_block(config: dict, block_id: int, *, cascade: bool = False) -> dict:
    config = canonical(config)
    block = _blocks(config).get(block_id)
    if block is None:
        raise ValueError(f"块不存在：{block_id}")
    container = _container_of(config, block_id)
    removed = {block_id} | _descendant_ids(config, block_id)
    if len(removed) > 1 and not cascade:
        raise ValueError(f"块 {block_id} 还有 {len(removed) - 1} 个子块，需要确认连带删除")
    _check_references(config, removed)
    container["blocks"].remove(block_id)
    if not container["blocks"]:
        raise ValueError(f"容器 {container['id']} 不能为空")
    remove_containers = _containers_under_blocks(config, {block_id})
    config["blocks"] = [item for item in config["blocks"] if item["id"] not in removed]
    config["containers"] = [item for item in config["containers"]
                            if item["id"] not in remove_containers]
    return canonical(config)


def add_branch(config: dict, block_id: int, *, condition: str | None = None,
               role: str | None = None) -> tuple[dict, str, int]:
    config = canonical(config)
    block = _blocks(config).get(block_id)
    if block is None or block["type"] != "branch":
        raise ValueError(f"块 {block_id} 不是分支块")
    if block.get("kind") == "try":
        if role != "except":
            raise ValueError("try 分支只能追加 role=except 的异常列表")
    elif role is not None:
        raise ValueError("非 try 分支不能写 role")
    child = _normal_block(_new_block_id(config), "异常处理" if role else "分支步骤")
    config["blocks"].append(child)
    cid = _branch_container_id(config, block_id)
    container = {"id": cid, "kind": "branch", "parent": block_id,
                 "blocks": [child["id"]]}
    if condition:
        container["condition"] = condition
    if role:
        container["role"] = role
    config["containers"].append(container)
    block["branches"].append(cid)
    return canonical(config), cid, child["id"]


def add_finally(config: dict, block_id: int) -> tuple[dict, str, int]:
    config = canonical(config)
    block = _blocks(config).get(block_id)
    if block is None or block["type"] != "branch" or block.get("kind") != "try":
        raise ValueError("只有 try 分支块可以添加 finally")
    if block.get("finally"):
        raise ValueError("try 分支块已经有 finally")
    child = _normal_block(_new_block_id(config), "finally 步骤")
    config["blocks"].append(child)
    cid = f"f{block_id}"
    if cid in _containers(config):
        raise ValueError(f"容器已存在：{cid}")
    config["containers"].append({"id": cid, "kind": "finally",
                                 "parent": block_id, "blocks": [child["id"]]})
    block["finally"] = cid
    return canonical(config), cid, child["id"]


def delete_container(config: dict, container_id: str) -> dict:
    config = canonical(config)
    container = _containers(config).get(container_id)
    if container is None or container["kind"] == "root":
        raise ValueError("只能删除分支或 finally 容器")
    parent = _blocks(config)[container["parent"]]
    removed = set(container["blocks"])
    for child in list(removed):
        removed.update(_descendant_ids(config, child))
    _check_references(config, removed)
    if container["kind"] == "branch":
        if container_id not in parent["branches"]:
            raise ValueError("容器不属于父分支块")
        if len(parent["branches"]) <= 1:
            raise ValueError("分支块至少保留一个分支列表")
        parent["branches"].remove(container_id)
    else:
        parent.pop("finally", None)
    remove_containers = {container_id} | _containers_under_blocks(config, removed)
    config["blocks"] = [block for block in config["blocks"] if block["id"] not in removed]
    config["containers"] = [item for item in config["containers"]
                            if item["id"] not in remove_containers]
    return canonical(config)


_UNSET = object()


def update_container(config: dict, container_id: str, *,
                     condition: object = _UNSET,
                     role: object = _UNSET) -> dict:
    config = canonical(config)
    container = _containers(config).get(container_id)
    if container is None or container["kind"] == "root":
        raise ValueError("只能修改分支或 finally 容器")
    if container["kind"] == "finally":
        raise ValueError("finally 容器没有 condition/role")
    if condition is not _UNSET:
        if condition is None:
            container.pop("condition", None)
        else:
            container["condition"] = condition
    if role is not _UNSET:
        if role is None:
            container.pop("role", None)
        else:
            container["role"] = role
    return canonical(config)
