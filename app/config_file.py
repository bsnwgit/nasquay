"""
The startup config file: where it is, what it currently says, and how the app rewrites
the handful of settings that must be known before the database opens.

Only the listen address and port are ever written from the app. Lines are rewritten in
place rather than dumped from a parsed document, so an operator's comments and layout
survive the edit.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from app.config import config_candidates

WRITABLE = ("host", "port")


def config_path() -> Optional[Path]:
    """The config.yaml the app actually loaded, or None if it is running on defaults."""
    for path in config_candidates():
        if path.is_file():
            return path
    return None


def current() -> dict[str, Any]:
    """What the file says now — which is not what the process is running until it restarts."""
    path = config_path()
    if path is None:
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def update(values: dict[str, Any]) -> Path:
    path = config_path()
    if path is None:
        raise RuntimeError("No config.yaml was loaded, so there is nothing to write")
    for key in values:
        if key not in WRITABLE:
            raise ValueError(f"{key} is not written from the app")

    lines = path.read_text().splitlines()
    for key, value in values.items():
        rendered = f'{key}: "{value}"' if isinstance(value, str) else f"{key}: {value}"
        for index, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            if line.split(":", 1)[0].strip() == key:
                lines[index] = rendered
                break
        else:
            lines.append(rendered)
    path.write_text("\n".join(lines) + "\n")
    return path
