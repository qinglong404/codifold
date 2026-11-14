"""Markdown export for text-only review of a Codifold workspace.

The document is a faithful projection of view ``name``/``description`` text
and navigation edges. It never rewrites the prose. Code is included only when
explicitly requested, and only as a separate appendix.

Examples:
    python3 -m codifold.workbench export-md examples/taskflow
    python3 -m codifold.workbench export-md examples/taskflow --out flow.md
    python3 -m codifold.workbench export-md examples/taskflow --with-code
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import block_config, contract, mapping_report, narrative, project_config

KIND_ORDER = ["main", "flow", "entry", "contract", "function",
              "struct", "toolbox"]
KIND_LABELS = {
    "main": "主线",
    "flow": "流程",
    "entry": "入口",
    "contract": "契约",
    "function": "函数细节",
    "struct": "结构/定义",
    "toolbox": "工具箱",
}
LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".sh": "bash",
    ".md": "markdown",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
}


def _one_line(value: str) -> str:
    return " ".join(str(value).split())


def _iter_blocks(blocks: list[dict]):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


def _sibling_next(blocks: list[dict]) -> dict[int, int | None]:
    """Map a block to the following block in the same step list, if any."""
    result: dict[int, int | None] = {}

    def walk(items: list[dict]) -> None:
        for index, block in enumerate(items):
            following = items[index + 1]["id"] if index + 1 < len(items) else None
            result[block["id"]] = following
            for branch in block.get("branches", []):
                walk(branch["steps"])
            if block.get("finally"):
                walk(block["finally"])

    walk(blocks)
    return result


def _execution_order(blocks: list[dict]) -> dict[int, int]:
    return {block["id"]: index for index, block in enumerate(_iter_blocks(blocks))}


def _continuations(blocks: list[dict]) -> dict[int, int | None]:
    """Map a block to the block that follows when it has no explicit next."""
    result: dict[int, int | None] = {}

    def walk(items: list[dict], continuation: int | None) -> None:
        for index, block in enumerate(items):
            next_id = items[index + 1]["id"] if index + 1 < len(items) else continuation
            result[block["id"]] = next_id
            if block["type"] != "branch":
                continue
            branch_continuation = next_id
            if block.get("kind") == "try" and block.get("finally"):
                branch_continuation = block["finally"][0]["id"]
            for branch in block.get("branches", []):
                walk(branch["steps"], branch_continuation)
            if block.get("kind") == "try" and block.get("finally"):
                walk(block["finally"], next_id)

    walk(blocks, None)
    return result


def _edge_targets(blocks: list[dict]) -> list[str]:
    targets: list[str] = []

    def add(view_id: str | None) -> None:
        if view_id and view_id not in targets:
            targets.append(view_id)

    for block in _iter_blocks(blocks):
        flow = block.get("flow")
        if flow:
            add(flow.get("view"))
        jump = block.get("jump")
        if jump:
            add(jump.get("view"))
        for ref in block.get("emit", []):
            add(ref.get("view"))
    return targets


def _roles(index: dict) -> dict[str, dict]:
    return {view["view_id"]: view for view in index["views"]}


def _discover(index: dict, configs: dict[str, dict]) -> tuple[str, dict[str, int], set[str]]:
    views = _roles(index)
    if not views:
        raise ValueError("工作区没有视图")
    main_id = next((view["view_id"] for view in index["views"]
                    if view.get("kind") == "main"), None)
    if main_id is None:
        main_id = index.get("entry") or index["views"][0]["view_id"]
    if main_id not in views:
        main_id = index["views"][0]["view_id"]
    queue = [main_id]
    seen = {main_id}
    discovery = {main_id: 0}
    while queue:
        current = queue.pop(0)
        config = configs.get(current)
        if config is None:
            continue
        for target in _edge_targets(config["blocks"]):
            if target in views and target not in seen:
                seen.add(target)
                discovery[target] = len(discovery)
                queue.append(target)
    return main_id, discovery, seen


def _order_views(index: dict, discovery: dict[str, int], seen: set[str]) -> list[str]:
    """Main first, then flow/entry, then functions, structs and toolbox."""
    views = _roles(index)
    groups: dict[str, list[str]] = {}
    for view_id, _ in sorted(discovery.items(), key=lambda item: item[1]):
        kind = views[view_id].get("kind") or "flow"
        groups.setdefault(kind, []).append(view_id)
    ordered: list[str] = []
    ordered.extend(groups.pop("main", []))
    for kind in KIND_ORDER:
        if kind == "main":
            continue
        ordered.extend(groups.pop(kind, []))
    for kind in sorted(groups):
        ordered.extend(groups[kind])
    for view in index["views"]:
        if view["view_id"] not in seen and view["view_id"] not in ordered:
            ordered.append(view["view_id"])
    return ordered


def _filter_views(index: dict, ordered: list[str], view_filters: list[str],
                  kind_filters: list[str]) -> list[str]:
    views = _roles(index)
    if view_filters:
        unknown = [view_id for view_id in view_filters if view_id not in views]
        if unknown:
            available = "、".join(view["view_id"] for view in index["views"])
            raise ValueError(
                f"找不到视图：{'、'.join(unknown)}（可用：{available}）"
            )
        selected = set(view_filters)
    else:
        selected = set(views)
    if kind_filters:
        wanted = set(kind_filters)
        selected = {view_id for view_id in selected
                    if (views[view_id].get("kind") or "flow") in wanted}
    result = [view_id for view_id in ordered if view_id in selected]
    if not result:
        raise ValueError("筛选后没有可导出的视图")
    return result


def _role_label(view: dict, config: dict | None) -> str:
    kind = view.get("kind") or "flow"
    label = KIND_LABELS.get(kind, kind)
    if config is not None and "kind" not in config.get("view", {}):
        label += "（按 id 推断）"
    return label


# 函数/结构/工具箱视图是并列条目，不是一条执行链；阅读规则要按角色区分。
SEQUENTIAL_KINDS = {"main", "flow", "entry"}
LISTING_NOTE = ("本视图是并列的条目（函数、声明或工具），块之间不默认存在执行顺序；"
                "没有箭头标注时只表示“同属一个视图”，不代表接着执行。")
ROUTER_NOTE = ("本视图按条件选择一条分支：一次请求只走其中一条，块和分支的排列"
               "不是执行顺序；标了 `如果：` 的地方才是选择点。")


def _view_semantics(view: dict) -> str:
    """视图执行语义：显式声明优先，否则按角色推断（兼容旧工作区）。"""
    declared = view.get("semantics")
    if declared in {"sequential", "router", "catalog"}:
        return declared
    kind = view.get("kind") or "flow"
    if kind in {"function", "struct", "toolbox", "contract"}:
        return "catalog"
    return "sequential"


def _view_note(view: dict) -> str:
    semantics = _view_semantics(view)
    if semantics == "catalog":
        return LISTING_NOTE
    if semantics == "router":
        return ROUTER_NOTE
    return ""


def _target_text(ref: dict, selected: set[str]) -> str:
    view_id = ref.get("view")
    if not view_id:
        return f"[{ref['id']}]"
    text = f"{view_id}:{ref['id']}"
    if view_id not in selected:
        text += "（未导出）"
    return text


def _list_falls_through(steps: list[dict]) -> bool:
    return bool(steps) and _falls_through(steps[-1])


def _falls_through(block: dict) -> bool:
    """Whether the block can reach the instruction after its step list."""
    if block["type"] != "branch":
        return "next" not in block
    if block.get("kind") == "try" and block.get("finally"):
        return _list_falls_through(block["finally"])
    return any(_list_falls_through(branch["steps"])
               for branch in block.get("branches", []))


def _navigation(block: dict, selected: set[str],
                sibling_next: dict[int, int | None],
                order: dict[int, int], continuation: int | None,
                context: str | None) -> str:
    parts: list[str] = []
    flow = block.get("flow")
    if flow:
        parts.append(f"主线继续 → {_target_text(flow, selected)}")
    jump = block.get("jump")
    if jump:
        parts.append(f"展开细节 → {_target_text(jump, selected)}")
    refs = block.get("emit", [])
    if refs:
        targets = "、".join(_target_text(ref, selected) for ref in refs)
        parts.append(f"事件通知 → {targets}")
    if "next" in block:
        target = block["next"]
        if target is None:
            parts.append("结束")
        elif sibling_next.get(block["id"]) != target:
            direction = ("回到"
                         if order.get(target, -1) < order.get(block["id"], -1)
                         else "继续")
            parts.append(f"{direction} → [{target}]")
    elif context is not None:
        if continuation is None:
            if block["type"] != "branch":
                parts.append("结束")
        elif (sibling_next.get(block["id"]) != continuation
              and _falls_through(block)):
            label = {
                "branch": "分支结束后继续",
                "try_body": "正常执行后继续",
                "try_except": "异常处理后继续",
                "finally": "收尾后继续",
            }.get(context, "继续")
            parts.append(f"{label} → [{continuation}]")
    elif continuation is None:
        if block["type"] != "branch":
            parts.append("结束")
    trigger = block.get("on")
    if trigger:
        if isinstance(trigger, (list, tuple)):
            trigger = "、".join(str(item) for item in trigger)
        parts.append(f"触发事件：{trigger}")
    return "；".join(parts)


def _branch_label(block: dict, branch: dict) -> str:
    condition = _one_line(branch.get("condition") or "")
    role = branch.get("role")
    if block.get("kind") == "try":
        if role == "body":
            return "正常执行"
        if role == "except":
            return "异常处理" + (f"：{condition}" if condition else "")
        return "分支" + (f"：{condition}" if condition else "")
    prefix = "并行分支：" if block.get("select") == "multi" else "如果："
    return prefix + (condition or "（未写条件）")


def _render_block(block: dict, depth: int, lines: list[str], *,
                  selected: set[str],
                  sibling_next: dict[int, int | None],
                  order: dict[int, int],
                  continuations: dict[int, int | None],
                  context: str | None = None) -> None:
    indent = "  " * depth
    description = _one_line(block["description"])
    text = f"{indent}- [{block['id']}] {_one_line(block['name'])} —— {description}"
    nav = _navigation(block, selected, sibling_next, order,
                      continuations.get(block["id"]), context)
    if nav:
        text += f"（{nav}）"
    lines.append(text)
    if block["type"] != "branch":
        return
    for branch in block.get("branches", []):
        lines.append(f"{indent}  - **{_branch_label(block, branch)}**")
        if block.get("kind") == "try":
            branch_context = ("try_body" if branch.get("role") == "body"
                              else "try_except")
        else:
            branch_context = "branch"
        for step in branch["steps"]:
            _render_block(step, depth + 2, lines, selected=selected,
                          sibling_next=sibling_next, order=order,
                          continuations=continuations, context=branch_context)
    if block.get("finally"):
        lines.append(f"{indent}  - **最后一定执行**")
        for step in block["finally"]:
            _render_block(step, depth + 2, lines, selected=selected,
                          sibling_next=sibling_next, order=order,
                          continuations=continuations, context="finally")


def _view_kind(view_id: str, config: dict | None) -> str:
    if config and config.get("view", {}).get("kind"):
        return config["view"]["kind"]
    return block_config.infer_view_kind(view_id)


def _cell(value) -> str:
    return _one_line(str(value)).replace("|", "\\|")


def _ref_label(view_id: str, block_id: int, selected: set[str]) -> str:
    text = f"{view_id}:{block_id}"
    return text if view_id in selected else f"{text}（未导出）"


def _evidence_text(block: dict, selected: set[str]) -> str:
    return "、".join(
        _ref_label(ref["view"], ref["id"], selected)
        for ref in block.get("evidence", [])
    )


def _render_contract_types(blocks: list[dict], lines: list[str],
                           selected: set[str]) -> None:
    lines.append("### 类型")
    lines.append("")
    for block in blocks:
        payload = block["contract"]
        lines.append(f"#### {_one_line(block['name'])} [{block['id']}]"
                     f" —— {_one_line(block['description'])}")
        lines.append("")
        evidence = _evidence_text(block, selected)
        if evidence:
            lines.append(f"来源：{evidence}")
            lines.append("")
        lines.append("| 字段 | 类型/取值 | 必填 | 说明 |")
        lines.append("|---|---|---|---|")
        for field in payload["fields"]:
            type_text = field["type"]
            if field.get("values"):
                type_text += "：" + " / ".join(field["values"])
            required = "是" if field.get("required") else ""
            lines.append(
                f"| {_cell(field['name'])} | {_cell(type_text)} | "
                f"{required} | {_cell(field.get('description') or '')} |")
        lines.append("")


def _render_contract_endpoints(blocks: list[dict], lines: list[str],
                               selected: set[str]) -> None:
    lines.append("### 接口")
    lines.append("")
    lines.append("| 名称 | 方法 | 路径 | 鉴权 | 请求 | 响应 | 错误 | 处理 | 说明 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for block in blocks:
        payload = block["contract"]
        errors = payload.get("errors") or []
        error_text = "；".join(
            f"{item['status']} {item['when']}" for item in errors)
        handler = payload.get("handler")
        if handler:
            handler_text = _ref_label(handler["view"], handler["id"], selected)
        elif payload.get("external"):
            handler_text = "外部接口"
        else:
            handler_text = ""
        response = payload.get("response") or ""
        if payload.get("status") is not None:
            response += f"（{payload['status']}）"
        name = f"{_one_line(block['name'])} [{block['id']}]"
        lines.append(
            f"| {_cell(name)} | {payload['method']} | "
            f"{_cell(payload['path'])} | "
            f"{'是' if payload.get('auth') else ''} | "
            f"{_cell(payload.get('request') or '')} | {_cell(response)} | "
            f"{_cell(error_text)} | {_cell(handler_text)} | "
            f"{_cell(block['description'])} |")
    lines.append("")


def _render_contract_view(config: dict, lines: list[str],
                          selected: set[str]) -> None:
    blocks = [block for block in config["blocks"] if block.get("contract")]
    types = [block for block in blocks
             if block["contract"]["kind"] == "type"]
    endpoints = [block for block in blocks
                 if block["contract"]["kind"] == "endpoint"]
    if types:
        _render_contract_types(types, lines, selected)
    if endpoints:
        _render_contract_endpoints(endpoints, lines, selected)
    if not types and not endpoints:
        lines.append("（没有可导出的契约内容）")
        lines.append("")


def _coverage(directory: str) -> tuple[dict | None, list[str], list[str]]:
    try:
        report = mapping_report.report(directory)
    except (OSError, ValueError) as error:
        return None, [str(error)], []
    files = report.get("files", [])
    covered = sum(item.get("covered", 0) for item in files)
    total = sum(item.get("total", 0) for item in files)
    return {
        "covered": covered,
        "total": total,
        "ratio": (covered / total) if total else 0.0,
        "files": files,
    }, list(report.get("errors", [])), list(report.get("warnings", []))


def _coherence(directory: str) -> tuple[dict | None, dict, list[str], list[str]]:
    data = narrative.report(directory)
    return (data.get("coherence"), data,
            list(data.get("errors", [])), list(data.get("warnings", [])))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _render_appendix_a(lines: list[str], *, configs: dict[str, dict],
                       selected: list[str], coverage: dict | None,
                       coherence: dict | None, narrative_data: dict,
                       contract_data: dict,
                       errors: list[str], warnings: list[str]) -> None:
    lines.append("## 附录 A. 自动检查")
    lines.append("")
    if coverage is None:
        lines.append("- 覆盖率：未知")
    else:
        lines.append(
            f"- 覆盖率：{coverage['covered']}/{coverage['total']}"
            f"（{coverage['ratio'] * 100:.1f}%）"
        )
    if coherence:
        lines.append(
            f"- 连贯性：{coherence.get('reachable', 0)}/"
            f"{coherence.get('total', 0)}（{coherence.get('score', 0):.4f}）"
        )
    else:
        lines.append("- 连贯性：未检查")
    if contract_data and contract_data.get("views"):
        lines.append(
            f"- 契约：{len(contract_data.get('types') or [])} 个类型、"
            f"{len(contract_data.get('endpoints') or [])} 个接口")
    lines.append(f"- 错误：{len(errors)}")
    lines.append(f"- 警告：{len(warnings)}")
    lines.append("")
    lines.append("口径说明：")
    lines.append("")
    lines.append("- 覆盖率只统计 `codifold.json` 的 `files` 里、按语言规则算作代码的行；"
                 "空行和纯注释不计入分母。分子是被至少一个块的 `code_mapping` 覆盖的行。")
    lines.append("- 连贯性是“视图可达率”：从 `kind: main` 的视图出发，沿 `jump` / "
                 "`flow` / `emit` 的跨视图引用能到达的视图数除以视图总数；"
                 "它不表示每条业务路径都正确。")
    lines.append("- 错误是违反硬性结构约束（如引用不存在、`next` 越界）的项；"
                 "警告是机械检查里需要人工判断的项（如重复映射、不可达块、叙事提示）。")
    lines.append("- 机械检查全绿只说明结构自洽；语义问题（职责归属、因果关系、"
                 "术语一致性）仍需按附录 B 逐条核对，本文不把它们计成警告。")
    lines.append("- 100% 覆盖只说明每一行代码有归属，不说明分支、调用和异常被正确表达；"
                 "语义完整度仍需人工或 AI 审核。")
    lines.append("")

    if coverage and coverage["files"]:
        lines.append("### 文件覆盖")
        lines.append("")
        for item in coverage["files"]:
            lines.append(
                f"- `{item['file']}`：{item['covered']}/{item['total']}"
                f"（{item['ratio'] * 100:.1f}%）"
            )
        lines.append("")

    if errors:
        lines.append("### 错误")
        lines.append("")
        for error in errors[:50]:
            lines.append(f"- {error}")
        if len(errors) > 50:
            lines.append(f"- … 另有 {len(errors) - 50} 条")
        lines.append("")
    if warnings:
        lines.append("### 警告")
        lines.append("")
        for warning in warnings[:50]:
            lines.append(f"- {warning}")
        if len(warnings) > 50:
            lines.append(f"- … 另有 {len(warnings) - 50} 条")
        lines.append("")

    orphans = (coherence or {}).get("orphans") or []
    if orphans:
        lines.append("### 未从主线到达的视图")
        lines.append("")
        for view_id in orphans:
            lines.append(f"- `{view_id}`")
        lines.append("")

    unmapped = []
    for view_id in selected:
        config = configs.get(view_id)
        if config is None or _view_kind(view_id, config) == "contract":
            continue
        missing = sum(1 for block in _iter_blocks(config["blocks"])
                      if not block.get("code_mapping"))
        if missing:
            unmapped.append((view_id, missing))
    if unmapped:
        lines.append("### 无代码映射的块")
        lines.append("")
        for view_id, count in unmapped:
            lines.append(f"- `{view_id}`：{count} 个")
        lines.append("")

    empty_conditions = []
    for view_id in selected:
        config = configs.get(view_id)
        if config is None:
            continue
        for block in _iter_blocks(config["blocks"]):
            if block["type"] != "branch":
                continue
            for branch in block.get("branches", []):
                if branch.get("role") == "body":
                    continue
                if not branch.get("condition"):
                    empty_conditions.append(f"{view_id}:{block['id']}（{block['name']}）")
    if empty_conditions:
        lines.append("### 未写条件的分支")
        lines.append("")
        for item in empty_conditions[:30]:
            lines.append(f"- `{item}`")
        if len(empty_conditions) > 30:
            lines.append(f"- … 另有 {len(empty_conditions) - 30} 条")
        lines.append("")

    short = []
    for view_id in selected:
        config = configs.get(view_id)
        if config is None:
            continue
        for block in _iter_blocks(config["blocks"]):
            text = block["description"].strip()
            if len(text) < 12:
                short.append(f"{view_id}:{block['id']} {block['name']}"
                             f"（{len(text)} 字）")
    if short:
        lines.append("### 描述过短的块")
        lines.append("")
        for item in short[:30]:
            lines.append(f"- `{item}`")
        if len(short) > 30:
            lines.append(f"- … 另有 {len(short) - 30} 条")
        lines.append("")

    if narrative_data.get("skipped"):
        lines.append("### 叙事检查")
        lines.append("")
        lines.append("- 跳过：工作区没有显式 `kind` 或 `flow`，只做了结构统计。")
        lines.append("")


def _render_appendix_b(lines: list[str], *, with_code: bool = False) -> None:
    lines.append("## 附录 B. 给审核 AI 的检查清单")
    lines.append("")
    lines.append("请用 `view:id` 引用具体块，并区分“文字问题”和“事实问题”。")
    lines.append("")
    lines.append("1. 主线是否从入口连续走到终点？有没有只有跳转、没有出口的块？")
    lines.append("2. 每个分支是否有明确条件、结果和汇合点？")
    lines.append("3. 每个循环是否有回到循环头的说明？终止条件是否清楚？")
    lines.append("4. 函数是否只在被调用处展开？主线里是否内联了过多细节？")
    lines.append("5. 有没有无法从主线到达的视图或块？")
    lines.append("6. 同一概念是否前后叫法不一致？")
    lines.append("7. 有没有只有标题、没有解释“为什么/然后呢”的块？")
    lines.append("8. 描述是否和跳转关系矛盾（例如说“继续”但实际结束）？")
    if with_code:
        lines.append("9. 纯文字不能判断代码事实；本文的代码证据在附录 C，"
                     "引用时请对照具体行。")
    else:
        lines.append("9. 纯文字不能判断代码事实；需要核对时用 `--with-code` 重新导出"
                     "（该模式会追加附录 C 代码证据），不要凭空推断。")
    lines.append("10. 输出时每条写清：`view:id`、原文引用、问题类型、建议。")
    lines.append("")


def _language(file: str) -> str:
    return LANGUAGES.get(Path(file).suffix.lower(), "")


def _render_appendix_c(lines: list[str], *, configs: dict[str, dict],
                       codes: dict[str, dict], selected: list[str],
                       max_code_lines: int) -> None:
    lines.append("## 附录 C. 代码证据")
    lines.append("")
    lines.append(f"> 只列 `code_mapping` 覆盖的行；每个块最多 {max_code_lines} 行，"
                 "超出部分截断。")
    lines.append("")
    section = 0
    rendered = 0
    for view_id in selected:
        config = configs.get(view_id)
        codes_for_view = codes.get(view_id) or {}
        if config is None or not codes_for_view:
            continue
        mapped = [block for block in _iter_blocks(config["blocks"])
                  if str(block["id"]) in codes_for_view]
        if not mapped:
            continue
        section += 1
        lines.append(f"### C.{section} {view_id} · {_one_line(config['view']['name'])}")
        lines.append("")
        for block in mapped:
            code = codes_for_view[str(block["id"])]
            lines.append(f"#### {view_id}:{block['id']} · {_one_line(block['name'])}")
            lines.append("")
            remaining = max_code_lines
            truncated = False
            for code_range in code.get("ranges", []):
                if remaining <= 0:
                    truncated = True
                    break
                start = code_range["start"]
                end = code_range["end"]
                span = f"{code['file']}:{start}" if start == end \
                    else f"{code['file']}:{start}-{end}"
                lines.append(f"`{span}`")
                lines.append("")
                fence = "````"
                language = _language(code["file"])
                lines.append(fence + language)
                source_lines = code_range.get("lines", [])
                take = source_lines[:remaining]
                for item in take:
                    lines.append(item["text"])
                if len(source_lines) > len(take):
                    lines.append("...")
                    truncated = True
                lines.append(fence)
                lines.append("")
                remaining -= len(take)
                rendered += 1
            if truncated:
                lines.append(f"（本块代码已截断，最多 {max_code_lines} 行）")
                lines.append("")
    if not rendered:
        lines.append("（没有可用的代码映射）")
        lines.append("")


def build(workspace: str, *, views: list[str] | None = None,
          kinds: list[str] | None = None, with_code: bool = False,
          max_code_lines: int = 20) -> tuple[str, dict]:
    """Build the Markdown document and a summary of what was exported."""
    if max_code_lines < 1:
        raise ValueError("--max-code-lines 必须大于 0")
    directory = Path(workspace).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区：{directory}")
    if not directory.is_dir():
        raise ValueError(f"工作区不是目录：{directory}")
    directory = directory.resolve()
    if project_config.load_manifest(directory) is None:
        raise ValueError(f"缺少 {project_config.MANIFEST_NAME}，不是 Codifold 工作区")
    index = block_config.load_index(str(directory))

    configs: dict[str, dict] = {}
    codes: dict[str, dict] = {}
    errors: list[str] = []
    for view in index["views"]:
        view_id = view["view_id"]
        try:
            payload = block_config.load(str(directory), view_id)
        except (OSError, ValueError) as error:
            errors.append(f"视图 {view_id} 读取失败：{error}")
            continue
        configs[view_id] = payload["config"]
        codes[view_id] = payload.get("codes", {})

    main_id, discovery, seen = _discover(index, configs)
    ordered = _order_views(index, discovery, seen)
    selected_order = _filter_views(index, ordered, views or [], kinds or [])
    selected = set(selected_order)

    coverage, coverage_errors, coverage_warnings = _coverage(str(directory))
    errors.extend(coverage_errors)
    try:
        coherence, narrative_data, narrative_errors, narrative_warnings = _coherence(str(directory))
    except (OSError, ValueError) as error:
        coherence = None
        narrative_data = {}
        narrative_errors = [str(error)]
        narrative_warnings = []
    errors.extend(narrative_errors)
    try:
        contract_data = contract.report(str(directory))
        contract_errors = list(contract_data.get("errors", []))
        contract_warnings = list(contract_data.get("warnings", []))
    except (OSError, ValueError) as error:
        contract_data = {}
        contract_errors = [str(error)]
        contract_warnings = []
    errors.extend(contract_errors)
    warnings = (list(coverage_warnings) + list(narrative_warnings)
                + list(contract_warnings))

    role_counts = {}
    for view_id in selected_order:
        kind = _roles(index)[view_id].get("kind") or "flow"
        role_counts[kind] = role_counts.get(kind, 0) + 1
    block_count = sum(
        len(list(_iter_blocks(configs[view_id]["blocks"])))
        for view_id in selected_order if view_id in configs
    )
    has_contract = any(
        _view_kind(view_id, configs.get(view_id)) == "contract"
        for view_id in selected_order
    )

    project = index.get("project") or {}
    title = f"{_one_line(project.get('name') or '流程图')} 流程图文字稿"
    lines: list[str] = [f"# {title}", ""]
    if project.get("description"):
        lines.append(f"> 项目：{_one_line(project['description'])}")
    lines.append(f"> 工作区：`{directory}`")
    lines.append(f"> 视图：{len(selected_order)} 个；块：{block_count} 个")
    if coverage is not None:
        lines.append(
            f"> 覆盖率：{coverage['covered']}/{coverage['total']}"
            f"（{coverage['ratio'] * 100:.1f}%；整个工作区）"
        )
    else:
        lines.append("> 覆盖率：未知")
    if coherence:
        lines.append(
            f"> 连贯性：{coherence.get('reachable', 0)}/"
            f"{coherence.get('total', 0)}（{coherence.get('score', 0):.4f}；整个工作区）"
        )
    else:
        lines.append("> 连贯性：未检查")
    if views or kinds:
        filters = []
        if views:
            filters.append("视图 " + "、".join(views))
        if kinds:
            filters.append("角色 " + "、".join(kinds))
        lines.append(f"> 本次只导出：{'；'.join(filters)}；覆盖率/连贯性按整个工作区计算")
    if with_code:
        lines.append("> 正文只含名称和描述；源码只在附录 C。")
    else:
        lines.append("> 本文只含名称和描述，不含源码。")
    lines.append("")

    lines.append("## 阅读说明")
    lines.append("")
    order_text = ("主线 → 流程/入口 → 契约 → 函数细节 → 结构/定义"
                  if has_contract
                  else "主线 → 流程/入口 → 函数细节 → 结构/定义")
    lines.append(f"- 顺序：{order_text}；每一节是一个视图。")
    lines.append("- `[65]` 是块 ID；`view:65` 是跨视图引用。")
    if has_contract:
        lines.append("- 契约视图用表格列出类型和接口；`来源` / `处理` 指向已有的"
                     "流程或结构块，代码证据仍看那些块。")
    lines.append("- `如果：` 是分支条件；`正常执行 / 异常处理 / 最后一定执行` "
                 "是 try 结构。")
    lines.append("- `→` 是跨视图跳转：`主线继续` 对应 flow，`展开细节` 对应 jump，"
                 "`事件通知` 对应 emit。")
    lines.append("- 每个视图标了「读取方式」：`顺序执行` 的视图里，块后没有标注时"
                 "默认执行下一块，`结束` 表示路径到此为止，`回到` 表示循环；"
                 "`按条件分流` 的视图一次只走一条分支；`并列条目` 的视图没有默认顺序，"
                 "箭头只表示引用关系。")
    if with_code:
        lines.append("- 本文正文不判断代码事实；需要核对代码时看附录 C。")
    else:
        lines.append("- 本文不含源码，不能用来判断描述与代码是否一致。")
    lines.append("")

    lines.append("## 目录")
    lines.append("")
    for number, view_id in enumerate(selected_order, 1):
        view = _roles(index)[view_id]
        note = "（未从主线到达）" if view_id not in seen else ""
        lines.append(f"{number}. [{view_id} · {_one_line(view['name'])}](#view-{view_id}){note}")
    lines.append("")

    for number, view_id in enumerate(selected_order, 1):
        view = _roles(index)[view_id]
        config = configs.get(view_id)
        lines.append(f'<a id="view-{view_id}"></a>')
        lines.append(f"## {number}. {view_id} · {_one_line(view['name'])}")
        lines.append("")
        lines.append(f"**角色**：{_role_label(view, config)}")
        note = _view_note(view)
        if note:
            lines.append("")
            lines.append(f"**读取方式**：{note}")
        if view_id not in seen:
            lines.append("")
            lines.append("**注意**：这个视图无法从主线到达。")
        lines.append("")
        lines.append(f"**说明**：{_one_line(view['description'])}")
        lines.append("")
        if config is None:
            lines.append(f"**读取失败**：{next((e for e in errors if view_id in e), '未知错误')}")
            lines.append("")
            continue
        if _view_kind(view_id, config) == "contract":
            _render_contract_view(config, lines, selected)
        else:
            sibling_next = _sibling_next(config["blocks"])
            order = _execution_order(config["blocks"])
            continuations = _continuations(config["blocks"])
            for block in config["blocks"]:
                _render_block(block, 0, lines, selected=selected,
                              sibling_next=sibling_next, order=order,
                              continuations=continuations)
            lines.append("")

    warnings = _dedupe(warnings)
    errors = _dedupe(errors)
    _render_appendix_a(lines, configs=configs,
                       selected=selected_order, coverage=coverage,
                       coherence=coherence, narrative_data=narrative_data,
                       contract_data=contract_data,
                       errors=errors, warnings=warnings)
    _render_appendix_b(lines, with_code=with_code)
    if with_code:
        _render_appendix_c(lines, configs=configs, codes=codes,
                           selected=selected_order,
                           max_code_lines=max_code_lines)

    summary = {
        "main": main_id,
        "views": len(selected_order),
        "blocks": block_count,
        "role_counts": role_counts,
        "coverage": coverage,
        "coherence": coherence,
        "contract": contract_data,
        "errors": errors,
        "warnings": warnings,
        "selected": selected_order,
    }
    return "\n".join(lines).rstrip() + "\n", summary


def write(text: str, out: str | None) -> Path | None:
    """Write the document to ``out``; ``None`` or ``-`` means stdout."""
    if out is None or out == "-":
        print(text, end="")
        return None
    target = Path(out).expanduser()
    if target.exists() and target.is_dir():
        raise ValueError(f"输出路径是目录：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target
