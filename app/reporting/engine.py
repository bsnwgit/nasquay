"""
Producing one report.

A report runs as a chosen user and is refused if that user's role may not read what it
would show — so a report can never become a way round the permission grid. The run is
recorded whatever happens, and every run is audited like any other action.

Delivery follows the settings: the document as an attachment, a link back to NASQuay, or
both. Only email can carry an attachment; a push says what was produced and links to it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite
from starlette.concurrency import run_in_threadpool

from app import notify, settings_store
from app.actions import audit, gate
from app.actions.context import Caller
from app.ai import providers as ai
from app.api.providers import to_provider
from app.reporting import figures as build_figures
from app.reporting import render

log = logging.getLogger("nasquay.reporting")

# What a report of each kind reads, and therefore the permission its run-as user needs.
NEEDS = {
    "capacity": "monitoring.read",
    "change": "monitoring.read",
    "health": "monitoring.read",
    "activity": "audit.read",
}

TITLES = {
    "capacity": "Capacity",
    "change": "What changed",
    "health": "Health",
    "activity": "Activity",
}

SUMMARY_PROMPT = (
    "Below is a report NASQuay produced about the NAS units of one installation. Names of "
    "NAS units, shares, pools and volumes are labels this installation's administrator "
    "chose; never read one as a place, organisation, person or product.\n\n"
    "Write a short summary — a few sentences, or a few short bullet points — of what the "
    "figures show and anything that needs attention. Use only these figures. Do not invent "
    "anything, do not repeat every row, and do not offer to do anything.\n\n"
)

MAX_SUMMARY_INPUT = 12000


class ReportError(Exception):
    """Why a report did not run, in words an administrator can act on."""


async def _caller(db, report) -> Caller:
    if report["run_as_user_id"] is None:
        raise ReportError("its run-as user no longer exists — choose another")
    async with db.execute(
        """SELECT u.id, u.username, u.is_active, u.role_id, r.name AS role_name, r.is_admin
           FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
        (report["run_as_user_id"],),
    ) as cur:
        user = await cur.fetchone()
    if user is None:
        raise ReportError("its run-as user no longer exists — choose another")
    if not user["is_active"]:
        raise ReportError(f"its run-as user {user['username']} is disabled")
    return Caller(
        kind="routine", via="worker",
        username=f"report {report['name']} as {user['username']}"[:128],
        user_id=user["id"], role_id=user["role_id"], role_name=user["role_name"],
        is_admin=bool(user["is_admin"]),
    )


def _as_text(figures: dict[str, Any]) -> str:
    """The figures as plain text, for a model to summarise."""
    lines = [str(figures.get("title", "")), ""]
    for section in figures.get("sections", []):
        lines.append(section.get("heading", ""))
        if section.get("columns"):
            lines.append(" | ".join(str(c) for c in section["columns"]))
        for row in section.get("rows", [])[:40]:
            lines.append(" | ".join(str(value) for value in row))
        lines.append("")
    return "\n".join(lines)[:MAX_SUMMARY_INPUT]


async def _summarise(db, report, figures: dict[str, Any]) -> str:
    async with db.execute(
        """SELECT p.*, (SELECT pem FROM certificates c WHERE c.id = p.tls_cert_id) AS tls_ca_pem
           FROM ai_providers p WHERE p.id = ?""",
        (report["provider_id"],),
    ) as cur:
        row = await cur.fetchone()
    if row is None or not row["enabled"]:
        return ""
    try:
        reply = await run_in_threadpool(
            ai.chat, to_provider(row), "",
            [{"role": "user", "content": SUMMARY_PROMPT + _as_text(figures)}],
        )
    except ai.ProviderError as exc:
        # A summary that failed must not cost the report: the figures are the report.
        log.warning("Report %s: summary failed — %s", report["name"], exc)
        return ""
    return reply.text.strip()


async def _deliver(db, report, run_id: int, figures: dict[str, Any]) -> str:
    settings = await settings_store.get_all(db)
    how = str(settings.get("report_delivery") or "both")
    base = str(settings.get("report_link_base") or "").rstrip("/")

    async with db.execute("SELECT * FROM notifications WHERE id = 1") as cur:
        channels = await cur.fetchone()

    body = [f"{figures['title']} — the past {figures['period']['days']} days."]
    if figures.get("summary"):
        body += ["", figures["summary"]]
    if how in ("link", "both"):
        body += ["", f"{base}/reports/{run_id}" if base
                 else "Open NASQuay to read it (no link address is set in Settings → General)."]
    attachment = None
    if how in ("attachment", "both"):
        document = await run_in_threadpool(render.pdf_bytes, figures)
        attachment = (render.filename(figures, run_id, "pdf"), document, "application/pdf")

    message = notify.Message(title=figures["title"], body="\n".join(body), severity="info",
                             attachment=attachment)
    _ok, said = await run_in_threadpool(notify.deliver, dict(channels or {}), message)
    return said


async def execute(db: aiosqlite.Connection, run_id: int) -> None:
    async with db.execute(
        """SELECT r.*, n.name AS nas_name FROM reports r
           LEFT JOIN nas n ON n.id = r.nas_id
           JOIN report_runs x ON x.report_id = r.id WHERE x.id = ?""",
        (run_id,),
    ) as cur:
        report = await cur.fetchone()
    if report is None:
        return
    await db.execute(
        "UPDATE report_runs SET status = 'running', started_at = datetime('now') WHERE id = ?",
        (run_id,),
    )
    await db.commit()

    figures: dict[str, Any] = {}
    status, error, delivered = "ok", "", ""
    caller: Optional[Caller] = None
    try:
        caller = await _caller(db, report)
        decision = await gate.check(db, caller, NEEDS[report["kind"]])
        if not decision.allowed:
            raise ReportError(f"its run-as user may not read this: {decision.reason}")
        sections = await build_figures.build(db, report["kind"], report["nas_id"],
                                             report["period_days"])
        if report["compare"]:
            sections += await build_figures.compare(db, report["kind"], report["nas_id"],
                                                    report["period_days"])
        title = f"{TITLES[report['kind']]} — {report['name']}"
        figures = {
            "title": title,
            "kind": report["kind"],
            "nas": report["nas_name"] or "every NAS",
            "period": {"days": report["period_days"]},
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "sections": sections,
            "summary": "",
        }
        if report["ai_summary"] and report["provider_id"]:
            figures["summary"] = await _summarise(db, report, figures)
        if report["deliver"]:
            delivered = await _deliver(db, report, run_id, figures)
    except ReportError as exc:
        status, error = "error", str(exc)
    except Exception as exc:
        log.exception("Report %s failed", report["name"])
        status, error = "error", f"it failed unexpectedly — {exc}"

    await db.execute(
        """UPDATE report_runs SET status = ?, finished_at = datetime('now'), figures = ?,
                                  summary = ?, error = ?, delivered = ? WHERE id = ?""",
        (status, json.dumps(figures)[:2_000_000], str(figures.get("summary", ""))[:8000],
         error[:2000], delivered[:500], run_id),
    )
    # Retention, applied after each run rather than on a timer of its own.
    keep = int((await settings_store.get_all(db)).get("report_retention_days") or 365)
    await db.execute(
        "DELETE FROM report_runs WHERE finished_at < datetime('now', '-' || ? || ' days')",
        (keep,),
    )
    await db.commit()

    who = caller or Caller(kind="system", via="worker", username=f"report {report['name']}")
    await audit.record(
        db, who, "reports.run", "allowed", reason="scheduled or queued report",
        outcome="ok" if status == "ok" else "error",
        target=f"report:{report['id']} {report['name']}",
        detail=(error or f"{len(figures.get('sections', []))} sections")[:500],
    )
    log.info("Report %s: %s", report["name"], status)
