"""Command line validation for a Codifold project.

Usage:
    python3 -m codifold.validate [项目目录] [--json] [--strict]
"""
from __future__ import annotations

import argparse
import json
import sys

from . import checks


def _range_text(item: dict) -> str:
    if item["start"] == item["end"]:
        return f"L{item['start']}"
    return f"L{item['start']}-L{item['end']}"


def _print_human(data: dict) -> None:
    mapping = data.get("mapping") or data
    project = mapping["project"]
    print("Codifold 校验")
    print(f"项目：{project['name']}")
    print(f"根目录：{project['root']}")
    passed = sum(1 for view in mapping["views"] if view["ok"])
    print(f"视图：{len(mapping['views'])} 个，通过 {passed} 个")
    for view in mapping["views"]:
        if not view["ok"]:
            print(f"  ✗ {view['view_id']}（{view['name']}）：{view['error']}")
    print("文件：")
    for item in mapping["files"]:
        print(f"  {item['file']}  {item['ratio'] * 100:.1f}% "
              f"({item['covered']}/{item['total']})")
        if item["uncovered"]:
            shown = "、".join(_range_text(rng) for rng in item["uncovered"][:8])
            more = " …" if len(item["uncovered"]) > 8 else ""
            print(f"    未覆盖：{shown}{more}")
        for overlap in item["overlaps"][:5]:
            blocks = ", ".join(str(block) for block in overlap["blocks"])
            print(f"    重复：{_range_text(overlap)}（块 {blocks}）")
        if len(item["overlaps"]) > 5:
            print(f"    … 另有 {len(item['overlaps']) - 5} 段重复")
        if item["outside"]:
            shown = "、".join(_range_text(rng) for rng in item["outside"][:5])
            print(f"    映射到非代码行：{shown}")
    print(f"错误：{len(mapping['errors'])}")
    for error in mapping["errors"]:
        print(f"  - {error}")
    print(f"警告：{len(mapping['warnings'])}")
    for warning in mapping["warnings"]:
        print(f"  - {warning}")

    narrative_data = data.get("narrative") or {}
    coherence = narrative_data.get("coherence")
    if coherence:
        state = "达标" if coherence["score"] == 1.0 else "未达标"
        print(f"连贯性：{coherence['reachable']}/{coherence['total']} "
              f"= {coherence['score']:.4f}（{state}）")
        if coherence.get("orphans"):
            print("  未到达：" + "、".join(coherence["orphans"][:12]))
    if narrative_data:
        if narrative_data.get("skipped"):
            print("叙事检查：跳过（未声明 view.kind 或 flow）")
        else:
            print(f"叙事检查：主线 {narrative_data.get('main')}")
            for error in narrative_data.get("errors", []):
                if not error.startswith("连贯性 "):
                    print(f"  ✗ {error}")
            for warning in narrative_data.get("warnings", []):
                print(f"  - {warning}")
            if (not narrative_data.get("errors")
                    and not narrative_data.get("warnings")):
                print("  无问题")

    contract_data = data.get("contract") or {}
    if (contract_data.get("views") or contract_data.get("errors")
            or contract_data.get("warnings")):
        types = contract_data.get("types") or []
        endpoints = contract_data.get("endpoints") or []
        print(f"契约检查：{len(types)} 个类型、{len(endpoints)} 个接口")
        for error in contract_data.get("errors", []):
            print(f"  ✗ {error}")
        for warning in contract_data.get("warnings", []):
            print(f"  - {warning}")
        if (not contract_data.get("errors")
                and not contract_data.get("warnings")):
            print("  无问题")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="检测 Codifold 项目的结构、覆盖率与连贯性")
    parser.add_argument("path", nargs="?", help="项目目录（省略时使用内置示例）")
    parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    parser.add_argument("--strict", action="store_true", help="有警告也返回失败")
    args = parser.parse_args(argv)
    try:
        data = checks.report(args.path, strict=args.strict)
    except (OSError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_human(data)
    return 0 if data["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
