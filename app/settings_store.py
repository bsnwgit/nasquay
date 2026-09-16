"""
Runtime settings stored in SQLite. Defaults live here, so a key missing from the table
means its default, and every value is validated before it is written.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

import aiosqlite

Validator = Callable[[Any], Any]


def _choice(*options: str) -> Validator:
    def check(value: Any) -> Any:
        if value not in options:
            raise ValueError(f"must be one of: {', '.join(options)}")
        return value
    return check


def _int_between(low: int, high: int) -> Validator:
    def check(value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"must be a whole number from {low} to {high}")
        return value
    return check


# key → (default, validator)
SCHEMA: dict[str, tuple[Any, Validator]] = {
    # Whether the dashboard needs a sign-in. The settings pages always do.
    "dashboard_access":     ("login", _choice("login", "open")),
    "audit_retention_days": (365,     _int_between(7, 3650)),

    # Monitoring thresholds. Defaults are the design's proposals and are meant to be tuned
    # once there are real readings to tune against — every one of them is a judgement about
    # how much movement is normal on this particular hardware.
    #
    # A drop in used space of this many percent, within the window below, is a flag.
    "rule_volume_drop_pct":   (5,   _int_between(1, 100)),
    "rule_volume_drop_hours": (1,   _int_between(1, 168)),
    # A share losing this share of its files, or this many outright, is a flag. Both apply:
    # whichever triggers first.
    "rule_file_drop_pct":     (2,   _int_between(1, 100)),
    "rule_file_drop_count":   (100, _int_between(1, 10_000_000)),
    # How far two measurements of the same thing may differ before that itself is a flag.
    # Not zero: `df` and the NAS's API are taken moments apart on a busy volume.
    "rule_divergence_pct":    (2,   _int_between(1, 50)),
}


class SettingsError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("invalid settings")
        self.errors = errors


def validate(updates: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in SCHEMA:
            errors[key] = "unknown setting"
            continue
        try:
            clean[key] = SCHEMA[key][1](value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise SettingsError(errors)
    return clean


async def get_all(db: aiosqlite.Connection) -> dict[str, Any]:
    values = {key: default for key, (default, _) in SCHEMA.items()}
    async with db.execute("SELECT key, value FROM settings") as cur:
        for row in await cur.fetchall():
            if row["key"] not in SCHEMA:
                continue
            try:
                values[row["key"]] = json.loads(row["value"])
            except ValueError:
                pass  # an undecodable row falls back to the default
    return values


async def set_many(db: aiosqlite.Connection, updates: dict[str, Any], user_id: Optional[int]) -> None:
    """Write already-validated settings."""
    for key, value in updates.items():
        await db.execute(
            """INSERT INTO settings (key, value, updated_at, updated_by)
               VALUES (?, ?, datetime('now'), ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at,
                   updated_by = excluded.updated_by""",
            (key, json.dumps(value), user_id),
        )
    await db.commit()
