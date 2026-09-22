"""
Reports, as something other callers can ask about.

One implementation, used by the assistant's data surface, by routines and by the MCP
endpoint, so a report reads the same however it was asked for and there is no second
version to keep in step.

A report shows what its run-as user could see, so these only ever return reports the
caller could have run themselves — their own, or any, for an administrator. Without that
an assistant conversation would be a way to read an administrator's report.
"""
from __future__ import annotations

from typing import Any, Optional

import aiosqlite

from app.actions.context import Caller

MAX_ROWS = 40          # per section, when a report is read as text
MAX_SECTIONS = 12


def _mine(caller: Caller) -> tuple[str, list[Any]]:
    if caller.is_admin:
        return "", []
    return " AND r.run_as_user_id = ?", [caller.user_id]


async def list_reports(db: aiosqlite.Connection, caller: Caller,
                       limit: int = 25) -> dict[str, Any]:
    clause, params = _mine(caller)
    async with db.execute(
        f"""SELECT r.name, r.kind, r.description, r.period_days, r.enabled,
                   COALESCE(n.name, 'every NAS') AS nas,
                   (SELECT status FROM report_runs x WHERE x.report_id = r.id
                    ORDER BY x.id DESC LIMIT 1) AS last_status,
                   (SELECT finished_at FROM report_runs x WHERE x.report_id = r.id
                    AND x.status = 'ok' ORDER BY x.id DESC LIMIT 1) AS last_produced
            FROM reports r LEFT JOIN nas n ON n.id = r.nas_id
            WHERE 1 = 1{clause} ORDER BY r.name LIMIT ?""",
        (*params, limit),
    ) as cur:
        rows = await cur.fetchall()
    return {
        "total": len(rows),
        "reports": [
            {"name": r["name"], "kind": r["kind"], "about": r["description"],
             "period_days": r["period_days"], "nas": r["nas"], "enabled": bool(r["enabled"]),
             "last_status": r["last_status"], "last_produced": r["last_produced"]}
            for r in rows
        ],
    }


async def read_report(db: aiosqlite.Connection, caller: Caller,
                      name: str) -> dict[str, Any]:
    """The newest report of that name that was produced successfully.

    Its figures, trimmed: a model given every row of a large report answers worse, and
    the whole thing is on the page for anybody who wants it.
    """
    clause, params = _mine(caller)
    async with db.execute(
        f"""SELECT r.name, x.id, x.finished_at, x.summary, x.figures
            FROM report_runs x JOIN reports r ON r.id = x.report_id
            WHERE r.name = ? COLLATE NOCASE AND x.status = 'ok'{clause}
            ORDER BY x.id DESC LIMIT 1""",
        (name, *params),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        known = await list_reports(db, caller)
        return {
            "found": False,
            "detail": f"No report called {name!r} has been produced. "
                      f"Reports here: {', '.join(r['name'] for r in known['reports']) or 'none'}.",
        }

    import json

    figures = json.loads(row["figures"] or "{}")
    sections = []
    for section in (figures.get("sections") or [])[:MAX_SECTIONS]:
        rows = section.get("rows") or []
        sections.append({
            "heading": section.get("heading", ""),
            "columns": section.get("columns", []),
            "rows": rows[:MAX_ROWS],
            "rows_left_out": max(0, len(rows) - MAX_ROWS),
        })
    return {
        "found": True,
        "report": row["name"],
        "run_id": row["id"],
        "produced_at": row["finished_at"],
        "period_days": (figures.get("period") or {}).get("days"),
        "summary": row["summary"],
        "sections": sections,
    }


async def produce_report(db: aiosqlite.Connection, caller: Caller,
                         name: str) -> dict[str, Any]:
    """Queue a report. It is produced by the worker within seconds; reading it is a
    separate call, so nothing here waits."""
    clause, params = _mine(caller)
    async with db.execute(
        f"SELECT r.id, r.name FROM reports r WHERE r.name = ? COLLATE NOCASE{clause}",
        (name, *params),
    ) as cur:
        report = await cur.fetchone()
    if report is None:
        return {"queued": False, "detail": f"There is no report called {name!r} here."}
    async with db.execute(
        "SELECT 1 FROM report_runs WHERE report_id = ? AND status IN ('queued', 'running')",
        (report["id"],),
    ) as cur:
        if await cur.fetchone():
            return {"queued": False, "detail": f"{report['name']} is already being produced."}
    cur = await db.execute(
        """INSERT INTO report_runs (report_id, trigger, requested_by, status)
           VALUES (?, 'manual', ?, 'queued')""",
        (report["id"], caller.user_id),
    )
    await db.commit()
    return {"queued": True, "run_id": cur.lastrowid,
            "detail": f"{report['name']} is being produced; read it in a few seconds."}


def find_name(figures: dict[str, Any]) -> Optional[str]:
    """The report a set of figures came from, where one is recorded."""
    return figures.get("title")
