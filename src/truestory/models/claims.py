"""The claim, the atom of TRUE STORY.

Principle P8. A factual claim is a first class object with its own lifecycle:
extracted, decomposed, routed, verified, versioned, monitored. It is not an
attribute hanging off an entity. That choice is what lets the system say "this
line is false, here is the record" rather than "this person is risky".

Atomicity is the rule the extraction prompt enforces. "Twice convicted stalker
sentenced to five years" is three claims, not one, because each verifies
independently and because that is exactly how a complaint itemises the alleged
falsehoods.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from truestory.models.enums import (
    ClaimType,
    Polarity,
    PublicFigureStatus,
    RiskTier,
    Verdict,
)
from truestory.models.evidence import Evidence
from truestory.models.spans import Occurrence


@dataclass(slots=True)
class FactualClaim:
    """One atomic, independently verifiable assertion about a real person or event."""

    claim_id: str  # content hash, cacheable across drafts
    subject_element_id: str  # the person or event it is about
    subject_name: str  # denormalised for the UI and the report
    claim_text: str  # atomic: "X was convicted of stalking"
    claim_type: ClaimType
    polarity: Polarity
    asserted_in: list[Occurrence] = field(default_factory=list)

    # ── set by RiskRouter ────────────────────────────────────────────────────
    risk_tier: RiskTier = RiskTier.HIGH
    schema_name: str = "claim_verification_v1"

    # ── set by research and adjudication ─────────────────────────────────────
    verdict: Verdict | None = None
    confidence: float = 0.0
    rationale: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    #: How well corroborated the verdict is: independent domains, source
    #: pedigree, and whether the research payload agreed with the verdict.
    #: Written by the Adjudicator, read by the UI and the report.
    corroboration: dict[str, Any] = field(default_factory=dict)

    # ── subject facts that change the legal standard ─────────────────────────
    subject_alive: bool | None = None
    subject_public_figure_status: PublicFigureStatus = PublicFigureStatus.UNKNOWN

    # ── remediation ──────────────────────────────────────────────────────────
    # `needs_counsel` means the system declined to decide. `awaiting_confirmation`
    # means it decided cleanly and a human signs the result off. Conflating the
    # two would put every verified claim in the lawyer's queue and save nobody
    # any work, which is the failure mode this distinction exists to prevent.
    needs_counsel: bool = False
    counsel_reason: str = ""
    awaiting_confirmation: bool = False
    remedy_id: str | None = None

    adjudicated_at: datetime | None = None

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def is_opinion(self) -> bool:
        """Opinion is protected speech. It gets no research spend and no colour."""
        return self.claim_type is ClaimType.CHARACTERIZATION or self.verdict is Verdict.OPINION

    @property
    def is_escalation_cocktail(self) -> bool:
        """Negative assertion about a living person. The pattern that gets sued.

        Every one of the three marquee cases is this shape.
        """
        return self.polarity is Polarity.NEGATIVE and self.subject_alive is True

    @property
    def is_amber(self) -> bool:
        """Unsupported or unverifiable.

        This is the category that settles. Not provably false, and therefore
        not defensible either. The Fairstein density rule counts exactly these.
        """
        return self.verdict in (Verdict.UNSUPPORTED, Verdict.UNVERIFIABLE)

    @property
    def occurrence_count(self) -> int:
        return len(self.asserted_in)

    @property
    def first_occurrence(self) -> Occurrence | None:
        return self.asserted_in[0] if self.asserted_in else None

    @property
    def citation_count(self) -> int:
        return sum(len(e.citations) for e in self.evidence)

    @property
    def has_usable_evidence(self) -> bool:
        return any(e.is_usable for e in self.evidence)

    def color(self) -> str:
        """Overlay colour. Unadjudicated renders neutral, never green."""
        if self.verdict is None:
            return "pending"
        from truestory.models.enums import VERDICT_COLOR

        return VERDICT_COLOR[self.verdict]

    def to_dict(self, *, include_evidence: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "claim_id": self.claim_id,
            "subject_element_id": self.subject_element_id,
            "subject_name": self.subject_name,
            "claim_text": self.claim_text,
            "claim_type": str(self.claim_type),
            "polarity": str(self.polarity),
            "risk_tier": str(self.risk_tier),
            "schema_name": self.schema_name,
            "verdict": str(self.verdict) if self.verdict else None,
            "color": self.color(),
            "confidence": self.confidence,
            "rationale": self.rationale,
            "subject_alive": self.subject_alive,
            "subject_public_figure_status": str(self.subject_public_figure_status),
            "needs_counsel": self.needs_counsel,
            "counsel_reason": self.counsel_reason,
            "awaiting_confirmation": self.awaiting_confirmation,
            "remedy_id": self.remedy_id,
            "citation_count": self.citation_count,
            "corroboration": self.corroboration,
            "occurrences": [o.to_dict() for o in self.asserted_in],
            "adjudicated_at": self.adjudicated_at.isoformat() if self.adjudicated_at else None,
        }
        if include_evidence:
            d["evidence"] = [e.to_dict() for e in self.evidence]
        return d

    def record_verdict(
        self,
        verdict: Verdict,
        confidence: float,
        rationale: str,
        evidence: list[Evidence],
    ) -> None:
        """Attach an adjudication.

        The guard is the point. A verdict that is not OPINION and carries no
        evidence is a programming error, not a low quality answer, and it
        raises here rather than reaching a report that an underwriter reads.
        """
        if verdict is not Verdict.OPINION and not any(e.is_usable for e in evidence):
            raise ValueError(
                f"claim {self.claim_id}: verdict {verdict} requires at least one "
                "citation bearing evidence record (principle P2)"
            )
        self.verdict = verdict
        self.confidence = confidence
        self.rationale = rationale
        self.evidence = evidence
        self.adjudicated_at = datetime.now(UTC)

    @staticmethod
    def make_id(subject_element_id: str, claim_text: str) -> str:
        """Content addressed.

        The same sentence about the same person is the same claim in draft one
        and in draft nine, so the cache hits and the diff only researches what
        actually changed. Roughly a ninety five percent reduction on a typical
        revision, which is what makes series economics work.
        """
        normalised = " ".join(claim_text.lower().split())
        digest = hashlib.sha256(f"{subject_element_id}|{normalised}".encode()).hexdigest()
        return f"cl_{digest[:20]}"


@dataclass(slots=True)
class ClaimRollup:
    """Per person view. The Fairstein rule made visible.

    Fairstein did not turn on one provably false line. It turned on a set of
    scenes attributing specific conduct that the record could not support. So
    the product counts amber claims per named living person and escalates the
    person, not just the line, once density crosses the rubric threshold.
    """

    element_id: str
    person_name: str
    alive: bool | None
    public_figure_status: PublicFigureStatus

    total_claims: int = 0
    verified: int = 0
    unsupported: int = 0
    contradicted: int = 0
    unverifiable: int = 0
    opinion: int = 0
    counsel_items: int = 0

    @property
    def amber_count(self) -> int:
        return self.unsupported + self.unverifiable

    @property
    def researched_count(self) -> int:
        """Claims that were actually researched. Opinions are excluded."""
        return max(0, self.total_claims - self.opinion)

    @property
    def amber_density(self) -> float:
        """Share of researched claims about this person that the record cannot support."""
        return self.amber_count / self.researched_count if self.researched_count else 0.0

    def exceeds_threshold(self, threshold: float) -> bool:
        return self.amber_density > threshold

    @classmethod
    def from_claims(
        cls,
        element_id: str,
        person_name: str,
        claims: list[FactualClaim],
        *,
        alive: bool | None = None,
        public_figure_status: PublicFigureStatus = PublicFigureStatus.UNKNOWN,
    ) -> ClaimRollup:
        r = cls(
            element_id=element_id,
            person_name=person_name,
            alive=alive,
            public_figure_status=public_figure_status,
            total_claims=len(claims),
        )
        for c in claims:
            match c.verdict:
                case Verdict.VERIFIED:
                    r.verified += 1
                case Verdict.UNSUPPORTED:
                    r.unsupported += 1
                case Verdict.CONTRADICTED:
                    r.contradicted += 1
                case Verdict.UNVERIFIABLE:
                    r.unverifiable += 1
                case Verdict.OPINION:
                    r.opinion += 1
                case _:
                    pass
            if c.needs_counsel:
                r.counsel_items += 1
        return r

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "person_name": self.person_name,
            "alive": self.alive,
            "public_figure_status": str(self.public_figure_status),
            "total_claims": self.total_claims,
            "verified": self.verified,
            "unsupported": self.unsupported,
            "contradicted": self.contradicted,
            "unverifiable": self.unverifiable,
            "opinion": self.opinion,
            "amber_count": self.amber_count,
            "amber_density": round(self.amber_density, 4),
            "counsel_items": self.counsel_items,
        }
