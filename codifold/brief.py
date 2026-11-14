"""Workspace brief: coverage, view index and one view's block structure.

Shared by ``workbench brief`` and the MCP server. The brief is read-only:
it never writes workspace JSON and never reads source files except for the
optional uncovered-line snippets.
"""
from __future__ import annotations

from pathlib import Path

from . import block_config, contract, draft, mapping_report, narrative, project_config


def _snippets(report: dict, manifest: dict, limit: int = 200) -> dict:
    rows: list[dict] = []
    truncated = False
    for item in report["files"]:
        source = manifest["paths"].get(item["file"])
        if source is None:
            continue
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for code_range in item["uncovered"]:
            for number in range(code_range["start"], code_range["end"] + 1):
                if len(rows) >= limit:
                    truncated = True
                    break
                text = lines[number - 1] if number <= len(lines) else ""
                rows.append({"file": item["file"], "line": number, "text": text})
            if truncated:
                break
        if truncated:
            break
    return {"lines": rows, "truncated": truncated}


def collect_brief(workspace: str, view_id: str | None = None,
                  snippets: bool = False) -> dict:
    directory = Path(workspace).expanduser()
    if not directory.exists():
        raise FileNotFoundError(f"找不到工作区：{directory}")
    directory = directory.resolve()
    report = mapping_report.report(str(directory))
    index = block_config.load_index(str(directory))
    chosen = view_id or index["entry"]
    view_entry = next((item for item in index["views"]
                       if item["view_id"] == chosen), None)
    if view_entry is None:
        available = "、".join(item["view_id"] for item in index["views"])
        raise ValueError(f"找不到视图：{chosen}（可用：{available}）")
    config = None
    schema = None
    view_error = None
    try:
        payload = block_config.load(str(directory), chosen)
        config = payload["config"]
        schema = payload.get("schema")
    except (OSError, ValueError) as error:
        view_error = str(error)
    data = {
        "workspace": str(directory),
        "schema": schema,
        "project": report["project"],
        "entry": index["entry"],
        "views": index["views"],
        "view": {
            "view_id": view_entry["view_id"],
            "name": view_entry["name"],
            "description": view_entry["description"],
            "kind": view_entry.get("kind"),
            "config": config,
            "error": view_error,
            "next_id": (max((block["id"] for block in draft.iter_blocks(
                config["blocks"])), default=0) + 1) if config else 1,
        },
        "files": report["files"],
        "errors": report["errors"],
        "warnings": report["warnings"],
    }
    narrative_data = narrative.report(directory)
    data["narrative"] = narrative_data
    contract_data = contract.report(directory)
    data["contract"] = contract_data
    data["errors"].extend(contract_data["errors"])
    data["warnings"].extend(contract_data["warnings"])
    if snippets:
        manifest = project_config.load_manifest(directory)
        if manifest is not None:
            data["snippets"] = _snippets(report, manifest)
    return data
