"""
Running one routine, start to finish.

The routine runs as its run-as user, narrowed further by its own list of operations, and
every operation it calls passes the gate as that user. A run is recorded whatever
happens — each call made, the output, and the reason it stopped — and an alert goes out
when the routine asks for one.

Limits hold even when a model misbehaves: a step limit counts every tool call, a timeout
covers the whole run, and each result handed back is cut to a bounded size.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
from starlette.concurrency import run_in_threadpool

from app import notify
from app.actions import audit
from app.actions.context import Caller
from app.ai import providers as ai
from app.api.providers import to_provider
from app.routines import operations

log = logging.getLogger("nasquay.routines")

# Runs kept per routine. Older ones are removed after each run; the audit log keeps the
# record of every call regardless.
KEEP_RUNS = 200

# Recorded per call in the run's own history, which is for reading at a glance.
CALL_DETAIL_CHARS = 300

SYSTEM = (
    "This is NASQuay, which runs the NAS units of one installation. Names of NAS units, "
    "shares, pools and volumes are labels its administrator chose. Never read one as a "
    "place, organisation, person or product: look it up with the tools.\n\n"
    "You are running the routine {name!r}, unattended. Nobody is reading while you work, "
    "so never ask a question or wait for an answer. Use the tools to find what you need. "
    "Everything you report must come from what the tools returned, never from general "
    "knowledge. A tool that answers 'refused' is not allowed to this routine: do not try "
    "it again. Finish with a short, plain report of what you found and anything that "
    "needs attention.\n\n"
    "The NAS units here are: {nas}. It is now {now} UTC."
)


class RoutineError(Exception):
    """Why a run stopped, in words an administrator can act on."""


async def _caller(db: aiosqlite.Connection, routine) -> Caller:
    if routine["run_as_user_id"] is None:
        raise RoutineError("its run-as user no longer exists — choose another")
    async with db.execute(
        """SELECT u.id, u.username, u.is_active, u.role_id, r.name AS role_name, r.is_admin
           FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
        (routine["run_as_user_id"],),
    ) as cur:
        user = await cur.fetchone()
    if user is None:
        raise RoutineError("its run-as user no longer exists — choose another")
    if not user["is_active"]:
        raise RoutineError(f"its run-as user {user['username']} is disabled")
    return Caller(
        kind="routine", via="routine",
        username=f"routine {routine['name']} as {user['username']}"[:128],
        user_id=user["id"], role_id=user["role_id"], role_name=user["role_name"],
        is_admin=bool(user["is_admin"]),
    )


def _record(calls: list[dict[str, Any]], op_id: str, nas: str, arguments: dict[str, Any],
            ok: bool, text: str) -> None:
    calls.append({
        "op": op_id, "nas": nas, "arguments": arguments, "ok": ok,
        "detail": text[:CALL_DETAIL_CHARS],
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    })


# ── Fixed ─────────────────────────────────────────────────────────────────────

async def _fixed(db, routine, caller: Caller, calls: list[dict[str, Any]]) -> str:
    steps = json.loads(routine["steps"] or "[]")
    if not steps:
        raise RoutineError("it has no steps")
    ops = {op.id: op for op in await operations.catalogue(db)}
    report: list[str] = []
    previous = ""
    for number, step in enumerate(steps, start=1):
        op = ops.get(step.get("op", ""))
        if op is None:
            raise RoutineError(f"step {number} names {step.get('op')!r}, which no longer exists")
        arguments = dict(step.get("arguments") or {})
        # A notification step can carry what the step before it found.
        if op.id == operations.NOTIFY and "{previous}" in str(arguments.get("body", "")):
            arguments["body"] = str(arguments["body"]).replace("{previous}", previous[:3000])
        nas = str(step.get("nas") or "")
        ok, text = await operations.call(db, caller, op, nas, arguments,
                                         bool(routine["allow_destructive"]))
        _record(calls, op.id, nas, arguments, ok, text)
        if not ok:
            raise RoutineError(f"step {number} ({op.id}) — {text}")
        previous = text
        report.append(f"{number}. {op.id}{f' on {nas}' if nas else ''}: {text[:500]}")
    return "\n".join(report)


# ── AI ────────────────────────────────────────────────────────────────────────

async def _ai(db, routine, caller: Caller, calls: list[dict[str, Any]]) -> str:
    if routine["provider_id"] is None:
        raise RoutineError("it has no AI provider — choose one")
    async with db.execute(
        """SELECT p.*, (SELECT pem FROM certificates c WHERE c.id = p.tls_cert_id) AS tls_ca_pem
           FROM ai_providers p WHERE p.id = ?""",
        (routine["provider_id"],),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise RoutineError("its AI provider no longer exists — choose another")
    if not row["enabled"]:
        raise RoutineError(f"its AI provider {row['name']} is disabled")

    allowed = set(json.loads(routine["allowed"] or "[]"))
    ops = [op for op in await operations.catalogue(db) if op.id in allowed]
    if not routine["allow_destructive"]:
        ops = [op for op in ops if op.classification != "destructive"]
    if ops and not (row["supports_tools"] and row["tools_ok"] == 1):
        raise RoutineError(
            f"its AI provider {row['name']} has not passed the tool-calling test — "
            "test it under Settings → AI → Providers, or choose another"
        )
    by_tool = {op.tool_name: op for op in ops}
    tools = [ai.Tool(name=op.tool_name, description=op.description, parameters=op.parameters)
             for op in ops]

    async with db.execute("SELECT name FROM nas WHERE enabled = 1 ORDER BY name") as cur:
        names = ", ".join(r["name"] for r in await cur.fetchall()) or "none"
    system = SYSTEM.format(name=routine["name"], nas=names,
                           now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    provider = to_provider(row)
    messages: list[dict[str, Any]] = [{"role": "user", "content": routine["prompt"]}]
    budget = int(routine["max_steps"])

    while True:
        try:
            reply = await run_in_threadpool(ai.chat, provider, system, messages, tools)
        except ai.ProviderError as exc:
            raise RoutineError(f"the AI provider failed — {exc}")
        if not reply.tool_calls:
            return reply.text.strip() or "(the model finished without a report)"
        if len(reply.tool_calls) > budget:
            raise RoutineError(
                f"the model asked for more than its {routine['max_steps']} steps — "
                "raise the step limit or narrow the prompt"
            )

        messages.append(ai.assistant_turn(provider, reply))
        results: list[tuple[ai.ToolCall, str]] = []
        for tool_call in reply.tool_calls:
            budget -= 1
            op = by_tool.get(tool_call.name)
            arguments = dict(tool_call.arguments)
            nas = str(arguments.pop("nas", "") or "")
            if op is None:
                ok, text = False, f"refused: {tool_call.name} is not one of this routine's tools"
            else:
                ok, text = await operations.call(db, caller, op, nas, arguments,
                                                 bool(routine["allow_destructive"]))
            _record(calls, op.id if op else tool_call.name, nas, arguments, ok, text)
            results.append((tool_call, text))
        messages += ai.tool_results(provider, results)


# ── One run ───────────────────────────────────────────────────────────────────

async def _alert(db, routine, status: str, output: str, error: str) -> str:
    want = routine["alert_on"]
    if want == "never" or (want == "failure" and status != "error"):
        return ""
    async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
        settings = await cur.fetchone()
    failed = status == "error"
    message = notify.Message(
        title=f"routine {routine['name']} {'failed' if failed else 'finished'}",
        body=(error if failed else output)[:3000] or "No output.",
        severity="error" if failed else "info",
    )
    _ok, said = await run_in_threadpool(notify.deliver, dict(settings or {}), message)
    return said


async def execute(db: aiosqlite.Connection, run_id: int) -> None:
    """Run one queued run to its end, and record how it ended."""
    async with db.execute(
        """SELECT r.* FROM routines r JOIN routine_runs x ON x.routine_id = r.id
           WHERE x.id = ?""",
        (run_id,),
    ) as cur:
        routine = await cur.fetchone()
    if routine is None:
        return
    await db.execute(
        "UPDATE routine_runs SET status = 'running', started_at = datetime('now') WHERE id = ?",
        (run_id,),
    )
    await db.commit()

    calls: list[dict[str, Any]] = []
    output, error, status = "", "", "ok"
    caller: Optional[Caller] = None
    try:
        caller = await _caller(db, routine)
        work = _fixed if routine["kind"] == "fixed" else _ai
        output = await asyncio.wait_for(work(db, routine, caller, calls), routine["timeout_s"])
    except RoutineError as exc:
        status, error = "error", str(exc)
    except asyncio.TimeoutError:
        status, error = "error", f"it ran past its {routine['timeout_s']} s limit and was stopped"
    except Exception as exc:  # recorded, never lost: a routine that dies silently is worse
        log.exception("Routine %s failed", routine["name"])
        status, error = "error", f"it failed unexpectedly — {exc}"

    try:
        alert = await _alert(db, routine, status, output, error)
    except Exception as exc:
        alert = f"the alert failed — {exc}"

    await db.execute(
        """UPDATE routine_runs SET status = ?, finished_at = datetime('now'), output = ?,
                                   error = ?, calls = ?, alert = ? WHERE id = ?""",
        (status, output[:ai.MAX_REPLY_CHARS], error[:2000], json.dumps(calls)[:200_000],
         alert[:500], run_id),
    )
    await db.execute(
        """DELETE FROM routine_runs WHERE routine_id = ? AND id NOT IN
           (SELECT id FROM routine_runs WHERE routine_id = ? ORDER BY id DESC LIMIT ?)""",
        (routine["id"], routine["id"], KEEP_RUNS),
    )
    await db.commit()

    who = caller or Caller(kind="system", via="routine", username=f"routine {routine['name']}")
    await audit.record(
        db, who, "routines.run", "allowed", reason="scheduled or queued run",
        outcome="ok" if status == "ok" else "error",
        target=f"routine:{routine['id']} {routine['name']}",
        detail=(error or f"{len(calls)} calls")[:500],
    )
    log.info("Routine %s: %s (%d calls)", routine["name"], status, len(calls))
