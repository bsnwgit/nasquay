"""
/api/audit — the audit log, newest first, with simple filters and id-based paging.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies import ActionCall, DbDep, require

router = APIRouter()


class AuditOut(BaseModel):
    id: int
    at: str
    actor_kind: str
    actor_id: Optional[int] = None
    actor_name: str
    via: str
    action_id: str
    nas_id: Optional[int] = None
    target: str
    params: str
    decision: str
    reason: str
    outcome: Optional[str] = None
    detail: str
    duration_ms: Optional[int] = None
    job_id: Optional[int] = None
    client_ip: str


class AuditPage(BaseModel):
    records: list[AuditOut]
    next_before_id: Optional[int] = None


@router.get("", response_model=AuditPage)
async def list_audit(
    db: DbDep,
    call: Annotated[ActionCall, Depends(require("audit.read"))],
    limit: int = Query(default=100, ge=1, le=500),
    before_id: Optional[int] = Query(default=None, ge=1),
    action_id: Optional[str] = Query(default=None, max_length=128),
    actor_name: Optional[str] = Query(default=None, max_length=128),
    decision: Optional[Literal["allowed", "denied"]] = None,
):
    # Each clause is a fixed string; every value is a bound parameter.
    clauses: list[str] = []
    values: list[Any] = []
    if before_id is not None:
        clauses.append("id < ?")
        values.append(before_id)
    if action_id:
        clauses.append("action_id = ?")
        values.append(action_id)
    if actor_name:
        clauses.append("actor_name = ?")
        values.append(actor_name)
    if decision:
        clauses.append("decision = ?")
        values.append(decision)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    async with db.execute(f"SELECT * FROM audit{where} ORDER BY id DESC LIMIT ?", (*values, limit)) as cur:
        rows = [dict(row) for row in await cur.fetchall()]

    await call.done(
        params={"limit": limit, "before_id": before_id, "action_id": action_id,
                "actor_name": actor_name, "decision": decision},
        detail=f"{len(rows)} records",
    )
    return {"records": rows, "next_before_id": rows[-1]["id"] if len(rows) == limit else None}
