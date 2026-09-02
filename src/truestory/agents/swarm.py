"""Agent 5, ResearchSwarm. The fan out. ADK ParallelAgent shaped.

Two hundred research subjects dispatched against a bounded pool, metered by the
budget governor, streamed back to the UI as they land.

The concurrency cap is not a budget decision, and treating it as one cost a
whole run. Parallel's Task API accepts roughly two thousand requests a minute,
which is an arrival rate, and this pool was sized at 32 on the strength of it.
The constraint that actually binds is how many runs an account may have active
at once. At 32 not one of thirty five subjects came back inside the deadline; at
6 all twelve did, in 141 seconds. Over-dispatching does not raise anything, it
queues, and every subject then ages out into the fallback while Parallel bills
for runs nobody collected. See `settings.swarm_max_concurrency`.

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

from truestory.agents.attribution import AttributionGate
from truestory.config import settings
from truestory.mcp.tools import ClearanceTools
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClearanceStatus, ElementType, Polarity
from truestory.models.evidence import Evidence
from truestory.providers import ProviderRegistry
from truestory.providers.budget import BudgetExhausted

log = logging.getLogger("truestory.swarm")

#: How many sources per subject are fetched in full so the gate has real text
#: to quote from. The citation list is already ordered strongest first.
_MAX_PAGE_FETCHES = 4

#: An excerpt shorter than this is a fragment chosen to explain an output
#: field, not a passage about the claim, so the page is worth fetching.
_THIN_EXCERPT_CHARS = 400

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

    #: Subject id -> the human readable name, so a failure can be reported as
    #: the thing a reviewer recognises rather than as an opaque identifier.
    labels: dict[str, str] = field(default_factory=dict)

    def add(self, subject_id: str, evidence: Evidence, label: str = "") -> None:
        self.evidence_by_subject.setdefault(subject_id, []).append(evidence)
        self.total_cost_cents += evidence.cost_cents
        self.completed += 1
        if label:
            self.labels.setdefault(subject_id, label)
        if evidence.error:
            self.failures[subject_id] = evidence.error
        self.records.append(evidence)

    #: Every Evidence in dispatch order, so telemetry can be written once at the
    #: end of the run rather than on the hot path. The unit economics in the
    #: pitch are a query against this, not an estimate.
    records: list[Evidence] = field(default_factory=list)

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
        attribution: AttributionGate | None = None,
        project_id: str = "",
    ) -> None:
        self.registry = registry
        self.tools = tools or ClearanceTools(registry)
        self.max_concurrency = max_concurrency or settings.swarm_max_concurrency
        self.on_progress = on_progress
        # Namespaces archived evidence pages in Cloud Storage. Empty means the
        # run is not archiving, which is the correct default for a unit test.
        self.project_id = project_id
        # Nothing this swarm retrieves becomes evidence until the gate has read
        # it against the specific proposition and quoted the words that bear on
        # it. Retrieval is the easy half; deciding what a source actually says
        # is the half that stops a run attaching four government domains to a
        # claim about a person who does not exist.
        self.attribution = attribution or AttributionGate()

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

        # Hand the resolved identities to the tool layer before anything is
        # dispatched, so every question names the entity rather than the string.
        for claim in claims:
            self.tools.set_identity(claim.claim_id, _identity_note(claim.identity))
        for element in elements:
            self.tools.set_identity(element.element_id, _identity_note(element.identity))

        tasks: list[Awaitable[None]] = []

        for claim in claims:
            if claim.is_opinion:
                continue  # settled at routing, never dispatched
            if claim.settled_without_research:
                # The identity stage found no real subject behind the name.
                # Dispatching anyway is what produced a swimmer's results page
                # as evidence for a screenplay character.
                continue
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
        # A failed subject becomes RESEARCH_FAILED on the report and an
        # UNSUPPORTED claim with no citations, both of which read as "the record
        # is silent". They are not the same thing: the record was never asked.
        # The reason was being stored and never surfaced, so a provider timeout
        # and a rejected schema looked identical from the outside and a run
        # could lose ten subjects without saying why.
        for subject_id, reason in result.failures.items():
            log.warning(
                "research failed for %s [%s]: %s",
                result.labels.get(subject_id, subject_id),
                subject_id,
                reason,
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
        returned = len(evidence.citations)
        evidence = await self._attribute(
            evidence, proposition=claim.claim_text, subject=claim.subject_name, claim=claim
        )
        result.add(claim.claim_id, evidence, label=claim.claim_text)

        await self._emit(
            {
                "event": "claim_researched",
                "claim_id": claim.claim_id,
                "subject": claim.subject_name,
                "tier": str(claim.risk_tier),
                "citations": len(evidence.citations),
                "sources_returned": returned,
                "cost_cents": round(evidence.cost_cents, 4),
                "cached": evidence.cached,
            }
        )

    # ── attribution ──────────────────────────────────────────────────────────
    async def _attribute(
        self,
        evidence: Evidence,
        *,
        proposition: str,
        subject: str,
        claim: FactualClaim | None = None,
        element: ClearableElement | None = None,
    ) -> Evidence:
        """Keep only the sources that were shown to bear on this proposition.

        The order matters and is the order a person works in. Read the page
        first, because a quote can only be checked against text that was
        actually retrieved; then say what the page does for the claim; then
        verify the quote is really in the page. A source that survives all
        three is evidence. A source that does not is dropped from the envelope
        entirely rather than shown greyed out, because a citation on screen
        under a verdict is read as supporting it whatever label it carries.
        """
        if not evidence.citations or evidence.error:
            return evidence

        texts = await self._page_texts(evidence)
        report = await self.attribution.assess(
            proposition=proposition,
            subject=subject,
            citations=evidence.citations,
            source_texts=texts,
        )

        target = claim if claim is not None else element
        if target is not None:
            existing = getattr(target, "attribution", None) or {}
            merged = report.to_dict()
            # One subject can be researched by several providers, so the
            # counts accumulate rather than overwrite.
            for key in ("assessed", "kept", "dropped_irrelevant", "dropped_unquotable"):
                merged[key] = int(existing.get(key, 0)) + int(merged.get(key, 0))
            merged["notes"] = [*existing.get("notes", []), *merged["notes"]][:6]
            target.attribution = merged

        return evidence.with_citations(report.citations)

    async def _page_texts(self, evidence: Evidence) -> dict[str, str]:
        """Fetch what each source actually says, where it is worth fetching.

        A research API returns an excerpt chosen to explain its own output
        field, which is frequently not the passage that bears on the claim, and
        for fact level sources it returns no excerpt at all. Capturing the page
        gives the gate real text to quote from and gives the evidence appendix
        a copy of the source as it read on the day, which is what an
        underwriter is actually relying on.

        Bounded on purpose: the strongest few sources per subject, in parallel,
        and any failure falls back to whatever excerpt came with the citation.
        """
        wanted = [
            c.url
            for c in evidence.citations[:_MAX_PAGE_FETCHES]
            if c.url and len(c.excerpt or "") < _THIN_EXCERPT_CHARS
        ]
        if not wanted:
            return {}

        async def fetch(url: str) -> tuple[str, str]:
            try:
                payload = await self.tools.capture_evidence_page(evidence.subject_id, url)
                finding = payload.get("finding") or {}
                return url, str(finding.get("content_markdown") or "")
            except Exception as exc:
                log.debug("page capture failed for %s: %s", url, exc)
                return url, ""

        pages = await asyncio.gather(*(fetch(u) for u in wanted), return_exceptions=False)
        captured = {url: text for url, text in pages if text}
        self._archive_pages(evidence, captured)
        return captured

    def _archive_pages(self, evidence: Evidence, pages: dict[str, str]) -> None:
        """Preserve each captured page to Cloud Storage.

        The page is archived at the moment it is read, because that is the only
        moment the production can prove what the source said. A citation whose
        page later changes is worth much less at claim time than one that
        travels with the copy the run actually quoted from.

        Best effort by design: an archival failure must never fail a clearance
        run, so it degrades to a debug line and the run continues.
        """
        if not pages or not self.project_id:
            return
        try:
            from truestory.storage import store_evidence_page
        except Exception:  # pragma: no cover - import guard
            return
        for index, (url, text) in enumerate(pages.items()):
            try:
                store_evidence_page(
                    self.project_id,
                    f"{evidence.evidence_id}-{index}",
                    f"<!-- source: {url} -->\n\n{text}",
                )
            except Exception as exc:
                log.debug("page not archived for %s: %s", url, exc)

    # ── elements ─────────────────────────────────────────────────────────────
    async def _research_element(self, element: ClearableElement, result: SwarmResult) -> None:
        payload = await self._dispatch_element(element)
        evidence = _rehydrate(payload, element.element_id, element.canonical_form)
        returned = len(evidence.citations)
        evidence = await self._attribute(
            evidence,
            proposition=_element_proposition(element),
            subject=element.canonical_form or element.display_form(),
            element=element,
        )
        result.add(
            element.element_id,
            evidence,
            label=element.canonical_form or element.display_form(),
        )

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
                "sources_returned": returned,
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
                    # Which of the three enumerations this is. It was being
                    # dropped here, so a namesake search and a company register
                    # search issued the identical query.
                    kind=side_effect,
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


def _element_proposition(element: ClearableElement) -> str:
    """The sentence a source has to bear on for a clearance element.

    A claim carries its own proposition. An element does not, so one is stated
    for it: the question being asked of the record, in the terms the record
    would answer in. Without this the gate has nothing specific to check
    relevance against and falls back to matching a bare name, which is how an
    unrelated stranger who shares a name became evidence in the first place.
    """
    name = element.canonical_form or element.display_form()
    kind = str(element.element_type).replace("_", " ").lower()
    jurisdiction = element.jurisdictions[0] if element.jurisdictions else "US"
    return (
        f"The {kind} known as {name!r} is a real, identifiable subject in {jurisdiction}, "
        "and this source concerns that same subject rather than another of the same name."
    )


def _identity_note(identity: dict[str, Any] | None) -> str:
    """The subject, as the research should understand it.

    Written into the question itself. Without it the researcher is given a
    string and goes looking for anything that matches: "ICC" came back as the
    International Code Council and the FIFA World Cup on a live run, and both
    were real, cited and completely wrong.
    """
    if not identity or identity.get("status") != "resolved":
        return ""
    canonical = identity.get("canonical") or {}
    label = canonical.get("label") or identity.get("name") or ""
    if not label:
        return ""

    lines = [f"SUBJECT IDENTITY, resolved before research. This and only this: {label}"]
    if canonical.get("description"):
        lines.append(f"  what it is: {canonical['description']}")
    if canonical.get("occupations"):
        lines.append(f"  known for: {', '.join(canonical['occupations'][:4])}")
    if canonical.get("qid"):
        lines.append(f"  Wikidata: {canonical['qid']} ({canonical.get('url', '')})")
    if canonical.get("official_site"):
        lines.append(f"  official site: {canonical['official_site']}")
    lines.append(
        "  A source about a different person, organisation or work that shares this "
        "name is not about this subject and must not be used."
    )
    return "\n".join(lines)
