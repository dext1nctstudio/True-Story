"""The provider registry and the selection algorithm.

This is where principle P3 becomes concrete. Selection walks four checks in a
fixed order and the result is auditable at every step:

    cache hit          -> serve for nothing
    routing policy     -> which provider and depth this subject deserves
    budget governor    -> degrade depth rather than fail the run
    provider health    -> fall back, and stamp the fallback

Changing vendor is an edit to routing.yaml plus a class in this package. No
agent, no tool, and no schema changes. On camera that is a ten second beat:
flip a provider live, watch the identical output shape come back, and the
audience understands they are looking at a production system rather than a
demo.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from truestory.config import Mode, settings
from truestory.models.enums import Processor, RiskTier
from truestory.models.evidence import Evidence
from truestory.policy import RoutingDecision
from truestory.providers.base import (
    ProviderOutOfService,
    ProviderUnavailable,
    RateLimited,
    ResearchProvider,
    ResearchRequest,
)
from truestory.providers.budget import BudgetExhausted, BudgetGovernor
from truestory.providers.cached import CachedProvider, LocalCacheBackend
from truestory.providers.mock import MockProvider


@dataclass(frozen=True, slots=True)
class Selection:
    """Which provider will run, at what depth, and why."""

    provider: ResearchProvider
    processor: Processor
    reason: str
    degraded: bool = False
    is_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "processor": str(self.processor),
            "reason": self.reason,
            "degraded": self.degraded,
            "is_fallback": self.is_fallback,
        }


class ProviderRegistry:
    """Owns every provider instance and decides which one answers a question."""

    #: Providers eligible to serve CRITICAL work, in preference order.
    FALLBACK_CHAIN = ("parallel_task", "gemini_grounded")

    def __init__(
        self,
        budget: BudgetGovernor | None = None,
        *,
        mode: Mode | None = None,
        providers: dict[str, ResearchProvider] | None = None,
    ) -> None:
        self.mode = mode or settings.mode
        self.budget = budget or BudgetGovernor()
        self._providers: dict[str, ResearchProvider] = providers or self._build_default()
        self._health: dict[str, bool] = {}
        #: Provider name -> why it left service mid run. Read by the report so
        #: an infrastructure failure is stated as one on the front page rather
        #: than distributed silently across every subject as "no record".
        self.outages: dict[str, str] = {}
        #: Subjects the primary could not answer and the fallback rescued, plus
        #: any fallback errors. Reported so a run that leaned on the fallback
        #: says so rather than presenting recovered answers as primary ones.
        self.recoveries: dict[str, list[str]] = {}
        self._health_lock = asyncio.Lock()
        self.cache = CachedProvider(backend=LocalCacheBackend())
        self.selections: list[Selection] = []

    # ── construction ─────────────────────────────────────────────────────────
    def _build_default(self) -> dict[str, ResearchProvider]:
        """Mock mode never constructs a live client, so no key is ever needed."""
        if self.mode is Mode.MOCK:
            mock = MockProvider()
            return {
                "parallel_task": mock,
                "parallel_search": mock,
                "parallel_findall": mock,
                "parallel_extract": mock,
                "parallel_monitor": mock,
                "gemini_grounded": mock,
                "registry_lookup": mock,
                "mock": mock,
            }

        from truestory.providers.gemini_grounded import GeminiGroundedProvider
        from truestory.providers.parallel_extract import ParallelExtractProvider
        from truestory.providers.parallel_findall import ParallelFindAllProvider
        from truestory.providers.parallel_monitor import ParallelMonitorProvider
        from truestory.providers.parallel_search import ParallelSearchProvider
        from truestory.providers.parallel_task import ParallelTaskProvider
        from truestory.providers.registry_lookup import RegistryLookupProvider

        return {
            "parallel_task": ParallelTaskProvider(),
            "registry_lookup": RegistryLookupProvider(),
            "parallel_search": ParallelSearchProvider(),
            "parallel_findall": ParallelFindAllProvider(),
            "parallel_extract": ParallelExtractProvider(),
            "parallel_monitor": ParallelMonitorProvider(),
            "gemini_grounded": GeminiGroundedProvider(),
            "mock": MockProvider(),
        }

    def get(self, name: str) -> ResearchProvider:
        if name not in self._providers:
            raise KeyError(f"unknown provider: {name}")
        return self._providers[name]

    def register(self, name: str, provider: ResearchProvider) -> None:
        """Add or replace a provider at runtime. The hot swap beat."""
        self._providers[name] = provider
        self._health.pop(name, None)

    # ── selection ────────────────────────────────────────────────────────────
    async def select(self, decision: RoutingDecision, request: ResearchRequest) -> Selection | None:
        """Resolve the four checks. Returns None when no research is warranted."""
        if not decision.researched:
            return None

        # 1. cache. Free and deterministic, so it precedes everything.
        if self.cache.has(request):
            return Selection(
                provider=self.cache,
                processor=request.processor,
                reason="cache hit",
            )

        # 2. policy
        wanted = decision.provider
        processor = decision.processor or Processor.LITE

        # 3. budget. Degrade depth before failing the run, and never touch
        #    CRITICAL, which draws on a reserve nothing else can reach.
        try:
            effective = self.budget.resolve(processor, decision.tier)
        except BudgetExhausted as exc:
            self.budget.ledger.refusals += 1
            raise exc
        degraded = effective is not processor

        # 4. health, plus the citation gate for CRITICAL work.
        provider = self._providers.get(wanted)
        is_fallback = False

        if provider is None or not await self._is_up(wanted):
            fallback = await self._pick_fallback(decision.tier, exclude=wanted)
            if fallback is None:
                raise ProviderUnavailable(wanted, "no healthy provider can serve this tier")
            provider, is_fallback = fallback, True

        if not provider.can_serve(decision.tier):
            fallback = await self._pick_fallback(decision.tier, exclude=provider.name)
            if fallback is None:
                raise ProviderUnavailable(
                    provider.name,
                    f"cannot serve {decision.tier}: citations are required and unavailable",
                )
            provider, is_fallback = fallback, True

        reason_parts = [f"routed by {decision.rule_id}"]
        if degraded:
            reason_parts.append(f"depth degraded {processor} to {effective} for budget")
        if is_fallback:
            reason_parts.append(f"{wanted} unavailable, fell back to {provider.name}")

        selection = Selection(
            provider=provider,
            processor=effective,
            reason="; ".join(reason_parts),
            degraded=degraded,
            is_fallback=is_fallback,
        )
        self.selections.append(selection)
        return selection

    # ── execution ────────────────────────────────────────────────────────────
    async def investigate(self, decision: RoutingDecision, request: ResearchRequest) -> Evidence:
        """Select, dispatch, meter, and cache. The single entry point for research."""
        try:
            selection = await self.select(decision, request)
        except (BudgetExhausted, ProviderUnavailable) as exc:
            return Evidence.failed(request.subject_id, request.question, "registry", str(exc))

        if selection is None:
            return Evidence.failed(
                request.subject_id,
                request.question,
                "registry",
                "routing declined research for this subject",
            )

        effective_request = ResearchRequest(
            subject_id=request.subject_id,
            question=request.question,
            output_schema=request.output_schema,
            schema_name=request.schema_name,
            tier=request.tier,
            processor=selection.processor,
            jurisdictions=request.jurisdictions,
            context=request.context,
            max_results=request.max_results,
            idempotency_key=request.idempotency_key or request.cache_key(),
        )

        cost = selection.provider.price_cents(selection.processor)
        try:
            self.budget.reserve(cost, decision.tier)
        except BudgetExhausted as exc:
            return Evidence.failed(request.subject_id, request.question, "registry", str(exc))

        try:
            evidence = await _with_retry(selection.provider, effective_request)
        except ProviderOutOfService as exc:
            # The account is drained or the key is rejected. Every remaining
            # subject would fail identically, so the provider leaves service
            # for the rest of the run and the next call selects the fallback.
            # Recorded on the registry so the report can say plainly that the
            # research provider stopped answering, rather than presenting two
            # hundred empty results as a silent record.
            self._health[selection.provider.name] = False
            self.outages.setdefault(selection.provider.name, str(exc))
            evidence = Evidence.failed(
                request.subject_id, request.question, selection.provider.name, str(exc)
            )
        except RateLimited as exc:
            # Sustained rate limiting is a health signal, not just a retry.
            self._health[selection.provider.name] = False
            evidence = Evidence.failed(
                request.subject_id, request.question, selection.provider.name, str(exc)
            )
        except Exception as exc:
            evidence = Evidence.failed(
                request.subject_id,
                request.question,
                selection.provider.name,
                f"{type(exc).__name__}: {exc}",
            )

        if selection.is_fallback and not evidence.is_fallback:
            evidence = _mark_fallback(evidence)

        # The primary answered, and answered with nothing usable. Health based
        # fallback never fires here, because the provider is up: it accepted the
        # run, it simply did not return a citable result before the deadline.
        #
        # That is the common case rather than the exotic one. Parallel's Task
        # API is asynchronous and its latency is measured in minutes under load;
        # a run that is still active when the deadline passes comes back parked,
        # with no citations, and every subject in that state was being reported
        # as an amber finding about a silent public record. On the run that
        # exposed this, two adjacent claims about the same fact took opposite
        # verdicts purely on which one finished first.
        #
        # Parallel is still called first, always, and its result is preferred
        # whenever it arrives. This only decides what happens to the subjects it
        # did not reach, and the alternative to a stamped fallback answer is not
        # a better answer, it is a fabricated silence.
        if not evidence.is_usable:
            recovered = await self._recover_with_fallback(decision, effective_request, evidence)
            if recovered is not None:
                evidence = recovered

        self.budget.record(
            evidence.cost_cents,
            decision.tier,
            evidence.provider,
            cached=evidence.cached,
            reserved=cost,
            # What this lookup would have cost had it gone out. On a hit the
            # difference is the saving, which is otherwise unrecoverable once
            # the envelope comes back stamped zero.
            list_price_cents=cost,
        )

        if evidence.is_usable and not evidence.cached:
            self.cache.backend.put(effective_request.cache_key(), evidence.to_dict())

        return evidence

    async def _recover_with_fallback(
        self,
        decision: RoutingDecision,
        request: ResearchRequest,
        primary: Evidence,
    ) -> Evidence | None:
        """Ask the fallback for a subject the primary could not answer.

        Returns None when there is nothing better to offer, in which case the
        primary's empty envelope stands and the claim is correctly reported as
        unchecked rather than as checked and silent.

        The recovered envelope is stamped `is_fallback`, which caps effective
        confidence at 0.6 and puts a coverage warning on the report front page.
        A grounded answer is worth having and is not worth the same as a multi
        hop research run with a citation per field, and the difference stays
        visible in the deliverable.
        """
        for name in self.FALLBACK_CHAIN:
            if name == primary.provider.split(":")[0]:
                continue
            provider = self._providers.get(name)
            if provider is None or not provider.can_serve(decision.tier):
                continue
            if not await self._is_up(name):
                continue

            try:
                recovered = await provider.investigate(request)
            except Exception as exc:  # a failing fallback must not fail the run
                self.recoveries.setdefault("errors", []).append(f"{name}: {exc}")
                continue

            if not recovered.is_usable:
                continue

            self.recoveries.setdefault("recovered", []).append(request.subject_id)
            return _mark_fallback(recovered)

        return None

    # ── health ───────────────────────────────────────────────────────────────
    async def _is_up(self, name: str) -> bool:
        if name in self._health:
            return self._health[name]
        async with self._health_lock:
            provider = self._providers.get(name)
            up = await provider.health() if provider else False
            self._health[name] = up
            return up

    async def _pick_fallback(self, tier: RiskTier, exclude: str) -> ResearchProvider | None:
        for name in self.FALLBACK_CHAIN:
            if name == exclude:
                continue
            provider = self._providers.get(name)
            if provider and provider.can_serve(tier) and await self._is_up(name):
                return provider
        return None

    # ── reporting ────────────────────────────────────────────────────────────
    @property
    def fallback_rate(self) -> float:
        if not self.selections:
            return 0.0
        return sum(1 for s in self.selections if s.is_fallback) / len(self.selections)

    @property
    def cache_hit_rate(self) -> float:
        return self.cache.hit_rate

    def stats(self) -> dict[str, Any]:
        return {
            "mode": str(self.mode),
            "selections": len(self.selections),
            "fallback_rate": round(self.fallback_rate, 4),
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "degradations": sum(1 for s in self.selections if s.degraded),
            "outages": dict(self.outages),
            "recovered_by_fallback": len(self.recoveries.get("recovered", [])),
            "budget": self.budget.snapshot(),
        }

    async def aclose(self) -> None:
        await asyncio.gather(
            *(p.close() for p in set(self._providers.values())), return_exceptions=True
        )


def _mark_fallback(evidence: Evidence) -> Evidence:
    """Stamp an envelope that came from a fallback path.

    Principle P5. Effective confidence is capped downstream, and the report
    front page states that part of the run was served by a degraded provider.
    """
    return Evidence(
        evidence_id=evidence.evidence_id,
        subject_id=evidence.subject_id,
        question=evidence.question,
        finding=evidence.finding,
        citations=evidence.citations,
        reasoning=evidence.reasoning,
        confidence=evidence.confidence,
        provider=evidence.provider,
        schema_version=evidence.schema_version,
        is_fallback=True,
        cost_cents=evidence.cost_cents,
        latency_ms=evidence.latency_ms,
        cached=evidence.cached,
        retrieved_at=evidence.retrieved_at,
        error=evidence.error,
    )


#: Transient failure wording. A provider returns these as a failed envelope
#: rather than raising, so the retry decision is made on the text it wrote.
_RETRYABLE = ("timeout", "429", "rate limit", "http 5", "temporarily", "unavailable")

#: Attempts, and the pause before each retry. Short: the swarm is already
#: running thirty of these at once and a long backoff stalls the whole run.
_RETRY_DELAYS = (1.5, 4.0)


async def _with_retry(provider: ResearchProvider, request: ResearchRequest) -> Evidence:
    """Retry a research call that failed for a reason that may not recur.

    Two true claims on a live run came back "research returned no citable
    source" because their Task call timed out while thirty others were in
    flight. To a reader that is indistinguishable from a fact nobody can
    verify, which is exactly the confusion this product exists to remove, so a
    transient failure is retried before it is reported as a finding.
    """
    evidence = await provider.investigate(request)
    for delay in _RETRY_DELAYS:
        if not evidence.error:
            return evidence
        lowered = evidence.error.lower()
        if not any(marker in lowered for marker in _RETRYABLE):
            return evidence
        await asyncio.sleep(delay)
        evidence = await provider.investigate(request)
    return evidence
