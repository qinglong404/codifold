"""Conversion workbench: focused briefs and compact draft application.

Examples:
    python3 -m codifold.workbench brief examples/gradebook-chain --view main
    python3 -m codifold.workbench apply examples/gradebook-chain draft.json --dry-run
    python3 -m codifold.workbench apply examples/gradebook-chain bundle.json
    python3 -m codifold.workbench check examples/gradebook-chain --strict
    python3 -m codifold.workbench export-md examples/gradebook-chain --out flow.md
    python3 -m codifold.workbench mcp
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, draft, editor, export_md, flat, narrative, project_config, validate
from .brief import collect_brief

KIND_LABELS = {
    "main": "主线",
    "flow": "流程",
    "entry": "事件入口",
    "contract": "契约",
    "function": "函数细节",
    "struct": "模块声明",
    "toolbox": "工具",
}


def _range_text(item: dict) -> str:
    if item["start"] == item["end"]:
        return f"L{item['start']}"
    return f"L{item['start']}-L{item['end']}"


def _mapping_text(block: dict) -> str:
    mapping = block.get("code_mapping")
    if not mapping:
        return "-"
    lines = ",".join(str(item) for item in mapping["lines"])
    return f"{mapping['file']}:{lines}"


def _ref_text(block: dict) -> list[str]:
    extra = []
    if "next" in block:
        extra.append("next=end" if block["next"] is None
                     else f"next={block['next']}")
    if block.get("jump"):
        jump = block["jump"]
        prefix = f"{jump['view']}:" if jump.get("view") else ""
        extra.append(f"jump={prefix}{jump['id']}")
    if block.get("emit"):
        refs = []
        for ref in block["emit"]:
            prefix = f"{ref['view']}:" if ref.get("view") else ""
            refs.append(f"{prefix}{ref['id']}")
        extra.append("emit=" + ",".join(refs))
    if block.get("on"):
        extra.append(f"on={block['on']}")
    return extra


def _print_blocks(blocks: list[dict], indent: int = 1) -> None:
    pad = "  " * indent
    for block in blocks:
        extra = " ".join(_ref_text(block))
        print(f"{pad}#{block['id']} {block['type']} {block['name']} "
              f"{_mapping_text(block)} {extra}".rstrip())
        for branch in block.get("branches", []):
            label = branch.get("condition") or branch.get("role") or "分支"
            print(f"{pad}  [{label}]")
            _print_blocks(branch["steps"], indent + 2)
        if block.get("finally"):
            print(f"{pad}  [finally]")
            _print_blocks(block["finally"], indent + 2)


def _print_view_groups(views: list[dict]) -> None:
    groups: dict[str, list[dict]] = {}
    for view in views:
        groups.setdefault(view.get("kind") or "flow", []).append(view)
    order = ["main", "flow", "entry", "contract", "function", "struct", "toolbox"]
    summary = " · ".join(
        f"{KIND_LABELS[kind]} {len(groups[kind])}"
        for kind in order if groups.get(kind)
    )
    print(f"视图（{len(views)}）：{summary}")
    for kind in order:
        items = groups.get(kind)
        if not items:
            continue
        limit = 12 if kind in {"main", "flow", "entry"} else 8
        shown = items[:limit]
        more = f" … 还有 {len(items) - limit}" if len(items) > limit else ""
        names = "、".join(item["view_id"] for item in shown)
        print(f"  {KIND_LABELS[kind]}（{len(items)}）：{names}{more}")


def _print_coherence(coherence: dict) -> None:
    score = coherence.get("score", 0.0)
    state = "达标" if score == 1.0 else "未达标"
    print(f"连贯性：{coherence.get('reachable', 0)}/{coherence.get('total', 0)} "
          f"= {score:.4f}（{state}）")
    if coherence.get("orphans"):
        names = "、".join(coherence["orphans"][:12])
        more = " …" if len(coherence["orphans"]) > 12 else ""
        print(f"  未到达：{names}{more}")


def print_brief(data: dict) -> None:
    print("Codifold 转换简报")
    print(f"工作区：{data['workspace']}")
    project = data["project"]
    print(f"项目：{project['name']}（入口 {data['entry']}）")
    print(f"视图格式：{data.get('schema') or 'nested'}")
    print("文件：")
    for item in data["files"]:
        print(f"  {item['file']}  {item['covered']}/{item['total']} "
              f"{item['ratio'] * 100:.1f}%")
        if item["uncovered"]:
            shown = "、".join(_range_text(rng) for rng in item["uncovered"][:10])
            more = " …" if len(item["uncovered"]) > 10 else ""
            print(f"    未覆盖：{shown}{more}")
        for overlap in item["overlaps"][:5]:
            blocks = ", ".join(str(ident) for ident in overlap["blocks"])
            print(f"    重复：{_range_text(overlap)}（块 {blocks}）")
        if len(item["overlaps"]) > 5:
            print(f"    … 另有 {len(item['overlaps']) - 5} 段重复")
        if item["outside"]:
            shown = "、".join(_range_text(rng) for rng in item["outside"][:5])
            print(f"    映射到非代码行：{shown}")
    _print_view_groups(data["views"])
    view = data["view"]
    kind = KIND_LABELS.get(view.get("kind") or "flow", view.get("kind") or "")
    print(f"当前视图：{view['view_id']}（{view['name']} · {kind}）")
    if view["error"]:
        print(f"  读取失败：{view['error']}")
    elif view["config"]:
        print(f"  下一个可用 id：{view['next_id']}")
        _print_blocks(view["config"]["blocks"])
    if data.get("snippets"):
        print("未覆盖源码（最多 200 行）：")
        for item in data["snippets"]["lines"]:
            print(f"  {item['file']}:{item['line']}  {item['text']}")
        if data["snippets"]["truncated"]:
            print("  … 已截断")
    contract_data = data.get("contract") or {}
    if contract_data.get("views"):
        print(f"契约：{len(contract_data.get('types') or [])} 个类型、"
              f"{len(contract_data.get('endpoints') or [])} 个接口")
    if data["errors"]:
        print("错误：")
        for error in data["errors"]:
            print(f"  - {error}")
    if data["warnings"]:
        print("警告：")
        for warning in data["warnings"]:
            print(f"  - {warning}")
    narrative_data = data.get("narrative") or {}
    coherence = narrative_data.get("coherence")
    if coherence:
        _print_coherence(coherence)
    if not narrative_data.get("skipped"):
        if narrative_data.get("errors"):
            print("叙事错误：")
            for error in narrative_data["errors"]:
                if not error.startswith("连贯性 "):
                    print(f"  - {error}")
        if narrative_data.get("warnings"):
            print("叙事警告：")
            for warning in narrative_data["warnings"]:
                print(f"  - {warning}")


def load_drafts(path: str) -> list[dict]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).expanduser().read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"草稿不是合法 JSON：{error}") from error
    return draft.normalize_drafts(data)


def _print_file_coverage(files: list[dict]) -> None:
    for item in files:
        print(f"  {item['file']}  {item['covered']}/{item['total']} "
              f"{item['ratio'] * 100:.1f}%")


def cmd_brief(args: argparse.Namespace) -> int:
    data = collect_brief(args.workspace, args.view, args.snippets)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_brief(data)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    specs = load_drafts(args.draft)
    configs = draft.compile_drafts(args.workspace, specs)
    if args.dry_run:
        manifest = project_config.load_manifest(Path(args.workspace).expanduser())
        if manifest is not None and manifest.get("format") == "flat":
            configs = [flat.from_nested(config) for config in configs]
        payload = configs[0] if len(configs) == 1 else {"views": configs}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    result = editor.save_views(args.workspace, configs, strict=args.strict)
    summary = {
        "created": result["created"],
        "updated": result["updated"],
        "warnings": result["warnings"],
        "files": result["report"]["files"],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        labels = []
        if summary["created"]:
            labels.append("新建 " + "、".join(summary["created"]))
        if summary["updated"]:
            labels.append("更新 " + "、".join(summary["updated"]))
        print("已写入视图：" + "；".join(labels))
        print("覆盖率：")
        _print_file_coverage(summary["files"])
        if summary["warnings"]:
            print("警告：")
            for warning in summary["warnings"]:
                print(f"  - {warning}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    data = checks.report(args.workspace, strict=args.strict)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        validate._print_human(data)
    return 0 if data["ok"] else 1


def cmd_coherence(args: argparse.Namespace) -> int:
    data = narrative.report(args.workspace)
    coherence = data.get("coherence") or {
        "score": 0.0, "reachable": 0, "total": 0,
        "root": "", "depths": {}, "orphans": [],
    }
    if args.json:
        print(json.dumps(coherence, ensure_ascii=False, indent=2))
    else:
        _print_coherence(coherence)
        print(f"主线：{coherence.get('root')}")
        depths = coherence.get("depths") or {}
        if depths:
            print("视图深度：")
            for view_id in sorted(depths, key=lambda item: (depths[item], item)):
                print(f"  {depths[view_id]}  {view_id}")
    return 0 if coherence.get("score") == 1.0 else 1


def cmd_export_md(args: argparse.Namespace) -> int:
    text, summary = export_md.build(
        args.workspace, views=args.view, kinds=args.kind,
        with_code=args.with_code, max_code_lines=args.max_code_lines,
    )
    target = export_md.write(text, args.out)
    location = f" 到 {target}" if target else ""
    print(f"已导出 {summary['views']} 个视图、{summary['blocks']} 个块{location}",
          file=sys.stderr)
    if summary["errors"]:
        print(f"有 {len(summary['errors'])} 个错误，详见文档附录 A", file=sys.stderr)
        return 1
    return 0


def cmd_mcp(_args: argparse.Namespace) -> int:
    from .mcp_server import serve
    return serve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codifold.workbench",
        description="Codifold 转换工作台：生成简报、编译局部草稿、批量写入并校验。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    brief = sub.add_parser("brief", help="输出当前转换简报")
    brief.add_argument("workspace")
    brief.add_argument("--view", help="查看哪个视图的块结构（默认入口视图）")
    brief.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    brief.add_argument("--snippets", action="store_true",
                       help="附带未覆盖源码行（最多 200 行）")

    apply = sub.add_parser("apply", help="编译并写入一份或多份视图草稿")
    apply.add_argument("workspace")
    apply.add_argument("draft", help="草稿 JSON 文件；- 表示从 stdin 读取")
    apply.add_argument("--dry-run", action="store_true",
                       help="只输出编译后的最终 JSON，不写文件")
    apply.add_argument("--json", action="store_true", help="输出写入结果 JSON")
    apply.add_argument("--strict", action="store_true",
                       help="有覆盖/可达性警告时回滚并失败")

    check = sub.add_parser("check", help="检查结构、覆盖率、叙事和连贯性")
    check.add_argument("workspace")
    check.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    check.add_argument("--strict", action="store_true", help="有警告也返回失败")

    coherence = sub.add_parser("coherence", help="检查从主线能否到达所有视图")
    coherence.add_argument("workspace")
    coherence.add_argument("--json", action="store_true", help="输出机器可读 JSON")

    export = sub.add_parser("export-md", help="导出供 AI 审核的 Markdown 文字稿")
    export.add_argument("workspace")
    export.add_argument("--out", help="写入文件；省略或写 - 表示输出到 stdout")
    export.add_argument("--view", action="append", default=[],
                        help="只导出指定视图，可重复")
    export.add_argument("--kind", action="append", default=[],
                        choices=export_md.KIND_ORDER,
                        help="只导出指定角色，可重复")
    export.add_argument("--with-code", action="store_true",
                        help="文末附加代码证据附录")
    export.add_argument("--max-code-lines", type=int, default=20,
                        help="每个块最多列出多少行代码（默认 20）")

    sub.add_parser("mcp", help="启动 MCP 服务器（stdio，供 AI 客户端调用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "mcp":
            return cmd_mcp(args)
        if args.command == "brief":
            return cmd_brief(args)
        if args.command == "apply":
            return cmd_apply(args)
        if args.command == "coherence":
            return cmd_coherence(args)
        if args.command == "export-md":
            return cmd_export_md(args)
        return cmd_check(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
