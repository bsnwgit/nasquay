"""
Reads this app's VERSION file — see scripts/bump_version.py for the
Major.Minor.Patch.CodeName[.Hotfix] format and bump rule.
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings


def get_version() -> str:
    candidates = (
        Path(get_settings().install_dir) / "VERSION",
        Path(__file__).resolve().parent.parent / "VERSION",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text().strip()
    return "0.0.0.unknown"
