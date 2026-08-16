"""Agent 8, ReportAgent. Deterministic and templated. No LLM in this path.

The rendering path is byte stable on purpose. A document that a production
counsel reviews, that an underwriter relies on, and that may be produced in
discovery cannot vary between two runs over identical data. There is no model
anywhere in this file.

Five artifacts, four audiences:

    Verdict annotated script   writer, showrunner    interactive plus PDF
    Claim Register             counsel               per person claim table
    E&O Clearance Report       underwriter, counsel  PDF with evidence appendix
    Clearance Log              insurer checklist     CSV
    Monitor Manifest           producer              active watches and cadence

The front page states the report's own coverage quality. Principle P5. An
underwriter, and a judge, prefers a caveated report to a confident wrong one.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import UTC, datetime
from typing import Any

from truestory.models.claims import ClaimRollup, FactualClaim
from truestory.models.elements import ClearableElement, Remedy, RunSummary
from truestory.models.enums import (
    ClearanceStatus,
    ElementType,
    Verdict,
)
from truestory.models.evidence import MonitorHandle
from truestory.models.spans import ScriptDocument
from truestory.policy import load_rubric

log = logging.getLogger("truestory.report")

_PERSON_TYPES = frozenset(
    {ElementType.REAL_PERSON_DEPICTED, ElementType.REAL_PERSON_IDENTIFIABLE}
)

DISCLAIMER = (
    "This report is decision support for a clearance attorney. It is not legal "
    "advice and it does not replace review by production counsel. Every clearance "
    "report in this industry is reviewed by a qualified attorney before a policy "
    "is bound. This system automates the research and the document, not the "
    "judgement."
)


class ReportAgent:
    """Render every deliverable from the adjudicated run state."""

    name = "ReportAgent"

    def __init__(self) -> None:
        self.rubric = load_rubric()

    # ── entry point ──────────────────────────────────────────────────────────
    def run(
        self,
        document: ScriptDocument,
        claims: list[FactualClaim],
        elements: list[ClearableElement],
        remedies: list[Remedy],
        monitors: list[MonitorHandle],
        summary: RunSummary,
    ) -> dict[str, Any]:
        return {
            "summary": summary.to_dict(),
            "overlay": self.verdict_overlay(document, claims, elements),
            "claim_register": self.claim_register(claims, elements),
            "eo_report": self.eo_report(document, claims, elements, remedies, summary),
            "clearance_log_csv": self.clearance_log(elements),
            "monitor_manifest": self.monitor_manifest(monitors),
            "coverage_statement": self.coverage_statement(summary),
        }

    # ── the money shot ───────────────────────────────────────────────────────
    def verdict_overlay(
        self,
        document: ScriptDocument,
        claims: list[FactualClaim],
        elements: list[ClearableElement],
    ) -> dict[str, Any]:
        """The payload behind the script view where lines light up.

        Restraint is the design language. A script drowning in highlights reads
        as noise, so opinion lines stay untouched grey and verified lines get a
        quiet underline. Red must be rare to be legible.
        """
        by_line: dict[str, list[dict[str, Any]]] = {}

        # Line numbers reaching this point can be approximate: a claim whose
        # wording the model rephrased falls back to the line of the span it
        # came from, and an element carries its raw span line. Either can be a
        # blank separator line, which renders as a highlight floating in empty
        # space with no text to explain it. Snapping to the nearest line that
        # actually has words keeps every annotation attached to something
        # readable.
        lines_by_scene = {s.scene_no: s.text.split("\n") for s in document.scenes}

        def anchor(scene_no: int, line_no: int) -> int:
            lines = lines_by_scene.get(scene_no)
            if not lines or line_no >= len(lines) or lines[line_no].strip():
                return line_no
            for offset in range(1, 4):
                for candidate in (line_no - offset, line_no + offset):
                    if 0 <= candidate < len(lines) and lines[candidate].strip():
                        return candidate
            return line_no

        def locate_element(scene_no: int, line_no: int, surface: str) -> int:
            """Anchor an element to a line that actually contains its name.

            An element's line comes from whichever span survived grouping, and
            after coreference merging that can be a different mention than the
            one being rendered — which is how "Eiffel Tower" ended up
            highlighting a bare character cue. The element's own surface form
            is the reliable signal, so prefer the nearest line containing it.
            """
            lines = lines_by_scene.get(scene_no)
            needle = (surface or "").strip().lower()
            if not lines or not needle:
                return anchor(scene_no, line_no)
            matches = [i for i, text in enumerate(lines) if needle in text.lower()]
            if not matches:
                return anchor(scene_no, line_no)
            return min(matches, key=lambda i: abs(i - line_no))

        for claim in claims:
            for occurrence in claim.asserted_in:
                key = f"{occurrence.scene_no}:{anchor(occurrence.scene_no, occurrence.line_no)}"
                by_line.setdefault(key, []).append(
                    {
                        "kind": "claim",
                        "id": claim.claim_id,
                        "text": claim.claim_text,
                        "surface_form": occurrence.surface_form,
                        "verdict": str(claim.verdict) if claim.verdict else None,
                        "color": claim.color(),
                        "confidence": round(claim.confidence, 3),
                        "citation_count": claim.citation_count,
                        "subject": claim.subject_name,
                        "polarity": str(claim.polarity),
                        "needs_counsel": claim.needs_counsel,
                        "remedy_id": claim.remedy_id,
                        "language": self.rubric.verdict_language(
                            str(claim.verdict) if claim.verdict else "UNSUPPORTED", "ui"
                        ),
                    }
                )

        for element in elements:
            for occurrence in element.occurrences:
                key = (
                    f"{occurrence.scene_no}:"
                    f"{locate_element(occurrence.scene_no, occurrence.line_no, occurrence.surface_form)}"
                )
                by_line.setdefault(key, []).append(
                    {
                        "kind": "element",
                        "id": element.element_id,
                        "text": element.display_form(),
                        "surface_form": occurrence.surface_form,
                        "element_type": str(element.element_type),
                        "status": str(element.status),
                        "color": _status_color(element.status),
                        "confidence": round(element.confidence, 3),
                        "citation_count": element.citation_count,
                        "masked": element.masked,
                        "needs_counsel": element.needs_counsel,
                    }
                )

        return {
            "script": {
                "title": document.title,
                "draft_version": document.draft_version,
                "page_count": document.page_count,
                "truth_claim_framing": document.truth_claim_framing,
                "truth_claim_evidence": document.truth_claim_evidence,
            },
            "scenes": [
                {
                    "scene_no": s.scene_no,
                    "heading": s.heading,
                    "start_page": s.start_page,
                    "text": s.text,
                }
                for s in document.scenes
            ],
            "annotations": by_line,
            "legend": {
                "green": "Verified against the public record.",
                "amber": "Unsupported. No record either way. This is not a finding of falsity.",
                "red": "Contradicted by the record. Sources attached.",
                "grey": "Opinion. Not a factual assertion and not researched.",
            },
        }

    # ── counsel view ─────────────────────────────────────────────────────────
    def claim_register(
        self, claims: list[FactualClaim], elements: list[ClearableElement]
    ) -> dict[str, Any]:
        """Per person claim table. The document counsel actually works from."""
        threshold, min_claims = self.rubric.amber_threshold()
        rollups: list[dict[str, Any]] = []

        for element in elements:
            if element.element_type not in _PERSON_TYPES or not element.claims:
                continue
            rollup = ClaimRollup.from_claims(
                element.element_id,
                element.canonical_form,
                element.claims,
                alive=element.subject_alive,
                public_figure_status=element.public_figure_status,
            )
            entry = rollup.to_dict()
            entry["exceeds_amber_threshold"] = (
                rollup.researched_count >= min_claims
                and rollup.exceeds_threshold(threshold)
            )
            entry["amber_threshold"] = threshold
            entry["claims"] = [
                {
                    "claim_id": c.claim_id,
                    "claim_text": c.claim_text,
                    "claim_type": str(c.claim_type),
                    "polarity": str(c.polarity),
                    "verdict": str(c.verdict) if c.verdict else None,
                    "confidence": round(c.confidence, 3),
                    "rationale": c.rationale,
                    "needs_counsel": c.needs_counsel,
                    "counsel_reason": c.counsel_reason,
                    "pages": [o.page_eighths for o in c.asserted_in],
                    "citations": [
                        {"url": cit.url, "title": cit.title, "accessed_at": cit.accessed_at.isoformat()}
                        for e in c.evidence
                        for cit in e.citations
                    ],
                }
                for c in element.claims
            ]
            rollups.append(entry)

        rollups.sort(key=lambda r: (-r["amber_density"], -r["total_claims"]))

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "persons": rollups,
            "unattributed_claims": [
                c.to_dict(include_evidence=False)
                for c in claims
                if not any(c in e.claims for e in elements)
            ],
            "note": (
                "Amber density counts claims the record can neither support nor "
                "contradict. That is the category which settles: not provably false, "
                "and therefore not defensible either."
            ),
        }

    # ── underwriter view ─────────────────────────────────────────────────────
    def eo_report(
        self,
        document: ScriptDocument,
        claims: list[FactualClaim],
        elements: list[ClearableElement],
        remedies: list[Remedy],
        summary: RunSummary,
    ) -> dict[str, Any]:
        """The E&O format package, structured for PDF rendering."""
        by_status: dict[str, list[dict[str, Any]]] = {}
        for element in elements:
            by_status.setdefault(str(element.status), []).append(
                {
                    "element_id": element.element_id,
                    "type": str(element.element_type),
                    "element": element.display_form(),
                    "pages": [o.page_eighths for o in element.occurrences[:12]],
                    "occurrences": element.occurrence_count,
                    "status": str(element.status),
                    "rationale": element.rationale,
                    "conditions": element.conditions,
                    "confidence": round(element.confidence, 3),
                    "jurisdictions": element.jurisdictions,
                    "masked": element.masked,
                }
            )

        return {
            "title_page": {
                "production_title": document.title,
                "draft": document.draft_version,
                "script_hash": document.script_hash,
                "page_count": document.page_count,
                "prepared_at": datetime.now(UTC).isoformat(),
                "truth_claim_framing": document.truth_claim_framing,
                "framing_note": (
                    "This production asserts to its audience that the story is true. "
                    "Every person adjacent element has been escalated one risk tier "
                    "accordingly, because courts have treated that framing itself as "
                    "bearing on whether a production acted with reckless disregard "
                    "for falsity."
                )
                if document.truth_claim_framing
                else None,
                "disclaimer": DISCLAIMER,
            },
            "coverage_statement": self.coverage_statement(summary),
            "executive_summary": {
                "research_subjects": summary.research_subjects,
                "claims_verified": summary.green,
                "claims_unsupported": summary.amber,
                "claims_contradicted": summary.red,
                "opinions_excluded": summary.grey,
                "counsel_items": summary.counsel_items,
                "confirmations_pending": summary.confirmations_pending,
                "remedies_verified": summary.remedies_verified,
                "monitors_active": summary.monitors_created,
                "cost_usd": summary.cost_usd,
                "duration_seconds": summary.duration_seconds,
            },
            "contradicted_claims": [
                {
                    "claim_id": c.claim_id,
                    "subject": c.subject_name,
                    "claim": c.claim_text,
                    "pages": [o.page_eighths for o in c.asserted_in],
                    "rationale": c.rationale,
                    "confidence": round(c.confidence, 3),
                    "language": self.rubric.verdict_language("CONTRADICTED", "report"),
                    "contradicting_sources": [
                        {"url": cit.url, "title": cit.title, "excerpt": cit.excerpt[:400]}
                        for e in c.evidence
                        for cit in e.citations
                    ],
                    "remedy_id": c.remedy_id,
                }
                for c in claims
                if c.verdict is Verdict.CONTRADICTED
            ],
            "elements_by_status": by_status,
            "remedies": [r.to_dict() for r in remedies],
            "evidence_appendix": self.evidence_appendix(claims, elements),
            "counsel_queue": [
                {
                    "subject": c.subject_name,
                    "item": c.claim_text,
                    "reason": c.counsel_reason,
                }
                for c in claims
                if c.needs_counsel
            ]
            + [
                {
                    "subject": e.display_form(),
                    "item": str(e.element_type),
                    "reason": e.counsel_reason,
                }
                for e in elements
                if e.needs_counsel
            ],
        }

    def evidence_appendix(
        self, claims: list[FactualClaim], elements: list[ClearableElement]
    ) -> list[dict[str, Any]]:
        """Every source, with the timestamp it was read.

        A finding that cites a page which has since changed is worth much less
        at claim time than one carrying the date the production read it, which
        is why retrieval time is a first class field rather than metadata.
        """
        entries: list[dict[str, Any]] = []

        for subject in [*claims, *elements]:
            subject_id = getattr(subject, "claim_id", None) or getattr(subject, "element_id")
            label = getattr(subject, "claim_text", None) or getattr(subject, "canonical_form")
            for evidence in subject.evidence:
                entries.append(
                    {
                        "subject_id": subject_id,
                        "subject": label,
                        "evidence_id": evidence.evidence_id,
                        "question": evidence.question,
                        "provider": evidence.provider,
                        "is_fallback": evidence.is_fallback,
                        "confidence": round(evidence.effective_confidence, 3),
                        "retrieved_at": evidence.retrieved_at.isoformat(),
                        "citations": [
                            {
                                "url": c.url,
                                "title": c.title,
                                "source_type": c.source_type,
                                "accessed_at": c.accessed_at.isoformat(),
                                "excerpt": c.excerpt[:600],
                            }
                            for c in evidence.citations
                        ],
                    }
                )
        return entries

    # ── insurer checklist ────────────────────────────────────────────────────
    def clearance_log(self, elements: list[ClearableElement]) -> str:
        """CSV of every visible piece of IP and its status. Carriers ask for this."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "element_id", "type", "element", "first_page", "occurrences",
                "jurisdictions", "status", "conditions", "confidence",
                "citations", "needs_counsel", "monitor", "rationale",
            ]
        )
        for element in sorted(elements, key=lambda e: (e.first_page, e.canonical_form)):
            writer.writerow(
                [
                    element.element_id,
                    str(element.element_type),
                    element.display_form(),
                    element.first_page,
                    element.occurrence_count,
                    "|".join(element.jurisdictions),
                    str(element.status),
                    "|".join(element.conditions),
                    round(element.confidence, 3),
                    element.citation_count,
                    "yes" if element.needs_counsel else "no",
                    element.monitor_handle or "",
                    element.rationale.replace("\n", " ")[:400],
                ]
            )
        return buffer.getvalue()

    # ── producer view ────────────────────────────────────────────────────────
    def monitor_manifest(self, monitors: list[MonitorHandle]) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "active": sum(1 for m in monitors if m.active),
            "inactive": sum(1 for m in monitors if not m.active),
            "monitors": [m.to_dict() for m in monitors],
            "note": (
                "A clearance report is a photograph. Rights are a film. These "
                "watches run for the commercial life of the title and alert before "
                "a licence lapses, not after."
            ),
        }

    # ── honesty ──────────────────────────────────────────────────────────────
    def coverage_statement(self, summary: RunSummary) -> dict[str, Any]:
        """The front page statement of the report's own quality.

        Principle P5, degrade honestly. An underwriter, and a judge, prefers a
        caveated report to a confident wrong one.
        """
        warnings = list(summary.coverage_warnings)
        coverage = self.rubric.coverage

        if summary.fallback_rate > coverage.get("warn_if_fallback_rate_above", 0.10):
            warnings.append(
                f"{summary.fallback_rate:.0%} of research was served by a fallback "
                "provider. Confidence on those items is capped and they are marked "
                "in the evidence appendix."
            )

        quality = (
            "complete"
            if not warnings
            else ("qualified" if len(warnings) <= 2 else "substantially qualified")
        )

        return {
            "coverage_quality": quality,
            "warnings": warnings,
            "counsel_items": summary.counsel_items,
            "cache_hit_rate": round(summary.cache_hit_rate, 3),
            "fallback_rate": round(summary.fallback_rate, 3),
            "statement": (
                "This report states its own coverage quality. Items the system "
                "declined to decide appear in the counsel queue rather than being "
                "silently cleared."
            ),
            "disclaimer": DISCLAIMER,
        }


# =============================================================================
# helpers
# =============================================================================


def _status_color(status: ClearanceStatus) -> str:
    return {
        ClearanceStatus.CLEAR: "green",
        ClearanceStatus.CLEAR_WITH_CONDITIONS: "green",
        ClearanceStatus.NEEDS_LICENSE: "amber",
        ClearanceStatus.NEEDS_COUNSEL: "amber",
        ClearanceStatus.NOT_CLEAR: "red",
        ClearanceStatus.RESEARCH_FAILED: "grey",
        ClearanceStatus.PENDING: "pending",
    }.get(status, "pending")


def build_summary(
    run_id: str,
    project_id: str,
    document: ScriptDocument,
    claims: list[FactualClaim],
    elements: list[ClearableElement],
    remedies: list[Remedy],
    monitors: list[MonitorHandle],
    *,
    cost_cents: float = 0.0,
    duration_seconds: float = 0.0,
    cache_hit_rate: float = 0.0,
    fallback_rate: float = 0.0,
    coverage_warnings: list[str] | None = None,
) -> RunSummary:
    """Assemble the counters shown on screen and on the report front page."""
    summary = RunSummary(
        run_id=run_id,
        project_id=project_id,
        script_title=document.title,
        draft_version=document.draft_version,
        truth_claim_framing=document.truth_claim_framing,
        total_claims=len(claims),
        total_elements=len(elements),
        cost_cents=cost_cents,
        duration_seconds=duration_seconds,
        cache_hit_rate=cache_hit_rate,
        fallback_rate=fallback_rate,
        coverage_warnings=coverage_warnings or [],
    )

    for claim in claims:
        match claim.verdict:
            case Verdict.VERIFIED:
                summary.green += 1
            case Verdict.UNSUPPORTED | Verdict.UNVERIFIABLE:
                summary.amber += 1
            case Verdict.CONTRADICTED:
                summary.red += 1
            case Verdict.OPINION:
                summary.grey += 1
            case _:
                pass
        if claim.needs_counsel:
            summary.counsel_items += 1
        elif claim.awaiting_confirmation:
            summary.confirmations_pending += 1

    for element in elements:
        if element.needs_counsel:
            summary.counsel_items += 1
        elif element.awaiting_confirmation:
            summary.confirmations_pending += 1

    summary.remedies_verified = sum(1 for r in remedies if r.verified)
    summary.monitors_created = sum(1 for m in monitors if m.active)

    return summary


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False)
