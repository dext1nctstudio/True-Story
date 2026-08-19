"""Clearable elements and remedies.

An element is one canonical thing that needs clearing: a name, a mark, a cue, a
poster, a person. LedgerAgent produces these by collapsing raw spans, and every
downstream stage keys off `element_id`, which is a content hash so that draft
over draft caching is free.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from truestory.models.claims import FactualClaim
from truestory.models.enums import (
    ClearanceStatus,
    ElementType,
    Processor,
    PublicFigureStatus,
    RiskTier,
)
from truestory.models.evidence import Evidence
from truestory.models.spans import Occurrence


@dataclass(slots=True)
class Remedy:
    """A proposed fix that has itself been verified.

    This is the difference between an agent and a research wrapper. The loop
    proposes a rewrite, sends it back through the same research path under the
    same schema, and only presents it as a fix once it comes back VERIFIED. The
    success criterion is objective, which is why the loop can terminate without
    a model deciding it is finished.
    """

    remedy_id: str
    subject_id: str  # claim_id or element_id
    kind: str  # rewrite | rename | license_request | substitution | disclaimer
    proposal: str  # the new line, name, or clause
    original: str
    rationale: str
    verified: bool = False
    verification_evidence: list[Evidence] = field(default_factory=list)
    iteration: int = 1
    preserves_beat: bool = True  # dramatic function retained
    alternatives: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "remedy_id": self.remedy_id,
            "subject_id": self.subject_id,
            "kind": self.kind,
            "proposal": self.proposal,
            "original": self.original,
            "rationale": self.rationale,
            "verified": self.verified,
            "iteration": self.iteration,
            "preserves_beat": self.preserves_beat,
            "alternatives": self.alternatives,
            "evidence": [e.to_dict() for e in self.verification_evidence],
            "created_at": self.created_at.isoformat(),
        }

    @staticmethod
    def make_id(subject_id: str, proposal: str, iteration: int) -> str:
        digest = hashlib.sha256(f"{subject_id}|{proposal}|{iteration}".encode()).hexdigest()
        return f"rm_{digest[:16]}"


@dataclass(slots=True)
class ClearableElement:
    """One canonical subject of clearance research."""

    element_id: str  # content hash, free draft over draft caching
    element_type: ElementType
    canonical_form: str
    aliases: list[str] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    jurisdictions: list[str] = field(default_factory=list)

    # Populated for person and event types by ClaimExtractor.
    claims: list[FactualClaim] = field(default_factory=list)

    # ── routing, set by RiskRouter ───────────────────────────────────────────
    risk_tier: RiskTier = RiskTier.MEDIUM
    processor: Processor = Processor.LITE
    schema_name: str = "entity_v1"
    also: list[str] = field(default_factory=list)  # findall, monitor, extract
    escalated_by: list[str] = field(default_factory=list)  # audit of why the tier moved

    # ── outcome ──────────────────────────────────────────────────────────────
    status: ClearanceStatus = ClearanceStatus.PENDING
    confidence: float = 0.0
    rationale: str = ""
    conditions: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    #: Independent domains, source pedigree and record agreement behind the
    #: clearance status. Written by the Adjudicator, shown in the UI.
    corroboration: dict[str, Any] = field(default_factory=dict)
    remedies: list[Remedy] = field(default_factory=list)

    # ── person facts ─────────────────────────────────────────────────────────
    subject_alive: bool | None = None
    public_figure_status: PublicFigureStatus = PublicFigureStatus.UNKNOWN
    masked: bool = False  # living private individual, withheld pending counsel

    # ── governance ───────────────────────────────────────────────────────────
    # See the note on FactualClaim. Escalation and confirmation are different
    # workloads and are counted separately everywhere they surface.
    needs_counsel: bool = False
    counsel_reason: str = ""
    awaiting_confirmation: bool = False
    monitor_handle: str | None = None
    adjudicated_at: datetime | None = None

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def first_page(self) -> float:
        return min((o.page for o in self.occurrences), default=0.0)

    @property
    def in_dialogue(self) -> bool:
        return any(o.modality.value == "script_dialogue" for o in self.occurrences)

    @property
    def is_cleared(self) -> bool:
        return self.status in (ClearanceStatus.CLEAR, ClearanceStatus.CLEAR_WITH_CONDITIONS)

    @property
    def citation_count(self) -> int:
        return sum(len(e.citations) for e in self.evidence)

    @property
    def total_cost_cents(self) -> float:
        return sum(e.cost_cents for e in self.evidence)

    def display_form(self) -> str:
        """What the UI is allowed to render.

        Privacy by default, principle P6. The system's output is assertions
        about real people, so a living private individual is summarised, never
        named, until counsel unmasks with an audit record behind it.
        """
        if not self.masked:
            return self.canonical_form
        matches = len(self.evidence)
        sources = self.citation_count
        return (
            f"{matches} matching individuals · {sources} sources · withheld pending counsel review"
        )

    def to_dict(self, *, include_evidence: bool = True, unmasked: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "element_id": self.element_id,
            "element_type": str(self.element_type),
            "canonical_form": self.canonical_form if (unmasked or not self.masked) else None,
            "display_form": self.canonical_form if unmasked else self.display_form(),
            "aliases": self.aliases if (unmasked or not self.masked) else [],
            "masked": self.masked,
            "jurisdictions": self.jurisdictions,
            "risk_tier": str(self.risk_tier),
            "processor": str(self.processor),
            "schema_name": self.schema_name,
            "also": self.also,
            "escalated_by": self.escalated_by,
            "status": str(self.status),
            "confidence": self.confidence,
            "rationale": self.rationale,
            "conditions": self.conditions,
            "subject_alive": self.subject_alive,
            "public_figure_status": str(self.public_figure_status),
            "needs_counsel": self.needs_counsel,
            "counsel_reason": self.counsel_reason,
            "awaiting_confirmation": self.awaiting_confirmation,
            "monitor_handle": self.monitor_handle,
            "occurrence_count": self.occurrence_count,
            "first_page": self.first_page,
            "citation_count": self.citation_count,
            "corroboration": self.corroboration,
            "cost_cents": round(self.total_cost_cents, 4),
            "occurrences": [o.to_dict() for o in self.occurrences],
            "claims": [c.to_dict(include_evidence=False) for c in self.claims],
            "remedies": [r.to_dict() for r in self.remedies],
            "adjudicated_at": self.adjudicated_at.isoformat() if self.adjudicated_at else None,
        }
        if include_evidence:
            d["evidence"] = [e.to_dict() for e in self.evidence]
        return d

    def record_adjudication(
        self,
        status: ClearanceStatus,
        confidence: float,
        rationale: str,
        evidence: list[Evidence],
        conditions: list[str] | None = None,
    ) -> None:
        if status is not ClearanceStatus.RESEARCH_FAILED and not any(e.is_usable for e in evidence):
            raise ValueError(
                f"element {self.element_id}: status {status} requires at least one "
                "citation bearing evidence record (principle P2)"
            )
        self.status = status
        self.confidence = confidence
        self.rationale = rationale
        self.evidence = evidence
        self.conditions = conditions or []
        self.adjudicated_at = datetime.now(UTC)

    @staticmethod
    def make_id(element_type: ElementType, canonical_form: str, jurisdictions: list[str]) -> str:
        """Content addressed on the three things that define the research question."""
        key = (
            f"{element_type}|{canonical_form.strip().casefold()}|{'|'.join(sorted(jurisdictions))}"
        )
        return f"el_{hashlib.sha256(key.encode()).hexdigest()[:20]}"


@dataclass(slots=True)
class RunSummary:
    """The counters on the front page of the report and on the demo screen."""

    run_id: str
    project_id: str
    script_title: str
    draft_version: str
    truth_claim_framing: bool

    total_claims: int = 0
    total_elements: int = 0
    green: int = 0
    amber: int = 0
    red: int = 0
    grey: int = 0
    counsel_items: int = 0
    confirmations_pending: int = 0
    monitors_created: int = 0
    remedies_verified: int = 0

    # Research spend, priced per Parallel task run.
    cost_cents: float = 0.0
    # Model spend, priced per Gemini token. A separate bill, reported next to
    # the research figure rather than folded into it, because the research
    # ceiling governs research only.
    model_cost_cents: float = 0.0
    duration_seconds: float = 0.0
    cache_hit_rate: float = 0.0
    fallback_rate: float = 0.0

    # Principle P5, degrade honestly. The report states its own coverage
    # quality on the front page. An underwriter, and a judge, prefers a
    # caveated report to a confident wrong one.
    coverage_warnings: list[str] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(self.cost_cents / 100.0, 4)

    @property
    def model_cost_usd(self) -> float:
        return round(self.model_cost_cents / 100.0, 4)

    @property
    def total_cost_usd(self) -> float:
        """Research plus model. What the run actually cost to produce."""
        return round((self.cost_cents + self.model_cost_cents) / 100.0, 4)

    @property
    def research_subjects(self) -> int:
        return self.total_claims + self.total_elements

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "script_title": self.script_title,
            "draft_version": self.draft_version,
            "truth_claim_framing": self.truth_claim_framing,
            "total_claims": self.total_claims,
            "total_elements": self.total_elements,
            "research_subjects": self.research_subjects,
            "verdicts": {
                "green": self.green,
                "amber": self.amber,
                "red": self.red,
                "grey": self.grey,
            },
            "counsel_items": self.counsel_items,
            "confirmations_pending": self.confirmations_pending,
            "monitors_created": self.monitors_created,
            "remedies_verified": self.remedies_verified,
            "cost_cents": round(self.cost_cents, 2),
            "cost_usd": self.cost_usd,
            "model_cost_cents": round(self.model_cost_cents, 2),
            "model_cost_usd": self.model_cost_usd,
            "total_cost_usd": self.total_cost_usd,
            "duration_seconds": round(self.duration_seconds, 1),
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "coverage_warnings": self.coverage_warnings,
        }
