"""
/api/run — running a NAS tool.

This is the only way a tool is ever called. The pages, and later the routines and the MCP
endpoint, all come through here, so one permission check and one audit record cover every
route in.

Four things are checked before a NAS is contacted:

  1. the caller's role allows that exact action, per NAS where an override says so;
  2. the tool is reviewed — an unrecognised one is offered to nobody, admin included;
  3. the NAS is known, enabled, and has a token;
  4. a destructive action carries an explicit confirmation from a person.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.actions import audit, gate, qnap_catalogue
from app.connectors import qnap_mcp
from app.dependencies import ActionCall, CurrentCaller, DbDep

router = APIRouter()


class RunIn(BaseModel):
    nas_id: int = Field(ge=1)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # A person ticking "yes, do it". Unattended callers have no dialog, so they need a
    # standing allowance instead — see the routines and MCP work.
    confirm: bool = False


class RunOut(BaseModel):
    tool: str
    nas: str
    classification: str
    text: str
    json_result: Optional[Any] = None


@router.post("", response_model=RunOut)
async def run_tool(body: RunIn, db: DbDep, caller: CurrentCaller):
    action_id = qnap_catalogue.action_id(body.tool)
    params = {"nas_id": body.nas_id, "tool": body.tool, "arguments": body.arguments}

    async with db.execute(
        "SELECT id, classification, reviewed FROM actions WHERE id = ? AND source = 'qnap_mcp'",
        (action_id,),
    ) as cur:
        action = await cur.fetchone()
    if action is None:
        await audit.record(db, caller, action_id, "denied", reason="unknown tool", params=params)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That tool is not known to NASQuay")

    async with db.execute(
        """SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token, enabled
           FROM nas WHERE id = ?""",
        (body.nas_id,),
    ) as cur:
        nas = await cur.fetchone()
    if nas is None:
        await audit.record(db, caller, action_id, "denied", reason="unknown NAS", params=params)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")

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
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Not permitted: {body.tool}")

    if not action["reviewed"]:
        reason = "tool not yet reviewed"
        await audit.record(db, caller, action_id, "denied", reason=reason, target=target,
                           params=params, nas_id=nas["id"])
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "That tool has not been reviewed yet, so nobody may run it")

    if action["classification"] == "destructive" and not body.confirm:
        reason = "destructive action without confirmation"
        await audit.record(db, caller, action_id, "denied", reason=reason, target=target,
                           params=params, nas_id=nas["id"])
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This action is destructive and needs an explicit confirmation")

    if not nas["enabled"]:
        await audit.record(db, caller, action_id, "denied", reason="NAS is disabled",
                           target=target, params=params, nas_id=nas["id"])
        raise HTTPException(status.HTTP_409_CONFLICT, f"{nas['name']} is disabled")

    token = crypto.decrypt_str(nas["mcp_token"])
    if not token:
        await audit.record(db, caller, action_id, "denied", reason="no token for this NAS",
                           target=target, params=params, nas_id=nas["id"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No token is set for {nas['name']}")

    call = ActionCall(db, caller, action_id, decision.reason)

    def invoke() -> str:
        connection = qnap_mcp.Connection(
            qnap_mcp.Target(
                address=nas["address"], port=nas["mcp_port"], token=token,
                tls_mode=nas["tls_mode"], fingerprint=nas["tls_fingerprint"],
            )
        )
        try:
            connection.open()
            return connection.call_tool(body.tool, body.arguments)
        finally:
            connection.close()

    try:
        text = await run_in_threadpool(invoke)
    except qnap_mcp.McpError as exc:
        await call.failed(str(exc), target=target, params=params)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    # QNAP returns JSON documents as text; hand back both so a page can use either.
    parsed: Optional[Any] = None
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None

    await call.done(target=target, params=params, detail=f"{len(text)} characters")
    return RunOut(
        tool=body.tool,
        nas=nas["name"],
        classification=action["classification"],
        text=text,
        json_result=parsed,
    )
