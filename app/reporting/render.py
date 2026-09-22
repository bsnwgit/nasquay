"""
A report's figures as a document: CSV for the numbers, PDF for the whole thing.

Both are made from the stored figures on demand. Nothing is written to disk, so a report
can be re-read in either form long after it ran, and there is no file to keep in step
with the database.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# Landscape, because these tables are wide: eight columns of figures in portrait is a
# table nobody can read.
PAGE = landscape(A4)
MARGIN = 12 * mm


def csv_bytes(figures: dict[str, Any]) -> bytes:
    """Every section, one after another, with a blank line between them."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([figures.get("title", "NASQuay report")])
    writer.writerow([f"period: {figures.get('period', {}).get('days', '')} days",
                     f"generated: {figures.get('generated_at', '')}"])
    for section in figures.get("sections", []):
        writer.writerow([])
        writer.writerow([section.get("heading", "")])
        if section.get("columns"):
            writer.writerow(section["columns"])
        for row in section.get("rows", []):
            writer.writerow(row)
    return out.getvalue().encode("utf-8-sig")   # the BOM is what spreadsheets want


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=18, spaceAfter=4),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9,
                              textColor=colors.HexColor("#555555"), spaceAfter=10),
        "heading": ParagraphStyle("h", parent=base["Heading2"], fontSize=12, spaceBefore=8,
                                  spaceAfter=2),
        "note": ParagraphStyle("n", parent=base["Normal"], fontSize=8,
                               textColor=colors.HexColor("#555555"), spaceAfter=4),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9, alignment=TA_LEFT),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=7.5, leading=9),
    }


def _table(section: dict[str, Any], style: ParagraphStyle) -> Table:
    columns = section.get("columns") or []
    # Cells are paragraphs so that a long detail wraps instead of running off the page.
    data = [[Paragraph(f"<b>{str(name)}</b>", style) for name in columns]]
    for row in section.get("rows", []):
        data.append([Paragraph(str(value), style) for value in row])
    width = PAGE[0] - 2 * MARGIN
    table = Table(data, repeatRows=1, colWidths=[width / max(len(columns), 1)] * len(columns))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
    ]))
    return table


def pdf_bytes(figures: dict[str, Any]) -> bytes:
    style = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
        title=figures.get("title", "NASQuay report"), author="NASQuay",
    )
    period = figures.get("period", {})
    flow: list[Any] = [
        Paragraph(str(figures.get("title", "NASQuay report")), style["title"]),
        Paragraph(
            f"The past {period.get('days', '?')} days · generated "
            f"{figures.get('generated_at', '')} · figures recorded by NASQuay, "
            "not read from a NAS for this report",
            style["sub"],
        ),
    ]
    if figures.get("summary"):
        flow += [
            Paragraph("Summary", style["heading"]),
            Paragraph("Written by a language model from the figures below.", style["note"]),
            Paragraph(str(figures["summary"]).replace("\n", "<br/>"), style["body"]),
        ]
    for section in figures.get("sections", []):
        parts = [Paragraph(str(section.get("heading", "")), style["heading"])]
        if section.get("note"):
            parts.append(Paragraph(str(section["note"]), style["note"]))
        if section.get("rows"):
            parts.append(_table(section, style["cell"]))
        else:
            parts.append(Paragraph("Nothing to report.", style["body"]))
        # The heading, its note and the first rows stay together; a heading alone at the
        # foot of a page reads as an empty section.
        flow.append(KeepTogether(parts[:2]))
        flow.append(parts[2])
        flow.append(Spacer(1, 6))
    if not figures.get("sections"):
        flow.append(Paragraph("Nothing to report.", style["body"]))
    document.build(flow)
    return buffer.getvalue()


def filename(figures: dict[str, Any], run_id: int, suffix: str) -> str:
    stem = "".join(
        ch if ch.isalnum() or ch in "-_" else "-"
        for ch in str(figures.get("title", "report")).lower()
    ).strip("-")
    return f"{stem or 'report'}-{run_id}.{suffix}"


__all__ = ["csv_bytes", "pdf_bytes", "filename", "PageBreak"]
