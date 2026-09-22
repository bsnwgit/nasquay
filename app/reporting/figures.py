"""
The four reports, as figures.

Each builder returns the same shape — a title, the period it covers, and a list of
sections, each a heading, a note, column names and rows. Everything downstream (the page,
the CSV, the PDF, the AI summary) reads that shape and nothing else, so a new report kind
is a builder and no more.

Nothing here contacts a NAS. Every figure comes from readings, flags, collection runs,
routine runs and the audit log, which is what makes a report cheap to produce and safe to
repeat.

A figure NASQuay does not have is reported as "—", never as zero: a share nobody has
measured and a share that is empty are different answers.
"""
from __future__ import annotations

from typing import Any, Optional

import aiosqlite

# What each kind of target calls its used, total and free figures. df is the fallback for
# a volume NASQuay reaches over SSH but not through the NAS's own API.
USED = {
    "pool": ("pool_used_bytes",),
    "volume": ("volume_used_bytes", "df_used_bytes"),
    "share": ("du_bytes",),
    "client_mount": ("client_df_used_bytes",),
}
TOTAL = {
    "pool": ("pool_capacity_bytes",),
    "volume": ("volume_capacity_bytes", "df_total_bytes"),
    "share": (),
    "client_mount": ("client_df_total_bytes",),
}
FREE = {
    "pool": ("pool_free_bytes",),
    "volume": ("volume_free_bytes", "df_available_bytes"),
    "share": (),
    "client_mount": ("client_df_available_bytes",),
}

DASH = "—"


def _gb(value: Optional[int]) -> str:
    """Bytes as a human figure. Binary units, because that is what a NAS reports."""
    if value is None:
        return DASH
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(size) < 1024 or unit == "PiB":
            return f"{size:,.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:,.1f} PiB"


def _signed(value: Optional[int]) -> str:
    if value is None:
        return DASH
    return ("+" if value > 0 else "") + _gb(value).replace("-", "−", 1)


def _pct(part: Optional[int], whole: Optional[int]) -> str:
    if part is None or not whole:
        return DASH
    return f"{part / whole * 100:.1f}%"


def _count(value: Optional[int]) -> str:
    return DASH if value is None else f"{value:,}"


async def _latest(db, target_id: int, metrics: tuple[str, ...]) -> tuple[Optional[int], str]:
    """The newest reading of the first of these metrics that has one, and when."""
    for metric in metrics:
        async with db.execute(
            """SELECT value, taken_at FROM readings
               WHERE target_id = ? AND metric = ? AND value IS NOT NULL
               ORDER BY taken_at DESC, id DESC LIMIT 1""",
            (target_id, metric),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            return row["value"], row["taken_at"]
    return None, ""


async def _earliest_in(db, target_id: int, metrics: tuple[str, ...],
                       days: int) -> tuple[Optional[int], str]:
    """The oldest reading inside the period — where the figure started from."""
    for metric in metrics:
        async with db.execute(
            """SELECT value, taken_at FROM readings
               WHERE target_id = ? AND metric = ? AND value IS NOT NULL
                 AND taken_at >= datetime('now', '-' || ? || ' days')
               ORDER BY taken_at ASC, id ASC LIMIT 1""",
            (target_id, metric, days),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            return row["value"], row["taken_at"]
    return None, ""


async def _between(db, target_id: int, metrics: tuple[str, ...], older: int,
                   newer: int) -> tuple[Optional[int], Optional[int]]:
    """The first and last readings inside a window that ended `newer` days ago and began
    `older` days ago — the arithmetic behind comparing one period with the last."""
    for metric in metrics:
        async with db.execute(
            """SELECT MIN(taken_at) AS first_at, MAX(taken_at) AS last_at FROM readings
               WHERE target_id = ? AND metric = ? AND value IS NOT NULL
                 AND taken_at >= datetime('now', '-' || ? || ' days')
                 AND taken_at <  datetime('now', '-' || ? || ' days')""",
            (target_id, metric, older, newer),
        ) as cur:
            edges = await cur.fetchone()
        if edges is None or edges["first_at"] is None:
            continue
        async with db.execute(
            """SELECT
                 (SELECT value FROM readings WHERE target_id = ? AND metric = ? AND taken_at = ?
                  ORDER BY id ASC LIMIT 1) AS started,
                 (SELECT value FROM readings WHERE target_id = ? AND metric = ? AND taken_at = ?
                  ORDER BY id DESC LIMIT 1) AS ended""",
            (target_id, metric, edges["first_at"], target_id, metric, edges["last_at"]),
        ) as cur:
            row = await cur.fetchone()
        return row["started"], row["ended"]
    return None, None


async def _targets(db, nas_id: Optional[int], kinds: tuple[str, ...]) -> list[Any]:
    where = ["t.enabled = 1", f"t.kind IN ({','.join('?' * len(kinds))})"]
    params: list[Any] = list(kinds)
    if nas_id:
        where.append("t.nas_id = ?")
        params.append(nas_id)
    async with db.execute(
        f"""SELECT t.id, t.kind, t.ref, t.label, n.name AS nas
            FROM targets t JOIN nas n ON n.id = t.nas_id
            WHERE {' AND '.join(where)}
            ORDER BY n.name, t.kind, COALESCE(NULLIF(t.label, ''), t.ref)""",
        params,
    ) as cur:
        return list(await cur.fetchall())


def _section(heading: str, note: str, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"heading": heading, "note": note, "columns": columns, "rows": rows}


def _days_to_full(free: Optional[int], per_day: Optional[float]) -> str:
    if free is None or not per_day or per_day <= 0:
        return DASH
    days = free / per_day
    if days > 3650:
        return "over 10 years"
    return f"{days:,.0f} days"


# ── Capacity ──────────────────────────────────────────────────────────────────

async def capacity(db, nas_id: Optional[int], days: int) -> list[dict[str, Any]]:
    """How full everything is, how fast it is filling, and when it runs out."""
    sections: list[dict[str, Any]] = []
    for kind, heading in (("pool", "Pools"), ("volume", "Volumes"), ("share", "Shares")):
        rows: list[list[Any]] = []
        for target in await _targets(db, nas_id, (kind,)):
            name = target["label"] or target["ref"]
            used, seen = await _latest(db, target["id"], USED[kind])
            total, _ = await _latest(db, target["id"], TOTAL[kind])
            free, _ = await _latest(db, target["id"], FREE[kind])
            was, _from = await _earliest_in(db, target["id"], USED[kind], days)
            growth = None if used is None or was is None else used - was
            per_day = None if growth is None else growth / days
            rows.append([
                target["nas"], name, _gb(used), _gb(total), _pct(used, total),
                _signed(growth), _signed(int(per_day)) if per_day is not None else DASH,
                _days_to_full(free, per_day), seen[:16] or DASH,
            ])
        if rows:
            sections.append(_section(
                heading,
                "Growth is measured from the oldest reading inside the period, so a figure "
                "NASQuay has been watching for less than that covers less than it says.",
                ["NAS", kind.title(), "Used", "Capacity", "Full", f"Growth ({days}d)",
                 "Per day", "Until full", "As at"],
                rows,
            ))
    if not sections:
        sections.append(_section("Capacity", "Nothing is being watched yet.", ["", ], []))
    return sections


# ── Change ────────────────────────────────────────────────────────────────────

async def change(db, nas_id: Optional[int], days: int) -> list[dict[str, Any]]:
    """What moved: the biggest growers, anything that shrank, and file counts."""
    moves: list[tuple[int, list[Any]]] = []
    shrank: list[list[Any]] = []
    for target in await _targets(db, nas_id, ("pool", "volume", "share", "client_mount")):
        kind = target["kind"]
        name = target["label"] or target["ref"]
        used, _ = await _latest(db, target["id"], USED[kind])
        was, first_at = await _earliest_in(db, target["id"], USED[kind], days)
        if used is None or was is None:
            continue
        moved = used - was
        row = [target["nas"], kind, name, _gb(was), _gb(used), _signed(moved),
               _pct(abs(moved), was) if was else DASH, first_at[:16]]
        moves.append((abs(moved), row))
        if moved < 0:
            shrank.append(row)

    moves.sort(key=lambda pair: pair[0], reverse=True)
    columns = ["NAS", "Kind", "Name", "At the start", "Now", "Change", "Of its size", "From"]

    counts: list[list[Any]] = []
    for target in await _targets(db, nas_id, ("share",)):
        name = target["label"] or target["ref"]
        now, _ = await _latest(db, target["id"], ("file_count",))
        was, _at = await _earliest_in(db, target["id"], ("file_count",), days)
        if now is None and was is None:
            continue
        moved = None if now is None or was is None else now - was
        counts.append([target["nas"], name, _count(was), _count(now),
                       DASH if moved is None else f"{moved:+,}"])

    sections = [
        _section("What moved most", "Every watched figure, largest change first.",
                 columns, [row for _size, row in moves[:25]]),
        _section("What shrank", "Space that went away. A deliberate deletion looks the "
                                "same here as an accident — this says what, not why.",
                 columns, shrank),
        _section("File counts", "Shares NASQuay counts files in.",
                 ["NAS", "Share", "At the start", "Now", "Change"], counts),
    ]
    return [one for one in sections if one["rows"]] or [
        _section("Change", "Nothing has moved in this period, or nothing is watched yet.", [], [])
    ]


# ── Health ────────────────────────────────────────────────────────────────────

async def health(db, nas_id: Optional[int], days: int) -> list[dict[str, Any]]:
    """Flags, pools, mounts and whether collection itself kept up."""
    where = ["f.raised_at >= datetime('now', '-' || ? || ' days')"]
    params: list[Any] = [days]
    if nas_id:
        where.append("f.nas_id = ?")
        params.append(nas_id)

    async with db.execute(
        f"""SELECT f.raised_at, f.cleared_at, f.rule, f.severity, f.detail,
                   COALESCE(n.name, '') AS nas,
                   COALESCE(NULLIF(t.label, ''), t.ref, '') AS target
            FROM flags f
            LEFT JOIN nas n ON n.id = f.nas_id
            LEFT JOIN targets t ON t.id = f.target_id
            WHERE {' AND '.join(where)}
            ORDER BY f.raised_at DESC LIMIT 200""",
        params,
    ) as cur:
        flags = [[r["raised_at"][:16], r["severity"], r["nas"], r["target"], r["rule"],
                  "open" if not r["cleared_at"] else f"cleared {r['cleared_at'][:16]}",
                  (r["detail"] or "")[:200]] for r in await cur.fetchall()]

    async with db.execute(
        f"""SELECT f.severity, COUNT(*) AS n,
                   SUM(CASE WHEN f.cleared_at IS NULL THEN 1 ELSE 0 END) AS open
            FROM flags f WHERE {' AND '.join(where)} GROUP BY f.severity""",
        params,
    ) as cur:
        counts = [[r["severity"], r["n"], r["open"]] for r in await cur.fetchall()]

    pools: list[list[Any]] = []
    for target in await _targets(db, nas_id, ("pool",)):
        status, seen = await _latest(db, target["id"], ("pool_status",))
        pools.append([target["nas"], target["label"] or target["ref"],
                      DASH if status is None else ("healthy" if status == 0 else f"status {status}"),
                      seen[:16] or DASH])

    mounts: list[list[Any]] = []
    for target in await _targets(db, nas_id, ("client_mount",)):
        mounted, seen = await _latest(db, target["id"], ("client_mounted",))
        mounts.append([target["nas"], target["label"] or target["ref"],
                       DASH if mounted is None else ("mounted" if mounted else "NOT MOUNTED"),
                       seen[:16] or DASH])

    async with db.execute(
        """SELECT tier, COUNT(*) AS runs,
                  SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok,
                  MAX(started_at) AS last
           FROM collection_runs
           WHERE started_at >= datetime('now', '-' || ? || ' days')
           GROUP BY tier ORDER BY tier""",
        (days,),
    ) as cur:
        collection = [[r["tier"], r["runs"], r["ok"], r["runs"] - (r["ok"] or 0),
                       (r["last"] or "")[:16]] for r in await cur.fetchall()]

    sections = [
        _section("Flags by severity", f"Raised in the past {days} days.",
                 ["Severity", "Raised", "Still open"], counts),
        _section("Pools", "As the NAS last reported them.",
                 ["NAS", "Pool", "State", "As at"], pools),
        _section("Client mounts", "A share can be healthy on the NAS and missing on the "
                                  "machine that needs it.",
                 ["NAS", "Mount", "State", "As at"], mounts),
        _section("Collection", "Whether the readings behind this report were actually taken.",
                 ["Tier", "Runs", "Succeeded", "Failed", "Last"], collection),
        _section("Every flag", "Newest first, up to 200.",
                 ["Raised", "Severity", "NAS", "Target", "Rule", "State", "Detail"], flags),
    ]
    return [one for one in sections if one["rows"]] or [
        _section("Health", "Nothing was flagged in this period.", [], [])
    ]


# ── Activity ──────────────────────────────────────────────────────────────────

async def activity(db, nas_id: Optional[int], days: int) -> list[dict[str, Any]]:
    """What NASQuay itself did, and who asked for it."""
    # audit.at is ISO with a T and a Z, so it is compared against the same shape rather
    # than against datetime(), whose space would sort wrongly against it.
    window = "a.at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')"
    where, params = [window], [days]
    if nas_id:
        where.append("a.nas_id = ?")
        params.append(nas_id)
    clause = " AND ".join(where)

    async with db.execute(
        f"""SELECT a.actor_name, a.actor_kind, a.via, COUNT(*) AS n,
                   SUM(CASE WHEN a.decision = 'denied' THEN 1 ELSE 0 END) AS denied
            FROM audit a WHERE {clause}
            GROUP BY a.actor_name, a.actor_kind, a.via ORDER BY n DESC LIMIT 50""",
        params,
    ) as cur:
        who = [[r["actor_name"], r["actor_kind"], r["via"], r["n"], r["denied"]]
               for r in await cur.fetchall()]

    async with db.execute(
        f"""SELECT a.action_id, COUNT(*) AS n,
                   SUM(CASE WHEN a.outcome = 'error' THEN 1 ELSE 0 END) AS failed
            FROM audit a WHERE {clause}
            GROUP BY a.action_id ORDER BY n DESC LIMIT 50""",
        params,
    ) as cur:
        actions = [[r["action_id"], r["n"], r["failed"]] for r in await cur.fetchall()]

    async with db.execute(
        f"""SELECT a.at, a.actor_name, a.via, a.action_id, a.target, a.reason
            FROM audit a WHERE {clause} AND a.decision = 'denied'
            ORDER BY a.at DESC LIMIT 100""",
        params,
    ) as cur:
        refused = [[r["at"][:16], r["actor_name"], r["via"], r["action_id"],
                    r["target"], r["reason"]] for r in await cur.fetchall()]

    async with db.execute(
        """SELECT r.name, COUNT(x.id) AS runs,
                  SUM(CASE WHEN x.status = 'ok' THEN 1 ELSE 0 END) AS ok,
                  MAX(x.finished_at) AS last
           FROM routines r LEFT JOIN routine_runs x
                ON x.routine_id = r.id
               AND x.queued_at >= datetime('now', '-' || ? || ' days')
           GROUP BY r.id ORDER BY r.name""",
        (days,),
    ) as cur:
        routines = [[r["name"], r["runs"], r["ok"] or 0, (r["runs"] or 0) - (r["ok"] or 0),
                     (r["last"] or DASH)[:16]] for r in await cur.fetchall()]

    sections = [
        _section("Who did what", f"Actions attempted in the past {days} days.",
                 ["Who", "Kind", "Through", "Actions", "Refused"], who),
        _section("Which actions", "Every action attempted, most used first.",
                 ["Action", "Times", "Failed"], actions),
        _section("Refusals", "Permission checks that said no. An empty table here is the "
                             "usual state; a full one is worth reading.",
                 ["When", "Who", "Through", "Action", "Target", "Why"], refused),
        _section("Routines", "How the scheduled work fared.",
                 ["Routine", "Runs", "Succeeded", "Failed", "Last"], routines),
    ]
    return [one for one in sections if one["rows"]] or [
        _section("Activity", "Nothing was recorded in this period.", [], [])
    ]


# ── Comparing with the period before ──────────────────────────────────────────

async def compare(db, kind: str, nas_id: Optional[int], days: int) -> list[dict[str, Any]]:
    """The same arithmetic over the period before this one, so a figure can be read as
    faster, slower or the same rather than merely large.

    A period NASQuay has no readings for is reported as "—": an installation younger
    than two periods cannot be compared, and saying so is the honest answer.
    """
    if kind in ("capacity", "change"):
        rows: list[list[Any]] = []
        for target in await _targets(db, nas_id, ("pool", "volume", "share", "client_mount")):
            metrics = USED[target["kind"]]
            now_from, now_to = await _between(db, target["id"], metrics, days, 0)
            was_from, was_to = await _between(db, target["id"], metrics, days * 2, days)
            this = None if now_from is None or now_to is None else now_to - now_from
            last = None if was_from is None or was_to is None else was_to - was_from
            if this is None and last is None:
                continue
            difference = None if this is None or last is None else this - last
            rows.append([
                target["nas"], target["kind"], target["label"] or target["ref"],
                _signed(last), _signed(this), _signed(difference),
                "faster" if difference and difference > 0 else
                "slower" if difference and difference < 0 else
                DASH if difference is None else "the same",
            ])
        return [_section(
            f"Against the previous {days} days",
            "The same measurement over the period before this one. A dash means NASQuay "
            "has no readings that far back.",
            ["NAS", "Kind", "Name", f"Previous {days}d", f"This {days}d", "Difference", "Trend"],
            rows,
        )] if rows else []

    if kind == "health":
        async with db.execute(
            """SELECT
                 SUM(CASE WHEN raised_at >= datetime('now', '-' || ? || ' days')
                          THEN 1 ELSE 0 END) AS this,
                 SUM(CASE WHEN raised_at >= datetime('now', '-' || ? || ' days')
                           AND raised_at <  datetime('now', '-' || ? || ' days')
                          THEN 1 ELSE 0 END) AS last
               FROM flags""",
            (days, days * 2, days),
        ) as cur:
            row = await cur.fetchone()
        this, last = row["this"] or 0, row["last"] or 0
        return [_section(
            f"Against the previous {days} days",
            "Flags raised in each period.",
            ["Measure", f"Previous {days}d", f"This {days}d", "Difference"],
            [["Flags raised", last, this, f"{this - last:+}"]],
        )]

    async with db.execute(
        """SELECT
             SUM(CASE WHEN at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                      THEN 1 ELSE 0 END) AS this,
             SUM(CASE WHEN at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                       AND at <  strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                      THEN 1 ELSE 0 END) AS last,
             SUM(CASE WHEN decision = 'denied'
                       AND at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                      THEN 1 ELSE 0 END) AS denied_this,
             SUM(CASE WHEN decision = 'denied'
                       AND at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                       AND at <  strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-' || ? || ' days')
                      THEN 1 ELSE 0 END) AS denied_last
           FROM audit""",
        (days, days * 2, days, days, days * 2, days),
    ) as cur:
        row = await cur.fetchone()
    return [_section(
        f"Against the previous {days} days",
        "What NASQuay did in each period.",
        ["Measure", f"Previous {days}d", f"This {days}d", "Difference"],
        [
            ["Actions", row["last"] or 0, row["this"] or 0,
             f"{(row['this'] or 0) - (row['last'] or 0):+}"],
            ["Refusals", row["denied_last"] or 0, row["denied_this"] or 0,
             f"{(row['denied_this'] or 0) - (row['denied_last'] or 0):+}"],
        ],
    )]


BUILDERS = {"capacity": capacity, "change": change, "health": health, "activity": activity}


async def build(db: aiosqlite.Connection, kind: str, nas_id: Optional[int],
                days: int) -> list[dict[str, Any]]:
    return await BUILDERS[kind](db, nas_id, days)
