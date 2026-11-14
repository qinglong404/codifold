"""Mechanical mapping report: code coverage and duplicate mappings.

覆盖按“代码行”计算：Python 用 tokenize 排除空行/纯注释行；其它语言用
非空且不以常见注释前缀开头的行。覆盖缺口和重复映射都是警告，不是硬错误。
"""
from __future__ import annotations

import tokenize
from pathlib import Path

from . import block_config, reachability
from .project_config import MANIFEST_NAME, load_manifest

COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", ";")


def _generic_code_lines(target: Path) -> set[int]:
    lines = set()
    for number, text in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        stripped = text.strip()
        if stripped and not stripped.startswith(COMMENT_PREFIXES):
            lines.add(number)
    return lines


def _python_code_lines(target: Path) -> set[int]:
    lines = set()
    try:
        with tokenize.open(target) as handle:
            for token in tokenize.generate_tokens(handle.readline):
                if token.type in {
                    tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE,
                    tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT,
                    tokenize.ENDMARKER,
                }:
                    continue
                for number in range(token.start[0], token.end[0] + 1):
                    lines.add(number)
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
        return _generic_code_lines(target)
    return lines


def code_lines(target: Path) -> set[int]:
    if target.suffix.lower() == ".py":
        return _python_code_lines(target)
    return _generic_code_lines(target)


def _ranges(numbers) -> list[dict]:
    ranges = []
    for number in sorted(numbers):
        if ranges and number == ranges[-1]["end"] + 1:
            ranges[-1]["end"] = number
        else:
            ranges.append({"start": number, "end": number})
    return ranges


def _overlap_ranges(mapped: dict[int, set[int]]) -> list[dict]:
    groups = []
    for number in sorted(mapped):
        blocks = sorted(mapped[number])
        if len(blocks) < 2:
            continue
        if groups and number == groups[-1]["end"] + 1 and groups[-1]["blocks"] == blocks:
            groups[-1]["end"] = number
        else:
            groups.append({"start": number, "end": number, "blocks": blocks})
    return groups


def _iter_blocks(blocks):
    for block in blocks:
        yield block
        for branch in block.get("branches", []):
            yield from _iter_blocks(branch["steps"])
        if block.get("finally"):
            yield from _iter_blocks(block["finally"])


def report(path: str | None = None) -> dict:
    if path:
        target = Path(path).expanduser()
        if not target.exists():
            raise FileNotFoundError(f"找不到路径：{target}")
        project_dir = (target if target.is_dir() else target.parent).resolve()
    else:
        project_dir = block_config.DEFAULT_PROJECT.resolve()
    manifest = load_manifest(project_dir)
    if manifest is None:
        raise ValueError(f"缺少 {MANIFEST_NAME}，无法检测代码覆盖")
    index = block_config.load_index(str(project_dir))
    views = []
    errors = []
    warnings = []
    per_file: dict[str, dict[int, set[int]]] = {}
    configs: dict[str, dict] = {}

    for view in index["views"]:
        try:
            payload = block_config.load(str(project_dir), view["view_id"])
        except (OSError, ValueError) as error:
            views.append({"view_id": view["view_id"], "name": view["name"],
                          "kind": view.get("kind"), "ok": False,
                          "error": str(error)})
            errors.append(f"视图 {view['view_id']}：{error}")
            continue
        views.append({"view_id": view["view_id"], "name": view["name"],
                      "kind": view.get("kind"), "ok": True})
        configs[view["view_id"]] = payload["config"]
        for block_id, code in payload["codes"].items():
            for code_range in code["ranges"]:
                for line in code_range["lines"]:
                    per_file.setdefault(code["file"], {}).setdefault(
                        line["number"], set()).add(int(block_id))

    jump_targets_by_view: dict[str, set[int]] = {}
    for view_id, config in configs.items():
        for block in _iter_blocks(config["blocks"]):
            jump = block.get("jump")
            if not jump:
                continue
            target_view = jump.get("view") or view_id
            jump_targets_by_view.setdefault(target_view, set()).add(jump["id"])

    known_views = {item["view_id"] for item in index["views"]}
    kinds_by_view = {item["view_id"]: item.get("kind") for item in index["views"]}
    for view_id, config in configs.items():
        # 声明区、函数实现和契约表不是执行链：允许并排的独立块。
        if kinds_by_view.get(view_id) in {"struct", "toolbox", "function",
                                          "contract"}:
            dead = []
        else:
            dead = reachability.unreachable(config["blocks"],
                                            jump_targets_by_view.get(view_id, set()))
        if dead:
            names = "、".join(f"{item['id']} {item['name']}" for item in dead[:8])
            more = "…" if len(dead) > 8 else ""
            warnings.append(f"视图 {view_id}：{len(dead)} 个不可达块（{names}{more}）")
        for item in views:
            if item["view_id"] == view_id:
                item["unreachable"] = dead
                break

    ids_by_view = {
        view_id: {block["id"] for block in _iter_blocks(config["blocks"])}
        for view_id, config in configs.items()
    }
    for view_id, config in configs.items():
        for block in _iter_blocks(config["blocks"]):
            jump = block.get("jump")
            if jump:
                target_view = jump.get("view") or view_id
                if target_view != view_id:
                    if target_view not in known_views:
                        errors.append(f"视图 {view_id} 的块 {block['id']} jump 指向不存在的视图：{target_view}")
                    elif target_view in ids_by_view and jump["id"] not in ids_by_view[target_view]:
                        errors.append(
                            f"视图 {view_id} 的块 {block['id']} jump 指向 {target_view} 里不存在的 id：{jump['id']}")
            flow = block.get("flow")
            if not flow:
                continue
            target_view = flow["view"]
            if target_view not in known_views:
                errors.append(f"视图 {view_id} 的块 {block['id']} flow 指向不存在的视图：{target_view}")
            elif target_view in ids_by_view and flow["id"] not in ids_by_view[target_view]:
                errors.append(
                    f"视图 {view_id} 的块 {block['id']} flow 指向 {target_view} 里不存在的 id：{flow['id']}")
            elif kinds_by_view.get(target_view) not in {"main", "flow", "entry"}:
                errors.append(
                    f"视图 {view_id} 的块 {block['id']} flow 目标不是主线/流程/入口视图：{target_view}")

    files = []
    for file in manifest["files"]:
        source = manifest["paths"][file]
        relevant = code_lines(source)
        mapped = per_file.get(file, {})
        covered = set(mapped) & relevant
        uncovered = sorted(relevant - covered)
        outside = sorted(set(mapped) - relevant)
        overlaps = _overlap_ranges(mapped)
        ratio = round(len(covered) / len(relevant), 4) if relevant else 1.0
        if uncovered:
            warnings.append(f"{file}：{len(uncovered)} 行代码未映射")
        if overlaps:
            warnings.append(f"{file}：{len(overlaps)} 段重复映射")
        if outside:
            warnings.append(f"{file}：{len(outside)} 行映射到了非代码行")
        files.append({
            "file": file,
            "total": len(relevant),
            "covered": len(covered),
            "ratio": ratio,
            "uncovered": _ranges(uncovered),
            "overlaps": overlaps,
            "outside": _ranges(outside),
        })

    undeclared = sorted(set(per_file) - set(manifest["files"]))
    for file in undeclared:
        errors.append(f"code_mapping 使用了未声明文件：{file}")

    return {
        "ok": not errors,
        "project": {
            "name": manifest["name"],
            "description": manifest["description"],
            "root": manifest["root"],
            "files": manifest["files"],
        },
        "views": views,
        "files": files,
        "errors": errors,
        "warnings": warnings,
    }
