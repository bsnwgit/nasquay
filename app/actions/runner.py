"""
Running a NAS tool — the one place it happens.

/api/run calls this for the pages, and the routines call it for themselves, so one
permission check and one audit record cover every route in.

Four things are checked before a NAS is contacted:

  1. the caller's role allows that exact action, per NAS where an override says so;
  2. the tool is reviewed — an unrecognised one is offered to nobody, admin included;
  3. the NAS is known, enabled, and has a token;
  4. a destructive action carries an explicit confirmation — from a person, or from a
     routine that was explicitly allowed destructive actions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import aiosqlite
from starlette.concurrency import run_in_threadpool

from app import crypto, visibility
from app.actions import audit, gate, qnap_catalogue
from app.actions.context import Caller
from app.connectors import qnap_mcp
from app.dependencies import ActionCall


class Refused(Exception):
    """The call did not happen, or failed at the NAS. status is the HTTP answer the web
    route gives; message says why, and is safe to show."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Result:
    tool: str
    nas: str
    classification: str
    text: str
    parsed: Optional[Any]
    hidden: int = 0


async def run_tool(
    db: aiosqlite.Connection, caller: Caller, nas_id: int, tool: str,
    arguments: dict[str, Any], confirm: bool,
) -> Result:
    action_id = qnap_catalogue.action_id(tool)
    params = {"nas_id": nas_id, "tool": tool, "arguments": arguments}

    async with db.execute(
        "SELECT id, classification, reviewed FROM actions WHERE id = ? AND source = 'qnap_mcp'",
        (action_id,),
    ) as cur:
        action = await cur.fetchone()
    if action is None:
        await audit.record(db, caller, action_id, "denied", reason="unknown tool", params=params)
        raise Refused(404, "That tool is not known to NASQuay")

    async with db.execute(
        """SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token, enabled,
                  (SELECT pem FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_ca_pem
           FROM nas WHERE id = ?""",
        (nas_id,),
    ) as cur:
        nas = await cur.fetchone()
    if nas is None:
        await audit.record(db, caller, action_id, "denied", reason="unknown NAS", params=params)
        raise Refused(404, "NAS not found")

    target = f"nas:{nas['id']} {nas['name']}"

    # The gate, including any per-NAS override of the role's general setting.
    decision = await gate.check(db, caller, action_id)
    if decision.allowed and not caller.is_admin:
        async with db.execute(
            "SELECT allowed FROM role_nas_permissions WHERE role_id = ? AND action_id = ? AND nas_id = ?",
            (caller.role_id, action_id, nas["id"]),
        ) as cur:
            override = await cur.fetchone()
        if override is not None and not override["allowed"]:
            decision = gate.Decision(False, f"not allowed on {nas['name']} for role {caller.role_name}")
    if not decision.allowed:
        await audit.record(db, caller, action_id, "denied", reason=decision.reason,
                           target=target, params=params, nas_id=nas["id"])
        raise Refused(403, f"Not permitted: {tool}")

    if not action["reviewed"]:
        reason = "tool not yet reviewed"
        await audit.record(db, caller, action_id, "denied", reason=reason, target=target,
                           params=params, nas_id=nas["id"])
        raise Refused(403, "That tool has not been reviewed yet, so nobody may run it")

    if action["classification"] == "destructive" and not confirm:
        reason = "destructive action without confirmation"
        await audit.record(db, caller, action_id, "denied", reason=reason, target=target,
                           params=params, nas_id=nas["id"])
        raise Refused(409, "This action is destructive and needs an explicit confirmation")

    if not nas["enabled"]:
        await audit.record(db, caller, action_id, "denied", reason="NAS is disabled",
                           target=target, params=params, nas_id=nas["id"])
        raise Refused(409, f"{nas['name']} is disabled")

    token = crypto.decrypt_str(nas["mcp_token"])
    if not token:
        await audit.record(db, caller, action_id, "denied", reason="no token for this NAS",
                           target=target, params=params, nas_id=nas["id"])
        raise Refused(400, f"No token is set for {nas['name']}")

    call = ActionCall(db, caller, action_id, decision.reason)

    def invoke() -> str:
        connection = qnap_mcp.Connection(
            qnap_mcp.Target(
                address=nas["address"], port=nas["mcp_port"], token=token,
                tls_mode=nas["tls_mode"], fingerprint=nas["tls_fingerprint"],
                ca_pem=nas["tls_ca_pem"] or "",
            )
        )
        try:
            connection.open()
            return connection.call_tool(tool, arguments)
        finally:
            connection.close()

    try:
        text = await run_in_threadpool(invoke)
    except qnap_mcp.McpError as exc:
        await call.failed(str(exc), target=target, params=params)
        raise Refused(502, str(exc))

    # QNAP returns JSON documents as text; hand back both so a caller can use either.
    parsed: Optional[Any] = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None

    # Presentation, applied here rather than in a page so that every caller sees the same
    # listing. It removes entries; it never adds or alters one.
    hidden_count = 0
    if parsed is not None and tool in visibility.LISTING_TOOLS:
        hidden_count = visibility.apply(
            tool, parsed, arguments, await visibility.rules(db, nas["id"])
        )
        if hidden_count:
            # Kept in step with the JSON, so a caller reading the text sees the listing
            # that was actually returned rather than the one before it was filtered.
            text = json.dumps(parsed)

    detail = f"{len(text)} characters"
    if hidden_count:
        detail += f" · {hidden_count} hidden"
    await call.done(target=target, params=params, detail=detail)
    return Result(tool=tool, nas=nas["name"], classification=action["classification"],
                  text=text, parsed=parsed, hidden=hidden_count)
