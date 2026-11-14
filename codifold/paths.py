"""Locations for read-only application resources and per-user state."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT.parent
_BUNDLED = PACKAGE_ROOT / "_resources"
RESOURCE_ROOT = _BUNDLED if _BUNDLED.is_dir() else SOURCE_ROOT


def state_dir() -> Path:
    override = os.environ.get("CODIFOLD_STATE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "Codifold"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Codifold"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "codifold"
