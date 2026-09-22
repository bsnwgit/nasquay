"""
The data half of the assistant contract: what the panel may ask NASQuay about.

app/api/resonance.py mounts the panel. This is what the panel is allowed to *read* once
it is mounted, and it is a surface of its own rather than a grant over the ordinary API,
for the reasons the contract sets out:

  1. a spec at a stable same-origin path     -> /api/resonance/openapi.json
  2. a grant file naming what may be called  -> /.well-known/resonance.json
  3. operations that behave: bounded pages,
     a real total, stable operationIds,
     enums for every fixed vocabulary        -> /api/resonance/data/*

Publishing the spec grants nothing; the grant file is the ceiling, and it names reads
only. Nothing here changes anything — no acknowledgement, no collection, no settings, and
nothing that touches a NAS.

**Nothing here contacts a NAS.** Every answer comes from what NASQuay already recorded, so
a conversation cannot wake two boxes up or start a walk across 28 TB, and an assistant
asking the same question ten times costs ten SQLite reads.

Authentication is NASQuay's own session. The panel cannot set an Authorization header, so
the page performs these calls itself and posts the result back into the frame — which
means every one of them arrives as the signed-in person, through the same permission gate
and into the same audit log as any page. The panel can never read what the person could
not already read.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, Field

from app.dependencies import ActionCall, DbDep, require
from app.reporting import surface as reports_surface
from app.version import get_version

router = APIRouter()

# Every page is small on purpose. The model is given a page and a count — "eleven
# thousand matched, here are fifty" — so it asks a better question instead of being
# handed a corpus it cannot read.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100

SPEC_PATH = "/api/resonance/openapi.json"


# ── What comes back ───────────────────────────────────────────────────────────

class NasSummary(BaseModel):
    name: str = Field(description="The NAS's name in NASQuay")
    address: str = Field(description="Where NASQuay reaches it")
    enabled: bool
    last_checked_at: Optional[str] = Field(default=None, description="UTC, ISO 8601")
    last_check_ok: Optional[bool] = None
    last_check_detail: str = ""


class NasList(BaseModel):
    total: int = Field(description="How many NAS units matched, before the page")
    nas: list[NasSummary]


class MeasurementOut(BaseModel):
    nas: str
    kind: str = Field(description="pool, volume, share or client_mount")
    label: str = Field(description="What it is called on the NAS")
    ref: str = Field(description="What identifies it on the NAS")
    metric: str = Field(description="What was measured, e.g. used_bytes, file_count")
    value: Optional[int] = None
    taken_at: Optional[str] = Field(default=None, description="UTC, ISO 8601")
    source: str = Field(default="", description="mcp, ssh or client")
    cached: bool = Field(default=False, description="A figure the NAS computed earlier")
    rounded: bool = Field(default=False, description="Accuracy was lost before NASQuay saw it")


class MeasurementList(BaseModel):
    total: int
    measurements: list[MeasurementOut]


class FlagOut(BaseModel):
    id: int
    raised_at: str
    rule: str
    severity: str = Field(description="info, warning or error")
    nas: str = ""
    target: str = ""
    detail: str = ""
    value: Optional[int] = None
    previous: Optional[int] = None
    cleared_at: Optional[str] = None
    acknowledged_at: Optional[str] = None


class FlagList(BaseModel):
    total: int
    flags: list[FlagOut]


class HistoryPoint(BaseModel):
    taken_at: str
    value: Optional[int] = None


class HistoryOut(BaseModel):
    nas: str
    label: str
    metric: str
    total: int = Field(description="Points in the range, before the page")
    first: Optional[HistoryPoint] = None
    last: Optional[HistoryPoint] = None
    points: list[HistoryPoint]


class CollectionOut(BaseModel):
    """Whether the figures above are current — the question behind most others."""

    newest_reading_at: Optional[str] = None
    last_run_at: Optional[str] = None
    last_run_status: str = ""
    last_run_detail: str = ""
    open_flags: int = 0
    version: str = get_version()


# ── The operations ────────────────────────────────────────────────────────────

@router.get("/api/resonance/data/nas", response_model=NasList, operation_id="listNasUnits",
            summary="Look up a NAS by name. Every NAS name here is a label for one of this installation's own units, never anything else")
async def list_nas_units(
    db: DbDep, call: Annotated[ActionCall, Depends(require("nas.list"))],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """The NAS units NASQuay knows, and how each answered when it was last checked.

    START HERE whenever a question names a device, or names anything you do not already
    recognise. The names returned are the only NAS names that exist for this
    installation; they were chosen by an administrator and mean nothing outside it. Match
    what was asked against this list, ignoring case, before answering.

    A name that is not in this list is not a NAS here — say so, and say which ones are.
    """
    async with db.execute("SELECT COUNT(*) AS n FROM nas") as cur:
        total = (await cur.fetchone())["n"]
    async with db.execute(
        """SELECT name, address, enabled, last_checked_at, last_check_ok, last_check_detail
           FROM nas ORDER BY name LIMIT ?""",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"assistant: {len(rows)} NAS units")
    return NasList(
        total=total,
        nas=[
            NasSummary(
                name=r["name"], address=r["address"], enabled=bool(r["enabled"]),
                last_checked_at=r["last_checked_at"],
                last_check_ok=None if r["last_check_ok"] is None else bool(r["last_check_ok"]),
                last_check_detail=r["last_check_detail"],
            )
            for r in rows
        ],
    )


@router.get("/api/resonance/data/measurements", response_model=MeasurementList,
            operation_id="listMeasurements",
            summary="The shares, volumes and pools on each NAS, with their latest used space, free space and file counts")
async def list_measurements(
    db: DbDep, call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    nas: str = Query("", description="Restrict to one NAS. Use a name exactly as listNasUnits gave it; this is a label, not a place or an organisation."),
    kind: str = Query("", description="pool, volume, share or client_mount"),
    metric: str = Query("", description="e.g. used_bytes, free_bytes, file_count"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """The latest measurement of everything watched, newest reading per series.

    This is the answer to "what shares are on it", "how full is it" and "how many files
    are there". Ask with kind=share to list a NAS's shares. These are recorded figures,
    not a fresh reading, so nothing here contacts a NAS, and only what an administrator
    chose to watch is listed.
    """
    where = ["t.enabled = 1"]
    params: list[Any] = []
    if nas:
        where.append("n.name = ? COLLATE NOCASE")
        params.append(nas)
    if kind:
        where.append("t.kind = ?")
        params.append(kind)
    if metric:
        where.append("r.metric = ? COLLATE NOCASE")
        params.append(metric)
    clause = " AND ".join(where)

    # One row per target and metric: the newest reading of each series.
    sql = f"""
        SELECT n.name AS nas, t.kind, t.label, t.ref, r.metric, r.value, r.taken_at,
               r.source, r.cached, r.rounded
        FROM readings r
        JOIN targets t ON t.id = r.target_id
        JOIN nas n     ON n.id = t.nas_id
        WHERE {clause}
          AND r.id = (SELECT id FROM readings
                      WHERE target_id = r.target_id AND metric = r.metric
                      ORDER BY taken_at DESC, id DESC LIMIT 1)
    """
    async with db.execute(f"SELECT COUNT(*) AS n FROM ({sql})", params) as cur:
        total = (await cur.fetchone())["n"]
    async with db.execute(f"{sql} ORDER BY n.name, t.kind, t.label, r.metric LIMIT ?",
                          (*params, limit)) as cur:
        rows = await cur.fetchall()

    await call.done(detail=f"assistant: {len(rows)} measurements")
    return MeasurementList(
        total=total,
        measurements=[
            MeasurementOut(
                nas=r["nas"], kind=r["kind"], label=r["label"] or r["ref"], ref=r["ref"],
                metric=r["metric"], value=r["value"], taken_at=r["taken_at"],
                source=r["source"], cached=bool(r["cached"]), rounded=bool(r["rounded"]),
            )
            for r in rows
        ],
    )


@router.get("/api/resonance/data/flags", response_model=FlagList, operation_id="listFlags",
            summary="Conditions NASQuay has flagged")
async def list_flags(
    db: DbDep, call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    state: str = Query("open", description="open, cleared or all"),
    severity: str = Query("", description="info, warning or error"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """What NASQuay has flagged: a rule that fired, with what it saw and when."""
    where: list[str] = []
    params: list[Any] = []
    if state == "open":
        where.append("f.cleared_at IS NULL")
    elif state == "cleared":
        where.append("f.cleared_at IS NOT NULL")
    if severity:
        where.append("f.severity = ?")
        params.append(severity)
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    async with db.execute(f"SELECT COUNT(*) AS n FROM flags f {clause}", params) as cur:
        total = (await cur.fetchone())["n"]
    async with db.execute(
        f"""SELECT f.id, f.raised_at, f.rule, f.severity, f.detail, f.value, f.previous,
                   f.cleared_at, f.acknowledged_at,
                   COALESCE(n.name, '') AS nas, COALESCE(t.label, t.ref, '') AS target
            FROM flags f
            LEFT JOIN nas n     ON n.id = f.nas_id
            LEFT JOIN targets t ON t.id = f.target_id
            {clause}
            ORDER BY f.raised_at DESC LIMIT ?""",
        (*params, limit),
    ) as cur:
        rows = await cur.fetchall()

    await call.done(detail=f"assistant: {len(rows)} flags")
    return FlagList(total=total, flags=[FlagOut(**dict(r)) for r in rows])


@router.get("/api/resonance/data/history", response_model=HistoryOut, operation_id="readHistory",
            summary="One measurement over time")
async def read_history(
    db: DbDep, call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    nas: str = Query(..., description="The NAS's name in NASQuay"),
    label: str = Query(..., description="The pool, volume, share or mount, as listMeasurements names it"),
    metric: str = Query(..., description="e.g. used_bytes, file_count"),
    days: int = Query(30, ge=1, le=3650, description="How far back to look"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """One figure over time, with the oldest and newest points of the range named.

    The page is the most recent points; `first` and `last` are the ends of the whole
    range, so "how much has it changed" is answerable without reading every point.
    """
    params = (nas, label, label, metric, days)
    base = """
        FROM readings r
        JOIN targets t ON t.id = r.target_id
        JOIN nas n     ON n.id = t.nas_id
        WHERE n.name = ? COLLATE NOCASE
          AND (t.label = ? COLLATE NOCASE OR t.ref = ? COLLATE NOCASE)
          AND r.metric = ? COLLATE NOCASE
          AND r.taken_at >= datetime('now', '-' || ? || ' days')
    """
    async with db.execute(f"SELECT COUNT(*) AS n {base}", params) as cur:
        total = (await cur.fetchone())["n"]
    async with db.execute(
        f"SELECT r.taken_at, r.value {base} ORDER BY r.taken_at DESC LIMIT ?", (*params, limit)
    ) as cur:
        rows = await cur.fetchall()
    async with db.execute(
        f"SELECT r.taken_at, r.value {base} ORDER BY r.taken_at ASC LIMIT 1", params
    ) as cur:
        oldest = await cur.fetchone()

    points = [HistoryPoint(taken_at=r["taken_at"], value=r["value"]) for r in rows]
    await call.done(detail=f"assistant: {len(points)} points of {metric}")
    return HistoryOut(
        nas=nas, label=label, metric=metric, total=total,
        first=HistoryPoint(taken_at=oldest["taken_at"], value=oldest["value"]) if oldest else None,
        last=points[0] if points else None,
        points=points,
    )


@router.get("/api/resonance/data/reports", operation_id="listReports",
            summary="The reports set up here, and when each was last produced")
async def list_reports(
    db: DbDep, call: Annotated[ActionCall, Depends(require("reports.list"))],
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    """What this installation reports on: capacity, change, health and activity, over a
    period somebody chose. Ask before readReport, which needs a name from here.

    Only reports this person could have produced themselves are listed.
    """
    answer = await reports_surface.list_reports(db, call.caller, limit)
    await call.done(detail=f"assistant: {answer['total']} reports")
    return answer


@router.get("/api/resonance/data/reports/read", operation_id="readReport",
            summary="Read the newest report of that name")
async def read_report(
    db: DbDep, call: Annotated[ActionCall, Depends(require("reports.list"))],
    name: str = Query(..., description="The report's name, exactly as listReports gives it"),
):
    """The figures of the newest report of that name that was produced, with its summary.

    Reports are built from figures NASQuay already recorded, so what comes back is as old
    as the report says it is — `produced_at` is part of the answer for that reason.
    """
    answer = await reports_surface.read_report(db, call.caller, name)
    await call.done(detail=f"assistant: report {name}"[:200])
    return answer


@router.get("/api/resonance/data/collection", response_model=CollectionOut,
            operation_id="getCollectionStatus")
async def collection_status(
    db: DbDep, call: Annotated[ActionCall, Depends(require("monitoring.read"))]
):
    """Whether the recorded figures are current, and how many flags are open.

    Worth asking before any other question here: a calm answer built on stale readings is
    worse than no answer.
    """
    async with db.execute("SELECT MAX(taken_at) AS at FROM readings") as cur:
        newest = (await cur.fetchone())["at"]
    async with db.execute(
        """SELECT started_at, status, detail FROM collection_runs
           ORDER BY id DESC LIMIT 1"""
    ) as cur:
        run = await cur.fetchone()
    async with db.execute("SELECT COUNT(*) AS n FROM flags WHERE cleared_at IS NULL") as cur:
        open_flags = (await cur.fetchone())["n"]

    await call.done(detail="assistant: collection status")
    return CollectionOut(
        newest_reading_at=newest,
        last_run_at=run["started_at"] if run else None,
        last_run_status=run["status"] if run else "",
        last_run_detail=(run["detail"] if run else "") or "",
        open_flags=open_flags,
    )


# ── The two documents resonance reads ─────────────────────────────────────────
#
# The spec describes only the operations above — not NASQuay's whole API. A model handed
# every route would spend its attention on the ones it may not call, and an operation it
# cannot reach is noise at best and a wrong answer at worst.
#
# The grant file is the ceiling, and it is served from this origin because that is the
# whole of its authenticity: anyone can serve a file claiming to speak for an
# application, but only this application answers on this name.

# Named by operationId, which is the only identifier stable enough to grant against: a
# path gets rewritten by a refactor and the grant would silently withdraw itself.
GRANTED = ("listNasUnits", "listMeasurements", "listFlags", "readHistory",
           "listReports", "readReport",
           "getCollectionStatus")


GROUNDING = (
    "This is NASQuay, which runs the NAS units of one installation. Names of NAS units, "
    "shares, pools and volumes are labels its administrator chose. Never read one as a "
    "place, organisation, person or product: look it up here. Answer only from these "
    "operations, never from general knowledge."
)


def _spec_for(app: FastAPI) -> dict[str, Any]:
    """This module's routes, as their own document.

    Built from the router's own routes rather than by filtering the application's: the
    router is exactly these operations and nothing else, so there is no filter to get
    subtly wrong — and getting it wrong produces a document with no operations in it,
    which resonance can read and cannot use.
    """
    routes = list(router.routes)
    spec = get_openapi(
        title="NASQuay — what the assistant may ask",
        version=get_version(),
        description=(
            "NASQuay operates the QNAP NAS units of ONE installation. Every question put "
            "to this assistant is about those units and nothing else.\n\n"

            "NAMES ARE LABELS. A NAS, share, pool or volume is called whatever the "
            "administrator here named it. Those names are arbitrary and frequently "
            "collide with the names of organisations, places, people or products that "
            "have nothing to do with this installation. A name is never to be "
            "interpreted, corrected, or treated as a reference to anything in the wider "
            "world: it is a label to be looked up. If a question names something not "
            "already known, call listNasUnits and match it there — case-insensitively — "
            "before answering or asking for clarification.\n\n"

            "ANSWER ONLY FROM THESE OPERATIONS. Everything needed is here. If these "
            "operations cannot answer something, say plainly that NASQuay does not hold "
            "it — do not answer from general knowledge, and do not explain what a word "
            "means outside this installation.\n\n"

            "Nothing here contacts a NAS; every answer is what NASQuay already recorded, "
            "and each measurement carries the moment it was taken, so say how old a "
            "figure is when it matters. Nothing here changes anything. Every call is "
            "made as the signed-in person and is refused if their role does not allow "
            "it. Sizes are bytes; every time is UTC."
        ),
        routes=routes,
    )
    # Resonance hands the model each operation's own summary and description and drops
    # the document's, so the rule that matters most rides on every operation. Without it
    # a small model asked about a NAS called NASA explains the space agency instead of
    # looking it up.
    for methods in spec.get("paths", {}).values():
        for operation in methods.values():
            operation["description"] = GROUNDING + "\n\n" + operation.get("description", "")
    return spec


def attach(app: FastAPI) -> None:
    """Serve the spec and the grant file. Both are public documents by necessity:
    resonance fetches the grant file without a session, and it names what may be called
    rather than answering with any of it."""

    @app.get("/api/resonance/openapi.json", include_in_schema=False)
    async def resonance_spec() -> dict[str, Any]:
        return _spec_for(app)

    @app.get("/.well-known/resonance.json", include_in_schema=False)
    async def resonance_grant() -> dict[str, Any]:
        # Reads only. `writes` is declared, never inferred, and there is nothing here to
        # declare: an operation that changed something would need a person's
        # confirmation, and this surface has none to change.
        return {
            "resonance": 1,
            "spec": SPEC_PATH,
            "allow": [{"op": name} for name in GRANTED],
        }
