"""Agent 5, ResearchSwarm. The fan out. ADK ParallelAgent shaped.

Two hundred research subjects dispatched against a bounded pool, metered by the
budget governor, streamed back to the UI as they land. The concurrency cap is
ours rather than the vendor's: Parallel's Task API supports roughly two
thousand requests a minute, so our own budget governance is the binding
constraint by a wide margin.

Depth decides transport. Lite and base are awaited inline, which is what keeps
the on camera run synchronous and the overlay filling in live. Core and above
dispatch with a webhook callback and park their run state in Firestore, and a
Cloud Scheduler sweep rescues anything whose callback never arrives.

Every subject carries its identifier as the idempotency key, so a webhook
replay is safe and a retry never double bills.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from truestory.config import settings
from truestory.mcp.tools import ClearanceTools
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClearanceStatus, ElementType, Polarity
from truestory.models.evidence import Evidence
from truestory.providers import ProviderRegistry
from truestory.providers.budget import BudgetExhausted

log = logging.getLogger("truestory.swarm")

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


@dataclass(slots=True)
class SwarmResult:
    """What the swarm produced, plus everything the report needs to caveat itself."""

    evidence_by_subject: dict[str, list[Evidence]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    monitors_requested: list[dict[str, Any]] = field(default_factory=list)
    total_cost_cents: float = 0.0
    duration_seconds: float = 0.0
    dispatched: int = 0
    completed: int = 0

    @property
    def failure_rate(self) -> float:
        return len(self.failures) / self.dispatched if self.dispatched else 0.0

    def add(self, subject_id: str, evidence: Evidence) -> None:
        self.evidence_by_subject.setdefault(subject_id, []).append(evidence)
        self.total_cost_cents += evidence.cost_cents
        self.completed += 1
        if evidence.error:
            self.failures[subject_id] = evidence.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "dispatched": self.dispatched,
            "completed": self.completed,
            "failures": len(self.failures),
            "failure_rate": round(self.failure_rate, 4),
            "monitors_requested": len(self.monitors_requested),
            "cost_cents": round(self.total_cost_cents, 4),
            "cost_usd": round(self.total_cost_cents / 100, 4),
            "duration_seconds": round(self.duration_seconds, 2),
        }


class ResearchSwarm:
    """Bounded, metered, streamed fan out over the domain tool layer."""

    name = "ResearchSwarm"

    def __init__(
        self,
        registry: ProviderRegistry,
        tools: ClearanceTools | None = None,
        *,
        max_concurrency: int | None = None,
        on_progress: ProgressCallback = None,
    ) -> None:
        self.registry = registry
        self.tools = tools or ClearanceTools(registry)
        self.max_concurrency = max_concurrency or settings.swarm_max_concurrency
        self.on_progress = on_progress

    # ── entry point ──────────────────────────────────────────────────────────
    @staticmethod
    def _is_opinion_element(element: ClearableElement, opinion_text: set[str]) -> bool:
        """Whether this element is a characterisation the claim stage settled.

        Checked against the element's own words rather than its attached
        claims: coreference frequently lifts a characterisation into its own
        element with nothing attached, which is exactly the case that was
        slipping through and getting researched.
        """
        if element.claims and all(c.is_opinion for c in element.claims):
            return True
        surface = _normalise(element.display_form())
        if not surface or len(surface) < 8:
            return False
        return any(surface in text for text in opinion_text)

    async def run(
        self, claims: list[FactualClaim], elements: list[ClearableElement]
    ) -> SwarmResult:
        started = asyncio.get_event_loop().time()
        result = SwarmResult()
        semaphore = asyncio.Semaphore(self.max_concurrency)

        tasks: list[Awaitable[None]] = []

        for claim in claims:
            if claim.is_opinion:
                continue  # settled at routing, never dispatched
            tasks.append(self._guarded(semaphore, self._research_claim(claim, result)))

        # Text the claim stage already settled as opinion. Coreference means a
        # characterisation is often lifted into its own element with no claims
        # attached to it, so matching on the element's own words is what
        # actually catches it.
        opinion_text = {_normalise(c.claim_text) for c in claims if c.is_opinion}

        for element in elements:
            if element.element_type in _NO_RESEARCH:
                continue
            # Defamation law protects opinion, which is why the claim loop
            # above skips it. The element path had no equivalent guard, so a
            # characterisation like "impossible woman to work for" was
            # dispatched at CRITICAL tier on the most expensive processor. A
            # web search on a value judgement cannot return anything
            # probative: it came back with an unrelated 1988 film, then with
            # a stranger's employment lawsuit, and both read as evidence.
            if self._is_opinion_element(element, opinion_text):
                element.status = ClearanceStatus.CLEAR
                element.confidence = 1.0
                element.rationale = (
                    "Characterisation rather than a factual assertion. Defamation law "
                    "protects opinion, so this is classified rather than researched."
                )
                log.debug("skipping opinion element %s", element.element_id)
                continue
            tasks.append(self._guarded(semaphore, self._research_element(element, result)))

        result.dispatched = len(tasks)
        await self._emit({"event": "swarm_dispatched", "subjects": result.dispatched})

        await asyncio.gather(*tasks, return_exceptions=True)

        result.duration_seconds = asyncio.get_event_loop().time() - started
        log.info(
            "swarm complete: %s subjects, %s failures, $%.4f in %.1fs",
            result.completed,
            len(result.failures),
            result.total_cost_cents / 100,
            result.duration_seconds,
        )
        await self._emit({"event": "swarm_complete", **result.to_dict()})
        return result

    async def _guarded(self, semaphore: asyncio.Semaphore, coro: Awaitable[None]) -> None:
        async with semaphore:
            try:
                await coro
            except BudgetExhausted as exc:
                # The budget is a governed resource, so exhaustion is a
                # reported condition rather than a crash. The report front page
                # will carry the coverage warning.
                log.warning("budget exhausted mid run: %s", exc)
            except Exception:
                log.exception("swarm subject failed")

    # ── claims ───────────────────────────────────────────────────────────────
    async def _research_claim(self, claim: FactualClaim, result: SwarmResult) -> None:
        if claim.claim_type.value == "QUOTE":
            payload = await self.tools.attribute_quote(
                subject_id=claim.claim_id,
                quote=claim.claim_text,
                purported_speaker=claim.subject_name,
            )
        else:
            payload = await self.tools.verify_factual_claim(
                subject_id=claim.claim_id,
                subject=claim.subject_name,
                claim=claim.claim_text,
                polarity=str(claim.polarity),
                subject_alive=claim.subject_alive,
            )

        evidence = _rehydrate(payload, claim.claim_id, claim.claim_text)
        result.add(claim.claim_id, evidence)

        await self._emit(
            {
                "event": "claim_researched",
                "claim_id": claim.claim_id,
                "subject": claim.subject_name,
                "tier": str(claim.risk_tier),
                "citations": len(evidence.citations),
                "cost_cents": round(evidence.cost_cents, 4),
                "cached": evidence.cached,
            }
        )

    # ── elements ─────────────────────────────────────────────────────────────
    async def _research_element(self, element: ClearableElement, result: SwarmResult) -> None:
        payload = await self._dispatch_element(element)
        evidence = _rehydrate(payload, element.element_id, element.canonical_form)
        result.add(element.element_id, evidence)

        # Side effects declared by the routing rule. These are what turn a
        # one off report into Living Clearance.
        for side_effect in element.also:
            await self._run_side_effect(side_effect, element, result)

        await self._emit(
            {
                "event": "element_researched",
                "element_id": element.element_id,
                "type": str(element.element_type),
                "tier": str(element.risk_tier),
                "citations": len(evidence.citations),
                "cost_cents": round(evidence.cost_cents, 4),
                "cached": evidence.cached,
            }
        )

    async def _dispatch_element(self, element: ClearableElement) -> dict[str, Any]:
        """Pick the domain tool that matches the element type."""
        eid, name = element.element_id, element.canonical_form
        city = _attribute(element, "city", "unknown")

        match element.element_type:
            case ElementType.REAL_PERSON_DEPICTED:
                return await self.tools.check_publicity_rights(
                    eid, name, _attribute(element, "domicile", "unknown")
                )
            case ElementType.REAL_PERSON_IDENTIFIABLE:
                return await self.tools.check_person_identifiability(
                    eid, _identifying_attributes(element)
                )
            case ElementType.PERSON_NAME_FICTIONAL:
                return await self.tools.check_person_collision(
                    eid,
                    name,
                    _attribute(element, "profession", "unknown"),
                    city,
                    occurrence_count=element.occurrence_count,
                )
            case ElementType.MUSIC_CUE:
                return await self.tools.check_music_rights(
                    eid,
                    name,
                    _attribute(element, "artist", "unknown"),
                    _attribute(element, "year", "unknown"),
                )
            case ElementType.TRADEMARK_LOGO | ElementType.BRAND_PRODUCT:
                return await self.tools.check_trademark_status(eid, name)
            case ElementType.BUSINESS_NAME:
                return await self.tools.check_entity_registration(
                    eid, name, element.jurisdictions[0] if element.jurisdictions else "US"
                )
            case ElementType.ARTWORK_VISUAL | ElementType.TATTOO | ElementType.FILM_CLIP:
                return await self.tools.check_visual_copyright(
                    eid, name, _attribute(element, "creator", "unknown")
                )
            case ElementType.SOURCE_MATERIAL:
                return await self.tools.check_public_domain(eid, name)
            case _:
                return await self.tools.check_entity(eid, name, str(element.element_type).lower())

    async def _run_side_effect(
        self, side_effect: str, element: ClearableElement, result: SwarmResult
    ) -> None:
        if side_effect == "monitor":
            request = {
                "subject_id": element.element_id,
                "query": _monitor_query(element),
                "cadence": self.tools.routing.monitor_cadence(element.element_type),
                "reason": _monitor_reason(element),
            }
            result.monitors_requested.append(request)
            return

        if side_effect in {
            "findall_similar_persons",
            "findall_matching_persons",
            "findall_registered_entities",
        }:
            try:
                matches = await self.tools.enumerate_matching_entities(
                    element.element_id,
                    element.canonical_form,
                    element.jurisdictions[0] if element.jurisdictions else "US",
                )
                for payload in matches:
                    result.add(
                        element.element_id,
                        _rehydrate(payload, element.element_id, element.canonical_form),
                    )
            except Exception as exc:
                log.warning("enumeration failed for %s: %s", element.element_id, exc)
            return

        if side_effect == "extract_evidence_page":
            for evidence in _existing_evidence(result, element.element_id):
                for citation in evidence.citations[:1]:  # the strongest source only
                    try:
                        payload = await self.tools.capture_evidence_page(
                            element.element_id, citation.url
                        )
                        result.add(
                            element.element_id,
                            _rehydrate(payload, element.element_id, citation.url),
                        )
                    except Exception as exc:
                        log.warning("page capture failed: %s", exc)

    # ── progress ─────────────────────────────────────────────────────────────
    async def _emit(self, payload: dict[str, Any]) -> None:
        """Stream progress to the UI.

        This is the demo's kinetic energy. Verdicts arrive as the swarm
        completes and the page fills in live rather than showing a spinner and
        then a wall of results.
        """
        payload["budget"] = self.registry.budget.snapshot()
        if self.on_progress:
            try:
                await self.on_progress(payload)
            except Exception:
                log.debug("progress callback failed", exc_info=True)


# =============================================================================
# helpers
# =============================================================================

#: Element types resolved by deterministic rules, never dispatched.
_NO_RESEARCH = frozenset(
    {
        ElementType.PHONE_NUMBER,
        ElementType.VEHICLE_PLATE,
        ElementType.URL_HANDLE,
        ElementType.TRUTH_CLAIM_FRAMING,
    }
)


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split()).strip(" .,\"'")


def _rehydrate(payload: dict[str, Any], subject_id: str, question: str) -> Evidence:
    from truestory.providers.cached import _evidence_from_dict

    if "evidence_id" in payload:
        return _evidence_from_dict(payload)
    return Evidence.failed(
        subject_id, question, "swarm", payload.get("error", "tool returned no envelope")
    )


def _existing_evidence(result: SwarmResult, subject_id: str) -> list[Evidence]:
    return [e for e in result.evidence_by_subject.get(subject_id, []) if e.is_usable]


def _attribute(element: ClearableElement, key: str, default: str) -> str:
    for occurrence in element.occurrences:
        context = occurrence.context.lower()
        if key in context:
            return occurrence.context[:120]
    return default


def _identifying_attributes(element: ClearableElement) -> list[str]:
    """Assemble the attribute cluster from the surrounding script text.

    No name required, which is the entire point. Profession plus city plus
    physical description plus relationship is what an audience assembles, so it
    is what the research is given.
    """
    attributes = [element.canonical_form] if element.canonical_form else []
    attributes.extend(
        occurrence.context.strip()[:200]
        for occurrence in element.occurrences[:4]
        if occurrence.context.strip()
    )
    return attributes or ["unspecified attribute cluster"]


def _monitor_query(element: ClearableElement) -> str:
    match element.element_type:
        case ElementType.MUSIC_CUE:
            return (
                f"Changes in the licensing position, rights ownership or licence term "
                f"for the musical work '{element.canonical_form}'."
            )
        case ElementType.REAL_PERSON_DEPICTED:
            return (
                f"News concerning {element.canonical_form}: death, new litigation naming "
                f"them, or newly surfaced records bearing on their documented history."
            )
        case ElementType.TRADEMARK_LOGO | ElementType.BUSINESS_NAME:
            return (
                f"Registration changes, ownership transfers or enforcement actions "
                f"involving the mark '{element.canonical_form}'."
            )
        case _:
            return f"Material changes affecting the clearance position of {element.canonical_form}."


def _monitor_reason(element: ClearableElement) -> str:
    match element.element_type:
        case ElementType.MUSIC_CUE:
            return "Licence terms are time boxed and lapse silently after delivery."
        case ElementType.REAL_PERSON_DEPICTED:
            return "Death changes publicity rights by state, and new litigation changes risk."
        case _:
            return "Rights positions change after the report is filed."


def negative_living_claims(claims: list[FactualClaim]) -> list[FactualClaim]:
    """The escalation cocktail. Every marquee case in the set is this shape."""
    return [c for c in claims if c.polarity is Polarity.NEGATIVE and c.subject_alive is True]
