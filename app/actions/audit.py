"""
The audit log writer. Every action attempt is recorded — allowed or denied, and how it
ended — with secrets stripped from its parameters.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import aiosqlite

from app.actions.context import Caller

_SECRET_NAME = re.compile(r"pass|secret|token|key|credential", re.I)
_MAX_PARAMS = 4000
_MAX_TEXT = 2000


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: "[redacted]" if _SECRET_NAME.search(str(k)) else _scrub(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def redact(params: Optional[dict[str, Any]]) -> str:
    """Parameters as JSON with secret-looking fields replaced, bounded in size."""
    if not params:
        return "{}"
    text = json.dumps(_scrub(params), default=str)
    if len(text) > _MAX_PARAMS:
        text = json.dumps({"_truncated": text[:_MAX_PARAMS]})
    return text


async def record(
    db: aiosqlite.Connection,
    caller: Caller,
    action_id: str,
    decision: str,
    *,
    reason: str = "",
    outcome: Optional[str] = None,
    target: str = "",
    params: Optional[dict[str, Any]] = None,
    detail: str = "",
    duration_ms: Optional[int] = None,
    nas_id: Optional[int] = None,
) -> None:
    """Write one audit record and commit it.

    Call after the action's own changes are committed: this commit would otherwise
    commit them as a side effect. A failure to write propagates — an action that
    cannot be audited should not appear to have succeeded.
    """
    await db.execute(
        """INSERT INTO audit (actor_kind, actor_id, actor_name, via, action_id, nas_id, target,
                              params, decision, reason, outcome, detail, duration_ms, client_ip)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            caller.kind, caller.user_id, caller.username[:128], caller.via, action_id, nas_id,
            target[:512], redact(params), decision, reason[:512], outcome, detail[:_MAX_TEXT],
            duration_ms, caller.client_ip[:64],
        ),
    )
    await db.commit()
