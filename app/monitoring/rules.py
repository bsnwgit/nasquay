"""
Turning readings into flags.

A rule compares a metric against its own past, or against the same fact measured another
way, and raises a flag when the difference is larger than a threshold. Thresholds are
settings, because what counts as normal movement is a property of the hardware, not of
this code.

Three principles hold throughout:

  **A rule never trusts a figure that lost accuracy.** Readings marked `rounded` (the
  imported history) or `cached` (the NAS's own stale per-share counts) are excluded from
  any comparison that needs precision. They are there to be looked at, not to fire alarms.

  **A flag is raised once and then left alone.** An open flag for the same rule and target
  is not duplicated on the next run; it is cleared when the condition stops holding, so
  the record of what was seen survives the condition ending.

  **A rule that cannot be evaluated says nothing.** Too few readings, a missing
  counterpart, a volume with no `df` — none of those are flags. Silence here means "not
  known", and the pages say elsewhere when a cross-check is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from starlette.concurrency import run_in_threadpool

import aiosqlite

from app import notify

VOLUME_DROP = "volume_drop"
FILE_COUNT_DROP = "file_count_drop"
DF_VS_DU = "df_vs_du"
MCP_VS_DF = "mcp_vs_df"
POOL_STATUS_CHANGE = "pool_status_change"
MOUNT_MISSING = "mount_missing"
CLIENT_VS_NAS = "client_vs_nas"
COLLECTION_STALE = "collection_stale"


@dataclass
class Raised:
    rule: str
    target_id: Optional[int]
    nas_id: Optional[int]
    severity: str
    detail: str
    value: Optional[int] = None
    previous: Optional[int] = None


async def _series(
    db: aiosqlite.Connection, target_id: int, metric: str, limit: int = 2, *, exact: bool = True
) -> list[aiosqlite.Row]:
    """The newest readings of one metric, newest first.

    `exact` does NOT mean "the newest readings that happen to be exact" — that would walk
    back past a degraded reading to an older clean one and compare across the gap, which
    is how a stale zero came to be compared against today's df. It means: take the newest
    readings, and if any of them lost accuracy, answer nothing at all. A rule that cannot
    be evaluated says nothing.
    """
    async with db.execute(
        """SELECT value, taken_at, rounded, cached, backfilled FROM readings
           WHERE target_id = ? AND metric = ? AND value IS NOT NULL
           ORDER BY taken_at DESC, id DESC LIMIT ?""",
        (target_id, metric, limit),
    ) as cur:
        rows = list(await cur.fetchall())
    if exact and any(r["rounded"] or r["cached"] or r["backfilled"] for r in rows):
        return []
    return rows


async def _latest(
    db: aiosqlite.Connection, target_id: int, metric: str, *, exact: bool = True
) -> Optional[aiosqlite.Row]:
    """The newest reading of one metric, or nothing if it is not fit to compare."""
    rows = await _series(db, target_id, metric, 1, exact=exact)
    return rows[0] if rows else None


def _percent(now: int, before: int) -> float:
    return abs(now - before) / before * 100 if before else 0.0


async def evaluate(db: aiosqlite.Connection, nas_id: int, settings: dict[str, Any]) -> list[Raised]:
    """Every rule that can be evaluated for one NAS, given what has been read."""
    async with db.execute(
        "SELECT id, kind, ref, label, parent_ref FROM targets WHERE nas_id = ? AND enabled = 1",
        (nas_id,),
    ) as cur:
        targets = list(await cur.fetchall())

    raised: list[Raised] = []
    for target in targets:
        if target["kind"] == "volume":
            raised += await _volume_rules(db, target, nas_id, settings)
        elif target["kind"] == "share":
            raised += await _share_rules(db, target, nas_id, settings)
        elif target["kind"] == "pool":
            raised += await _pool_rules(db, target, nas_id)
        elif target["kind"] == "client_mount":
            raised += await _mount_rules(db, target, targets, nas_id, settings)

    raised += await _df_vs_du(db, targets, nas_id, settings)
    return raised


async def _volume_rules(db, target, nas_id: int, settings) -> list[Raised]:
    out: list[Raised] = []
    window = int(settings.get("rule_volume_drop_hours", 1))
    limit_pct = float(settings.get("rule_volume_drop_pct", 5))

    # volume_drop — used space falling faster than it should.
    async with db.execute(
        """SELECT value, taken_at FROM readings
           WHERE target_id = ? AND metric = 'volume_used_bytes' AND value IS NOT NULL
             AND rounded = 0 AND backfilled = 0
           ORDER BY taken_at DESC, id DESC LIMIT 1""",
        (target["id"],),
    ) as cur:
        newest = await cur.fetchone()
    if newest is not None:
        async with db.execute(
            """SELECT value, taken_at FROM readings
               WHERE target_id = ? AND metric = 'volume_used_bytes' AND value IS NOT NULL
                 AND rounded = 0 AND backfilled = 0
                 AND taken_at <= datetime(?, ?)
               ORDER BY taken_at DESC, id DESC LIMIT 1""",
            (target["id"], newest["taken_at"], f"-{window} hours"),
        ) as cur:
            earlier = await cur.fetchone()
        if earlier is not None and newest["value"] < earlier["value"]:
            fall = _percent(newest["value"], earlier["value"])
            if fall >= limit_pct:
                out.append(Raised(
                    VOLUME_DROP, target["id"], nas_id, "error",
                    f"{target['label'] or 'volume ' + target['ref']} lost "
                    f"{fall:.1f}% of its used space within {window} h",
                    newest["value"], earlier["value"],
                ))

    # mcp_vs_df — the NAS's own free space against what df says.
    margin = float(settings.get("rule_divergence_pct", 2))
    mcp_free = await _latest(db, target["id"], "volume_free_bytes")
    df_free = await _latest(db, target["id"], "df_available_bytes")
    if mcp_free and df_free and df_free["value"]:
        apart = _percent(mcp_free["value"], df_free["value"])
        if apart >= margin:
            out.append(Raised(
                MCP_VS_DF, target["id"], nas_id, "warning",
                f"the NAS reports {mcp_free['value']:,} bytes free while df says "
                f"{df_free['value']:,} — {apart:.1f}% apart",
                mcp_free["value"], df_free["value"],
            ))
    return out


async def _share_rules(db, target, nas_id: int, settings) -> list[Raised]:
    out: list[Raised] = []
    rows = await _series(db, target["id"], "file_count", 2)
    if len(rows) >= 2 and rows[0]["value"] < rows[1]["value"]:
        now, before = rows[0]["value"], rows[1]["value"]
        lost = before - now
        fell = _percent(now, before)
        if lost >= int(settings.get("rule_file_drop_count", 100)) or fell >= float(
            settings.get("rule_file_drop_pct", 2)
        ):
            out.append(Raised(
                FILE_COUNT_DROP, target["id"], nas_id, "error",
                f"{target['ref']} lost {lost:,} files ({fell:.1f}%) since the previous count",
                now, before,
            ))
    return out


async def _pool_rules(db, target, nas_id: int) -> list[Raised]:
    rows = await _series(db, target["id"], "pool_status", 2)
    if len(rows) >= 2 and rows[0]["value"] != rows[1]["value"]:
        return [Raised(
            POOL_STATUS_CHANGE, target["id"], nas_id, "error",
            f"pool {target['ref']} changed status from {rows[1]['value']} to {rows[0]['value']}",
            rows[0]["value"], rows[1]["value"],
        )]
    return []


async def _mount_rules(db, target, targets, nas_id: int, settings) -> list[Raised]:
    """What a client sees, against what the NAS says.

    A client's view is the one that matters to whoever uses it: a share can be perfectly
    healthy on the NAS and simply not be mounted on the machine that needs it. That has
    already happened here, and nothing on the NAS side would have shown it.
    """
    out: list[Raised] = []

    mounted = await _latest(db, target["id"], "client_mounted")
    if mounted is not None and not mounted["value"]:
        return [Raised(
            MOUNT_MISSING, target["id"], nas_id, "error",
            f"{target['label'] or target['ref']} is not mounted on the client",
            0, 1,
        )]
    if mounted is None or not mounted["value"]:
        # Never read, or not mounted and already reported above.
        return out

    # client_vs_nas — the client's idea of the filesystem against the NAS's own df. Both
    # measure the same thing from opposite ends, so they should agree closely.
    client_used = await _latest(db, target["id"], "client_df_used_bytes")
    if client_used is None or not client_used["value"]:
        return out

    volume = None
    for candidate in targets:
        if candidate["kind"] != "volume":
            continue
        for share in targets:
            if (share["kind"] == "share" and share["ref"] == target["parent_ref"]
                    and share["parent_ref"] == candidate["ref"]):
                volume = candidate
                break
        if volume is not None:
            break
    if volume is None:
        return out

    nas_used = await _latest(db, volume["id"], "df_used_bytes")
    if nas_used is None or not nas_used["value"]:
        return out

    margin = float(settings.get("rule_divergence_pct", 2))
    apart = _percent(client_used["value"], nas_used["value"])
    if apart >= margin:
        out.append(Raised(
            CLIENT_VS_NAS, target["id"], nas_id, "warning",
            f"the client sees {client_used['value']:,} bytes used where the NAS says "
            f"{nas_used['value']:,} — {apart:.1f}% apart",
            client_used["value"], nas_used["value"],
        ))
    return out


async def collection_stale(db: aiosqlite.Connection, settings: dict[str, Any]) -> list[Raised]:
    """Has collection itself stopped?

    Only asked when the schedule is meant to be running: with it off, nothing collecting is
    the correct state, not a fault. The window is twice the interval, so one slow or missed
    pass is not an alarm.
    """
    if not settings.get("monitoring_enabled"):
        return []
    minutes = int(settings.get("monitoring_fast_minutes", 10)) * 2
    async with db.execute(
        """SELECT started_at FROM collection_runs
           WHERE tier = 'fast' AND status IN ('ok', 'partial')
           ORDER BY started_at DESC LIMIT 1"""
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return [Raised(COLLECTION_STALE, None, None, "warning",
                       "the schedule is on but no collection has completed yet")]
    async with db.execute(
        "SELECT datetime(?, ?) < datetime('now') AS late", (row["started_at"], f"+{minutes} minutes")
    ) as cur:
        answer = await cur.fetchone()
    if answer["late"]:
        return [Raised(COLLECTION_STALE, None, None, "error",
                       f"no collection has completed since {row['started_at']} UTC, "
                       f"which is more than twice the interval")]
    return []


async def _df_vs_du(db, targets, nas_id: int, settings) -> list[Raised]:
    """The sum of a volume's shares against what df says that volume holds.

    Only evaluated when every share the NAS reports on that volume is watched and has an
    exact `du` figure. A sum missing a share — or one whose `du` could not read part of
    the tree — is always smaller than df, and would flag for ever while meaning nothing.
    """
    out: list[Raised] = []
    margin = float(settings.get("rule_divergence_pct", 2))
    for volume in (t for t in targets if t["kind"] == "volume"):
        shares = [t for t in targets if t["kind"] == "share" and t["parent_ref"] == volume["ref"]]
        if not shares:
            continue
        # Any share on this volume that is not watched makes the sum meaningless.
        async with db.execute(
            """SELECT COUNT(*) AS n FROM targets
               WHERE nas_id = ? AND kind = 'share' AND parent_ref = ? AND enabled = 0""",
            (nas_id, volume["ref"]),
        ) as cur:
            unwatched = (await cur.fetchone())["n"]
        if unwatched:
            continue
        total = 0
        for share in shares:
            reading = await _latest(db, share["id"], "du_bytes")
            if reading is None:
                total = -1
                break
            total += reading["value"]
        if total < 0:
            continue
        df_used = await _latest(db, volume["id"], "df_used_bytes")
        if df_used is None or not df_used["value"]:
            continue
        apart = _percent(total, df_used["value"])
        if apart >= margin:
            out.append(Raised(
                DF_VS_DU, volume["id"], nas_id, "warning",
                f"the watched shares total {total:,} bytes while df says the volume holds "
                f"{df_used['value']:,} — {apart:.1f}% apart",
                total, df_used["value"],
            ))
    return out


async def _announce(db: aiosqlite.Connection, sent: list[tuple[Raised, bool]]) -> None:
    """Tell somebody, if anybody asked to be told.

    Run after the flags are committed, and never allowed to fail the caller: a mail server
    that has gone away must not stop readings being recorded.
    """
    if not sent:
        return
    async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
        row = await cur.fetchone()
    if row is None:
        return
    settings = dict(row)

    outcome = ""
    for one, cleared in sent:
        if not notify.wanted(settings, one.severity, cleared):
            continue
        message = notify.describe(one.rule, one.detail, cleared=cleared)
        try:
            ok, said = await run_in_threadpool(notify.deliver, settings, message)
            outcome = said if ok else f"failed: {said}"
        except Exception as exc:  # never let telling somebody break the thing being told
            outcome = f"failed: {exc}"

    if outcome:
        await db.execute(
            """UPDATE notifications SET last_sent_at = datetime('now'), last_result = ?
               WHERE id = 1""",
            (outcome[:500],),
        )
        await db.commit()


async def apply(db: aiosqlite.Connection, nas_id: int, raised: list[Raised]) -> dict[str, int]:
    """Record what fired, and clear what no longer does.

    An open flag for the same rule and target is left as it is: the flag marks when the
    condition was first seen, and re-raising it every few minutes would bury that.
    """
    now_firing = {(one.rule, one.target_id) for one in raised}
    opened = 0
    announce: list[tuple[Raised, bool]] = []

    for one in raised:
        async with db.execute(
            """SELECT id FROM flags
               WHERE rule = ? AND target_id IS ? AND cleared_at IS NULL""",
            (one.rule, one.target_id),
        ) as cur:
            existing = await cur.fetchone()
        if existing is not None:
            continue
        await db.execute(
            """INSERT INTO flags (rule, target_id, nas_id, severity, detail, value, previous)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (one.rule, one.target_id, one.nas_id, one.severity, one.detail, one.value,
             one.previous),
        )
        opened += 1
        announce.append((one, False))

    async with db.execute(
        """SELECT f.id, f.rule, f.target_id FROM flags f
           WHERE f.cleared_at IS NULL AND f.nas_id = ?""",
        (nas_id,),
    ) as cur:
        open_flags = list(await cur.fetchall())

    cleared = 0
    for flag in open_flags:
        if (flag["rule"], flag["target_id"]) not in now_firing:
            await db.execute(
                "UPDATE flags SET cleared_at = datetime('now') WHERE id = ?", (flag["id"],)
            )
            cleared += 1
            announce.append((
                Raised(flag["rule"], flag["target_id"], nas_id, "info", ""), True,
            ))

    await db.commit()
    await _announce(db, announce)
    return {"raised": opened, "cleared": cleared, "firing": len(raised)}


async def apply_global(db: aiosqlite.Connection, raised: list[Raised]) -> dict[str, int]:
    """The same as apply(), for rules that belong to no single NAS."""
    firing = {one.rule for one in raised}
    opened = 0
    announce: list[tuple[Raised, bool]] = []
    for one in raised:
        async with db.execute(
            "SELECT id FROM flags WHERE rule = ? AND nas_id IS NULL AND cleared_at IS NULL",
            (one.rule,),
        ) as cur:
            if await cur.fetchone() is not None:
                continue
        await db.execute(
            """INSERT INTO flags (rule, target_id, nas_id, severity, detail, value, previous)
               VALUES (?, NULL, NULL, ?, ?, ?, ?)""",
            (one.rule, one.severity, one.detail, one.value, one.previous),
        )
        opened += 1
        announce.append((one, False))

    async with db.execute(
        "SELECT id, rule FROM flags WHERE nas_id IS NULL AND cleared_at IS NULL"
    ) as cur:
        open_flags = list(await cur.fetchall())
    cleared = 0
    for flag in open_flags:
        if flag["rule"] not in firing:
            await db.execute(
                "UPDATE flags SET cleared_at = datetime('now') WHERE id = ?", (flag["id"],)
            )
            cleared += 1
            announce.append((Raised(flag["rule"], None, None, "info", ""), True))
    await db.commit()
    await _announce(db, announce)
    return {"raised": opened, "cleared": cleared}
