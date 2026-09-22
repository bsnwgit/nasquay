"""
/api/reports — report definitions, their runs, and the documents made from them.

A report acts as its run-as user, so the same rule the routines use applies here: you may
only point a report at yourself, or at a user whose role you could hand out, and the same
check covers editing, running, deleting and reading what a report produced. Without it,
anybody allowed reports.create could read the audit log through a report that runs as an
administrator.

The CSV and the PDF are rendered from the stored figures when they are asked for; nothing
is written to disk.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.actions import gate
from app.actions.context import Caller
from app.dependencies import ActionCall, DbDep, require
from app.reporting import render
from app.reporting.engine import TITLES

router = APIRouter()

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SCHEDULE_FIELDS = ("schedule_kind", "interval_minutes", "at_time", "weekday")
COLUMNS = ("name", "description", "kind", "enabled", "period_days", "nas_id",
           "schedule_kind", "interval_minutes", "at_time", "weekday", "run_as_user_id",
           "deliver", "ai_summary", "provider_id", "compare")

_SELECT = """
    SELECT r.*, u.username AS run_as_username, n.name AS nas_name, p.name AS provider_name,
           (SELECT status      FROM report_runs x WHERE x.report_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_status,
           (SELECT finished_at FROM report_runs x WHERE x.report_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_finished_at,
           (SELECT error       FROM report_runs x WHERE x.report_id = r.id ORDER BY x.id DESC LIMIT 1) AS last_error,
           (SELECT id          FROM report_runs x WHERE x.report_id = r.id AND x.status = 'ok' ORDER BY x.id DESC LIMIT 1) AS last_ok_run
    FROM reports r
    LEFT JOIN users u        ON u.id = r.run_as_user_id
    LEFT JOIN nas n          ON n.id = r.nas_id
    LEFT JOIN ai_providers p ON p.id = r.provider_id
"""


class ReportOut(BaseModel):
    id: int
    name: str
    description: str
    kind: str
    enabled: bool
    period_days: int
    nas_id: Optional[int] = None
    nas_name: Optional[str] = None
    schedule_kind: str
    interval_minutes: int
    at_time: str
    weekday: int
    run_as_user_id: Optional[int] = None
    run_as_username: Optional[str] = None
    deliver: bool
    ai_summary: bool
    compare: bool
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    last_status: Optional[str] = None
    last_finished_at: Optional[str] = None
    last_error: Optional[str] = None
    last_ok_run: Optional[int] = None


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    kind: str = Field(pattern="^(capacity|change|health|activity)$")
    enabled: bool = True
    period_days: int = Field(default=30, ge=1, le=3650)
    nas_id: Optional[int] = None
    schedule_kind: str = Field(default="manual", pattern="^(manual|interval|daily|weekly)$")
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    at_time: str = "07:00"
    weekday: int = Field(default=0, ge=0, le=6)
    run_as_user_id: int = Field(ge=1)
    deliver: bool = False
    ai_summary: bool = False
    compare: bool = False
    provider_id: Optional[int] = None

    @field_validator("at_time")
    @classmethod
    def _time(cls, value: str) -> str:
        if not TIME.match(value):
            raise ValueError("a time of day as HH:MM, 24-hour")
        return value


class ReportUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    # Everything is editable, the kind included: a report is a saved question, and
    # changing the question should not mean making a new one and losing its history.
    kind: Optional[str] = Field(default=None, pattern="^(capacity|change|health|activity)$")
    description: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = None
    period_days: Optional[int] = Field(default=None, ge=1, le=3650)
    nas_id: Optional[int] = None
    schedule_kind: Optional[str] = Field(default=None, pattern="^(manual|interval|daily|weekly)$")
    interval_minutes: Optional[int] = Field(default=None, ge=5, le=10080)
    at_time: Optional[str] = None
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    run_as_user_id: Optional[int] = Field(default=None, ge=1)
    deliver: Optional[bool] = None
    ai_summary: Optional[bool] = None
    compare: Optional[bool] = None
    provider_id: Optional[int] = None

    @field_validator("at_time")
    @classmethod
    def _time(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not TIME.match(value):
            raise ValueError("a time of day as HH:MM, 24-hour")
        return value


class RunOut(BaseModel):
    id: int
    report_id: int
    report_name: str
    kind: str
    trigger: str
    status: str
    queued_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    summary: str
    error: str
    delivered: str
    figures: Optional[dict[str, Any]] = None


def _out(row) -> dict[str, Any]:
    data = dict(row)
    for flag in ("enabled", "deliver", "ai_summary", "compare"):
        data[flag] = bool(data[flag])
    return {k: v for k, v in data.items() if k in ReportOut.model_fields}


def _target(row) -> str:
    return f"report:{row['id']} {row['name']}"


async def _fetch(db, report_id: int):
    async with db.execute(_SELECT + " WHERE r.id = ?", (report_id,)) as cur:
        return await cur.fetchone()


async def _may_run_as(db, caller: Caller, user_id: Optional[int]) -> bool:
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
    if not await _may_run_as(db, call.caller, row["run_as_user_id"]):
        raise await call.refused("this report runs as a user above your own role",
                                 target=_target(row))


async def _check(db, call: ActionCall, merged: dict[str, Any], target: str) -> None:
    async def bad(message: str) -> None:
        await call.failed(message, target=target)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, message)

    async with db.execute("SELECT 1 FROM users WHERE id = ?", (merged["run_as_user_id"],)) as cur:
        if await cur.fetchone() is None:
            await bad("The run-as user does not exist")
    if not await _may_run_as(db, call.caller, merged["run_as_user_id"]):
        raise await call.refused("you may not have a report run as that user", target=target)
    if merged["nas_id"]:
        async with db.execute("SELECT 1 FROM nas WHERE id = ?", (merged["nas_id"],)) as cur:
            if await cur.fetchone() is None:
                await bad("That NAS does not exist")
    if merged["ai_summary"]:
        if not merged["provider_id"]:
            await bad("A summary needs an AI provider")
        async with db.execute("SELECT 1 FROM ai_providers WHERE id = ?",
                              (merged["provider_id"],)) as cur:
            if await cur.fetchone() is None:
                await bad("That AI provider does not exist")


def _values(merged: dict[str, Any]) -> dict[str, Any]:
    values = dict(merged)
    for flag in ("enabled", "deliver", "ai_summary", "compare"):
        values[flag] = int(bool(merged[flag]))
    values["name"] = merged["name"].strip()
    values["nas_id"] = merged["nas_id"] or None
    values["provider_id"] = merged["provider_id"] or None
    return values


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/kinds")
async def list_kinds(call: Annotated[ActionCall, Depends(require("reports.list"))]):
    """What a report can be. Descriptions live here so the page and the PDF agree."""
    await call.done(detail="kinds")
    return [
        {"kind": "capacity", "title": TITLES["capacity"],
         "description": "How full pools, volumes and shares are, how fast they are filling, "
                        "and when they run out."},
        {"kind": "change", "title": TITLES["change"],
         "description": "What moved in the period: the biggest changes, anything that "
                        "shrank, and file counts."},
        {"kind": "health", "title": TITLES["health"],
         "description": "Flags raised and cleared, pool states, client mounts, and whether "
                        "collection itself kept up."},
        {"kind": "activity", "title": TITLES["activity"],
         "description": "What NASQuay did and who asked: actions, refusals and routine runs, "
                        "from the audit log."},
    ]


@router.get("", response_model=list[ReportOut])
async def list_reports(db: DbDep, call: Annotated[ActionCall, Depends(require("reports.list"))]):
    async with db.execute(_SELECT + " ORDER BY r.name") as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} reports")
    return [_out(row) for row in rows]


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report(
    body: ReportIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("reports.create"))],
):
    merged = body.model_dump()
    await _check(db, call, merged, body.name)
    values = _values(merged)
    try:
        cur = await db.execute(
            f"""INSERT INTO reports ({', '.join(COLUMNS)}, created_by)
                VALUES ({', '.join('?' * len(COLUMNS))}, ?)""",
            (*(values[c] for c in COLUMNS), call.caller.user_id),
        )
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a report with that name already exists", target=body.name)
        raise HTTPException(status.HTTP_409_CONFLICT, "A report with that name already exists")
    row = await _fetch(db, cur.lastrowid)
    await call.done(target=_target(row), detail=f"{body.kind}, {body.schedule_kind}")
    return _out(row)


@router.patch("/{report_id}", response_model=ReportOut)
async def update_report(
    report_id: int, body: ReportUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("reports.update"))],
):
    row = await _fetch(db, report_id)
    if row is None:
        await call.failed("report not found", target=f"report:{report_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    target = _target(row)
    await _authority(db, call, row)

    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    current = {c: dict(row)[c] for c in COLUMNS}
    merged = current | changes
    await _check(db, call, merged, target)

    values = _values(merged)
    sets = [f"{c} = ?" for c in COLUMNS]
    params = [values[c] for c in COLUMNS]
    if any(c in changes and changes[c] != current[c] for c in SCHEDULE_FIELDS):
        sets.append("schedule_from = datetime('now')")
    sets += ["updated_at = datetime('now')", "updated_by = ?"]
    params.append(call.caller.user_id)
    try:
        await db.execute(f"UPDATE reports SET {', '.join(sets)} WHERE id = ?",
                         (*params, report_id))
        await db.commit()
    except sqlite3.IntegrityError:
        await db.rollback()
        await call.failed("a report with that name already exists", target=target)
        raise HTTPException(status.HTTP_409_CONFLICT, "A report with that name already exists")
    await call.done(target=target, detail=", ".join(changes) or "no changes")
    return _out(await _fetch(db, report_id))


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("reports.delete"))],
) -> None:
    row = await _fetch(db, report_id)
    if row is None:
        await call.failed("report not found", target=f"report:{report_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    await _authority(db, call, row)
    await db.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    await db.commit()
    await call.done(target=_target(row), detail="and everything it produced")


@router.post("/{report_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_report(
    report_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("reports.run"))],
):
    row = await _fetch(db, report_id)
    if row is None:
        await call.failed("report not found", target=f"report:{report_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    await _authority(db, call, row)
    async with db.execute(
        "SELECT 1 FROM report_runs WHERE report_id = ? AND status IN ('queued', 'running')",
        (report_id,),
    ) as cur:
        if await cur.fetchone():
            await call.failed("already queued or running", target=_target(row))
            raise HTTPException(status.HTTP_409_CONFLICT, "It is already queued or running")
    cur = await db.execute(
        """INSERT INTO report_runs (report_id, trigger, requested_by, status)
           VALUES (?, 'manual', ?, 'queued')""",
        (report_id, call.caller.user_id),
    )
    await db.commit()
    await call.done(target=_target(row), detail=f"queued run {cur.lastrowid}")
    return {"run_id": cur.lastrowid}


_RUNS = """
    SELECT x.id, x.report_id, r.name AS report_name, r.kind, x.trigger, x.status,
           x.queued_at, x.started_at, x.finished_at, x.summary, x.error, x.delivered,
           x.figures, r.run_as_user_id
    FROM report_runs x JOIN reports r ON r.id = x.report_id
"""


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    db: DbDep, call: Annotated[ActionCall, Depends(require("reports.list"))],
    report_id: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
):
    """Every report produced, newest first — without their figures, which are large."""
    where, params = [], []
    if report_id:
        where.append("x.report_id = ?")
        params.append(report_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    async with db.execute(f"{_RUNS}{clause} ORDER BY x.id DESC LIMIT ?", (*params, limit)) as cur:
        rows = await cur.fetchall()
    allowed = []
    for row in rows:
        if await _may_run_as(db, call.caller, row["run_as_user_id"]):
            allowed.append(RunOut(**{**dict(row), "figures": None}))
    await call.done(detail=f"{len(allowed)} runs")
    return allowed


async def _run_row(db, call: ActionCall, run_id: int):
    async with db.execute(_RUNS + " WHERE x.id = ?", (run_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        await call.failed("report not found", target=f"report run:{run_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That report was not found")
    # A report shows what its run-as user could see, so it is read by somebody who could
    # have run it as that user, and nobody else.
    if not await _may_run_as(db, call.caller, row["run_as_user_id"]):
        raise await call.refused("this report runs as a user above your own role",
                                 target=f"report run:{run_id}")
    return row


@router.get("/runs/{run_id}", response_model=RunOut)
async def read_run(
    run_id: int, db: DbDep, call: Annotated[ActionCall, Depends(require("reports.list"))]
):
    row = await _run_row(db, call, run_id)
    await call.done(target=f"report run:{run_id}", detail=row["report_name"])
    return RunOut(**{**dict(row), "figures": json.loads(row["figures"] or "{}")})


@router.get("/runs/{run_id}/document")
async def download(
    run_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("reports.download"))],
    format: str = Query("pdf", pattern="^(pdf|csv)$"),
):
    row = await _run_row(db, call, run_id)
    figures = json.loads(row["figures"] or "{}")
    if not figures:
        await call.failed("that report produced nothing", target=f"report run:{run_id}")
        raise HTTPException(status.HTTP_409_CONFLICT, "That report produced nothing to download")
    if format == "csv":
        content = await run_in_threadpool(render.csv_bytes, figures)
        media = "text/csv; charset=utf-8"
    else:
        content = await run_in_threadpool(render.pdf_bytes, figures)
        media = "application/pdf"
    name = render.filename(figures, run_id, format)
    await call.done(target=f"report run:{run_id}", detail=f"{format}, {len(content)} bytes")
    return Response(
        content=content, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
