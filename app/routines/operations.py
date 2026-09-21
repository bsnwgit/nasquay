"""
What a routine may call, and the one function that calls it.

Three families:

  **Recorded data** — the same five reads the assistant has, answered from what NASQuay
  already holds. Nothing here contacts a NAS.

  **NAS tools** — every reviewed QNAP tool, through app/actions/runner.py, exactly as the
  pages run them.

  **Send a notification** — on the channels set up under Settings → Notifications.

Every call passes the gate as the routine's run-as user and is audited, allowed or not. A
destructive operation is refused here unless the routine was explicitly allowed them —
checked again at run time, not only when the routine was saved, because a tool can be
reclassified after.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import aiosqlite
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app import notify
from app.actions import audit, gate, runner
from app.actions.context import Caller
from app.actions.registry import DESTRUCTIVE, READ, WRITE
from app.api import resonance_data as data
from app.dependencies import ActionCall

# What one call may hand back to a model. A listing of a large share is far longer, and
# a model given all of it answers worse, not better.
MAX_RESULT_CHARS = 4000

NOTIFY = "notify"


@dataclass
class Operation:
    id: str
    action_id: str
    classification: str
    description: str
    parameters: dict[str, Any]
    needs_nas: bool = False
    nas_names: list[str] = field(default_factory=list)

    @property
    def tool_name(self) -> str:
        # Model tool names allow letters, digits, _ and - only.
        return self.id.replace(".", "__")


def _object(properties: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


_NAS = {"type": "string", "description": "The NAS's name exactly as listNasUnits gives it"}

# ── Recorded data ─────────────────────────────────────────────────────────────

Handler = Callable[[aiosqlite.Connection, ActionCall, dict[str, Any]], Awaitable[Any]]


def _int(args: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(args.get(key, default))))
    except (TypeError, ValueError):
        return default


DATA: dict[str, tuple[str, str, dict[str, Any], Handler]] = {
    "listNasUnits": (
        "nas.list",
        "List this installation's NAS units by name, and how each answered when last checked.",
        _object({}),
        lambda db, call, a: data.list_nas_units(
            db=db, call=call, limit=_int(a, "limit", data.DEFAULT_LIMIT, 1, data.MAX_LIMIT)),
    ),
    "listMeasurements": (
        "monitoring.read",
        "The shares, volumes and pools on each NAS, with their latest used space, free "
        "space and file counts. kind=share lists a NAS's shares.",
        _object({
            "nas": _NAS,
            "kind": {"type": "string", "enum": ["pool", "volume", "share", "client_mount"]},
            "metric": {"type": "string", "description": "e.g. used_bytes, free_bytes, file_count"},
        }),
        lambda db, call, a: data.list_measurements(
            db=db, call=call, nas=str(a.get("nas") or ""), kind=str(a.get("kind") or ""),
            metric=str(a.get("metric") or ""),
            limit=_int(a, "limit", data.DEFAULT_LIMIT, 1, data.MAX_LIMIT)),
    ),
    "listFlags": (
        "monitoring.read",
        "Conditions NASQuay has flagged: a rule that fired, with what it saw and when.",
        _object({
            "state": {"type": "string", "enum": ["open", "cleared", "all"]},
            "severity": {"type": "string", "enum": ["info", "warning", "error"]},
        }),
        lambda db, call, a: data.list_flags(
            db=db, call=call, state=str(a.get("state") or "open"),
            severity=str(a.get("severity") or ""),
            limit=_int(a, "limit", data.DEFAULT_LIMIT, 1, data.MAX_LIMIT)),
    ),
    "readHistory": (
        "monitoring.read",
        "One measurement over time, with the first and last points of the range.",
        _object({
            "nas": _NAS,
            "label": {"type": "string", "description": "The share, volume or pool, as listMeasurements names it"},
            "metric": {"type": "string", "description": "e.g. used_bytes, file_count"},
            "days": {"type": "integer", "description": "How far back to look"},
        }, ["nas", "label", "metric"]),
        lambda db, call, a: data.read_history(
            db=db, call=call, nas=str(a.get("nas") or ""), label=str(a.get("label") or ""),
            metric=str(a.get("metric") or ""), days=_int(a, "days", 30, 1, 3650),
            limit=_int(a, "limit", data.DEFAULT_LIMIT, 1, data.MAX_LIMIT)),
    ),
    "getCollectionStatus": (
        "monitoring.read",
        "Whether the recorded figures are current, and how many flags are open.",
        _object({}),
        lambda db, call, a: data.collection_status(db=db, call=call),
    ),
}


async def catalogue(db: aiosqlite.Connection) -> list[Operation]:
    """Everything a routine could be given, before any role or routine narrows it."""
    ops = [
        Operation(id=op_id, action_id=action_id, classification=READ, description=desc,
                  parameters=schema)
        for op_id, (action_id, desc, schema, _handler) in DATA.items()
    ]
    ops.append(Operation(
        id=NOTIFY, action_id="notifications.send", classification=WRITE,
        description="Send a notification on the channels set up in NASQuay.",
        parameters=_object({
            "title": {"type": "string"},
            "body": {"type": "string"},
            "severity": {"type": "string", "enum": ["info", "warning", "error"]},
        }, ["title", "body"]),
    ))

    # Reviewed NAS tools only: an unreviewed one can be run by nobody, so offering it
    # would only produce refusals.
    async with db.execute(
        """SELECT a.id, a.classification, a.description,
                  GROUP_CONCAT(n.name, '\x1f') AS nas_names,
                  MAX(t.input_schema) AS input_schema,
                  MAX(t.tool_description) AS tool_description
           FROM actions a
           JOIN nas_tools t ON t.action_id = a.id AND t.available = 1
           JOIN nas n ON n.id = t.nas_id
           WHERE a.source = 'qnap_mcp' AND a.reviewed = 1
           GROUP BY a.id ORDER BY a.id"""
    ) as cur:
        rows = await cur.fetchall()
    for row in rows:
        names = sorted(set((row["nas_names"] or "").split("\x1f")) - {""})
        try:
            schema = json.loads(row["input_schema"] or "{}")
        except ValueError:
            schema = {}
        properties = dict(schema.get("properties") or {}) if isinstance(schema, dict) else {}
        required = list(schema.get("required") or []) if isinstance(schema, dict) else []
        properties["nas"] = {**_NAS, "enum": names}
        ops.append(Operation(
            id=row["id"], action_id=row["id"], classification=row["classification"],
            description=(row["tool_description"] or row["description"] or row["id"])[:1000],
            parameters=_object(properties, ["nas", *[r for r in required if r != "nas"]]),
            needs_nas=True, nas_names=names,
        ))
    return ops


def _clip(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + f"\n[cut: {len(text) - MAX_RESULT_CHARS} more characters]"


async def call(
    db: aiosqlite.Connection, caller: Caller, op: Operation, nas: str,
    arguments: dict[str, Any], allow_destructive: bool,
) -> tuple[bool, str]:
    """Run one operation as the routine's caller. Returns (ok, what came back) — a
    refusal or failure is text for the model or the run record, never an exception."""
    params = {"op": op.id, "nas": nas, "arguments": arguments}

    if op.classification == DESTRUCTIVE and not allow_destructive:
        await audit.record(db, caller, op.action_id, "denied",
                           reason="destructive action from a routine not allowed them",
                           params=params)
        return False, f"refused: {op.id} is destructive and this routine may not run destructive actions"

    if op.needs_nas:
        async with db.execute("SELECT id FROM nas WHERE name = ? COLLATE NOCASE", (nas,)) as cur:
            row = await cur.fetchone()
        if row is None:
            known = ", ".join(op.nas_names) or "none"
            return False, f"refused: no NAS is called {nas!r}. NAS units offering {op.id}: {known}"
        tool = op.id.removeprefix("qnap.")
        try:
            result = await runner.run_tool(db, caller, row["id"], tool, arguments,
                                           confirm=allow_destructive)
        except runner.Refused as exc:
            return False, f"{'refused' if exc.status in (403, 409) else 'failed'}: {exc.message}"
        return True, _clip(result.text)

    decision = await gate.check(db, caller, op.action_id)
    if not decision.allowed:
        await audit.record(db, caller, op.action_id, "denied", reason=decision.reason,
                           params=params)
        return False, f"refused: {decision.reason}"
    action = ActionCall(db, caller, op.action_id, decision.reason)

    if op.id == NOTIFY:
        async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
            settings = await cur.fetchone()
        message = notify.Message(
            title=str(arguments.get("title") or "routine")[:200],
            body=str(arguments.get("body") or "")[:4000],
            severity=str(arguments.get("severity") or "info")
            if arguments.get("severity") in ("info", "warning", "error") else "info",
        )
        ok, said = await run_in_threadpool(notify.deliver, dict(settings or {}), message)
        if ok:
            await action.done(params=params, detail=said[:200])
        else:
            await action.failed(said[:200], params=params)
        return ok, said

    _action_id, _desc, _schema, handler = DATA[op.id]
    try:
        # The handler is the assistant's own route function, which records done() itself.
        answer = await handler(db, action, arguments)
    except HTTPException as exc:
        await action.failed(str(exc.detail), params=params)
        return False, f"failed: {exc.detail}"
    return True, _clip(answer.model_dump_json())
