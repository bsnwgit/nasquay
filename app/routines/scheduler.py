"""
When routines run.

One loop, in whichever process keeps the monitoring schedule — the worker normally, the
web process when collection_in_web is set. Each tick it queues any routine whose time has
come, then starts every queued run. "Run now" in the interface only queues a run, so it
starts here within one tick, and a run is never shared between two processes.

A routine never runs twice at once: one that is queued or running is not queued again,
and a run longer than its interval delays the next rather than piling up.

Times are the installation's time zone for "daily at 07:00", and UTC everywhere they are
stored.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app import settings_store
from app.database import connect
from app.routines import engine

log = logging.getLogger("nasquay.routines")

TICK_SECONDS = 15
STORED = "%Y-%m-%d %H:%M:%S"

_task: Optional[asyncio.Task] = None
_active: dict[int, asyncio.Task] = {}      # routine id -> its running run


def _parse(value: str) -> datetime:
    return datetime.strptime(value[:19], STORED).replace(tzinfo=timezone.utc)


def last_slot(routine, now: datetime, zone: ZoneInfo) -> Optional[datetime]:
    """The most recent moment this routine was due, in UTC — or None for a routine that
    runs only when somebody presses Run."""
    kind = routine["schedule_kind"]
    if kind == "manual":
        return None
    if kind == "interval":
        # Due every N minutes after the schedule was set, whatever the clock says.
        start = _parse(routine["schedule_from"])
        step = timedelta(minutes=int(routine["interval_minutes"]))
        if now < start + step:
            return None
        return start + step * ((now - start) // step)

    hour, minute = (int(part) for part in str(routine["at_time"]).split(":"))
    local = now.astimezone(zone)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    if kind == "weekly":
        slot -= timedelta(days=(slot.weekday() - int(routine["weekday"])) % 7)
    return slot.astimezone(timezone.utc)


async def _queue_due(db) -> None:
    zone_name = (await settings_store.get_all(db)).get("timezone") or "UTC"
    try:
        zone = ZoneInfo(zone_name)
    except Exception:
        zone = ZoneInfo("UTC")
    now = datetime.now(timezone.utc)

    async with db.execute(
        """SELECT r.*,
                  (SELECT MAX(queued_at) FROM routine_runs x
                   WHERE x.routine_id = r.id AND x.trigger = 'schedule') AS last_scheduled,
                  (SELECT COUNT(*) FROM routine_runs x
                   WHERE x.routine_id = r.id AND x.status IN ('queued', 'running')) AS pending
           FROM routines r WHERE r.enabled = 1 AND r.schedule_kind != 'manual'"""
    ) as cur:
        routines = await cur.fetchall()

    for routine in routines:
        if routine["pending"]:
            continue
        slot = last_slot(routine, now, zone)
        if slot is None:
            continue
        # A slot before the schedule was set, or one already run, is not due.
        floor = _parse(routine["schedule_from"])
        if routine["last_scheduled"]:
            floor = max(floor, _parse(routine["last_scheduled"]))
        if slot <= floor:
            continue
        await db.execute(
            "INSERT INTO routine_runs (routine_id, trigger, status) VALUES (?, 'schedule', 'queued')",
            (routine["id"],),
        )
        log.info("Routine %s queued for its %s slot", routine["name"],
                 slot.strftime("%Y-%m-%d %H:%M UTC"))
    await db.commit()


async def _run(run_id: int) -> None:
    db = await connect()
    try:
        await engine.execute(db, run_id)
    except Exception:
        log.exception("Routine run %s could not be recorded", run_id)
    finally:
        await db.close()


async def _tick() -> None:
    db = await connect()
    try:
        await _queue_due(db)
        async with db.execute(
            "SELECT id, routine_id FROM routine_runs WHERE status = 'queued' ORDER BY id"
        ) as cur:
            queued = await cur.fetchall()
    finally:
        await db.close()

    for run in queued:
        routine_id = run["routine_id"]
        running = _active.get(routine_id)
        if running is not None and not running.done():
            continue
        _active[routine_id] = asyncio.create_task(_run(run["id"]))


async def _abandon_stale() -> None:
    """A run left 'running' by a process that stopped will never finish; say so."""
    db = await connect()
    try:
        cur = await db.execute(
            """UPDATE routine_runs SET status = 'error', finished_at = datetime('now'),
                      error = 'NASQuay stopped while this was running'
               WHERE status = 'running'"""
        )
        await db.commit()
        if cur.rowcount:
            log.warning("Marked %d interrupted routine run(s)", cur.rowcount)
    finally:
        await db.close()


async def _loop() -> None:
    try:
        await _abandon_stale()
    except Exception:
        log.exception("Could not tidy interrupted routine runs")
    while True:
        try:
            await _tick()
        except Exception:
            log.exception("Routine schedule tick failed")
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
