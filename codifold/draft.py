"""Compile compact view drafts into canonical Codifold view JSON.

A draft keeps the same block semantics as the final schema, but uses local
``key`` strings for references and short ``map`` line ranges. The compiler
allocates numeric block ids and resolves ``next`` / ``jump`` / ``emit``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import block_config, project_config


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空字符串")
    return value.strip()


def iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from iter_blocks(block["finally"])


def normalize_drafts(data) -> list[dict]:
    """Validate a draft container: one view, a list of views, or ``{views}``."""
    if isinstance(data, list):
        specs = data
    elif isinstance(data, dict) and "views" in data:
        unknown = sorted(set(data) - {"views"})
        if unknown:
            raise ValueError(f"草稿批次有未知字段：{', '.join(unknown)}")
        specs = data["views"]
    elif isinstance(data, dict):
        specs = [data]
    else:
        raise ValueError("草稿必须是视图对象、视图数组或 {views: [...]}")
    if not isinstance(specs, list) or not specs:
        raise ValueError("草稿至少需要一个视图")
    for index, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise ValueError(f"views[{index}] 必须是对象")
    return specs


def _block_ids(config: dict) -> set[int]:
    return {block["id"] for block in iter_blocks(config["blocks"])}


def _check_keys(value: dict, allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} 有未知字段：{', '.join(unknown)}")


def _as_lines(value: Any, field: str) -> list[Any]:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是行号、区间或数组")
    if isinstance(value, (int, str)):
        values = [value]
    elif isinstance(value, list) and value:
        values = list(value)
    else:
        raise ValueError(f"{field} 必须是行号、区间或非空数组")
    return [int(item.strip()) if isinstance(item, str) and item.strip().isdigit()
            else item for item in values]


def _scan_blocks(blocks: Any, field: str, depth: int,
                 keys: set[str], ids: set[int]) -> None:
    if not isinstance(blocks, list) or not blocks:
        raise ValueError(f"{field} 必须是非空数组")
    if depth > block_config.MAX_DEPTH:
        raise ValueError(f"{field} 嵌套过深，最多 {block_config.MAX_DEPTH} 层")
    for index, item in enumerate(blocks):
        where = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        key = item.get("key")
        if key is not None:
            key = _text(key, f"{where}.key")
            if key == "end":
                raise ValueError(f"{where}.key 不能使用保留字 end")
            if key in keys:
                raise ValueError(f"{where}.key 重复：{key}")
            keys.add(key)
        ident = item.get("id")
        if ident is not None:
            if isinstance(ident, bool) or not isinstance(ident, int) or ident < 1:
                raise ValueError(f"{where}.id 必须是正整数")
            if ident in ids:
                raise ValueError(f"{where}.id 重复：{ident}")
            ids.add(ident)
        branches = item.get("branches")
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"{where}.branches 必须是非空数组")
            for branch_index, branch in enumerate(branches):
                branch_field = f"{where}.branches[{branch_index}]"
                if not isinstance(branch, dict):
                    raise ValueError(f"{branch_field} 必须是对象")
                _check_keys(branch, {"condition", "role", "steps"}, branch_field)
                _scan_blocks(branch.get("steps"), f"{branch_field}.steps",
                             depth + 1, keys, ids)
        finally_blocks = item.get("finally")
        if finally_blocks is not None:
            _scan_blocks(finally_blocks, f"{where}.finally", depth + 1, keys, ids)


@dataclass(slots=True)
class _PendingLocal:
    field: str
    block: dict
    target: str | int
    path: str
    index: int | None = None


@dataclass(slots=True)
class _PendingExternal:
    field: str
    block: dict
    view_id: str
    target: str | int
    by_key: bool
    path: str
    index: int | None = None


class _ViewCompiler:
    def __init__(self, spec: dict, view: dict, existing_ids: set[int],
                 declared_files: set[str], default_file: str | None) -> None:
        self.spec = spec
        self.view = view
        self.existing_ids = set(existing_ids)
        self.declared_files = declared_files
        self.default_file = default_file
        self.explicit_keys: set[str] = set()
        self.explicit_ids: set[int] = set()
        _scan_blocks(spec.get("blocks"), "blocks", 1,
                     self.explicit_keys, self.explicit_ids)
        self.next_id = max(self.existing_ids | self.explicit_ids, default=0) + 1
        self.used_ids: set[int] = set()
        self.keys: dict[str, int] = {}
        self.auto_index = 0
        self.count = 0
        self.pending_local: list[_PendingLocal] = []
        self.pending_external: list[_PendingExternal] = []
        self.config = {"view": view, "blocks": []}

    def compile(self) -> dict:
        blocks = self.spec.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise ValueError("blocks 必须是非空数组")
        self.config["blocks"] = [
            self._block(item, f"blocks[{index}]", 1)
            for index, item in enumerate(blocks)
        ]
        return self.config

    def _key_for(self, item: dict, field: str) -> str:
        key = item.get("key")
        if key is None:
            self.auto_index += 1
            key = f"_auto_{self.auto_index}"
            while key in self.explicit_keys or key in self.keys:
                self.auto_index += 1
                key = f"_auto_{self.auto_index}"
        key = _text(key, f"{field}.key")
        if key in self.keys:
            raise ValueError(f"{field}.key 重复：{key}")
        return key

    def _id_for(self, item: dict, field: str) -> int:
        if "id" in item:
            ident = item["id"]
            if isinstance(ident, bool) or not isinstance(ident, int) or ident < 1:
                raise ValueError(f"{field}.id 必须是正整数")
            if ident in self.used_ids:
                raise ValueError(f"{field}.id 重复：{ident}")
        else:
            while self.next_id in self.used_ids or self.next_id in self.existing_ids:
                self.next_id += 1
            ident = self.next_id
            self.next_id += 1
        self.used_ids.add(ident)
        self.count += 1
        if self.count > block_config.MAX_BLOCKS:
            raise ValueError(f"块过多，最多 {block_config.MAX_BLOCKS} 个")
        return ident

    def _mapping(self, item: dict, field: str) -> dict | None:
        has_mapping = item.get("code_mapping") is not None
        has_map = item.get("map") is not None
        if has_mapping and has_map:
            raise ValueError(f"{field} 不能同时写 map 和 code_mapping")
        if not has_mapping and not has_map:
            return None
        if has_mapping:
            value = item["code_mapping"]
            if not isinstance(value, dict):
                raise ValueError(f"{field}.code_mapping 必须是对象")
            _check_keys(value, {"file", "lines"}, f"{field}.code_mapping")
            file = _text(value.get("file"), f"{field}.code_mapping.file")
            lines = value.get("lines")
        else:
            value = item["map"]
            if isinstance(value, dict):
                _check_keys(value, {"file", "lines"}, f"{field}.map")
                file = value.get("file") or self.default_file
                lines = value.get("lines")
            else:
                file = self.default_file
                lines = value
        if file is None:
            raise ValueError(f"{field} 使用了 map，但视图没有 file，块也没写 file")
        if not isinstance(file, str) or not file.strip():
            raise ValueError(f"{field}.map.file 必须是非空字符串")
        file = file.strip()
        if file not in self.declared_files:
            raise ValueError(f"{field}.map.file 未在 codifold.json 声明：{file}")
        lines = _as_lines(lines, f"{field}.map")
        block_config.line_ranges(lines, f"{field}.map")
        return {"file": file, "lines": lines}

    def _block(self, item: dict, field: str, depth: int) -> dict:
        if not isinstance(item, dict):
            raise ValueError(f"{field} 必须是对象")
        if depth > block_config.MAX_DEPTH:
            raise ValueError(f"{field} 嵌套过深，最多 {block_config.MAX_DEPTH} 层")
        _check_keys(item, {
            "key", "id", "type", "name", "description", "map", "code_mapping",
            "contract", "evidence", "on", "jump", "flow", "next", "emit",
            "select", "branches", "finally", "kind",
        }, field)
        key = self._key_for(item, field)
        ident = self._id_for(item, field)
        self.keys[key] = ident
        block_type = item.get("type")
        if block_type is None:
            block_type = "branch" if "branches" in item else "normal"
        if block_type not in {"normal", "branch"}:
            raise ValueError(f"{field}.type 只能是 normal 或 branch")
        result = {
            "id": ident,
            "type": block_type,
            "name": _text(item.get("name"), f"{field}.name"),
            "description": _text(item.get("description"), f"{field}.description"),
        }
        mapping = self._mapping(item, field)
        if mapping:
            result["code_mapping"] = mapping
        if item.get("on") is not None:
            result["on"] = _text(item["on"], f"{field}.on")
        if item.get("jump") is not None:
            self._parse_ref(item["jump"], result, "jump", f"{field}.jump")
        if item.get("flow") is not None:
            self._parse_flow(item["flow"], result, f"{field}.flow")
        if block_type == "normal":
            forbidden = [name for name in ("select", "branches", "finally", "kind")
                         if item.get(name) is not None]
            if forbidden:
                raise ValueError(f"{field} 是普通块，不能写 {', '.join(forbidden)}")
            if item.get("contract") is not None:
                result["contract"] = item["contract"]
                if item.get("evidence") is not None:
                    result["evidence"] = item["evidence"]
            elif item.get("evidence") is not None:
                raise ValueError(f"{field}.evidence 必须和 contract 一起使用")
            if item.get("emit") is not None:
                emit = item["emit"]
                if not isinstance(emit, list) or not emit:
                    raise ValueError(f"{field}.emit 必须是非空数组")
                result["emit"] = [{} for _ in emit]
                for index, ref in enumerate(emit):
                    self._parse_ref(ref, result, "emit", f"{field}.emit[{index}]",
                                    index)
            if "next" in item:
                self._parse_ref(item["next"], result, "next", f"{field}.next")
        else:
            if "next" in item or "emit" in item:
                raise ValueError(f"{field} 是分支块，不能写 next/emit")
            if (item.get("contract") is not None
                    or item.get("evidence") is not None):
                raise ValueError(f"{field} 是分支块，不能写 contract/evidence")
            select = item.get("select", "single")
            if select not in {"single", "multi"}:
                raise ValueError(f"{field}.select 只能是 single 或 multi")
            result["select"] = select
            kind = item.get("kind")
            if kind is not None:
                kind = _text(kind, f"{field}.kind")
                if kind != "try":
                    raise ValueError(f"{field}.kind 目前只支持 try")
                result["kind"] = kind
            branches = item.get("branches")
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"{field}.branches 必须是非空数组")
            result["branches"] = [
                self._branch(branch, f"{field}.branches[{index}]", depth)
                for index, branch in enumerate(branches)
            ]
            finally_blocks = item.get("finally")
            if finally_blocks is not None:
                if not isinstance(finally_blocks, list) or not finally_blocks:
                    raise ValueError(f"{field}.finally 必须是非空数组")
                result["finally"] = [
                    self._block(step, f"{field}.finally[{index}]", depth + 1)
                    for index, step in enumerate(finally_blocks)
                ]
        return result

    def _branch(self, branch: dict, field: str, depth: int) -> dict:
        if not isinstance(branch, dict):
            raise ValueError(f"{field} 必须是对象")
        _check_keys(branch, {"condition", "role", "steps"}, field)
        result = {}
        if branch.get("role") is not None:
            result["role"] = _text(branch["role"], f"{field}.role")
        if branch.get("condition") is not None:
            result["condition"] = _text(branch["condition"],
                                         f"{field}.condition")
        steps = branch.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{field}.steps 必须是非空数组")
        result["steps"] = [
            self._block(step, f"{field}.steps[{index}]", depth + 1)
            for index, step in enumerate(steps)
        ]
        return result

    def _parse_ref(self, value: Any, block: dict, field: str, path: str,
                   index: int | None = None) -> None:
        if field == "next":
            if value is None or value == "end":
                block["next"] = None
                return
            if isinstance(value, int) and not isinstance(value, bool):
                if value < 1:
                    raise ValueError(f"{path} 必须是正整数或块 key")
                self.pending_local.append(_PendingLocal(field, block, value, path))
                return
            if isinstance(value, str):
                target = value.strip()
                if target.startswith("@"):
                    target = target[1:]
                if not target:
                    raise ValueError(f"{path} 不能为空")
                if ":" in target:
                    raise ValueError(f"{path} 不能跨视图；跨视图请用 jump")
                self.pending_local.append(_PendingLocal(field, block, target, path))
                return
            raise ValueError(f"{path} 只能是 end、null、块 key 或正整数")
        if field == "emit" and value is None:
            raise ValueError(f"{path} 不能为空")
        if isinstance(value, str):
            target = value.strip()
            if not target:
                raise ValueError(f"{path} 不能为空")
            if target.startswith("@"):
                self.pending_local.append(
                    _PendingLocal(field, block, target[1:], path, index))
                return
            if ":" in target:
                view_id, token = target.split(":", 1)
                view_id, token = view_id.strip(), token.strip()
                if not view_id or not token:
                    raise ValueError(f"{path} 的视图或目标为空")
                self._external_ref(view_id, token, block, field, path, index)
                return
            self.pending_local.append(_PendingLocal(field, block, target, path, index))
            return
        if isinstance(value, dict):
            _check_keys(value, {"view", "id", "key"}, path)
            has_id = "id" in value
            has_key = "key" in value
            if has_id == has_key:
                raise ValueError(f"{path} 必须且只能写 id 或 key 之一")
            view_id = value.get("view")
            if view_id is not None:
                view_id = _text(view_id, f"{path}.view")
            if has_key:
                key = _text(value["key"], f"{path}.key")
                if view_id is None or view_id == self.view["id"]:
                    self.pending_local.append(
                        _PendingLocal(field, block, key, path, index))
                else:
                    self.pending_external.append(
                        _PendingExternal(field, block, view_id, key, True, path, index))
                return
            ident = value["id"]
            if isinstance(ident, bool) or not isinstance(ident, int) or ident < 1:
                raise ValueError(f"{path}.id 必须是正整数")
            if view_id is None or view_id == self.view["id"]:
                self.pending_local.append(
                    _PendingLocal(field, block, ident, path, index))
            else:
                self.pending_external.append(
                    _PendingExternal(field, block, view_id, ident, False, path, index))
            return
        raise ValueError(f"{path} 必须是视图:目标、局部 key 或 {id/key} 对象")

    def _parse_flow(self, value: Any, block: dict, path: str) -> None:
        if isinstance(value, str):
            target = value.strip()
            if not target:
                raise ValueError(f"{path} 不能为空")
            if ":" not in target:
                raise ValueError(f"{path} 必须写成 view:key 或 {view, id}，不能指向本视图")
            view_id, token = target.split(":", 1)
            view_id, token = view_id.strip(), token.strip()
            if not view_id or not token:
                raise ValueError(f"{path} 的视图或目标为空")
            if view_id == self.view["id"]:
                raise ValueError(f"{path} 必须指向其他视图；同视图请用 next")
            self._external_ref(view_id, token, block, "flow", path, None)
            return
        if isinstance(value, dict):
            _check_keys(value, {"view", "id", "key"}, path)
            view_id = _text(value.get("view"), f"{path}.view")
            if view_id == self.view["id"]:
                raise ValueError(f"{path} 必须指向其他视图；同视图请用 next")
            has_id = "id" in value
            has_key = "key" in value
            if has_id == has_key:
                raise ValueError(f"{path} 必须且只能写 id 或 key 之一")
            if has_key:
                key = _text(value["key"], f"{path}.key")
                self.pending_external.append(
                    _PendingExternal("flow", block, view_id, key, True, path))
                return
            ident = value["id"]
            if isinstance(ident, bool) or not isinstance(ident, int) or ident < 1:
                raise ValueError(f"{path}.id 必须是正整数")
            self.pending_external.append(
                _PendingExternal("flow", block, view_id, ident, False, path))
            return
        raise ValueError(f"{path} 必须是 view:key 或 {view, id/key} 对象")

    def _external_ref(self, view_id: str, token: str, block: dict,
                      field: str, path: str, index: int | None) -> None:
        if not block_config.VIEW_ID.fullmatch(view_id):
            raise ValueError(f"{path} 的视图 id 不合法：{view_id}")
        if token.isdigit():
            ident = int(token)
            if ident < 1:
                raise ValueError(f"{path} 的 id 必须是正整数")
            target: str | int = ident
            by_key = False
        else:
            target = token
            by_key = True
        if view_id == self.view["id"]:
            if by_key:
                self.pending_local.append(
                    _PendingLocal(field, block, target, path, index))
            else:
                self.pending_local.append(
                    _PendingLocal(field, block, target, path, index))
            return
        self.pending_external.append(
            _PendingExternal(field, block, view_id, target, by_key, path, index))

    def resolve_local(self) -> None:
        for pending in self.pending_local:
            if isinstance(pending.target, int):
                ident = pending.target
            else:
                ident = self.keys.get(pending.target)
                if ident is None:
                    available = "、".join(sorted(self.keys)) or "无"
                    raise ValueError(f"{pending.path} 指向不存在的块 key："
                                     f"{pending.target}（可用：{available}）")
            if ident not in self.used_ids:
                raise ValueError(f"{pending.path} 指向不存在的 id：{ident}")
            self._set_ref(pending.block, pending.field, {"id": ident},
                          pending.index)

    def resolve_external(self, bundle_ids: dict[str, set[int]],
                         bundle_keys: dict[tuple[str, str], int],
                         existing_ids: Callable[[str], set[int]]) -> None:
        for pending in self.pending_external:
            if pending.view_id in bundle_ids:
                if pending.by_key:
                    ident = bundle_keys.get((pending.view_id, pending.target))
                    if ident is None:
                        raise ValueError(f"{pending.path} 指向 {pending.view_id} "
                                         f"里不存在的块 key：{pending.target}")
                else:
                    ident = pending.target
                    if ident not in bundle_ids[pending.view_id]:
                        raise ValueError(f"{pending.path} 指向 {pending.view_id} "
                                         f"里不存在的 id：{ident}")
            else:
                if pending.by_key:
                    raise ValueError(f"{pending.path} 的跨视图 key 只能指向同一批次"
                                     "里的视图；外部视图请写数字 id")
                ident = pending.target
                ids = existing_ids(pending.view_id)
                if ident not in ids:
                    raise ValueError(f"{pending.path} 指向 {pending.view_id} "
                                     f"里不存在的 id：{ident}")
            self._set_ref(pending.block, pending.field,
                          {"view": pending.view_id, "id": ident}, pending.index)

    @staticmethod
    def _set_ref(block: dict, field: str, ref: dict, index: int | None) -> None:
        if field == "next":
            block["next"] = ref["id"]
        elif field == "jump":
            block["jump"] = ref
        elif field == "flow":
            block["flow"] = ref
        else:
            block["emit"][index] = ref


def _view_meta(spec: dict, existing: dict | None) -> dict:
    value = spec.get("view")
    if not isinstance(value, dict):
        raise ValueError("草稿缺少 view 对象（id/name/description）")
    _check_keys(value, {"id", "name", "description", "kind", "semantics"}, "view")
    view_id = _text(value.get("id"), "view.id")
    if not block_config.VIEW_ID.fullmatch(view_id):
        raise ValueError("view.id 只能是小写字母开头的 [a-z0-9_-]")
    name = value.get("name")
    description = value.get("description")
    if existing is not None:
        name = name or existing.get("name")
        description = description or existing.get("description")
    kind = value.get("kind") or (existing or {}).get("kind") \
        or block_config.infer_view_kind(view_id)
    kind = _text(kind, "view.kind")
    if kind not in block_config.VIEW_KINDS:
        raise ValueError("view.kind 只能是 main / flow / entry / function / struct / toolbox")
    semantics = value.get("semantics") or (existing or {}).get("semantics")
    if semantics is not None:
        semantics = _text(semantics, "view.semantics")
        if semantics not in block_config.VIEW_SEMANTICS:
            raise ValueError("view.semantics 只能是 sequential / router / catalog")
    result = {
        "id": view_id,
        "name": _text(name, "view.name"),
        "description": _text(description, "view.description"),
        "kind": kind,
    }
    if semantics is not None:
        result["semantics"] = semantics
    return result


def _read_existing_ids(directory: Path, entry: dict) -> set[int]:
    raw = json.loads((directory / entry["file"]).read_text(encoding="utf-8"))
    # 已有视图可能是 flat（blocks + containers），必须按 flat 校验后再投影，
    # 否则分支块的 branches 是容器 id 字符串，会被当成嵌套格式报错。
    return _block_ids(block_config._validate_any(raw))


def compile_drafts(workspace: str | Path, specs: list[dict]) -> list[dict]:
    """Compile one or more drafts against a workspace without writing anything."""
    directory = Path(workspace).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区：{directory}")
    directory = directory.resolve()
    manifest = project_config.load_manifest(directory)
    if manifest is None:
        raise ValueError("缺少 codifold.json，不能转换")
    if not isinstance(specs, list) or not specs:
        raise ValueError("至少需要一个视图草稿")
    index = block_config.load_index(str(directory))
    existing_views = {view["view_id"]: view for view in index["views"]}
    declared = set(manifest["files"])
    compilers: list[_ViewCompiler] = []
    seen: set[str] = set()
    for spec_index, spec in enumerate(specs):
        field = f"views[{spec_index}]" if len(specs) > 1 else "草稿"
        if not isinstance(spec, dict):
            raise ValueError(f"{field} 必须是对象")
        _check_keys(spec, {"view", "file", "blocks"}, field)
        view_value = spec.get("view")
        if not isinstance(view_value, dict):
            raise ValueError(f"{field} 缺少 view 对象")
        view_id = _text(view_value.get("id"), f"{field}.view.id")
        existing = existing_views.get(view_id)
        view = _view_meta(spec, existing)
        if view_id in seen:
            raise ValueError(f"同一批次里 view.id 重复：{view_id}")
        seen.add(view_id)
        existing_ids = _read_existing_ids(directory, existing) if existing else set()
        default_file = spec.get("file")
        if default_file is not None:
            default_file = _text(default_file, f"{field}.file")
            if default_file not in declared:
                raise ValueError(f"{field}.file 未在 codifold.json 声明：{default_file}")
        elif len(declared) == 1:
            default_file = next(iter(declared))
        compiler = _ViewCompiler(spec, view, existing_ids, declared, default_file)
        compiler.compile()
        compilers.append(compiler)
    bundle_ids = {compiler.view["id"]: set(compiler.used_ids)
                  for compiler in compilers}
    bundle_keys = {(compiler.view["id"], key): ident
                   for compiler in compilers
                   for key, ident in compiler.keys.items()}
    cache: dict[str, set[int]] = {}

    def existing_ids(view_id: str) -> set[int]:
        if view_id in cache:
            return cache[view_id]
        entry = existing_views.get(view_id)
        if entry is None:
            raise ValueError(f"jump/emit 指向不存在的视图：{view_id}")
        cache[view_id] = _read_existing_ids(directory, entry)
        return cache[view_id]

    for compiler in compilers:
        compiler.resolve_local()
        compiler.resolve_external(bundle_ids, bundle_keys, existing_ids)
    configs = [compiler.config for compiler in compilers]
    for config in configs:
        block_config.validate(config)
    return configs
