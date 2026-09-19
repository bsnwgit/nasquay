"""
/api/monitoring — what is watched, what was read, and what fired.

Collection is the same shape as everything else here: an action, checked against the
caller's role and written to the audit log. The worker will call the same functions when
it exists, which is why the work itself lives in app/monitoring/ and not in this module.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import crypto
from app import keys
from app.config import get_settings
from app.connectors import qnap_mcp, ssh
from app.dependencies import ActionCall, CurrentCaller, DbDep, require
from app.monitoring import backfill, collector, rules
from app import settings_store

router = APIRouter()


class TargetOut(BaseModel):
    id: int
    nas_id: int
    nas: str
    kind: str
    ref: str
    label: str
    # For a share, the volume it lives on; for a mount, the share it should hold.
    parent_ref: str = ""
    enabled: bool
    client_id: Optional[int] = None
    first_seen: str
    last_seen: str
    last_reading_at: Optional[str] = None


class TargetUpdate(BaseModel):
    enabled: bool


class ReadingOut(BaseModel):
    taken_at: str
    target_id: int
    metric: str
    value: Optional[int]
    source: str
    rounded: bool
    cached: bool
    backfilled: bool


class FlagOut(BaseModel):
    id: int
    raised_at: str
    rule: str
    target_id: Optional[int]
    nas_id: Optional[int]
    severity: str
    detail: str
    value: Optional[int]
    previous: Optional[int]
    cleared_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledged_by: str


class CollectIn(BaseModel):
    nas_id: int = Field(ge=1)
    tier: str = Field(default=collector.FAST, pattern="^(fast|slow|client)$")


class CollectOut(BaseModel):
    nas: str
    tier: str
    readings: int
    problems: list[str]
    run_id: int
    flags_raised: int = 0
    flags_cleared: int = 0
    flags_open: int = 0


# ── helpers ───────────────────────────────────────────────────────────────────

async def _nas_row(db, nas_id: int):
    async with db.execute(
        """SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token,
                  ssh_user, ssh_port, enabled,
                  (SELECT pem FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_ca_pem
           FROM nas WHERE id = ?""",
        (nas_id,),
    ) as cur:
        return await cur.fetchone()


def _mcp_target(row, token: str) -> qnap_mcp.Target:
    return qnap_mcp.Target(
        address=row["address"], port=row["mcp_port"], token=token,
        tls_mode=row["tls_mode"], fingerprint=row["tls_fingerprint"],
        ca_pem=row["tls_ca_pem"] or "",
    )


def _ssh_target(row) -> Optional[ssh.Target]:
    if not row["ssh_user"]:
        return None
    return ssh.Target(
        address=row["address"], user=row["ssh_user"], port=row["ssh_port"],
        key_path=get_settings().ssh_key_path,
    )


# ── targets ───────────────────────────────────────────────────────────────────

@router.get("/targets", response_model=list[TargetOut])
async def list_targets(
    db: DbDep, call: Annotated[ActionCall, Depends(require("monitoring.read"))]
):
    async with db.execute(
        """SELECT t.*, n.name AS nas,
                  (SELECT MAX(taken_at) FROM readings r WHERE r.target_id = t.id)
                      AS last_reading_at
           FROM targets t JOIN nas n ON n.id = t.nas_id
           ORDER BY n.name, t.kind, t.ref"""
    ) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} targets")
    return [TargetOut(**{**dict(row), "enabled": bool(row["enabled"])}) for row in rows]


@router.patch("/targets/{target_id}", response_model=TargetOut)
async def update_target(
    target_id: int, body: TargetUpdate, db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.update"))],
):
    async with db.execute("SELECT id FROM targets WHERE id = ?", (target_id,)) as cur:
        if await cur.fetchone() is None:
            await call.failed("target not found", target=f"target:{target_id}")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Target not found")
    await db.execute(
        "UPDATE targets SET enabled = ? WHERE id = ?", (int(body.enabled), target_id)
    )
    await db.commit()
    await call.done(target=f"target:{target_id}",
                    detail="watched" if body.enabled else "not watched")
    async with db.execute(
        """SELECT t.*, n.name AS nas,
                  (SELECT MAX(taken_at) FROM readings r WHERE r.target_id = t.id)
                      AS last_reading_at
           FROM targets t JOIN nas n ON n.id = t.nas_id WHERE t.id = ?""",
        (target_id,),
    ) as cur:
        row = await cur.fetchone()
    return TargetOut(**{**dict(row), "enabled": bool(row["enabled"])})


@router.post("/discover/{nas_id}")
async def discover(
    nas_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.discover"))],
):
    """Ask a NAS what there is to watch. Nothing is ever removed — a target that stops
    being reported keeps its history and simply stops gaining readings."""
    row = await _nas_row(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    token = crypto.decrypt_str(row["mcp_token"])
    if not token:
        await call.failed("no token", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No token is set for {row['name']}")

    try:
        found, problems = await run_in_threadpool(collector.discover, _mcp_target(row, token))
    except qnap_mcp.McpError as exc:
        await call.failed(str(exc), target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    added = 0
    for item in found:
        async with db.execute(
            "SELECT id FROM targets WHERE nas_id = ? AND kind = ? AND ref = ?",
            (nas_id, item.kind, item.ref),
        ) as cur:
            existing = await cur.fetchone()
        if existing is None:
            await db.execute(
                "INSERT INTO targets (nas_id, kind, ref, label, parent_ref) VALUES (?, ?, ?, ?, ?)",
                (nas_id, item.kind, item.ref, item.label, item.parent_ref),
            )
            added += 1
        else:
            await db.execute(
                """UPDATE targets SET last_seen = datetime('now'), label = ?, parent_ref = ?
                   WHERE id = ?""",
                (item.label, item.parent_ref, existing["id"]),
            )
    await db.commit()
    await call.done(target=f"nas:{nas_id}", detail=f"{len(found)} found, {added} new")
    return {"nas": row["name"], "found": len(found), "added": added, "problems": problems}


# ── collection ────────────────────────────────────────────────────────────────

@router.post("/collect", response_model=CollectOut)
async def collect_now(
    body: CollectIn, db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.collect"))],
):
    row = await _nas_row(db, body.nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{body.nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    if not row["enabled"]:
        await call.failed("NAS is disabled", target=f"nas:{body.nas_id}")
        raise HTTPException(status.HTTP_409_CONFLICT, f"{row['name']} is disabled")

    watched = await _watched(db, body.nas_id)
    if not watched:
        await call.failed("nothing is being watched on this NAS", target=f"nas:{body.nas_id}")
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Nothing is being watched on this NAS yet — discover first")

    token = crypto.decrypt_str(row["mcp_token"])
    cursor = await db.execute(
        "INSERT INTO collection_runs (tier) VALUES (?)", ("manual",)
    )
    run_id = cursor.lastrowid
    await db.commit()

    outcome = await run_in_threadpool(
        collector.collect,
        _mcp_target(row, token) if token else None,
        _ssh_target(row),
        watched,
        body.tier,
        get_settings().ssh_key_path,
    )

    await _write(db, outcome.readings)
    status_word = "ok" if not outcome.problems else ("partial" if outcome.readings else "failed")
    await db.execute(
        """UPDATE collection_runs SET finished_at = datetime('now'), status = ?,
                                      readings = ?, detail = ?
           WHERE id = ?""",
        (status_word, len(outcome.readings), " · ".join(outcome.problems)[:500], run_id),
    )
    await db.commit()

    # Rules run on what was just read: a reading nobody looks at is not monitoring.
    settings = await settings_store.get_all(db)
    firing = await rules.evaluate(db, body.nas_id, settings)
    counts = await rules.apply(db, body.nas_id, firing)
    await rules.apply_global(db, await rules.collection_stale(db, settings))

    await call.done(
        target=f"nas:{row['name']}",
        detail=f"{body.tier}: {len(outcome.readings)} readings, {status_word}, "
               f"{counts['firing']} rules firing",
    )
    return CollectOut(nas=row["name"], tier=body.tier, readings=len(outcome.readings),
                      problems=outcome.problems, run_id=run_id,
                      flags_raised=counts["raised"], flags_cleared=counts["cleared"],
                      flags_open=counts["firing"])


async def _write(db, readings, backfilled: bool = False) -> None:
    """Store readings. One that carries its own moment keeps it; the rest are now."""
    for reading in readings:
        if reading.taken_at:
            await db.execute(
                """INSERT INTO readings
                       (taken_at, target_id, metric, value, source, rounded, cached,
                        backfilled, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (reading.taken_at, reading.target_id, reading.metric, reading.value,
                 reading.source, int(reading.rounded), int(reading.cached),
                 int(backfilled), reading.raw),
            )
        else:
            await db.execute(
                """INSERT INTO readings
                       (target_id, metric, value, source, rounded, cached, backfilled, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (reading.target_id, reading.metric, reading.value, reading.source,
                 int(reading.rounded), int(reading.cached), int(backfilled), reading.raw),
            )


@router.post("/backfill/{nas_id}")
async def import_history(
    nas_id: int, db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.backfill"))],
):
    """Import the NAS's own usage history, so there is a baseline from day one.

    Safe to repeat: everything previously imported for these targets is replaced, so a
    second run corrects the first rather than doubling it."""
    row = await _nas_row(db, nas_id)
    if row is None:
        await call.failed("NAS not found", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not found")
    token = crypto.decrypt_str(row["mcp_token"])
    if not token:
        await call.failed("no token", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"No token is set for {row['name']}")

    watched = await _watched(db, nas_id)
    wanted = [one for one in watched if one.kind in ("volume", "pool")]
    if not wanted:
        await call.failed("no volumes or pools are watched", target=f"nas:{nas_id}")
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "No volumes or pools are watched on this NAS")

    imported = await run_in_threadpool(backfill.history, _mcp_target(row, token), wanted)

    # Replace rather than add to, so running it twice cannot double a series.
    for target in wanted:
        await db.execute(
            "DELETE FROM readings WHERE target_id = ? AND backfilled = 1", (target.id,)
        )
    await _write(db, imported.readings, backfilled=True)
    await db.commit()

    await call.done(target=f"nas:{row['name']}",
                    detail=f"{len(imported.readings)} historical readings")
    return {
        "nas": row["name"],
        "readings": len(imported.readings),
        "windows": imported.windows,
        "problems": imported.problems,
    }


async def _watched(db, nas_id: int) -> list[collector.Watched]:
    """Enabled targets for one NAS, with a share attached to each volume so `df` has a
    path — QNAP's /share/<name> is a symlink onto the volume the share lives on."""
    async with db.execute(
        """SELECT t.id, t.kind, t.ref, t.label, t.parent_ref,
                  c.name AS client_name, c.address AS client_address,
                  c.ssh_user AS client_user, c.ssh_port AS client_port,
                  c.key_name AS client_key
           FROM targets t LEFT JOIN clients c ON c.id = t.client_id AND c.enabled = 1
           WHERE t.nas_id = ? AND t.enabled = 1""",
        (nas_id,),
    ) as cur:
        rows = await cur.fetchall()

    watched = [
        collector.Watched(
            id=r["id"], kind=r["kind"], ref=r["ref"], label=r["label"],
            parent_ref=r["parent_ref"],
            client=collector.ClientTarget(
                name=r["client_name"], address=r["client_address"],
                user=r["client_user"], port=r["client_port"],
                key_path=(keys.path_for(r["client_key"]) if r["client_key"]
                          else get_settings().ssh_key_path),
            ) if r["client_name"] else None,
        )
        for r in rows
    ]
    # A volume is measured through a share that actually lives on it. A volume with no
    # watched share gets no `df` reading rather than another volume's figures.
    for volume in (w for w in watched if w.kind == "volume"):
        for share in (w for w in watched if w.kind == "share" and w.parent_ref == volume.ref):
            volume.via_share = share.ref
            break
    return watched


# ── readings and flags ────────────────────────────────────────────────────────

@router.get("/readings", response_model=list[ReadingOut])
async def list_readings(
    db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    target_id: Optional[int] = None,
    metric: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
):
    where: list[str] = []
    params: list[Any] = []
    if target_id is not None:
        where.append("target_id = ?")
        params.append(target_id)
    if metric:
        where.append("metric = ?")
        params.append(metric)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)
    async with db.execute(
        f"""SELECT taken_at, target_id, metric, value, source, rounded, cached, backfilled
            FROM readings {clause} ORDER BY taken_at DESC, id DESC LIMIT ?""",
        params,
    ) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} readings")
    return [
        ReadingOut(**{**dict(row), "rounded": bool(row["rounded"]),
                      "cached": bool(row["cached"]), "backfilled": bool(row["backfilled"])})
        for row in rows
    ]


class AcknowledgeIn(BaseModel):
    clear: bool = False


@router.patch("/flags/{flag_id}", response_model=FlagOut)
async def acknowledge(
    flag_id: int, body: AcknowledgeIn, db: DbDep, caller: CurrentCaller,
    call: Annotated[ActionCall, Depends(require("monitoring.acknowledge"))],
):
    """Mark a flag as seen, and optionally close it.

    Clearing by hand does not stop the rule: if the condition still holds, the next
    collection raises it again."""
    async with db.execute("SELECT id FROM flags WHERE id = ?", (flag_id,)) as cur:
        if await cur.fetchone() is None:
            await call.failed("flag not found", target=f"flag:{flag_id}")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Flag not found")
    await db.execute(
        """UPDATE flags
              SET acknowledged_at = datetime('now'), acknowledged_by = ?,
                  cleared_at = CASE WHEN ? THEN datetime('now') ELSE cleared_at END
            WHERE id = ?""",
        (caller.username, int(body.clear), flag_id),
    )
    await db.commit()
    await call.done(target=f"flag:{flag_id}", detail="cleared" if body.clear else "acknowledged")
    async with db.execute("SELECT * FROM flags WHERE id = ?", (flag_id,)) as cur:
        row = await cur.fetchone()
    return FlagOut(**dict(row))


class RunOut(BaseModel):
    id: int
    tier: str
    status: str
    readings: int
    detail: str
    started_at: str
    finished_at: Optional[str] = None


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    limit: int = Query(default=20, ge=1, le=200),
):
    """Recent collection runs, whether they worked or not.

    A scheduled run that fails has nowhere else to be seen: nobody is watching when it
    happens, and a monitor whose own failures are silent is the thing it was built to
    prevent.
    """
    async with db.execute(
        """SELECT id, tier, status, readings, detail, started_at, finished_at
           FROM collection_runs ORDER BY id DESC LIMIT ?""",
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} runs")
    return [RunOut(**dict(row)) for row in rows]


@router.get("/flags", response_model=list[FlagOut])
async def list_flags(
    db: DbDep,
    call: Annotated[ActionCall, Depends(require("monitoring.read"))],
    open_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
):
    clause = "WHERE cleared_at IS NULL" if open_only else ""
    async with db.execute(
        f"SELECT * FROM flags {clause} ORDER BY raised_at DESC LIMIT ?", (limit,)
    ) as cur:
        rows = await cur.fetchall()
    await call.done(detail=f"{len(rows)} flags")
    return [FlagOut(**dict(row)) for row in rows]
