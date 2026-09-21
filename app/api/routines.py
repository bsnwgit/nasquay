"""
/api/routines — scheduled work, created and run from the interface.

A routine acts as its run-as user, so who may set one up is checked as carefully as who
may hand out a role. Without that, anyone allowed routines.create could name an
administrator as the run-as user and have a routine do what they may not:

  - the run-as user must be the caller, or hold a role the caller could hand out
    (app/actions/gate.can_manage_role);
  - the same holds for editing, running or deleting an existing routine — its run-as
    user is checked, not only the one being chosen;
  - only an administrator may allow a routine destructive actions, and a routine that
    has them can be edited, run or deleted by an administrator only.

"Run now" queues a run; the routine schedule starts it within seconds. That keeps every
run in one process, the worker, whichever way it was asked for.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.actions import gate
from app.actions.context import Caller
from app.dependencies import ActionCall, DbDep, require
from app.routines import operations

router = APIRouter()

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SCHEDULE_FIELDS = ("schedule_kind", "interval_minutes", "at_time", "weekday")

_SELECT = """
    SELECT r.*,
           u.username AS run_as_username,
           p.name     AS provider_name,
           (SELECT status      FROM routine_runs x WHERE x.routine_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_status,
           (SELECT queued_at   FROM routine_runs x WHERE x.routine_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_queued_at,
           (SELECT finished_at FROM routine_runs x WHERE x.routine_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_finished_at,
           (SELECT error       FROM routine_runs x WHERE x.routine_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_error
    FROM routines r
    LEFT JOIN users u        ON u.id = r.run_as_user_id
    LEFT JOIN ai_providers p ON p.id = r.provider_id
"""


# ── Models ────────────────────────────────────────────────────────────────────

class Step(BaseModel):
    op: str = Field(min_length=1, max_length=160)
    nas: str = Field(default="", max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class RoutineOut(BaseModel):
    id: int
    name: str
    description: str
    enabled: bool
    kind: str
    run_as_user_id: Optional[int] = None
    run_as_username: Optional[str] = None
    schedule_kind: str
    interval_minutes: int
    at_time: str
    weekday: int
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    prompt: str
    steps: list[Step]
    allowed: list[str]
    allow_destructive: bool
    max_steps: int
    timeout_s: int
    alert_on: str
    created_at: str
    updated_at: Optional[str] = None
    last_status: Optional[str] = None
    last_queued_at: Optional[str] = None
    last_finished_at: Optional[str] = None
    last_error: Optional[str] = None


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    kind: str = Field(pattern="^(fixed|ai)$")
    run_as_user_id: int = Field(ge=1)
    schedule_kind: str = Field(default="manual", pattern="^(manual|interval|daily|weekly)$")
    interval_minutes: int = Field(default=60, ge=5, le=10080)
    at_time: str = "07:00"
    weekday: int = Field(default=0, ge=0, le=6)
    provider_id: Optional[int] = None
    prompt: str = Field(default="", max_length=8000)
    steps: list[Step] = Field(default_factory=list, max_length=30)
    allowed: list[str] = Field(default_factory=list, max_length=200)
    allow_destructive: bool = False
    max_steps: int = Field(default=8, ge=1, le=30)
    timeout_s: int = Field(default=600, ge=30, le=3600)
    alert_on: str = Field(default="failure", pattern="^(never|failure|always)$")

    @field_validator("at_time")
    @classmethod
    def _time(cls, value: str) -> str:
        if not TIME.match(value):
            raise ValueError("a time of day as HH:MM, 24-hour")
        return value


class RoutineUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    description: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = None
    run_as_user_id: Optional[int] = Field(default=None, ge=1)
    schedule_kind: Optional[str] = Field(default=None, pattern="^(manual|interval|daily|weekly)$")
    interval_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    at_time: Optional[str] = None
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    provider_id: Optional[int] = None
    prompt: Optional[str] = Field(default=None, max_length=8000)
    steps: Optional[list[Step]] = Field(default=None, max_length=30)
    allowed: Optional[list[str]] = Field(default=None, max_length=200)
    allow_destructive: Optional[bool] = None
    max_steps: Optional[int] = Field(default=None, ge=1, le=30)
    timeout_s: Optional[int] = Field(default=None, ge=30, le=3600)
    alert_on: Optional[str] = Field(default=None, pattern="^(never|failure|always)$")

    @field_validator("at_time")
    @classmethod
    def _time(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not TIME.match(value):
            raise ValueError("a time of day as HH:MM, 24-hour")
        return value


class OperationOut(BaseModel):
    id: str
    description: str
    classification: str
    needs_nas: bool
    nas_names: list[str]
    parameters: dict[str, Any]


class RunOut(BaseModel):
    id: int
    trigger: str
    status: str
    queued_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    output: str
    error: str
    calls: list[dict[str, Any]]
    alert: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _out(row) -> dict[str, Any]:
    data = dict(row)
    for flag in ("enabled", "allow_destructive"):
        data[flag] = bool(data[flag])
    data["steps"] = json.loads(data["steps"] or "[]")
    data["allowed"] = json.loads(data["allowed"] or "[]")
    return {k: v for k, v in data.items() if k in RoutineOut.model_fields}


def _target(row) -> str:
    return f"routine:{row['id']} {row['name']}"


async def _fetch(db, routine_id: int):
    async with db.execute(_SELECT + " WHERE r.id = ?", (routine_id,)) as cur:
        return await cur.fetchone()


async def _may_run_as(db, caller: Caller, user_id: Optional[int]) -> bool:
    """Whether the caller may have something act as this user."""
    if caller.is_admin:
        return True
    if user_id is None:
        return False
    if user_id == caller.user_id:
        return True
    async with db.execute("SELECT role_id FROM users WHERE id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    return row is not None and await gate.can_manage_role(db, caller, row["role_id"])


async def _authority(db, call: ActionCall, row) -> None:
    """Refuse a caller who could not have set this routine up themselves."""
    if row["allow_destructive"] and not call.caller.is_admin:
        raise await call.refused("only an administrator may manage a routine allowed destructive actions",
                                 target=_target(row))
    if not await _may_run_as(db, call.caller, row["run_as_user_id"]):
        raise await call.refused("this routine runs as a user above your own role",
                                 target=_target(row))


async def _check(db, call: ActionCall, merged: dict[str, Any], target: str) -> None:
    """Everything a routine must satisfy to be saved, checked against the whole routine
    as it will be, not only the fields that changed."""

    async def bad(message: str) -> None:
        await call.failed(message, target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    async with db.execute("SELECT is_active FROM users WHERE id = ?",
                          (merged["run_as_user_id"],)) as cur:
        user = await cur.fetchone()
    if user is None:
        await bad("The run-as user does not exist")
    if not await _may_run_as(db, call.caller, merged["run_as_user_id"]):
        raise await call.refused("you may not have a routine run as that user", target=target)
    if merged["allow_destructive"] and not call.caller.is_admin:
        raise await call.refused("only an administrator may allow a routine destructive actions",
                                 target=target)

    ops = {op.id: op for op in await operations.catalogue(db)}
    named = [s["op"] for s in merged["steps"]] if merged["kind"] == "fixed" else merged["allowed"]
    for op_id in named:
        op = ops.get(op_id)
        if op is None:
            await bad(f"{op_id} is not something a routine can call")
        if op.classification == "destructive" and not merged["allow_destructive"]:
            await bad(f"{op_id} is destructive; allow destructive actions first")

    if merged["kind"] == "fixed":
        if not merged["steps"]:
            await bad("A fixed routine needs at least one step")
        for number, step in enumerate(merged["steps"], start=1):
            op = ops[step["op"]]
            if op.needs_nas and step.get("nas", "").lower() not in {n.lower() for n in op.nas_names}:
                await bad(f"Step {number}: choose a NAS that offers {op.id}")
    else:
        if not merged["prompt"].strip():
            await bad("An AI routine needs a prompt")
        if not merged["provider_id"]:
            await bad("An AI routine needs an AI provider")
        async with db.execute("SELECT 1 FROM ai_providers WHERE id = ?",
                              (merged["provider_id"],)) as cur:
            if await cur.fetchone() is None:
                await bad("That AI provider does not exist")


def _row_values(merged: dict[str, Any]) -> dict[str, Any]:
    values = dict(merged)
    values["steps"] = json.dumps(merged["steps"])
    values["allowed"] = json.dumps(sorted(set(merged["allowed"])))
    for flag in ("enabled", "allow_destructive"):
        values[flag] = int(bool(merged[flag]))
    values["name"] = merged["name"].strip()
    values["provider_id"] = merged["provider_id"] or None
    return values


COLUMNS = ("name", "description", "enabled", "kind", "run_as_user_id", "schedule_kind",
           "interval_minutes", "at_time", "weekday", "provider_id", "prompt", "steps",
           "allowed", "allow_destructive", "max_steps", "timeout_s", "alert_on")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[RoutineOut])
async def list_routines(db: DbDep, call: Annotated[ActionCall, Depends(require("routines.list"))]):
    async with db.execute(_SELECT + " ORDER BY r.name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} routines")
    return [_out(row) for row in rows]


@router.get("/operations", response_model=list[OperationOut])
async def list_operations(db: DbDep, call: Annotated[ActionCall, Depends(require("routines.list"))]):
    """What a routine could be given. A role still decides, at run time, what it gets."""
    ops = await operations.catalogue(db)
    await call.done(detail=f"{len(ops)} operations")
    return [OperationOut(id=op.id, description=op.description, classification=op.classification,
                         needs_nas=op.needs_nas, nas_names=op.nas_names,
                         parameters=op.parameters) for op in ops]


@router.post("", response_model=RoutineOut, status_code=status.HTTP_201_CREATED)
async def create_routine(
    body: RoutineIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("routines.create"))],
):
    merged = body.model_dump()
    merged["steps"] = [s.model_dump() for s in body.steps]
    await _check(db, call, merged, body.name)
    values = _row_values(merged)
    try:
        cur = await db.execute(
            f"""INSERT INTO routines ({', '.join(COLUMNS)}, created_by)
                VALUES ({', '.join('?' * len(COLUMNS))}, ?)""",
            (*(values[c] for c in COLUMNS), call.caller.user_id),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a routine with that name already exists", target=body.name)
        raise HTTPException(status.HTTP_409_CONFLICT, "A routine with that name already exists")
    row = await _fetch(db, cur.lastrowid)
    await call.done(target=_target(row), detail=f"{body.kind}, {body.schedule_kind}")
    return _out(row)


@router.patch("/{routine_id}", response_model=RoutineOut)
async def update_routine(
    routine_id: int, body: RoutineUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("routines.update"))],
):
    row = await _fetch(db, routine_id)
    if row is None:
        await call.failed("routine not found", target=f"routine:{routine_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routine not found")
    target = _target(row)
    await _authority(db, call, row)

    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "steps" in changes:
        changes["steps"] = [s.model_dump() for s in body.steps or []]
    current = _out(row)
    current["steps"] = [dict(s) for s in current["steps"]]
    merged = {c: current[c] for c in COLUMNS} | changes
    await _check(db, call, merged, target)

    values = _row_values(merged)
    sets = [f"{c} = ?" for c in COLUMNS]
    params = [values[c] for c in COLUMNS]
    # A changed schedule starts from now, so a slot already past does not fire at once.
    if any(c in changes and changes[c] != current[c] for c in SCHEDULE_FIELDS):
        sets.append("schedule_from = datetime('now')")
    sets += ["updated_at = datetime('now')", "updated_by = ?"]
    params.append(call.caller.user_id)
    try:
        await db.execute(f"UPDATE routines SET {', '.join(sets)} WHERE id = ?",
                         (*params, routine_id))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a routine with that name already exists", target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, "A routine with that name already exists")
    await call.done(target=target, detail=", ".join(changes) or "no changes")
    return _out(await _fetch(db, routine_id))


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(
    routine_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("routines.delete"))],
) -> None:
    row = await _fetch(db, routine_id)
    if row is None:
        await call.failed("routine not found", target=f"routine:{routine_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routine not found")
    await _authority(db, call, row)
    if row["last_status"] == "running":
        await call.failed("routine is running", target=_target(row))
        raise HTTPException(status.HTTP_409_CONFLICT, "It is running now; delete it when it finishes")
    await db.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    await db.commit()
    await call.done(target=_target(row))


@router.post("/{routine_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_routine(
    routine_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("routines.run"))],
):
    row = await _fetch(db, routine_id)
    if row is None:
        await call.failed("routine not found", target=f"routine:{routine_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routine not found")
    await _authority(db, call, row)
    async with db.execute(
        "SELECT 1 FROM routine_runs WHERE routine_id = ? AND status IN ('queued', 'running')",
        (routine_id,),
    ) as cur:
        if await cur.fetchone():
            await call.failed("already queued or running", target=_target(row))
            raise HTTPException(status.HTTP_409_CONFLICT, "It is already queued or running")
    cur = await db.execute(
        """INSERT INTO routine_runs (routine_id, trigger, requested_by, status)
           VALUES (?, 'manual', ?, 'queued')""",
        (routine_id, call.caller.user_id),
    )
    await db.commit()
    await call.done(target=_target(row), detail=f"queued run {cur.lastrowid}")
    return {"run_id": cur.lastrowid}


@router.get("/{routine_id}/runs", response_model=list[RunOut])
async def list_runs(
    routine_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("routines.list"))],
    limit: int = Query(20, ge=1, le=200),
):
    # A run's output is what its run-as user could read, so it is shown only to somebody
    # who could have run it as that user.
    row = await _fetch(db, routine_id)
    if row is None:
        await call.failed("routine not found", target=f"routine:{routine_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routine not found")
    if not await _may_run_as(db, call.caller, row["run_as_user_id"]):
        raise await call.refused("this routine runs as a user above your own role",
                                 target=_target(row))
    async with db.execute(
        """SELECT id, trigger, status, queued_at, started_at, finished_at, output, error,
                  calls, alert
           FROM routine_runs WHERE routine_id = ? ORDER BY id DESC LIMIT ?""",
        (routine_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    await call.done(target=f"routine:{routine_id}", detail=f"{len(rows)} runs")
    return [RunOut(**{**dict(r), "calls": json.loads(r["calls"] or "[]")}) for r in rows]
