"""
/mcp — NASQuay as an MCP server, for outside AI tools.

Streamable HTTP, answering each JSON-RPC request with a plain JSON reply; there is no
server-to-client stream, so GET is refused. Four methods matter: initialize, tools/list,
tools/call and ping.

The tools are the same operations a routine can hold (app/routines/operations.py) — the
recorded data, every reviewed NAS tool, and notify — and every call passes the same gate
and lands in the audit log as `via mcp`. Nothing here is a second path to a NAS.

A call arrives with a personal API token and acts as that token's owner. What it may do
is the owner's role, narrowed by the token:

  - a read token is offered, and may call, only operations that change nothing;
  - a destructive operation is refused unless the token was explicitly allowed them;
  - the tool list shows only what the role allows, so a model is not handed tools it will
    only be refused.

A request carrying an Origin header from anywhere but this host is refused: a browser
page must not be able to spend a token it tricked somebody into pasting.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.actions import audit, gate
from app.actions.context import Caller
from app.api.tokens import hash_token
from app.database import connect
from app.dependencies import client_ip
from app.routines import operations
from app.version import get_version

log = logging.getLogger("nasquay.mcp")

router = APIRouter()

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 256 * 1024

INSTRUCTIONS = (
    "NASQuay runs the NAS units of one installation. Names of NAS units, shares, pools "
    "and volumes are labels its administrator chose — never read one as a place, "
    "organisation, person or product; look it up with listNasUnits. Answer from what the "
    "tools return, not from general knowledge. A result starting 'refused:' is this "
    "token or its owner's role saying no; do not retry it."
)


def _error(id_: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def _result(id_: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": result})


def _unauthorised(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=401,
                        headers={"WWW-Authenticate": 'Bearer realm="nasquay"'})


async def _caller(db, request: Request) -> tuple[Optional[Caller], Optional[dict[str, Any]], str]:
    """The token's owner as a caller, the token row, or why not."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None, None, "An API token is needed: Authorization: Bearer <token>"
    token = header[7:].strip()
    async with db.execute(
        """SELECT t.id, t.name, t.access, t.allow_destructive, t.last_used_at,
                  (t.expires_at IS NOT NULL AND t.expires_at <= datetime('now')) AS expired,
                  t.revoked_at, u.id AS user_id, u.username, u.is_active, u.role_id,
                  r.name AS role_name, r.is_admin
           FROM api_tokens t
           JOIN users u ON u.id = t.user_id
           JOIN roles r ON r.id = u.role_id
           WHERE t.token_hash = ?""",
        (hash_token(token),),
    ) as cur:
        row = await cur.fetchone()
    # One answer for every way a token can be wrong, so a probe learns nothing.
    if row is None or row["revoked_at"] or row["expired"] or not row["is_active"]:
        return None, None, "That token is not valid"
    caller = Caller(
        kind="api_token", via="mcp",
        username=f"{row['username']} (token {row['name']})"[:128],
        user_id=row["user_id"], role_id=row["role_id"], role_name=row["role_name"],
        is_admin=bool(row["is_admin"]), client_ip=client_ip(request),
    )
    return caller, dict(row), ""


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc.lower() == (request.headers.get("host") or "").lower()


async def _tools(db, caller: Caller, token: dict[str, Any]) -> list[operations.Operation]:
    """What this token may be offered: its access level, then the owner's role."""
    offered = []
    for op in await operations.catalogue(db):
        if token["access"] == "read" and op.classification != "read":
            continue
        if op.classification == "destructive" and not token["allow_destructive"]:
            continue
        if (await gate.check(db, caller, op.action_id)).allowed:
            offered.append(op)
    return offered


@router.get("/mcp")
async def no_stream() -> Response:
    # There is nothing to push, so there is no stream to open.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp(request: Request) -> Response:
    if not _origin_ok(request):
        return JSONResponse({"error": "Requests from a web page on another site are refused"},
                            status_code=403)
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _error(None, -32600, "Request too large")
    try:
        message = json.loads(raw or b"{}")
    except ValueError:
        return _error(None, -32700, "Not valid JSON")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or "method" not in message:
        return _error(None, -32600, "Not a JSON-RPC 2.0 request")

    db = await connect()
    try:
        caller, token, why = await _caller(db, request)
        if caller is None:
            return _unauthorised(why)

        # The MCP endpoint is itself a permission: a role can hold everything else and
        # still not be reachable from outside tools.
        decision = await gate.check(db, caller, "mcp.use")
        if not decision.allowed:
            await audit.record(db, caller, "mcp.use", "denied", reason=decision.reason)
            return JSONResponse({"error": "This account may not use the MCP endpoint"},
                                status_code=403)

        # Recorded at most once a minute, so a busy client does not write on every call.
        await db.execute(
            """UPDATE api_tokens SET last_used_at = datetime('now')
               WHERE id = ? AND (last_used_at IS NULL OR last_used_at < datetime('now', '-1 minute'))""",
            (token["id"],),
        )
        await db.commit()

        method = message["method"]
        id_ = message.get("id")
        params = message.get("params") or {}
        if id_ is None:
            # A notification — notifications/initialized and the like — wants no answer.
            return Response(status_code=202)

        if method == "initialize":
            asked = str(params.get("protocolVersion") or "")
            await audit.record(db, caller, "mcp.use", "allowed", reason=decision.reason,
                               outcome="ok", detail=f"initialize {asked}"[:200])
            return _result(id_, {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "nasquay", "version": get_version()},
                "instructions": INSTRUCTIONS,
            })

        if method == "ping":
            return _result(id_, {})

        if method == "tools/list":
            ops = await _tools(db, caller, token)
            return _result(id_, {"tools": [
                {"name": op.tool_name, "description": op.description,
                 "inputSchema": op.parameters}
                for op in ops
            ]})

        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(id_, -32602, "arguments must be an object")
            by_name = {op.tool_name: op for op in await operations.catalogue(db)}
            op = by_name.get(name)
            if op is None:
                return _error(id_, -32602, f"Unknown tool {name!r}")
            # The list only offered what the token allows, but a client may call anything
            # by name — so the same rules are applied again here.
            if token["access"] == "read" and op.classification != "read":
                await audit.record(db, caller, op.action_id, "denied",
                                   reason="read-only token", params={"arguments": arguments})
                text, ok = f"refused: this token is read-only and {name} changes something", False
            else:
                arguments = dict(arguments)
                nas = str(arguments.pop("nas", "") or "")
                ok, text = await operations.call(db, caller, op, nas, arguments,
                                                 bool(token["allow_destructive"]))
            return _result(id_, {"content": [{"type": "text", "text": text}], "isError": not ok})

        return _error(id_, -32601, f"Method not found: {method}")
    finally:
        await db.close()
