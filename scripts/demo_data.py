#!/usr/bin/env python3
"""
Fill an empty NASQuay database with a believable installation, for screenshots, a
demonstration, or trying the interface without a NAS.

Nothing here touches a NAS, and nothing here is real: the units, addresses, shares,
people and figures are invented. Addresses come from the documentation ranges reserved
for exactly this (RFC 5737), so a screenshot of it can be published.

    NASQUAY_INSTALL_DIR=/path/to/demo \\
    NASQUAY_SECRET_KEY=... NASQUAY_CREDENTIAL_KEY=... \\
    venv/bin/python scripts/demo_data.py

It refuses to run against a database that already has a NAS in it, so it cannot be
pointed at a real installation by accident.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.actions.registry import sync_actions          # noqa: E402
from app.auth.local import hash_password               # noqa: E402
from app.config import get_settings                    # noqa: E402
from app.database import connect, init_db              # noqa: E402

TiB = 1024 ** 4
GiB = 1024 ** 3

# Every demo account gets this password. Never a fixed literal: $NASQUAY_DEMO_PASSWORD if
# set, otherwise a fresh random one, printed once when the database is seeded so whoever
# ran this is the only one who ever sees it.
PASSWORD = os.environ.get("NASQUAY_DEMO_PASSWORD") or secrets.token_urlsafe(12)

# One tidy box and one that is filling up, because a screenshot of two healthy NAS units
# shows none of what the app is for.
UNITS = [
    {"name": "Atlas", "address": "192.0.2.10", "note": "the tidy one"},
    {"name": "Borealis", "address": "192.0.2.11", "note": "the one filling up"},
]

SHARES = [
    # nas, share, size now, growth per day, file count
    ("Atlas", "Archive", 6.1 * TiB, 2 * GiB, 48_210),
    ("Atlas", "Backups", 11.4 * TiB, 30 * GiB, 9_840),
    ("Atlas", "Home", 820 * GiB, 900_000_000, 121_400),
    ("Borealis", "Media", 24.8 * TiB, 180 * GiB, 61_230),
    ("Borealis", "Projects", 3.2 * TiB, 12 * GiB, 204_880),
]

PEOPLE = [
    ("avery", "Avery Quinn", "Operators"),
    ("morgan", "Morgan Reyes", "Viewers"),
    ("sam", "Sam Okafor", "Operators"),
]

DAYS = 90
STEP_HOURS = 6


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


async def main() -> None:
    await init_db()
    db = await connect()
    try:
        reset = "--reset" in sys.argv
        async with db.execute("SELECT COUNT(*) AS n FROM nas") as cur:
            filled = (await cur.fetchone())["n"]
        if filled and not reset:
            print("This database already has a NAS in it. Point me at an empty one, "
                  "or pass --reset to empty this one first.")
            raise SystemExit(1)
        if reset:
            # Only the tables this script fills, and only in the database it was pointed
            # at — which is why it prints what it is about to empty.
            print("Emptying the demo database at", get_settings().db_path)
            for table in ("report_runs", "reports", "routine_runs", "routines",
                          "ai_providers", "flags", "readings", "collection_runs",
                          "targets", "clients", "nas", "api_tokens", "audit"):
                await db.execute(f"DELETE FROM {table}")
            await db.execute("DELETE FROM users WHERE username != 'admin'")
            await db.execute("DELETE FROM roles WHERE is_builtin = 0")
            await db.commit()
        await sync_actions(db)
        await people(db)
        ids = await units(db)
        await watched(db, ids)
        await schedule_history(db)
        await ai(db)
        await routines(db)
        await reports(db)
        await db.commit()
        print("Demo installation ready. Sign in as admin, password", PASSWORD)
    finally:
        await db.close()


async def people(db) -> None:
    """An administrator, two ordinary roles, and three people to hold them."""
    for name, description, permissions in (
        ("Operators", "May run reads and acknowledge flags, but not change how NASQuay works.",
         ("nas.list", "nas.check", "tools.list", "monitoring.read", "monitoring.collect",
          "monitoring.acknowledge", "clients.list", "clients.check", "audit.read",
          "reports.list", "reports.run", "reports.download", "routines.list", "mcp.use",
          "tokens.list", "tokens.create", "tokens.revoke", "resonance.use")),
        ("Viewers", "May look, and nothing else.",
         ("nas.list", "monitoring.read", "clients.list", "tools.list", "reports.list",
          "reports.download", "resonance.use")),
    ):
        cur = await db.execute(
            "INSERT OR IGNORE INTO roles (name, description) VALUES (?, ?)",
            (name, description),
        )
        role_id = cur.lastrowid
        for action in permissions:
            await db.execute(
                """INSERT OR IGNORE INTO role_permissions (role_id, action_id, allowed)
                   VALUES (?, ?, 1)""",
                (role_id, action),
            )

    await db.execute(
        """INSERT OR IGNORE INTO users (username, display_name, email, hashed_password, role_id)
           VALUES ('admin', 'Alex Carter', 'admin@example.com', ?, 1)""",
        (hash_password(PASSWORD),),
    )
    for username, display, role in PEOPLE:
        async with db.execute("SELECT id FROM roles WHERE name = ?", (role,)) as cur:
            role_id = (await cur.fetchone())["id"]
        await db.execute(
            """INSERT OR IGNORE INTO users (username, display_name, email, hashed_password,
                                            role_id, last_login)
               VALUES (?, ?, ?, ?, ?, datetime('now', '-2 hours'))""",
            (username, display, f"{username}@example.com", hash_password(PASSWORD), role_id),
        )


async def units(db) -> dict[str, int]:
    ids: dict[str, int] = {}
    for unit in UNITS:
        cur = await db.execute(
            """INSERT INTO nas (name, address, mcp_port, tls_mode, tls_fingerprint, mcp_token,
                                ssh_user, ssh_port, admin_url, enabled, last_checked_at,
                                last_check_ok, last_check_detail)
               VALUES (?, ?, 8443, 'pinned', ?, '', 'nasquay', 22, ?, 1,
                       datetime('now', '-6 minutes'), 1, '42 tools, SSH ok')""",
            (unit["name"], unit["address"], "".join(random.choice("0123456789abcdef")
                                                    for _ in range(64)),
             f"https://{unit['address']}:8080"),
        )
        ids[unit["name"]] = cur.lastrowid
    return ids


async def _target(db, nas_id: int, kind: str, ref: str, label: str) -> int:
    cur = await db.execute(
        """INSERT INTO targets (nas_id, kind, ref, label, enabled)
           VALUES (?, ?, ?, ?, 1)""",
        (nas_id, kind, ref, label),
    )
    return cur.lastrowid


async def _series(db, target_id: int, metric: str, ending: float, per_day: float,
                  source: str, wobble: float = 0.004) -> None:
    """A plausible history: a trend, with enough noise that a chart looks measured."""
    moment = now() - timedelta(days=DAYS)
    rows = []
    while moment <= now():
        days_left = (now() - moment).total_seconds() / 86400
        value = ending - per_day * days_left
        value *= 1 + random.uniform(-wobble, wobble)
        rows.append((stamp(moment), target_id, metric, int(max(value, 0)), source))
        moment += timedelta(hours=STEP_HOURS)
    await db.executemany(
        """INSERT INTO readings (taken_at, target_id, metric, value, source)
           VALUES (?, ?, ?, ?, ?)""",
        rows,
    )


async def watched(db, ids: dict[str, int]) -> None:
    """Pools, volumes, shares and one client mount, each with three months of readings."""
    plans = {
        "Atlas": [("Pool 1", 40 * TiB, 18.4 * TiB, 33 * GiB, 0)],
        "Borealis": [("Pool 1", 36 * TiB, 28.1 * TiB, 195 * GiB, -1)],
    }
    for name, pools in plans.items():
        nas_id = ids[name]
        for ref, capacity, used, per_day, status in pools:
            pool = await _target(db, nas_id, "pool", ref.lower().replace(" ", ""), ref)
            await _series(db, pool, "pool_capacity_bytes", capacity, 0, "mcp", 0)
            await _series(db, pool, "pool_used_bytes", used, per_day, "mcp")
            await _series(db, pool, "pool_free_bytes", capacity - used, -per_day, "mcp")
            await _series(db, pool, "pool_status", status, 0, "mcp", 0)

            volume = await _target(db, nas_id, "volume", "2", "Data")
            await _series(db, volume, "volume_capacity_bytes", capacity, 0, "mcp", 0)
            await _series(db, volume, "volume_used_bytes", used, per_day, "mcp")
            await _series(db, volume, "volume_free_bytes", capacity - used, -per_day, "mcp")
            await _series(db, volume, "df_total_bytes", capacity, 0, "ssh", 0)
            await _series(db, volume, "df_used_bytes", used * 1.002, per_day, "ssh")
            await _series(db, volume, "df_available_bytes", capacity - used * 1.002,
                          -per_day, "ssh")

    for nas_name, share, size, per_day, files in SHARES:
        target = await _target(db, ids[nas_name], "share", share, share)
        await _series(db, target, "du_bytes", size, per_day, "ssh")
        await _series(db, target, "file_count", files, files / 400, "ssh", 0.001)
        await _series(db, target, "file_count_reported", files * 0.98, files / 400, "mcp", 0.001)
        await _series(db, target, "dir_count", files / 12, files / 5000, "ssh", 0.001)

    # A client that mounts two shares, one of which has gone missing — the case a NAS's
    # own view can never show.
    cur = await db.execute(
        """INSERT INTO clients (name, address, ssh_user, ssh_port, key_name, enabled,
                                last_checked_at, last_check_ok, last_check_detail)
           VALUES ('Studio', '192.0.2.40', 'nasquay', 22, 'clients', 1,
                   datetime('now', '-5 minutes'), 1, 'Darwin arm64 ok')""",
    )
    client_id = cur.lastrowid
    for nas_name, share, mounted in (("Borealis", "Media", 1), ("Atlas", "Archive", 0)):
        cur = await db.execute(
            """INSERT INTO targets (nas_id, kind, ref, label, parent_ref, client_id, enabled)
               VALUES (?, 'client_mount', ?, ?, ?, ?, 1)""",
            (ids[nas_name], f"/mnt/{share.lower()}", f"/mnt/{share.lower()}", share, client_id),
        )
        mount = cur.lastrowid
        await _series(db, mount, "client_mounted", mounted, 0, "client", 0)
        if mounted:
            await _series(db, mount, "client_df_total_bytes", 36 * TiB, 0, "client", 0)
            await _series(db, mount, "client_df_used_bytes", 28.1 * TiB, 195 * GiB, "client")
            await _series(db, mount, "client_df_available_bytes", 7.9 * TiB, -195 * GiB, "client")

        if not mounted:
            await db.execute(
                """INSERT INTO flags (raised_at, rule, target_id, nas_id, severity, detail,
                                      value, previous)
                   VALUES (datetime('now', '-3 hours'), 'mount_missing', ?, ?, 'error',
                           ?, 0, 1)""",
                (mount, ids[nas_name],
                 "Studio no longer has /mnt/archive mounted. "
                 "The share itself is healthy on Atlas."),
            )

    # One open warning and one that fixed itself, so both states are on the page.
    async with db.execute(
        "SELECT id, nas_id FROM targets WHERE kind = 'share' AND ref = 'Media'"
    ) as cur:
        media = await cur.fetchone()
    await db.execute(
        """INSERT INTO flags (raised_at, rule, target_id, nas_id, severity, detail, value, previous)
           VALUES (datetime('now', '-19 hours'), 'volume_filling', ?, ?, 'warning', ?, ?, ?)""",
        (media["id"], media["nas_id"],
         "Media has grown 1.2 TiB in a day; at this rate the pool is full in 21 days.",
         int(24.8 * TiB), int(23.6 * TiB)),
    )
    await db.execute(
        """INSERT INTO flags (raised_at, cleared_at, rule, nas_id, severity, detail)
           VALUES (datetime('now', '-4 days'), datetime('now', '-4 days', '+40 minutes'),
                   'divergence', ?, 'warning', ?)""",
        (media["nas_id"],
         "df and the NAS disagreed about Data by 3.1%. They agree again."),
    )


async def schedule_history(db) -> None:
    """Collection runs, so the dashboard can say the figures are current."""
    rows = []
    moment = now() - timedelta(days=2)
    while moment <= now():
        rows.append((stamp(moment), stamp(moment + timedelta(seconds=9)), "fast", "ok"))
        moment += timedelta(minutes=10)
    moment = now() - timedelta(days=2)
    while moment <= now():
        rows.append((stamp(moment), stamp(moment + timedelta(minutes=7)), "slow", "ok"))
        moment += timedelta(hours=6)
    await db.executemany(
        """INSERT INTO collection_runs (started_at, finished_at, tier, status)
           VALUES (?, ?, ?, ?)""",
        rows,
    )


async def ai(db) -> None:
    await db.execute(
        """INSERT INTO ai_providers (name, kind, base_url, model, api_key, timeout_s,
                                     supports_tools, enabled, tools_ok, last_tested_at,
                                     last_result)
           VALUES ('Local model', 'openai', 'http://192.0.2.60:11434/v1', 'qwen3:8b-instruct',
                   '', 120, 1, 1, 1, datetime('now', '-1 day'),
                   'answered: ''ready''; tool calling works')"""
    )


async def routines(db) -> None:
    """One AI routine and one fixed one, each with a run behind it."""
    await db.execute(
        """INSERT INTO routines (name, description, kind, enabled, run_as_user_id,
                                 schedule_kind, at_time, prompt, allowed, max_steps,
                                 timeout_s, alert_on, provider_id)
           VALUES ('Morning check', ?, 'ai', 1, 1, 'daily', '07:00', ?, ?, 8, 600,
                   'failure', 1)""",
        (
            "Looks over both NAS units and reports anything odd.",
            "Check every NAS for open flags, shares over 90% full, and any share that "
            "shrank. Report anything that needs attention.",
            json.dumps(["listNasUnits", "listMeasurements", "listFlags", "readHistory",
                        "getCollectionStatus"]),
        ),
    )
    await db.execute(
        """INSERT INTO routines (name, description, kind, enabled, run_as_user_id,
                                 schedule_kind, interval_minutes, steps, alert_on)
           VALUES ('Flag digest', ?, 'fixed', 1, 1, 'interval', 360, ?, 'failure')""",
        (
            "Sends whatever is open, every six hours.",
            json.dumps([
                {"op": "listFlags", "nas": "", "arguments": {"state": "open"}},
                {"op": "notify", "nas": "", "arguments": {
                    "title": "Open flags", "body": "{previous}", "severity": "info"}},
            ]),
        ),
    )
    await db.execute(
        """INSERT INTO routine_runs (routine_id, trigger, status, queued_at, started_at,
                                     finished_at, output, calls)
           VALUES (1, 'schedule', 'ok', datetime('now', '-9 hours'),
                   datetime('now', '-9 hours'),
                   datetime('now', '-9 hours', '+38 seconds'), ?, ?)""",
        (
            "Borealis is the one to watch: Media grew 1.2 TiB yesterday and the pool is "
            "78% full, which is about three weeks of headroom at this rate. Atlas is "
            "steady. One mount on Studio is missing — /mnt/archive — though the share "
            "itself is healthy.",
            json.dumps([
                {"op": "listNasUnits", "nas": "", "arguments": {}, "ok": True,
                 "detail": "2 NAS units"},
                {"op": "listFlags", "nas": "", "arguments": {"state": "open"}, "ok": True,
                 "detail": "2 flags"},
                {"op": "listMeasurements", "nas": "Borealis", "arguments": {"kind": "share"},
                 "ok": True, "detail": "5 measurements"},
            ]),
        ),
    )


async def reports(db) -> None:
    from app.reporting import figures as build

    definitions = [
        ("Monthly capacity", "capacity", 30, "daily", 1, 1,
         "Where the space went, and how long what is left will last."),
        ("Weekly change", "change", 7, "weekly", 1, 0,
         "What moved in the past week, against the week before."),
        ("Health", "health", 14, "manual", 0, 0,
         "Flags, pools, mounts and whether collection kept up."),
        ("Activity", "activity", 30, "manual", 0, 0,
         "What NASQuay did, and who asked."),
    ]
    for index, (name, kind, days, when, compare, summary, about) in enumerate(definitions, 1):
        await db.execute(
            """INSERT INTO reports (name, description, kind, enabled, period_days,
                                    schedule_kind, at_time, weekday, run_as_user_id, deliver,
                                    ai_summary, provider_id, compare)
               VALUES (?, ?, ?, 1, ?, ?, '07:30', 0, 1, ?, ?, 1, ?)""",
            (name, about, kind, days, when, 1 if when != "manual" else 0, summary, compare),
        )
        sections = await build.build(db, kind, None, days)
        if compare:
            sections += await build.compare(db, kind, None, days)
        text = ""
        if summary:
            text = ("Borealis is filling fastest: Media took 1.2 TiB in a day and the pool has "
                    "about three weeks of headroom left. Atlas is steady and has room. One "
                    "mount on Studio is missing, though the share behind it is healthy.")
        await db.execute(
            """INSERT INTO report_runs (report_id, trigger, status, queued_at, started_at,
                                        finished_at, figures, summary)
               VALUES (?, 'schedule', 'ok', datetime('now', '-8 hours'),
                       datetime('now', '-8 hours'), datetime('now', '-8 hours', '+3 seconds'),
                       ?, ?)""",
            (index, json.dumps({
                "title": f"{kind.title()} — {name}",
                "kind": kind,
                "nas": "every NAS",
                "period": {"days": days},
                "generated_at": (now() - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M UTC"),
                "sections": sections,
                "summary": text,
            }), text),
        )


if __name__ == "__main__":
    random.seed(7)          # the same demo every time, so screenshots can be retaken
    asyncio.run(main())
