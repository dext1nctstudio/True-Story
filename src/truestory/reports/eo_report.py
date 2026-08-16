"""PDF rendering. Deterministic, no model anywhere in this path.

A document that production counsel reviews, that an underwriter relies on, and
that may be produced in discovery must render identically from identical data
every time. That rules out any generative step in the rendering path, so this
module is templates and layout arithmetic and nothing else.

Structure follows the format carriers already read, which is the point: the
output is not a novel artifact that a broker has to learn, it is the document
their checklist already asks for.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("truestory.reports")

PAGE_WIDTH = 595  # A4 points
PAGE_HEIGHT = 842
MARGIN = 54


def render_pdf(report: dict[str, Any], *, watermark: str | None = None) -> bytes:
    """Render the E&O clearance report.

    `watermark` is set for the underwriter role, which receives the package
    read only and watermarked because it is an external party outside the
    production's trust boundary.
    """
    try:
        return _render_reportlab(report, watermark)
    except ImportError:
        log.warning("reportlab unavailable, emitting the plain text fallback")
        return _render_text(report).encode("utf-8")


def _render_reportlab(report: dict[str, Any], watermark: str | None) -> bytes:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title="E&O Clearance Report",
        author="TRUE STORY",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=14)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=HexColor("#555555"))

    flow: list[Any] = []
    title_page = report.get("title_page", {})

    # ── title page ───────────────────────────────────────────────────────────
    flow.append(Paragraph("E&O CLEARANCE REPORT", h1))
    flow.append(Paragraph(str(title_page.get("production_title", "Untitled")), h2))
    flow.append(Spacer(1, 6 * mm))

    flow.append(
        _kv_table(
            Table,
            TableStyle,
            HexColor,
            [
                ("Draft", title_page.get("draft", "")),
                ("Script hash", title_page.get("script_hash", "")),
                ("Pages", title_page.get("page_count", "")),
                ("Prepared", title_page.get("prepared_at", "")),
                ("Truth claim framing", "YES" if title_page.get("truth_claim_framing") else "no"),
            ],
        )
    )

    # The framing note is the single most consequential sentence on the page
    # when it applies, so it sits above everything except the identifiers.
    if title_page.get("framing_note"):
        flow.append(Spacer(1, 4 * mm))
        flow.append(Paragraph(f"<b>{title_page['framing_note']}</b>", body))

    # ── coverage statement ───────────────────────────────────────────────────
    coverage = report.get("coverage_statement", {})
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph("Coverage quality", h2))
    flow.append(
        Paragraph(
            f"This report is <b>{coverage.get('coverage_quality', 'unknown')}</b>. "
            f"{coverage.get('statement', '')}",
            body,
        )
    )
    for warning in coverage.get("warnings", []):
        flow.append(Paragraph(f"&bull; {warning}", small))

    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(str(title_page.get("disclaimer", "")), small))

    # ── executive summary ────────────────────────────────────────────────────
    summary = report.get("executive_summary", {})
    flow.append(PageBreak())
    flow.append(Paragraph("Executive summary", h1))
    flow.append(
        _kv_table(
            Table,
            TableStyle,
            HexColor,
            [
                ("Research subjects", summary.get("research_subjects", 0)),
                ("Claims verified", summary.get("claims_verified", 0)),
                ("Claims unsupported", summary.get("claims_unsupported", 0)),
                ("Claims contradicted", summary.get("claims_contradicted", 0)),
                ("Opinions excluded", summary.get("opinions_excluded", 0)),
                ("Counsel items", summary.get("counsel_items", 0)),
                ("Remedies verified", summary.get("remedies_verified", 0)),
                ("Monitors active", summary.get("monitors_active", 0)),
                ("Research cost", f"${summary.get('cost_usd', 0):.2f}"),
                ("Elapsed", f"{summary.get('duration_seconds', 0):.0f}s"),
            ],
        )
    )

    # ── contradicted claims ──────────────────────────────────────────────────
    contradicted = report.get("contradicted_claims", [])
    if contradicted:
        flow.append(PageBreak())
        flow.append(Paragraph("Contradicted factual claims", h1))
        flow.append(
            Paragraph(
                "Each item below is an assertion about a real person or event that "
                "the public record contradicts. Sources are listed with each item "
                "and again in full in the evidence appendix.",
                body,
            )
        )
        for item in contradicted:
            flow.append(Spacer(1, 4 * mm))
            flow.append(Paragraph(f"<b>{item.get('subject', '')}</b>", h2))
            flow.append(Paragraph(f"Claim: {item.get('claim', '')}", body))
            flow.append(Paragraph(f"Pages: {', '.join(item.get('pages', []))}", small))
            flow.append(Paragraph(item.get("language", ""), body))
            flow.append(Paragraph(f"Rationale: {item.get('rationale', '')}", body))
            for source in item.get("contradicting_sources", [])[:6]:
                flow.append(
                    Paragraph(f"&bull; {source.get('title', '')} ({source.get('url', '')})", small)
                )

    # ── elements by status ───────────────────────────────────────────────────
    flow.append(PageBreak())
    flow.append(Paragraph("Clearance ledger", h1))
    for status, items in (report.get("elements_by_status", {}) or {}).items():
        flow.append(Paragraph(f"{status} ({len(items)})", h2))
        rows = [["Element", "Type", "Pages", "Conditions"]]
        rows.extend(
            [
                str(i.get("element", ""))[:48],
                str(i.get("type", "")).replace("_", " ").title()[:24],
                ", ".join(i.get("pages", [])[:4]),
                "; ".join(i.get("conditions", []))[:40],
            ]
            for i in items[:60]
        )
        flow.append(_grid(Table, TableStyle, HexColor, rows))
        flow.append(Spacer(1, 3 * mm))

    # ── evidence appendix ────────────────────────────────────────────────────
    flow.append(PageBreak())
    flow.append(Paragraph("Evidence appendix", h1))
    flow.append(
        Paragraph(
            "Every source relied on, with the timestamp at which it was read. A "
            "finding that cites a page which later changes is worth much less at "
            "claim time than one carrying the date the production read it.",
            body,
        )
    )
    for entry in report.get("evidence_appendix", [])[:400]:
        flow.append(Spacer(1, 3 * mm))
        flow.append(Paragraph(f"<b>{entry.get('subject', '')}</b>", body))
        flow.append(
            Paragraph(
                f"Provider {entry.get('provider', '')}"
                f"{' (FALLBACK)' if entry.get('is_fallback') else ''}, "
                f"confidence {entry.get('confidence', 0):.2f}, "
                f"retrieved {entry.get('retrieved_at', '')}",
                small,
            )
        )
        for citation in entry.get("citations", [])[:8]:
            flow.append(
                Paragraph(
                    f"&bull; [{citation.get('source_type', '')}] {citation.get('title', '')} "
                    f"({citation.get('url', '')}) accessed {citation.get('accessed_at', '')}",
                    small,
                )
            )

    doc.build(
        flow,
        onFirstPage=lambda c, d: _decorate(c, d, watermark),
        onLaterPages=lambda c, d: _decorate(c, d, watermark),
    )
    return buffer.getvalue()


# reportlab is imported inside `render_pdf` so that nothing in the import graph
# depends on it, which is why these helpers take the classes rather than
# importing them. The parameters are the classes themselves, hence the `_cls`
# names: a bare `Table` reads as a type annotation at every call site.
def _kv_table(table_cls: Any, style_cls: Any, hex_color: Any, pairs: list[tuple[str, Any]]) -> Any:
    table = table_cls([[k, str(v)] for k, v in pairs], colWidths=[150, 320])
    table.setStyle(
        style_cls(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), hex_color("#555555")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, hex_color("#dddddd")),
            ]
        )
    )
    return table


def _grid(table_cls: Any, style_cls: Any, hex_color: Any, rows: list[list[str]]) -> Any:
    table = table_cls(rows, colWidths=[190, 110, 90, 90], repeatRows=1)
    table.setStyle(
        style_cls(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), hex_color("#f2f2f2")),
                ("GRID", (0, 0), (-1, -1), 0.25, hex_color("#dddddd")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _decorate(canvas: Any, doc: Any, watermark: str | None) -> None:
    """Footer on every page, plus the watermark for external copies."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillGray(0.45)
    canvas.drawString(
        MARGIN,
        28,
        "TRUE STORY  ·  decision support for a clearance attorney, not legal advice",
    )
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 28, f"page {doc.page}")

    if watermark:
        canvas.setFont("Helvetica-Bold", 52)
        canvas.setFillGray(0.92)
        canvas.saveState()
        canvas.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, watermark)
        canvas.restoreState()

    canvas.restoreState()


def _render_text(report: dict[str, Any]) -> str:
    """Plain text fallback so the artifact always exists."""
    title_page = report.get("title_page", {})
    summary = report.get("executive_summary", {})
    lines = [
        "E&O CLEARANCE REPORT",
        "=" * 60,
        f"Production : {title_page.get('production_title', '')}",
        f"Draft      : {title_page.get('draft', '')}",
        f"Prepared   : {title_page.get('prepared_at', datetime.now(UTC).isoformat())}",
        f"Framing    : {'TRUE STORY ASSERTED' if title_page.get('truth_claim_framing') else 'none'}",
        "",
        "EXECUTIVE SUMMARY",
        "-" * 60,
    ]
    lines.extend(f"  {k.replace('_', ' ').title():28} {v}" for k, v in summary.items())
    lines.extend(["", title_page.get("disclaimer", "")])
    return "\n".join(lines)
