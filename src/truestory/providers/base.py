"""The ResearchProvider contract.

Principle P3, vendor swappable and contract stable. Everything above this line
speaks in domain terms and receives an `Evidence` envelope. Nothing above this
line knows that Parallel exists. Swapping a vendor is an edit to routing.yaml
and a new class in this package, not a change to any agent.

The gate that matters is `supports_citations`. A provider that cannot produce
citations is structurally disqualified from CRITICAL work, enforced in the
registry rather than left to a reviewer to notice.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from truestory.models.enums import Processor, RiskTier
from truestory.models.evidence import Evidence


@dataclass(frozen=True, slots=True)
class ResearchRequest:
    """One question, fully specified.

    `question` is natural language because that is what the research APIs take,
    but it is assembled from a template in the MCP tool layer rather than
    written by a model. Determinism starts here: the same subject produces
    byte identical question text on every run, which is what makes the cache
    key stable.
    """

    subject_id: str
    question: str
    output_schema: dict[str, Any]
    schema_name: str
    tier: RiskTier
    processor: Processor
    jurisdictions: tuple[str, ...] = ()
    context: str = ""
    max_results: int = 10
    idempotency_key: str = ""
    #: Literal queries for the Search API, which requires the field. Left empty
    #: for Task, which derives its own from the objective.
    search_queries: tuple[str, ...] = ()
    #: The category of thing being enumerated, for the FindAll API which requires
    #: it. "people" and "companies" route the crawler very differently, and the
    #: three enumeration side effects in the routing table mean different things:
    #: a namesake search is not a registered entity search.
    entity_type: str = ""
    #: Named criteria a candidate must satisfy, as (name, description) pairs.
    #: FindAll requires at least one and evaluates each separately, which is what
    #: makes a match auditable rather than a similarity score.
    match_conditions: tuple[tuple[str, str], ...] = ()

    def cache_key(self) -> str:
        import hashlib

        raw = "|".join(
            [
                EVIDENCE_ENVELOPE_VERSION,
                self.subject_id,
                self.question,
                self.schema_name,
                str(self.processor),
                ",".join(sorted(self.jurisdictions)),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


#: Bumped whenever the shape of a stored Evidence envelope changes in a way
#: that makes an older entry misleading rather than merely sparse. It is part
#: of the cache key, so a bump retires the whole cache instead of replaying
#: envelopes that predate a field the adjudicator now relies on.
#:
#:   v2  citation pedigree: source_class, trust, verified_source, published_at
EVIDENCE_ENVELOPE_VERSION = "v2"


class ProviderError(RuntimeError):
    """A provider level failure. Recorded as failed evidence, never swallowed."""

    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.retryable = retryable


class ProviderUnavailable(ProviderError):
    """Health check failed or the circuit is open. Triggers the fallback path."""


class ProviderOutOfService(ProviderUnavailable):
    """The provider will refuse every request in this run, not just this one.

    A drained account, a rejected key or a revoked permission is not a property
    of the question that was asked. Treating it as a per request failure is what
    produced the worst run this system has recorded: Parallel returned
    ``HTTP 402: Insufficient credit in account`` to every single subject, each
    one was caught individually, and each was rendered to the reviewer as

        "Research returned no citable source. The system declines to make this
         call rather than guessing."

    That sentence describes a silent public record. The record was never asked.
    A clearance report that says "no record found" for two hundred subjects
    because the account was empty is worse than no report, because it reads
    exactly like a clean one.

    Raised once, this takes the provider out of service for the rest of the run
    so the fallback carries the remaining subjects, and it is reported as an
    infrastructure failure rather than as a finding.
    """


class RateLimited(ProviderError):
    """Back off and retry. Cloud Tasks owns the schedule, not this layer."""

    def __init__(self, provider: str, retry_after_seconds: float = 30.0) -> None:
        super().__init__(
            provider, f"rate limited, retry after {retry_after_seconds}s", retryable=True
        )
        self.retry_after_seconds = retry_after_seconds


class ResearchProvider(ABC):
    """One way of answering a research question."""

    #: Stable identifier used in routing.yaml and stamped on every Evidence.
    name: str = "abstract"

    #: Whether findings come back with source URLs. Gates CRITICAL work.
    supports_citations: bool = False

    #: Whether results may arrive later by webhook rather than inline.
    supports_async: bool = False

    #: Whether this provider can enumerate a set rather than answer a question.
    supports_enumeration: bool = False

    #: Cost per call in US cents, used for pre flight budget projection.
    unit_cost_cents: float = 0.0

    @abstractmethod
    async def investigate(self, request: ResearchRequest) -> Evidence:
        """Answer one question and return a fully attributed envelope.

        Implementations must never raise for an ordinary research failure.
        Return `Evidence.failed(...)` instead, so that a single bad subject
        degrades one line of the report rather than the run.
        """

    async def health(self) -> bool:
        """Cheap liveness check. Drives fallback selection in the registry."""
        return True

    async def close(self) -> None:
        """Release any client resources."""
        return None

    # ── helpers available to every implementation ────────────────────────────
    @contextmanager
    def _timed(self) -> Any:
        start = time.perf_counter()
        box = {"latency_ms": 0}
        try:
            yield box
        finally:
            box["latency_ms"] = int((time.perf_counter() - start) * 1000)

    def _qualified_name(self, processor: Processor | None = None) -> str:
        return f"{self.name}:{processor}" if processor else self.name

    def can_serve(self, tier: RiskTier) -> bool:
        """CRITICAL work requires citations. Not a convention, a gate."""
        if tier is RiskTier.CRITICAL:
            return self.supports_citations
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} citations={self.supports_citations}>"


class EnumerationProvider(ResearchProvider):
    """A provider that returns a set of entities rather than one answer.

    FindAll shaped. Used for the two questions that are inherently plural:
    every registered business bearing this name in this jurisdiction, and every
    real person matching this attribute cluster. The second is the Baby
    Reindeer question and it has no single answer by construction.
    """

    supports_enumeration = True

    @abstractmethod
    async def enumerate(self, request: ResearchRequest) -> list[Evidence]:
        """Return one Evidence per matched entity."""

    async def investigate(self, request: ResearchRequest) -> Evidence:
        """Collapse an enumeration into a single summary envelope."""
        results = await self.enumerate(request)
        if not results:
            return Evidence.failed(
                request.subject_id, request.question, self.name, "no matches found"
            )
        citations = [c for r in results for c in r.citations]
        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding={"matches": [r.finding for r in results], "match_count": len(results)},
            citations=citations,
            reasoning=f"Enumerated {len(results)} matching entities.",
            confidence=max((r.confidence for r in results), default=0.0),
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=sum(r.cost_cents for r in results),
        )


def _resolve_api_key() -> str:
    """The Parallel key. Which source wins depends on where the code is running.

    Deployed, the credential lives in Secret Manager and never in an
    environment variable, a container image or the repository.

    Locally, `.env` wins, and that ordering is deliberate rather than a
    convenience. Preferring Secret Manager everywhere meant a developer who
    rotated the key in `.env` was silently ignored while a stale version in
    Secret Manager kept being used: every request failed 402 on a drained
    account while the same key tested by hand from `.env` succeeded, which cost
    an afternoon to find. The file a developer just edited is the file they
    mean, so it is also the same rule `current_principal` already uses for
    identity.
    """
    from truestory.config import settings as _settings

    if _settings.env_name == "local":
        local = _settings.parallel_api_key
        if local and not local.startswith("PLACEHOLDER"):
            return local

    from truestory.storage.secrets import get_secret

    try:
        value = get_secret("parallel_api_key")
    except Exception:  # pragma: no cover - never fail a run over resolution
        value = ""
    return value or _settings.parallel_api_key
