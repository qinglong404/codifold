"""Read and validate block view JSON.

完整字段说明见 ``docs/blocks-schema.md``。摘要：

    codifold.json   工作区配置：project.name/description/root、files、
                    views.suffix/entry；只有声明过的文件才能被 code_mapping 引用。
    视图文件         *.blocks.json：{view: {id, name, description}, blocks: [...]}

视图块共享：id / type / name / description / code_mapping / jump / on。
普通块扩展：next（缺省/整数/null 三态）、emit（事件目标）、kind（暂未启用）。
分支块扩展：select、branches（condition/role/steps）、finally、kind="try"。

嵌套分支、finally 和分支列表步骤中的 id 与顶层块共享全局唯一命名空间。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .fsutil import data_revision
from .project_config import MANIFEST_NAME, load_manifest

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "examples" / "gradebook" / "gradebook.blocks.json"
DEFAULT_PROJECT = ROOT / "examples" / "gradebook"
VIEW_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
VIEW_KINDS = {"main", "flow", "entry", "contract", "function",
              "struct", "toolbox"}
# 视图的执行语义：sequential 一条链；router 按条件选一条分支；catalog 并列条目。
# 省略时按 kind 推断（entry 为 sequential，保持旧行为）。
VIEW_SEMANTICS = {"sequential", "router", "catalog"}
VIEW_KIND_ORDER = {"main": 0, "flow": 1, "entry": 2, "contract": 3,
                   "function": 4, "struct": 5, "toolbox": 6}
CONTRACT_KINDS = {"type", "endpoint"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
MAX_BYTES = 2 * 1024 * 1024
MAX_BLOCKS = 300
MAX_DEPTH = 5
MAX_LINES_PER_BLOCK = 400
MAX_CODE_FILE_BYTES = 1024 * 1024


def infer_view_kind(view_id: str) -> str:
    """Infer a default role from the conventional view id prefix."""
    if view_id == "main":
        return "main"
    if view_id == "struct":
        return "struct"
    if view_id == "toolbox" or view_id.startswith("toolbox-"):
        return "toolbox"
    for prefix, kind in (("entry-", "entry"), ("fn-", "function"),
                         ("mod-", "struct"), ("flow-", "flow"),
                         ("contract-", "contract")):
        if view_id.startswith(prefix):
            return kind
    return "flow"


def _text(value, field: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise ValueError(f"配置缺少 {field}")
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} 不能为空")
    return value


def _int(value, field: str, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field} 必须是不小于 {minimum} 的整数")
    return value


def line_ranges(value, field: str) -> list[tuple[int, int]]:
    """``lines`` accepts ``1``, ``2``, ``"6-9"``; returns (start, end) pairs in written order."""
    if not isinstance(value, list) or not value:
        raise ValueError(f'{field} 必须是非空数组，如 [1, 2, "6-9"]')
    ranges = []
    for index, item in enumerate(value):
        where = f"{field}[{index}]"
        if isinstance(item, bool):
            raise ValueError(f"{where} 只能是正整数或 \"6-9\" 形式的区间")
        if isinstance(item, int):
            if item < 1:
                raise ValueError(f"{where} 行号必须是正整数")
            ranges.append((item, item))
            continue
        if isinstance(item, str):
            parts = item.strip().split("-")
            if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                start, end = int(parts[0]), int(parts[1])
                if start >= 1 and start <= end:
                    ranges.append((start, end))
                    continue
        raise ValueError(f'{where} 只能是正整数或 "6-9" 形式的区间')
    if sum(end - start + 1 for start, end in ranges) > MAX_LINES_PER_BLOCK:
        raise ValueError(f"{field} 映射的行数过多，最多 {MAX_LINES_PER_BLOCK} 行")
    return ranges


def _code_mapping(value, field: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    file = _text(value.get("file"), f"{field}.file")
    if Path(file).is_absolute() or ".." in Path(file).parts:
        raise ValueError(f"{field}.file 只能是配置目录内的相对路径")
    line_ranges(value.get("lines"), f"{field}.lines")
    return {"file": file, "lines": list(value["lines"])}


def _jump(value, field: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    target = _int(value.get("id"), f"{field}.id", 1)
    result = {"id": target}
    view = value.get("view")
    if view is not None:
        view = _text(view, f"{field}.view")
        if not VIEW_ID.fullmatch(view):
            raise ValueError(f"{field}.view 只能是小写字母开头的 [a-z0-9_-]")
        result["view"] = view
    return result


def _flow(value, field: str) -> dict | None:
    """A flow link is a cross-view mainline continuation, not a detail jump."""
    result = _jump(value, field)
    if result is None:
        return None
    if "view" not in result:
        raise ValueError(f"{field}.view 必填；flow 必须指向另一个视图")
    return result


def _emit(value, field: str) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 必须是非空数组")
    result = []
    for index, item in enumerate(value):
        where = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        target = _int(item.get("id"), f"{where}.id", 1)
        ref = {"id": target}
        view = item.get("view")
        if view is not None:
            view = _text(view, f"{where}.view")
            if not VIEW_ID.fullmatch(view):
                raise ValueError(f"{where}.view 只能是小写字母开头的 [a-z0-9_-]")
            ref["view"] = view
        result.append(ref)
    return result


def _bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} 必须是布尔值")
    return value


def _view_ref(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 {{view, id}} 对象")
    unknown = sorted(set(value) - {"view", "id"})
    if unknown:
        raise ValueError(f"{field} 有未知字段：{', '.join(unknown)}")
    view = _text(value.get("view"), f"{field}.view")
    if not VIEW_ID.fullmatch(view):
        raise ValueError(f"{field}.view 只能是小写字母开头的 [a-z0-9_-]")
    return {"view": view, "id": _int(value.get("id"), f"{field}.id", 1)}


def _evidence(value, field: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 必须是非空数组")
    return [_view_ref(item, f"{field}[{index}]")
            for index, item in enumerate(value)]


def _contract_fields(value, field: str) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 必须是非空数组")
    result = []
    names: set[str] = set()
    for index, item in enumerate(value):
        where = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        unknown = sorted(set(item) - {"name", "type", "required",
                                      "values", "description"})
        if unknown:
            raise ValueError(f"{where} 有未知字段：{', '.join(unknown)}")
        name = _text(item.get("name"), f"{where}.name")
        if name in names:
            raise ValueError(f"{where}.name 重复：{name}")
        names.add(name)
        type_name = _text(item.get("type"), f"{where}.type")
        field_value = {"name": name, "type": type_name}
        if item.get("required") is not None:
            field_value["required"] = _bool(item["required"],
                                            f"{where}.required")
        if type_name == "enum":
            values = item.get("values")
            if not isinstance(values, list) or not values:
                raise ValueError(
                    f"{where}.values 在 type=enum 时必须是非空数组")
            checked = []
            for value_index, value_item in enumerate(values):
                text = _text(value_item, f"{where}.values[{value_index}]")
                if text in checked:
                    raise ValueError(
                        f"{where}.values[{value_index}] 重复：{text}")
                checked.append(text)
            field_value["values"] = checked
        elif item.get("values") is not None:
            raise ValueError(f"{where}.values 只在 type=enum 时允许")
        if item.get("description") is not None:
            field_value["description"] = _text(
                item["description"], f"{where}.description")
        result.append(field_value)
    return result


def _contract_errors(value, field: str) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError(f"{field} 必须是数组")
    result = []
    statuses: set[int] = set()
    for index, item in enumerate(value):
        where = f"{field}[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        unknown = sorted(set(item) - {"status", "when"})
        if unknown:
            raise ValueError(f"{where} 有未知字段：{', '.join(unknown)}")
        status = _int(item.get("status"), f"{where}.status", 100)
        if not 400 <= status <= 599:
            raise ValueError(f"{where}.status 必须在 400-599")
        if status in statuses:
            raise ValueError(f"{where}.status 重复：{status}")
        statuses.add(status)
        result.append({
            "status": status,
            "when": _text(item.get("when"), f"{where}.when"),
        })
    return result


def _contract(value, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    kind = _text(value.get("kind"), f"{field}.kind")
    if kind not in CONTRACT_KINDS:
        raise ValueError(f"{field}.kind 只能是 {' / '.join(sorted(CONTRACT_KINDS))}")
    if kind == "type":
        allowed = {"kind", "fields"}
    else:
        allowed = {"kind", "method", "path", "auth", "request", "response",
                   "status", "errors", "handler", "external"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{field} 有未知字段：{', '.join(unknown)}")
    if kind == "type":
        return {"kind": kind,
                "fields": _contract_fields(value.get("fields"),
                                           f"{field}.fields")}
    method = _text(value.get("method"), f"{field}.method").upper()
    if method not in HTTP_METHODS:
        raise ValueError(f"{field}.method 只能是 {' / '.join(sorted(HTTP_METHODS))}")
    path = _text(value.get("path"), f"{field}.path")
    if not path.startswith("/") or any(char.isspace() for char in path):
        raise ValueError(f"{field}.path 必须以 / 开头且不能包含空白")
    result = {"kind": kind, "method": method, "path": path}
    if value.get("auth") is not None:
        result["auth"] = _bool(value["auth"], f"{field}.auth")
    for key in ("request", "response"):
        if value.get(key) is not None:
            result[key] = _text(value[key], f"{field}.{key}")
    if value.get("status") is not None:
        status = _int(value["status"], f"{field}.status", 100)
        if not 100 <= status <= 599:
            raise ValueError(f"{field}.status 必须在 100-599")
        result["status"] = status
    if value.get("errors") is not None:
        result["errors"] = _contract_errors(value["errors"],
                                            f"{field}.errors")
    if value.get("handler") is not None:
        result["handler"] = _view_ref(value["handler"],
                                      f"{field}.handler")
    if value.get("external") is not None:
        result["external"] = _bool(value["external"], f"{field}.external")
    return result


def _on(value, field: str) -> str | None:
    if value is None:
        return None
    text = _text(value, field)
    if len(text) > 80:
        raise ValueError(f"{field} 最多 80 个字符")
    return text


class _Walker:
    def __init__(self):
        self.ids: set[int] = set()
        self.refs: list[tuple[str, int]] = []
        self.jumps: list[tuple[str, int, str | None]] = []
        self.flows: list[tuple[str, int, str]] = []
        self.mappings: list[tuple[int, dict]] = []

    def block(self, value, field: str, depth: int, top_index: int | None = None) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"{field} 必须是对象")
        if depth > MAX_DEPTH:
            raise ValueError(f"{field} 嵌套过深，最多 {MAX_DEPTH} 层")
        if len(self.ids) >= MAX_BLOCKS:
            raise ValueError(f"块过多，最多 {MAX_BLOCKS} 个")
        ident = _int(value.get("id"), f"{field}.id", 1)
        if ident in self.ids:
            raise ValueError(f"id 重复：{ident}")
        self.ids.add(ident)
        block_type = value.get("type")
        if block_type not in {"normal", "branch"}:
            raise ValueError(f"{field}.type 只能是 normal 或 branch")
        result = {
            "id": ident,
            "type": block_type,
            "name": _text(value.get("name"), f"{field}.name"),
            "description": _text(value.get("description"), f"{field}.description"),
        }
        has_branch_fields = value.get("select") is not None or value.get("branches") is not None
        contract = value.get("contract")
        evidence = value.get("evidence")
        if contract is not None:
            if block_type != "normal":
                raise ValueError(f"{field} 是分支块，不能写 contract")
            for name in ("next", "jump", "flow", "emit", "on"):
                if (name == "next" and "next" in value) or (
                        name != "next" and value.get(name) is not None):
                    raise ValueError(
                        f"{field} 是契约块，不能写 {name}；契约不是流程节点")
            result["contract"] = _contract(contract, f"{field}.contract")
        if evidence is not None:
            if block_type != "normal":
                raise ValueError(f"{field} 是分支块，不能写 evidence")
            if contract is None:
                raise ValueError(f"{field}.evidence 必须和 contract 一起使用")
            result["evidence"] = _evidence(evidence, f"{field}.evidence")
        mapping = _code_mapping(value.get("code_mapping"), f"{field}.code_mapping")
        if contract is not None and mapping:
            raise ValueError(
                f"{field} 是契约块，不能写 code_mapping；"
                "请用 evidence 指向已有的流程/结构块")
        if mapping:
            result["code_mapping"] = mapping
            self.mappings.append((ident, mapping))
        jump = _jump(value.get("jump"), f"{field}.jump")
        if jump:
            result["jump"] = jump
            self.jumps.append((f"{field}.jump", jump["id"], jump.get("view")))
        flow = _flow(value.get("flow"), f"{field}.flow")
        if flow:
            result["flow"] = flow
            self.flows.append((f"{field}.flow", flow["id"], flow["view"]))
        if value.get("on") is not None:
            if top_index != 0:
                raise ValueError(f"{field}.on 只能写在视图的第一个顶层块")
            result["on"] = _on(value["on"], f"{field}.on")
        if block_type == "normal":
            if has_branch_fields:
                raise ValueError(f"{field} 是普通块，不能写 select/branches")
            if value.get("kind") is not None:
                raise ValueError(f"{field} 是普通块，kind 目前只用于分支块的 try")
            if value.get("finally") is not None:
                raise ValueError(f"{field} 是普通块，不能写 finally")
            emit = _emit(value.get("emit"), f"{field}.emit")
            if emit:
                result["emit"] = emit
            if "next" in value:
                next_value = value["next"]
                if next_value is None:
                    result["next"] = None
                else:
                    target = _int(next_value, f"{field}.next", 1)
                    if target == ident:
                        raise ValueError(f"{field}.next 不能指向自己")
                    result["next"] = target
                    self.refs.append((f"{field}.next", target))
        else:
            if "next" in value:
                raise ValueError(f"{field} 是分支块，不能写 next；分支出口由列表尾决定")
            if value.get("emit") is not None:
                raise ValueError(f"{field} 是分支块，不能写 emit；事件发出请放在普通块上")
            kind = value.get("kind")
            if kind is not None:
                kind = _text(kind, f"{field}.kind")
                if kind != "try":
                    raise ValueError(f"{field}.kind 目前只支持 try")
                result["kind"] = kind
            select = value.get("select")
            if select not in {"single", "multi"}:
                raise ValueError(f"{field}.select 只能是 single（单选）或 multi（多选/并行）")
            branches = value.get("branches")
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"{field}.branches 必须是非空数组")
            result["select"] = select
            result["branches"] = [self._branch(item, f"{field}.branches[{i}]", depth)
                                  for i, item in enumerate(branches)]
            if kind == "try":
                finally_value = value.get("finally")
                if finally_value is not None:
                    if not isinstance(finally_value, list) or not finally_value:
                        raise ValueError(f"{field}.finally 必须是非空数组")
                    result["finally"] = [self.block(item, f"{field}.finally[{i}]", depth + 1)
                                         for i, item in enumerate(finally_value)]
                self._validate_try(result, field)
            else:
                if any("role" in item for item in result["branches"]):
                    raise ValueError(f"{field} 不是 try 分支，不能写 role")
                if value.get("finally") is not None:
                    raise ValueError(f"{field} 不是 try 分支，不能写 finally")
        return result

    def _branch(self, value, field: str, depth: int) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"{field} 必须是对象")
        result = {}
        role = value.get("role")
        if role is not None:
            role = _text(role, f"{field}.role")
            if role not in {"body", "except"}:
                raise ValueError(f"{field}.role 只能是 body 或 except")
            result["role"] = role
        condition = value.get("condition")
        if condition is not None:
            result["condition"] = _text(condition, f"{field}.condition")
        steps = value.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{field}.steps 必须是非空数组")
        result["steps"] = [self.block(item, f"{field}.steps[{i}]", depth + 1)
                           for i, item in enumerate(steps)]
        return result

    def _validate_try(self, block: dict, field: str) -> None:
        if block["select"] != "single":
            raise ValueError(f"{field} 是 try 分支，select 必须是 single")
        lists = block["branches"]
        roles = [item.get("role") for item in lists]
        if any(role not in {"body", "except"} for role in roles):
            raise ValueError(f"{field} 的每条分支列表都必须写 role（body/except）")
        if roles.count("body") != 1:
            raise ValueError(f"{field} 必须恰好有一条 role=body 的列表")
        if roles[0] != "body":
            raise ValueError(f"{field} 的 body 列表必须是第一条")
        if "condition" in lists[0]:
            raise ValueError(f"{field} 的 body 列表不能写 condition")
        if roles.count("except") == 0 and not block.get("finally"):
            raise ValueError(f"{field} 至少要有一条 except 列表或一个 finally")


def _view(value, field: str = "view") -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"配置缺少 {field}")
    view_id = _text(value.get("id"), f"{field}.id")
    if not VIEW_ID.fullmatch(view_id):
        raise ValueError(f"{field}.id 只能是小写字母开头的 [a-z0-9_-]")
    result = {
        "id": view_id,
        "name": _text(value.get("name"), f"{field}.name"),
        "description": _text(value.get("description"), f"{field}.description"),
    }
    kind = value.get("kind")
    if kind is not None:
        kind = _text(kind, f"{field}.kind")
        if kind not in VIEW_KINDS:
            raise ValueError(f"{field}.kind 只能是 {' / '.join(sorted(VIEW_KINDS))}")
        result["kind"] = kind
    semantics = value.get("semantics")
    if semantics is not None:
        semantics = _text(semantics, f"{field}.semantics")
        if semantics not in VIEW_SEMANTICS:
            raise ValueError(
                f"{field}.semantics 只能是 {' / '.join(sorted(VIEW_SEMANTICS))}")
        result["semantics"] = semantics
    return result


def validate(config) -> dict:
    if not isinstance(config, dict):
        raise ValueError("配置必须是 JSON 对象")
    view = _view(config.get("view"))
    blocks_value = config.get("blocks")
    if not isinstance(blocks_value, list) or not blocks_value:
        raise ValueError("blocks 必须是非空数组")
    if len(blocks_value) > MAX_BLOCKS:
        raise ValueError(f"blocks 过多，最多 {MAX_BLOCKS} 个")
    walker = _Walker()
    blocks = [walker.block(item, f"blocks[{index}]", 1, index)
              for index, item in enumerate(blocks_value)]
    for where, target in walker.refs:
        if target not in walker.ids:
            raise ValueError(f"{where} 指向不存在的 id：{target}")
    for where, target, jump_view in walker.jumps:
        if jump_view is None and target not in walker.ids:
            raise ValueError(f"{where} 指向不存在的 id：{target}")
    for where, target, flow_view in walker.flows:
        if flow_view == view["id"]:
            raise ValueError(f"{where} 必须指向其他视图；同视图请用 next")
        if target < 1:
            raise ValueError(f"{where} 指向不存在的 id：{target}")
    for block in _iter_blocks(blocks):
        for index, ref in enumerate(block.get("emit", [])):
            if ref.get("view") is None and ref["id"] not in walker.ids:
                raise ValueError(f"id {block['id']} 的 emit[{index}] 指向不存在的 id：{ref['id']}")
    view_kind = view.get("kind") or infer_view_kind(view["id"])
    contract_blocks = [block for block in _iter_blocks(blocks)
                       if block.get("contract") is not None
                       or block.get("evidence") is not None]
    if view_kind == "contract":
        for block in _iter_blocks(blocks):
            if block["type"] != "normal":
                raise ValueError(
                    f"契约视图 {view['id']} 的块 {block['id']} 必须是普通块")
            if block.get("contract") is None:
                raise ValueError(
                    f"契约视图 {view['id']} 的块 {block['id']} 缺少 contract")
    elif contract_blocks:
        raise ValueError(
            f"contract/evidence 只能写在 kind=contract 的视图：{view['id']}")
    return {"view": view, "blocks": blocks}


def _iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


def _iter_jumps(blocks: list[dict]):
    for block in _iter_blocks(blocks):
        if block.get("jump"):
            yield block, block["jump"]


def _iter_flows(blocks: list[dict]):
    for block in _iter_blocks(blocks):
        if block.get("flow"):
            yield block, block["flow"]


def _view_blocks(directory: Path, view: dict) -> dict[int, dict]:
    config = _validate_any(_read_config(directory / view["file"]))
    return {block["id"]: block for block in _iter_blocks(config["blocks"])}


def _validate_any(raw_config):
    from . import flat
    if flat.is_flat(raw_config):
        return flat.validate_flat(raw_config)
    return validate(raw_config)


def _resolve_code(ident: int, mapping: dict, codes: dict, manifest: dict | None):
    file = mapping["file"]
    target = manifest["paths"].get(file) if manifest else None
    if target is None:
        if manifest is None:
            raise ValueError("缺少 codifold.json，不能使用 code_mapping")
        declared = "、".join(manifest["files"])
        raise ValueError(f"code_mapping.file 未在 codifold.json 中声明：{file}（已声明：{declared}）")
    if target.stat().st_size > MAX_CODE_FILE_BYTES:
        raise ValueError(f"代码文件过大：{file}")
    try:
        rows = target.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"代码文件不是 UTF-8 文本：{file}") from error
    snippets = []
    for start, end in line_ranges(mapping["lines"], f"id {ident} 代码映射"):
        if end > len(rows):
            raise ValueError(f"代码映射超出文件行数：{file} 共 {len(rows)} 行，映射到了 {end}")
        snippets.append({"start": start, "end": end,
                         "lines": [{"number": n, "text": rows[n - 1]}
                                   for n in range(start, end + 1)]})
    codes[str(ident)] = {"file": file, "ranges": snippets}


def _read_config(target: Path) -> dict:
    if target.stat().st_size > MAX_BYTES:
        raise ValueError(f"配置文件超过 2 MB：{target.name}")
    return json.loads(target.read_text(encoding="utf-8"))


def _read_config_with_revision(target: Path) -> tuple[dict, str]:
    if target.stat().st_size > MAX_BYTES:
        raise ValueError(f"配置文件超过 2 MB：{target.name}")
    raw = target.read_bytes()
    return json.loads(raw.decode("utf-8")), data_revision(raw)


def _single_index(target: Path) -> dict:
    config, revision = _read_config_with_revision(target)
    view = _view(config.get("view") if isinstance(config, dict) else None)
    view_id = view["id"]
    result = {
        "source": {"kind": "file", "path": str(target)},
        "entry": view_id,
        "manifest_revision": None,
        "views": [{
            "view_id": view_id,
            "name": view["name"],
            "description": view["description"],
            "kind": view.get("kind") or infer_view_kind(view_id),
            "file": target.name,
            "entry": True,
            "revision": revision,
            **({"semantics": view["semantics"]} if view.get("semantics") else {}),
        }],
    }
    manifest = load_manifest(target.parent)
    if manifest:
        result["manifest_revision"] = manifest.get("revision")
        result["project"] = {
            "name": manifest["name"],
            "description": manifest["description"],
            "root": manifest["root"],
            "files": manifest["files"],
        }
    return result


def _project_index(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = load_manifest(directory)
    if manifest is None:
        raise ValueError(f"缺少 {MANIFEST_NAME} 工作区配置")
    files = sorted(target for target in directory.glob(f"*{manifest['suffix']}")
                   if target.is_file())
    if not files:
        raise ValueError(f"目录里没有 {manifest['suffix']} 视图文件：{directory}")
    views = []
    seen: dict[str, str] = {}
    for target in files:
        config, revision = _read_config_with_revision(target)
        view = _view(config.get("view") if isinstance(config, dict) else None,
                     f"{target.name}.view")
        view_id = view["id"]
        if view_id in seen:
            raise ValueError(f"view_id 重复：{view_id}（{seen[view_id]} 与 {target.name}）")
        seen[view_id] = target.name
        entry_view = {
            "view_id": view_id,
            "name": view["name"],
            "description": view["description"],
            "kind": view.get("kind") or infer_view_kind(view_id),
            "file": target.name,
            "revision": revision,
        }
        if view.get("semantics"):
            entry_view["semantics"] = view["semantics"]
        views.append(entry_view)
    if manifest["entry"] is not None:
        entry = manifest["entry"]
        if entry not in seen:
            available = "、".join(sorted(seen))
            raise ValueError(f"views.entry 指向不存在的视图：{entry}（可用：{available}）")
    else:
        entry = views[0]["view_id"]
    for view in views:
        view["entry"] = view["view_id"] == entry
    views.sort(key=lambda view: (VIEW_KIND_ORDER[view["kind"]],
                                 view["view_id"] != entry, view["file"]))
    return {
        "source": {"kind": "project", "path": str(directory)},
        "project": {
            "name": manifest["name"],
            "description": manifest["description"],
            "root": manifest["root"],
            "files": manifest["files"],
        },
        "entry": entry,
        "manifest_revision": manifest.get("revision"),
        "views": views,
    }


def load_index(path: str | None = None) -> dict:
    """Return the view index for a project directory or a single config file."""
    if not path:
        return _project_index(DEFAULT_PROJECT)
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"找不到路径：{target}")
    if target.is_dir():
        return _project_index(target)
    if target.is_file() and target.suffix.lower() == ".json":
        return _single_index(target)
    raise ValueError("路径必须是 .json 文件或包含视图 JSON 的目录")


def _pick_view(index: dict, view: str | None) -> dict:
    wanted = view or index["entry"]
    for item in index["views"]:
        if item["view_id"] == wanted:
            return item
    available = "、".join(item["view_id"] for item in index["views"])
    raise ValueError(f"找不到视图：{wanted}（可用：{available}）")


def load(path: str | None = None, view: str | None = None) -> dict:
    if not path and view is not None:
        path = str(DEFAULT_PROJECT)
    chosen = None
    project_views = None
    if path:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"找不到配置路径：{target}")
        if target.is_dir():
            index = _project_index(target)
            chosen = _pick_view(index, view)
            target_file, project_dir = target / chosen["file"], target
            source = {"kind": "project", "path": str(target),
                      "view": chosen["view_id"], "file": chosen["file"]}
            project_views = {item["view_id"] for item in index["views"]}
        elif target.is_file() and target.suffix.lower() == ".json":
            index = _single_index(target)
            if view is not None and view != index["entry"]:
                raise ValueError(f"单个文件模式不支持视图：{view}（只有 {index['entry']}）")
            chosen = index["views"][0]
            target_file, project_dir = target, target.parent
            source = {"kind": "file", "path": str(target)}
        else:
            raise ValueError("配置必须是 .json 文件或包含视图 JSON 的目录")
    else:
        if not DEFAULT.is_file():
            raise FileNotFoundError("默认视图文件不存在")
        target_file, project_dir = DEFAULT, DEFAULT.parent
        source = {"kind": "default", "path": str(DEFAULT)}
    manifest = load_manifest(project_dir)
    raw_config, revision = _read_config_with_revision(target_file)
    from . import flat
    is_flat_view = flat.is_flat(raw_config)
    config = _validate_any(raw_config)
    flat_config = flat.from_nested(config) if is_flat_view else None
    for block, jump in _iter_jumps(config["blocks"]):
        target_view = jump.get("view")
        if target_view is None:
            continue
        if project_views is None:
            raise ValueError(f"id {block['id']} 的 jump.view 需要文件夹项目；单文件模式没有其他视图")
        if target_view not in project_views:
            available = "、".join(sorted(project_views))
            raise ValueError(f"id {block['id']} 的 jump.view 指向不存在的视图：{target_view}（可用：{available}）")
    current_view_id = config["view"]["id"]
    by_view = {item["view_id"]: item for item in index["views"]} if project_views is not None else {}
    for block, flow in _iter_flows(config["blocks"]):
        target_view = flow["view"]
        if project_views is None:
            raise ValueError(f"id {block['id']} 的 flow 需要文件夹项目；单文件模式没有其他视图")
        if target_view not in project_views:
            available = "、".join(sorted(project_views))
            raise ValueError(f"id {block['id']} 的 flow 指向不存在的视图：{target_view}（可用：{available}）")
        target_kind = by_view[target_view].get("kind")
        if target_kind not in {"main", "flow", "entry"}:
            raise ValueError(f"id {block['id']} 的 flow 目标必须是主线/流程/入口视图：{target_view} 是 {target_kind}")
    block_cache = {current_view_id: {block["id"]: block for block in _iter_blocks(config["blocks"])}}
    for block, flow in _iter_flows(config["blocks"]):
        target_view = flow["view"]
        if target_view not in block_cache:
            block_cache[target_view] = _view_blocks(target, by_view[target_view])
        if flow["id"] not in block_cache[target_view]:
            raise ValueError(f"id {block['id']} 的 flow 指向 {target_view} 里不存在的 id：{flow['id']}")
    for block in _iter_blocks(config["blocks"]):
        for index, ref in enumerate(block.get("emit", [])):
            ref_view = ref.get("view")
            if ref_view is None:
                target_view = current_view_id
            elif project_views is None:
                raise ValueError(f"id {block['id']} 的 emit[{index}].view 需要文件夹项目；单文件模式没有其他视图")
            else:
                target_view = ref_view
                if target_view not in project_views:
                    available = "、".join(sorted(project_views))
                    raise ValueError(f"id {block['id']} 的 emit[{index}].view 指向不存在的视图：{target_view}（可用：{available}）")
            if target_view not in block_cache:
                block_cache[target_view] = _view_blocks(target, by_view[target_view])
            target_block = block_cache[target_view].get(ref["id"])
            if target_block is None:
                raise ValueError(f"id {block['id']} 的 emit[{index}] 指向 {target_view} 里不存在的 id：{ref['id']}")
            if not target_block.get("on"):
                raise ValueError(f"id {block['id']} 的 emit[{index}] 目标 {target_view} · {ref['id']} 不是事件入口（缺少 on）")
    codes: dict[str, dict] = {}
    for block in _iter_blocks(config["blocks"]):
        mapping = block.get("code_mapping")
        if mapping:
            _resolve_code(block["id"], mapping, codes, manifest)
    payload = {
        "config": config,
        "source": source,
        "schema": "flat" if is_flat_view else "nested",
        "flat": flat_config,
        "order": [block["id"] for block in config["blocks"]],
        "codes": codes,
    }
    if manifest:
        payload["project"] = {
            "name": manifest["name"],
            "description": manifest["description"],
            "root": manifest["root"],
            "files": manifest["files"],
        }
    if chosen is not None:
        payload["view"] = {"view_id": chosen["view_id"], "file": chosen["file"],
                           "name": chosen["name"], "description": chosen["description"]}
    payload["revision"] = revision
    payload["manifest_revision"] = manifest.get("revision") if manifest else None
    return payload
