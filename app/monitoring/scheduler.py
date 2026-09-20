"""
Collection on a schedule, so history builds itself.

A monitor that only runs when somebody presses a button is not a monitor: the readings
that matter are the ones taken while nobody was watching. This keeps two loops, at the
two costs the measurements actually have.

  **Fast** — pool status, volume capacity and free space, and `df`. Seconds, so it runs
  every few minutes.

  **Deep** — `du` and a live `find` across every watched share. Minutes on a large share,
  so it runs a few times a day.

This runs in the `nasquay-worker` process, so that a collection walking a large share is
not interrupted every time the interface is restarted. An install without a worker sets
`collection_in_web` in config.yaml and the web process keeps the schedule instead; the
work is identical either way, since it calls exactly what the /api/monitoring endpoints
call.

Two things keep it honest. A run that is already going is never started twice — a deep
read taking longer than its interval delays the next one rather than piling up. And every
run is recorded in collection_runs whether it succeeded or not, which is what lets a rule
notice that collection itself has stopped.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app import crypto, settings_store
from app import keys
from app.config import get_settings
from app.connectors import qnap_mcp, ssh
from app.database import connect
from app.monitoring import collector, rules

log = logging.getLogger("nasquay.monitoring")

# How often the loop wakes to ask whether anything is due. Not the collection interval.
TICK_SECONDS = 30

_task: Optional[asyncio.Task] = None


async def _due(db, tier: str, minutes: int) -> bool:
    """Has it been long enough since the last run of this tier that finished?"""
    async with db.execute(
        """SELECT started_at FROM collection_runs
           WHERE tier = ? ORDER BY started_at DESC LIMIT 1""",
        (tier,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return True
    async with db.execute(
        "SELECT datetime(?, ?) <= datetime('now') AS ready", (row["started_at"], f"+{minutes} minutes")
    ) as cur:
        answer = await cur.fetchone()
    return bool(answer["ready"])


async def _watched(db, nas_id: int) -> list[collector.Watched]:
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
    for volume in (w for w in watched if w.kind == "volume"):
        for share in (w for w in watched if w.kind == "share" and w.parent_ref == volume.ref):
            volume.via_share = share.ref
            break
    return watched


async def run_tier(db, tier: str) -> dict[str, Any]:
    """One pass of a tier across every enabled NAS."""
    cursor = await db.execute("INSERT INTO collection_runs (tier) VALUES (?)", (tier,))
    run_id = cursor.lastrowid
    await db.commit()

    async with db.execute(
        """SELECT id, name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token,
                  ssh_user, ssh_port,
                  (SELECT pem FROM certificates WHERE certificates.id = nas.tls_cert_id) AS tls_ca_pem
           FROM nas WHERE enabled = 1"""
    ) as cur:
        units = list(await cur.fetchall())

    settings = await settings_store.get_all(db)
    total = 0
    problems: list[str] = []

    for row in units:
        watched = await _watched(db, row["id"])
        if not watched:
            continue
        token = crypto.decrypt_str(row["mcp_token"])
        mcp = qnap_mcp.Target(
            address=row["address"], port=row["mcp_port"], token=token,
            tls_mode=row["tls_mode"], fingerprint=row["tls_fingerprint"],
            ca_pem=row["tls_ca_pem"] or "",
        ) if token else None
        sshing = ssh.Target(
            address=row["address"], user=row["ssh_user"], port=row["ssh_port"],
            key_path=get_settings().ssh_key_path,
        ) if row["ssh_user"] else None

        try:
            outcome = await asyncio.to_thread(collector.collect, mcp, sshing, watched, tier,
                                        get_settings().ssh_key_path)
        except Exception as exc:  # a NAS falling over must not stop the loop
            problems.append(f"{row['name']}: {exc}")
            log.warning("Collection failed for %s: %s", row["name"], exc)
            continue

        for reading in outcome.readings:
            await db.execute(
                """INSERT INTO readings (target_id, metric, value, source, rounded, cached, raw)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (reading.target_id, reading.metric, reading.value, reading.source,
                 int(reading.rounded), int(reading.cached), reading.raw),
            )
        total += len(outcome.readings)
        problems += [f"{row['name']}: {one}" for one in outcome.problems]
        await db.commit()

        firing = await rules.evaluate(db, row["id"], settings)
        await rules.apply(db, row["id"], firing)

    status = "ok" if not problems else ("partial" if total else "failed")
    await db.execute(
        """UPDATE collection_runs SET finished_at = datetime('now'), status = ?,
                                      readings = ?, detail = ?
           WHERE id = ?""",
        (status, total, " · ".join(problems)[:500], run_id),
    )
    await db.commit()
    await rules.apply_global(db, await rules.collection_stale(db, settings))
    log.info("Scheduled %s collection: %d readings, %s", tier, total, status)
    return {"tier": tier, "readings": total, "status": status}


async def _loop() -> None:
    # Once, at startup: anything left "running" belongs to a process that is gone.
    try:
        db = await connect()
        try:
            closed = await abandon_stale(db)
            if closed:
                log.info("Closed %d collection run(s) left by an earlier process", closed)
        finally:
            await db.close()
    except Exception:
        log.exception("Could not close abandoned collection runs")

    while True:
        try:
            db = await connect()
            try:
                settings = await settings_store.get_all(db)
                if settings.get("monitoring_enabled"):
                    fast = int(settings.get("monitoring_fast_minutes", 10))
                    deep = int(settings.get("monitoring_deep_hours", 6)) * 60
                    if await _due(db, collector.FAST, fast):
                        await run_tier(db, collector.FAST)
                    if await _due(db, collector.SLOW, deep):
                        await run_tier(db, collector.SLOW)
                    clients = int(settings.get("monitoring_client_minutes", 5))
                    if await _due(db, collector.CLIENT, clients):
                        await run_tier(db, collector.CLIENT)
            finally:
                await db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let one bad pass end the schedule.
            log.exception("Scheduled collection tick failed")
        await asyncio.sleep(TICK_SECONDS)


async def abandon_stale(db) -> int:
    """Close off runs left mid-flight by a crash or a restart.

    A row stuck at "running" is not a run in progress once the process that owned it has
    gone, and leaving it there hides the fact that collection stopped.
    """
    cursor = await db.execute(
        """UPDATE collection_runs
              SET status = 'failed', finished_at = datetime('now'),
                  detail = CASE WHEN detail = '' THEN 'interrupted' ELSE detail END
            WHERE status = 'running'"""
    )
    await db.commit()
    return cursor.rowcount or 0


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(), name="nasquay-monitoring")
        log.info("Monitoring schedule started")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
