"""Combined workspace checks: coverage, narrative and contract.

``mapping_report`` answers "is every line explained"; ``narrative`` answers
"can a reader follow the story"; ``contract`` answers "are the static
contracts internally consistent". The CLI, MCP server and validator all
consume this single combined report so the three checks cannot drift.
"""
from __future__ import annotations

from pathlib import Path

from . import block_config, contract, mapping_report, narrative


def report(path=None, *, strict: bool = False, draft: bool = False) -> dict:
    """Check a workspace; drafts may contain disconnected, unfinished views.

    Draft mode only downgrades narrative errors. Broken mappings, references
    and contracts remain errors. Final CLI/MCP checks use draft=False.
    """
    target = (Path(path).expanduser() if path is not None
              else block_config.DEFAULT_PROJECT)
    mapping = mapping_report.report(path)
    if target.is_dir():
        narrative_data = narrative.report(target)
        contract_data = contract.report(target)
    else:
        narrative_data = {"ok": True, "skipped": True, "errors": [],
                          "warnings": [], "coherence": None, "views": []}
        contract_data = {"ok": True, "errors": [], "warnings": [], "views": [],
                         "types": [], "endpoints": []}
    errors = mapping["errors"] + contract_data["errors"]
    warnings = (mapping["warnings"] + narrative_data["warnings"]
                + contract_data["warnings"])
    if draft:
        warnings += narrative_data["errors"]
    else:
        errors += narrative_data["errors"]
    ok = not errors and not (strict and warnings)
    return {
        **mapping,
        "ok": ok,
        "strict": strict,
        "draft": draft,
        "errors": errors,
        "warnings": warnings,
        "mapping": mapping,
        "narrative": narrative_data,
        "contract": contract_data,
    }
