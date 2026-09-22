"""
When reports run.

The same loop shape as the routine schedule, and the same slot arithmetic — a report's
schedule means what a routine's does, so it is the same code rather than a second
version of it that drifts.

A report never runs twice at once, and "Run now" queues a run so that it starts here
whichever process asked for it.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app import settings_store
from app.database import connect
from app.reporting import engine
from app.routines.scheduler import TICK_SECONDS, _parse, last_slot

log = logging.getLogger("nasquay.reporting")

_task: Optional[asyncio.Task] = None
_active: dict[int, asyncio.Task] = {}


async def _queue_due(db) -> None:
    zone_name = (await settings_store.get_all(db)).get("timezone") or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo("UTC")
    now = datetime.now(timezone.utc)

    async with db.execute(
        """SELECT r.*,
                  (SELECT MAX(queued_at) FROM report_runs x
                   WHERE x.report_id = r.id AND x.trigger = 'schedule') AS last_scheduled,
                  (SELECT COUNT(*) FROM report_runs x
                   WHERE x.report_id = r.id AND x.status IN ('queued', 'running')) AS pending
           FROM reports r WHERE r.enabled = 1 AND r.schedule_kind != 'manual'"""
    ) as cur:
        reports = await cur.fetchall()

    for report in reports:
        if report["pending"]:
            continue
        slot = last_slot(report, now, zone)
        if slot is None:
            continue
        floor = _parse(report["schedule_from"])
        if report["last_scheduled"]:
            floor = max(floor, _parse(report["last_scheduled"]))
        if slot <= floor:
            continue
        await db.execute(
            "INSERT INTO report_runs (report_id, trigger, status) VALUES (?, 'schedule', 'queued')",
            (report["id"],),
        )
        log.info("Report %s queued for its %s slot", report["name"],
                 slot.strftime("%Y-%m-%d %H:%M UTC"))
    await db.commit()


async def _run(run_id: int) -> None:
    db = await connect()
    try:
        await engine.execute(db, run_id)
    except Exception:
        log.exception("Report run %s could not be recorded", run_id)
    finally:
        await db.close()


async def _tick() -> None:
    db = await connect()
    try:
        await _queue_due(db)
        async with db.execute(
            "SELECT id, report_id FROM report_runs WHERE status = 'queued' ORDER BY id"
        ) as cur:
            queued = await cur.fetchall()
    finally:
        await db.close()

    for run in queued:
        running = _active.get(run["report_id"])
        if running is not None and not running.done():
            continue
        _active[run["report_id"]] = asyncio.create_task(_run(run["id"]))


async def _abandon_stale() -> None:
    db = await connect()
    try:
        cur = await db.execute(
            """UPDATE report_runs SET status = 'error', finished_at = datetime('now'),
                      error = 'NASQuay stopped while this was running'
               WHERE status = 'running'"""
        )
        await db.commit()
        if cur.rowcount:
            log.warning("Marked %d interrupted report run(s)", cur.rowcount)
    finally:
        await db.close()


async def _loop() -> None:
    try:
        await _abandon_stale()
    except Exception:
        log.exception("Could not tidy interrupted report runs")
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("Report schedule tick failed")
        await asyncio.sleep(TICK_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    tasks = [t for t in [_task, *_active.values()] if t is not None and not t.done()]
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None
    _active.clear()
