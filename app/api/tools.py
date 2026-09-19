"""
/api/tools — the QNAP tools each NAS offers, and their classification.

Discovery asks a NAS what it can do and records each tool as an action, so roles switch
them on and off exactly like NASQuay's own. A tool NASQuay does not recognise arrives
unreviewed, which means nobody may run it — admin included — until it is classified here.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto
from app.actions import qnap_catalogue
from app.connectors import qnap_mcp
from app.dependencies import ActionCall, DbDep, require

router = APIRouter()


class ToolOut(BaseModel):
    action_id: str
    tool_name: str
    category: str
    classification: str
    description: str
    reviewed: bool
    nas: list[str] = Field(default_factory=list)


class ToolReview(BaseModel):
    classification: str = Field(pattern="^(read|write|destructive)$")
    category: Optional[str] = Field(default=None, max_length=64)
    reviewed: bool = True


class DiscoverOut(BaseModel):
    nas: str
    found: int
    added: int
    unreviewed: int


@router.get("", response_model=list[ToolOut])
async def list_tools(db: DbDep, call: Annotated[ActionCall, Depends(require("tools.list"))]):
    async with db.execute(
        """SELECT a.id, a.category, a.classification, a.description, a.reviewed,
                  COALESCE(GROUP_CONCAT(n.name, ', '), '') AS nas_names,
                  COALESCE(MAX(t.tool_name), '') AS tool_name
           FROM actions a
           LEFT JOIN nas_tools t ON t.action_id = a.id AND t.available = 1
           LEFT JOIN nas n ON n.id = t.nas_id
           WHERE a.source = 'qnap_mcp'
           GROUP BY a.id
           ORDER BY a.reviewed, a.category, a.id"""
    ) as cur:
        rows = await cur.fetchall()

    tools = [
        ToolOut(
            action_id=row["id"],
            tool_name=row["tool_name"] or row["id"].removeprefix(qnap_catalogue.ACTION_PREFIX),
            category=row["category"],
            classification=row["classification"],
            description=row["description"],
            reviewed=bool(row["reviewed"]),
            nas=[name for name in (row["nas_names"] or "").split(", ") if name],
        )
        for row in rows
    ]
    await call.done(detail=f"{len(tools)} tools")
    return tools


@router.post("/discover/{nas_id}", response_model=DiscoverOut)
async def discover(
    nas_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("tools.discover"))]
):
    async with db.execute(
        """SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token, enabled,
                  (SELECT pem FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_ca_pem
           FROM nas WHERE id = ?""",
        (nas_id,),
    ) as cur:
        nas = await cur.fetchone()
    if nas is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")

    target = f"nas:{nas['id']} {nas['name']}"
    token = crypto.decrypt_str(nas["mcp_token"])
    if not token:
        await call.failed("no token is set for this NAS", target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No token is set for this NAS")

    def fetch() -> list[dict[str, Any]]:
        connection = qnap_mcp.Connection(
            qnap_mcp.Target(
                address=nas["address"], port=nas["mcp_port"], token=token,
                tls_mode=nas["tls_mode"], fingerprint=nas["tls_fingerprint"],
                ca_pem=nas["tls_ca_pem"] or "",
            )
        )
        try:
            connection.open()
            return connection.list_tools()
        finally:
            connection.close()

    try:
        found = await run_in_threadpool(fetch)
    except qnap_mcp.McpError as exc:
        await call.failed(str(exc), target=target)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    added = 0
    unreviewed = 0
    for tool in found:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        action_id = qnap_catalogue.action_id(name)
        category, classification, description, reviewed = qnap_catalogue.classify(
            name, str(tool.get("description") or "")
        )
        if not reviewed:
            unreviewed += 1

        async with db.execute("SELECT 1 FROM actions WHERE id = ?", (action_id,)) as cur:
            exists = await cur.fetchone() is not None
        if not exists:
            added += 1
            await db.execute(
                """INSERT INTO actions (id, source, category, classification, description, reviewed)
                   VALUES (?, 'qnap_mcp', ?, ?, ?, ?)""",
                (action_id, category, classification, description, int(reviewed)),
            )
        # An existing action keeps its classification: a review decision is not undone by
        # rediscovery, and neither are the permissions hanging off it.

        await db.execute(
            """INSERT INTO nas_tools (nas_id, action_id, tool_name, available, last_seen)
               VALUES (?, ?, ?, 1, datetime('now'))
               ON CONFLICT(nas_id, action_id) DO UPDATE SET
                   available = 1, tool_name = excluded.tool_name, last_seen = excluded.last_seen""",
            (nas_id, action_id, name),
        )

    # Anything this NAS no longer offers stops being available, without losing its history.
    names = [qnap_catalogue.action_id(str(t.get("name") or "")) for t in found]
    placeholders = ",".join("?" * len(names)) if names else "''"
    await db.execute(
        f"UPDATE nas_tools SET available = 0 WHERE nas_id = ? AND action_id NOT IN ({placeholders})",
        (nas_id, *names),
    )
    await db.commit()

    detail = f"{len(found)} tools, {added} new, {unreviewed} unreviewed"
    await call.done(target=target, detail=detail)
    return DiscoverOut(nas=nas["name"], found=len(found), added=added, unreviewed=unreviewed)


@router.patch("/{action_id}", response_model=ToolOut)
async def review_tool(
    action_id: str, body: ToolReview, db: DbDep,
    call: Annotated[ActionCall, Depends(require("tools.review"))],
):
    if not action_id.startswith(qnap_catalogue.ACTION_PREFIX):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a NAS tool")

    async with db.execute(
        "SELECT id, category FROM actions WHERE id = ? AND source = 'qnap_mcp'", (action_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("tool not found", target=action_id)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")

    await db.execute(
        """UPDATE actions SET classification = ?, category = ?, reviewed = ?,
                              updated_at = datetime('now')
           WHERE id = ?""",
        (body.classification, body.category or row["category"], int(body.reviewed), action_id),
    )
    await db.commit()
    await call.done(
        target=action_id,
        params=body.model_dump(),
        detail=f"{body.classification}, reviewed={body.reviewed}",
    )

    async with db.execute(
        """SELECT a.id, a.category, a.classification, a.description, a.reviewed,
                  COALESCE(GROUP_CONCAT(n.name, ', '), '') AS nas_names,
                  COALESCE(MAX(t.tool_name), '') AS tool_name
           FROM actions a
           LEFT JOIN nas_tools t ON t.action_id = a.id AND t.available = 1
           LEFT JOIN nas n ON n.id = t.nas_id
           WHERE a.id = ?
           GROUP BY a.id""",
        (action_id,),
    ) as cur:
        updated = await cur.fetchone()

    return ToolOut(
        action_id=updated["id"],
        tool_name=updated["tool_name"] or action_id.removeprefix(qnap_catalogue.ACTION_PREFIX),
        category=updated["category"],
        classification=updated["classification"],
        description=updated["description"],
        reviewed=bool(updated["reviewed"]),
        nas=[name for name in (updated["nas_names"] or "").split(", ") if name],
    )
