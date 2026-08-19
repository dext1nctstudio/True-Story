"""The Evidence envelope, the central contract of the system.

Principle P2: no verdict without evidence. A red line with no citation is
legally worthless and is itself defamatory of the production, so `Evidence` is
mandatory on every adjudication and is enforced structurally through forced
function calling rather than by asking a model nicely.

Parallel's Basis framework, which returns citations, reasoning, excerpts and a
calibrated confidence per output field, maps onto this envelope close to one to
one. That is the deepest reason this partner fits this product. Any provider
that cannot populate `citations` is disqualified from CRITICAL work by
`ResearchProvider.supports_citations`, not by convention.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Citation:
    """One source behind one finding.

    `accessed_at` is not decoration. The evidence appendix of an E&O report
    carries a retrieval timestamp per URL because the web moves and an
    underwriter needs to know when the record was read.
    """

    url: str
    title: str
    excerpt: str
    accessed_at: datetime = field(default_factory=_now)
    source_type: str = "secondary"  # primary | secondary | tertiary
    publisher: str | None = None
    published_at: datetime | None = None
    reliability: float | None = None  # provider supplied, 0..1

    # ── pedigree, filled by providers.source_quality at ingestion ───────────
    # A research API returns a URL and an excerpt. What kind of source that URL
    # is decides whether a CONTRADICTED verdict may stand, so it is classified
    # once, on the way in, rather than assumed downstream.
    source_class: str = "unknown"  # official | registry | archive | news | …
    trust: float = 0.5  # 0..1, weights corroboration
    verified_source: bool = False  # False: host was not in any table

    @property
    def is_primary(self) -> bool:
        return self.source_type == "primary"

    @property
    def is_classified_primary(self) -> bool:
        """Primary *and* recognised, which is what a red line requires.

        A researcher declaring its own blog a primary record does not make it
        one. This is the stricter test the rubric uses for CONTRADICTED.
        """
        return self.source_type == "primary" and self.verified_source

    @property
    def domain(self) -> str:
        from truestory.providers.source_quality import registrable_domain

        return registrable_domain(self.url)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["accessed_at"] = self.accessed_at.isoformat()
        d["published_at"] = self.published_at.isoformat() if self.published_at else None
        d["domain"] = self.domain
        return d

    @classmethod
    def classified(
        cls,
        url: str,
        title: str = "",
        excerpt: str = "",
        *,
        declared_type: str | None = None,
        publisher: str | None = None,
        published_at: datetime | None = None,
        accessed_at: datetime | None = None,
    ) -> Citation:
        """Build a citation with its pedigree resolved from the URL.

        Every provider funnels through here, so there is exactly one place
        where a URL becomes a typed, weighted source, and no provider can
        accidentally reintroduce the "everything is secondary" default that
        made the CONTRADICTED verdict unreachable.
        """
        from truestory.providers.source_quality import assess

        verdict = assess(url, declared_type)
        return cls(
            url=url,
            title=(title or verdict.host or url)[:300],
            excerpt=(excerpt or "")[:1200],
            accessed_at=accessed_at or _now(),
            source_type=verdict.source_type,
            publisher=publisher or (verdict.host or None),
            published_at=published_at,
            source_class=verdict.source_class,
            trust=verdict.trust,
            verified_source=verdict.verified,
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """One research answer, fully attributed and fully costed.

    Every field after `reasoning` exists for a reason that shows up somewhere
    the user can see:

      confidence   drives the deterministic post checks in the Adjudicator
      provider     printed in the evidence appendix so the report is auditable
      is_fallback  caps confidence at 0.6 and stamps the report coverage note
      cost_cents   feeds the live cost meter and the BigQuery unit economics
      cached       feeds the cache hit rate metric, above ninety percent by
                   the third draft, which is what makes series economics work
    """

    evidence_id: str
    subject_id: str  # claim_id or element_id
    question: str  # exactly what was asked
    finding: dict[str, Any]  # conforms to the declared JSON schema
    citations: list[Citation]
    reasoning: str
    confidence: float  # calibrated 0..1
    provider: str  # "parallel_task:core" | "gemini_grounded" | "cache"
    schema_version: str
    is_fallback: bool = False
    cost_cents: float = 0.0
    latency_ms: int = 0
    cached: bool = False
    retrieved_at: datetime = field(default_factory=_now)
    error: str | None = None

    # ── invariants ───────────────────────────────────────────────────────────
    @property
    def is_usable(self) -> bool:
        """Whether this evidence may support a verdict at all."""
        return self.error is None and bool(self.citations)

    @property
    def effective_confidence(self) -> float:
        """Confidence after the fallback cap.

        Principle P5, degrade honestly. A grounded fallback answer is worth
        having but must never present as equal to a fully cited research run.
        """
        return min(self.confidence, 0.6) if self.is_fallback else self.confidence

    @property
    def primary_source_count(self) -> int:
        return sum(1 for c in self.citations if c.is_primary)

    @property
    def classified_primary_count(self) -> int:
        """Primary sources on a recognised host. The strict count."""
        return sum(1 for c in self.citations if c.is_classified_primary)

    @property
    def low_trust_count(self) -> int:
        return sum(1 for c in self.citations if c.source_class == "user")

    @property
    def domains(self) -> set[str]:
        """Distinct registrable domains. Two pages on one site are one source."""
        return {c.domain for c in self.citations if c.domain}

    @property
    def source_strength(self) -> float:
        """Best trust score among the citations, 0 when there are none.

        Used to weight, not to decide. The adjudicator's rules read the counts;
        this is the single number the UI puts on a source pedigree meter.
        """
        return max((c.trust for c in self.citations), default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "subject_id": self.subject_id,
            "question": self.question,
            "finding": self.finding,
            "citations": [c.to_dict() for c in self.citations],
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "effective_confidence": self.effective_confidence,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "is_fallback": self.is_fallback,
            "cost_cents": self.cost_cents,
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "retrieved_at": self.retrieved_at.isoformat(),
            "error": self.error,
            # Pedigree, so the UI and the report can show what the verdict is
            # standing on without re deriving it from the citation list.
            "primary_source_count": self.primary_source_count,
            "classified_primary_count": self.classified_primary_count,
            "independent_domains": sorted(self.domains),
            "source_strength": round(self.source_strength, 3),
        }

    @staticmethod
    def make_id(subject_id: str, question: str, provider: str) -> str:
        """Content addressed identifier.

        Deterministic on purpose. The same question, about the same subject,
        through the same provider produces the same id across runs and across
        drafts, which is what makes the cache and the diff based re
        verification work without a bookkeeping table.
        """
        digest = hashlib.sha256(f"{subject_id}|{question}|{provider}".encode()).hexdigest()
        return f"ev_{digest[:20]}"

    @classmethod
    def failed(cls, subject_id: str, question: str, provider: str, error: str) -> Evidence:
        """An honest empty envelope.

        A failed lookup is recorded, never swallowed. The Adjudicator sees a
        subject with no usable evidence and routes it to counsel rather than
        guessing, and the report front page counts it against coverage quality.
        """
        return cls(
            evidence_id=cls.make_id(subject_id, question, provider),
            subject_id=subject_id,
            question=question,
            finding={},
            citations=[],
            reasoning="",
            confidence=0.0,
            provider=provider,
            schema_version="none",
            error=error,
        )


@dataclass(frozen=True, slots=True)
class MonitorHandle:
    """A live watch on a subject, held for the commercial life of the title.

    A clearance report is a photograph. Rights are a film. Music licences of
    the WKRP era expired quietly years after the report was filed and the show
    went out with sound alikes for three decades. Every MUSIC_CUE gets an
    expiry aware cadence, and for adapted reality productions the monitors also
    watch the facts: a depicted person dies and publicity rights change by
    state, a related suit is filed, a new record surfaces against a verified
    claim.
    """

    monitor_id: str
    subject_id: str
    provider_monitor_id: str  # the id held by Parallel Monitor
    query: str
    cadence: str  # daily | weekly | monthly | quarterly
    reason: str  # why this subject is watched, shown in the manifest
    created_at: datetime = field(default_factory=_now)
    last_checked_at: datetime | None = None
    last_event_at: datetime | None = None
    expiry_hint: datetime | None = None  # licence term end, drives cadence
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "subject_id": self.subject_id,
            "provider_monitor_id": self.provider_monitor_id,
            "query": self.query,
            "cadence": self.cadence,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "expiry_hint": self.expiry_hint.isoformat() if self.expiry_hint else None,
            "active": self.active,
        }
