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

import aiosqlite

VOLUME_DROP = "volume_drop"
FILE_COUNT_DROP = "file_count_drop"
DF_VS_DU = "df_vs_du"
MCP_VS_DF = "mcp_vs_df"
POOL_STATUS_CHANGE = "pool_status_change"


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
    """Recent readings of one metric, newest first.

    `exact` excludes anything rounded, cached or backfilled — the default, because most
    rules compare magnitudes where three significant digits would invent a change.
    """
    clause = "AND rounded = 0 AND cached = 0 AND backfilled = 0" if exact else ""
    async with db.execute(
        f"""SELECT value, taken_at FROM readings
            WHERE target_id = ? AND metric = ? AND value IS NOT NULL {clause}
            ORDER BY taken_at DESC, id DESC LIMIT ?""",
        (target_id, metric, limit),
    ) as cur:
        return list(await cur.fetchall())


async def _latest(
    db: aiosqlite.Connection, target_id: int, metric: str, *, exact: bool = True
) -> Optional[aiosqlite.Row]:
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


async def _df_vs_du(db, targets, nas_id: int, settings) -> list[Raised]:
    """The sum of a volume's shares against what df says that volume holds.

    Only evaluated when every share on the volume has a `du` figure — a partial sum would
    always look smaller than df and would flag for no reason.
    """
    out: list[Raised] = []
    margin = float(settings.get("rule_divergence_pct", 2))
    for volume in (t for t in targets if t["kind"] == "volume"):
        shares = [t for t in targets if t["kind"] == "share" and t["parent_ref"] == volume["ref"]]
        if not shares:
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


async def apply(db: aiosqlite.Connection, nas_id: int, raised: list[Raised]) -> dict[str, int]:
    """Record what fired, and clear what no longer does.

    An open flag for the same rule and target is left as it is: the flag marks when the
    condition was first seen, and re-raising it every few minutes would bury that.
    """
    now_firing = {(one.rule, one.target_id) for one in raised}
    opened = 0

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

    await db.commit()
    return {"raised": opened, "cleared": cleared, "firing": len(raised)}
