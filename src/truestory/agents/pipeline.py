"""The pipeline. Eight stages, four language model calls, one fixed order.

    TrueStoryPipeline = SequentialAgent(
        IngestAgent      -> LlmAgent   (Gemini, per scene)          [LLM 1]
        ClaimExtractor   -> LlmAgent   (claim decomposition)        [LLM 2]
        LedgerAgent      -> deterministic (coreference, dedupe)
        RiskRouter       -> deterministic (policy table)
        ResearchSwarm    -> ParallelAgent (bounded fan out)
        Adjudicator      -> LlmAgent   (forced function calling)    [LLM 3]
        RemedyLoop       -> LoopAgent  (propose, verify, max 3)     [LLM 4]
        ReportAgent      -> deterministic (templated)
    )

Why ADK workflow agents rather than one model with a bag of tools: stage order
is fixed by the domain, concurrency is infrastructure, and loop termination is
objective. When a judge asks how we know this is reproducible, the answer is to
point at the tree. There are exactly four places where judgement is required
and every one of them is named in `prompts.py`.

The class below is the executable pipeline and runs anywhere, including with no
credentials at all. `build_adk_pipeline` wraps the same stages in ADK workflow
agents for deployment to Vertex AI Agent Engine, so the deployed topology and
the local one are the same eight stages rather than two divergent code paths.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from truestory.agents.adjudicator import Adjudicator
from truestory.agents.claims import ClaimExtractor
from truestory.agents.identity import IdentityResolver, IdentityStatus
from truestory.agents.ingest import IngestAgent
from truestory.agents.ledger import LedgerAgent
from truestory.agents.remedy import RemedyLoop
from truestory.agents.report import ReportAgent, build_summary
from truestory.agents.router import RiskRouter
from truestory.agents.swarm import ResearchSwarm, SwarmResult
from truestory.config import settings
from truestory.mcp.tools import ClearanceTools
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement, Remedy, RunSummary
from truestory.models.enums import RunStatus
from truestory.models.evidence import Evidence, MonitorHandle
from truestory.models.spans import ScriptDocument
from truestory.policy import load_jurisdictions
from truestory.providers import BudgetGovernor, ProviderRegistry
from truestory.providers.model_cost import set_meter

log = logging.getLogger("truestory.pipeline")

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]] | None


@dataclass(slots=True)
class RunState:
    """Everything one run produces. Persisted to Firestore stage by stage."""

    run_id: str
    project_id: str
    status: RunStatus = RunStatus.QUEUED
    # Nothing on this dataclass previously recorded when a run started, so a
    # project level run list had no way to order or timestamp its rows.
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    document: ScriptDocument | None = None
    spans: list[Any] = field(default_factory=list)
    claims: list[FactualClaim] = field(default_factory=list)
    elements: list[ClearableElement] = field(default_factory=list)
    remedies: list[Remedy] = field(default_factory=list)
    monitors: list[MonitorHandle] = field(default_factory=list)
    review_queue: list[dict[str, Any]] = field(default_factory=list)

    summary: RunSummary | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    parent_run_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": str(self.status),
            "parent_run_id": self.parent_run_id,
            "script": self.document.to_dict() if self.document else None,
            "counts": {
                "spans": len(self.spans),
                "claims": len(self.claims),
                "elements": len(self.elements),
                "remedies": len(self.remedies),
                "monitors": len(self.monitors),
                "review_queue": len(self.review_queue),
            },
            "summary": self.summary.to_dict() if self.summary else None,
            "error": self.error,
        }


@dataclass(slots=True)
class ProjectConfig:
    """Project level settings that shape every stage downstream."""

    project_id: str
    title: str = "Untitled Production"
    shoot_territories: list[str] = field(default_factory=lambda: ["US"])
    distribution_territories: list[str] = field(default_factory=lambda: ["US"])
    budget_usd: float | None = None

    # Normally detected by ingest. Set explicitly when the production has
    # already decided how it will present itself.
    truth_claim_framing_override: bool | None = None

    def jurisdictions(self) -> list[str]:
        return load_jurisdictions().expand(self.shoot_territories, self.distribution_territories)


class TrueStoryPipeline:
    """The executable eight stage pipeline."""

    name = "TrueStoryPipeline"

    def __init__(
        self,
        project: ProjectConfig,
        *,
        registry: ProviderRegistry | None = None,
        on_progress: ProgressCallback = None,
    ) -> None:
        self.project = project
        self.jurisdictions = project.jurisdictions()
        self.budget = BudgetGovernor(ceiling_usd=project.budget_usd)
        self.registry = registry or ProviderRegistry(budget=self.budget)
        self.on_progress = on_progress

        self.tools = ClearanceTools(self.registry, jurisdictions=tuple(self.jurisdictions))

        # The eight stages.
        self.ingest = IngestAgent()
        self.claim_extractor = ClaimExtractor()
        self.ledger = LedgerAgent(jurisdictions=self.jurisdictions)
        self.router = RiskRouter()
        # Before anything is researched: does the subject exist. Free, fast,
        # and the difference between checking a claim and inventing evidence
        # for a character.
        self.identity = IdentityResolver()
        self.swarm = ResearchSwarm(
            self.registry,
            self.tools,
            on_progress=self._emit_passthrough,
            project_id=self.project.project_id,
        )
        self.adjudicator = Adjudicator()
        self.remedy = RemedyLoop(self.tools)
        self.reporter = ReportAgent()

    # ── entry point ──────────────────────────────────────────────────────────
    async def run(
        self,
        source: Path | str,
        *,
        draft_version: str = "v1",
        parent_run_id: str | None = None,
        run_id: str | None = None,
        on_state: Callable[[RunState], None] | None = None,
    ) -> RunState:
        state = RunState(
            run_id=run_id or f"run_{uuid.uuid4().hex[:16]}",
            project_id=self.project.project_id,
            parent_run_id=parent_run_id,
        )
        started = asyncio.get_event_loop().time()

        # Point model metering at this run's governor. A context variable
        # rather than a module global, because two runs are routinely in
        # flight at once and their token spend must not blend.
        set_meter(self.budget)

        try:
            await self._stage_ingest(state, source, draft_version)
            # Publish the state object the moment there is a script to show.
            # Every later stage mutates this same instance, so a caller that
            # holds it can serve the overlay while the run is still going
            # rather than after it ends.
            if on_state is not None:
                on_state(state)
            await self._stage_claims(state)
            await self._stage_ledger(state)
            await self._stage_identity(state)
            await self._stage_route(state)
            await self._stage_research(state)
            await self._stage_adjudicate(state)
            await self._stage_remedy(state)
            await self._stage_report(state, started)
        except Exception as exc:
            log.exception("pipeline failed")
            state.status = RunStatus.FAILED
            state.error = f"{type(exc).__name__}: {exc}"
            await self._emit({"event": "run_failed", "error": state.error})

        return state

    # ── stage 1 ──────────────────────────────────────────────────────────────
    async def _stage_ingest(self, state: RunState, source: Path | str, draft_version: str) -> None:
        state.status = RunStatus.INGESTING
        await self._emit({"event": "stage", "stage": "ingest", "status": "started"})

        document, spans = await self.ingest.run(source, draft_version=draft_version)

        if self.project.truth_claim_framing_override is not None:
            document = _with_framing(document, self.project.truth_claim_framing_override)

        state.document = document
        state.spans = spans

        await self._emit(
            {
                "event": "ingest_complete",
                "scenes": document.scene_count,
                "spans": len(spans),
                "pages": document.page_count,
                "truth_claim_framing": document.truth_claim_framing,
                # The escalation banner on screen. One boolean that changes the
                # tier of every person adjacent subject in the script.
                "truth_claim_evidence": document.truth_claim_evidence,
            }
        )

    # ── stage 2 ──────────────────────────────────────────────────────────────
    async def _stage_claims(self, state: RunState) -> None:
        state.status = RunStatus.EXTRACTING_CLAIMS
        await self._emit({"event": "stage", "stage": "claims", "status": "started"})

        assert state.document is not None
        state.claims = await self.claim_extractor.run(state.spans, state.document.scenes)

        await self._emit(
            {
                "event": "claims_extracted",
                "claims": len(state.claims),
                "opinions": sum(1 for c in state.claims if c.is_opinion),
            }
        )

    # ── stage 3 ──────────────────────────────────────────────────────────────
    async def _stage_ledger(self, state: RunState) -> None:
        state.status = RunStatus.BUILDING_LEDGER
        await self._emit({"event": "stage", "stage": "ledger", "status": "started"})

        assert state.document is not None
        state.elements = self.ledger.run(state.spans, state.claims, state.document)

        await self._emit(
            {
                "event": "ledger_built",
                "elements": len(state.elements),
                "spans": len(state.spans),
                "reduction": round(len(state.spans) / max(1, len(state.elements)), 2),
            }
        )

    # ── stage 3b ─────────────────────────────────────────────────────────────
    async def _stage_identity(self, state: RunState) -> None:
        """Resolve every named subject before a cent is spent researching one.

        This stage exists because of a measured failure. Asked to verify claims
        about a screenplay character called Dr Maya Rowan, the pipeline
        dispatched research at the name and attached what came back: four
        government domains from Google's grounding and, from Parallel, a
        teenage swimmer's results page. Every source real, every source
        authoritative looking, none of them about anybody in the script.

        A person does not work that way. They establish who the subject is
        first, and if the answer is nobody they stop, because the question has
        no answer and any source offered for it is about somebody else.

        Three outcomes, three different downstream paths:

            resolved      research the claims against the record
            collision     the character is invented and the name is the
                          finding; the collision check runs, fact verification
                          does not
            unidentified  nothing to verify. No dispatch, no spend, no
                          citations, and a verdict that says so
        """
        state.status = RunStatus.ROUTING
        await self._emit({"event": "stage", "stage": "identity", "status": "started"})

        subjects = _identifiable_subjects(state.elements)
        if not subjects:
            return

        verdicts = await asyncio.gather(
            *(
                self.identity.resolve(name, hints=hints, is_person=is_person)
                for name, hints, is_person in subjects
            ),
            return_exceptions=True,
        )

        by_name: dict[str, Any] = {}
        for (name, _, _), verdict in zip(subjects, verdicts, strict=True):
            if isinstance(verdict, BaseException):
                log.warning("identity resolution failed for %s: %s", name, verdict)
                continue
            by_name[name.casefold()] = verdict

        resolved = collisions = unidentified = 0
        for element in state.elements:
            verdict = by_name.get((element.canonical_form or "").casefold())
            if verdict is None:
                continue
            element.identity = verdict.to_dict()
            if verdict.canonical is not None and verdict.canonical.deceased is not None:
                element.subject_alive = not verdict.canonical.deceased
            if verdict.status == IdentityStatus.RESOLVED:
                resolved += 1
            elif verdict.status == IdentityStatus.COLLISION:
                collisions += 1
            else:
                unidentified += 1

        # Claims inherit their subject's identity, and the ones whose subject
        # is nobody are settled here rather than researched.
        by_element = {e.element_id: e for e in state.elements}
        settled = 0
        for claim in state.claims:
            element = by_element.get(claim.subject_element_id)
            identity = getattr(element, "identity", None) if element else None
            if not identity:
                identity = by_name.get(claim.subject_name.casefold())
                identity = identity.to_dict() if identity is not None else None
            if not identity:
                continue
            claim.identity = identity
            element_type = str(element.element_type) if element is not None else ""
            if not _blocks_research(identity, element_type):
                continue
            _settle_unresearchable(claim, identity)
            settled += 1

        state.artifacts["identity"] = {
            "subjects": len(subjects),
            "resolved": resolved,
            "collisions": collisions,
            "unidentified": unidentified,
            "claims_not_researched": settled,
        }
        log.info(
            "identity: %s subjects, %s resolved, %s collisions, %s unidentified, "
            "%s claims settled without research",
            len(subjects),
            resolved,
            collisions,
            unidentified,
            settled,
        )
        await self._emit({"event": "identity_resolved", **state.artifacts["identity"]})

    # ── stage 4 ──────────────────────────────────────────────────────────────
    async def _stage_route(self, state: RunState) -> None:
        state.status = RunStatus.ROUTING
        await self._emit({"event": "stage", "stage": "routing", "status": "started"})

        assert state.document is not None
        plan = self.router.run(
            state.elements,
            state.claims,
            truth_claim_framing=state.document.truth_claim_framing,
        )
        state.artifacts["routing_plan"] = plan.to_dict()

        # The projection is registered on the governor here rather than only
        # logged, so the live meter can show the estimate beside the actual for
        # the whole run instead of the estimate scrolling past once.
        projection = self.budget.project(
            [
                (d.processor, d.tier)
                for d in (*plan.claim_routes.values(), *plan.element_routes.values())
                if d.researched and d.processor is not None
            ]
        )
        state.artifacts["cost_projection"] = projection

        # The projected cost lands on screen before a cent is spent. Two
        # hundred subjects, a couple of dollars, against a manual report priced
        # in thousands and delivered in days.
        await self._emit({"event": "plan_ready", **plan.to_dict(), "projection": projection})

    # ── stage 5 ──────────────────────────────────────────────────────────────
    async def _stage_research(self, state: RunState) -> None:
        state.status = RunStatus.RESEARCHING
        await self._emit({"event": "stage", "stage": "research", "status": "started"})

        result = await self.swarm.run(state.claims, state.elements)
        state.artifacts["swarm"] = result.to_dict()
        state.artifacts["evidence_by_subject"] = result.evidence_by_subject

        self._record_research_telemetry(state, result)

        # Monitors are opened after research so the licence term discovered
        # during research can drive the cadence.
        for request in result.monitors_requested:
            handle = await self._open_monitor(request)
            if handle:
                state.monitors.append(handle)
                for element in state.elements:
                    if element.element_id == handle.subject_id:
                        element.monitor_handle = handle.monitor_id

    def _record_research_telemetry(self, state: RunState, result: SwarmResult) -> None:
        """Write one BigQuery row per Evidence produced by the swarm.

        Deliberately best effort and it swallows its own failures, because
        telemetry is not worth failing a clearance run over. What it is worth
        is that every unit economics number in the pitch becomes a query
        against `cost_telemetry` rather than an estimate: cost per script, cost
        per claim type, cache hit rate, fallback rate.

        Evidence pages are archived separately, by the swarm at the moment of
        capture, because that is the only point the page text exists.
        """
        try:
            from truestory.storage.bigquery import get_sink
        except Exception as exc:  # pragma: no cover - import guard
            log.debug("telemetry unavailable: %s", exc)
            return

        sink = get_sink()
        for evidence in result.records:
            try:
                sink.record_evidence(state.run_id, state.project_id, evidence)
            except Exception as exc:
                log.debug("telemetry row skipped for %s: %s", evidence.evidence_id, exc)

        try:
            sink.flush()
            log.info("telemetry: %s rows written to BigQuery", sink.rows_written)
        except Exception as exc:
            log.warning("telemetry flush failed: %s", exc)

    async def _open_monitor(self, request: dict[str, Any]) -> MonitorHandle | None:
        try:
            payload = await self.tools.watch_subject(**request)
            if not payload.get("monitor_id"):
                return None
            return MonitorHandle(
                monitor_id=payload["monitor_id"],
                subject_id=payload.get("subject_id", request["subject_id"]),
                provider_monitor_id=payload.get("provider_monitor_id", ""),
                query=payload.get("query", request["query"]),
                cadence=payload.get("cadence", request.get("cadence", "monthly")),
                reason=payload.get("reason", request.get("reason", "")),
                active=bool(payload.get("active", True)),
            )
        except Exception as exc:
            log.warning("monitor creation failed for %s: %s", request["subject_id"], exc)
            return None

    # ── stage 6 ──────────────────────────────────────────────────────────────
    async def _stage_adjudicate(self, state: RunState) -> None:
        state.status = RunStatus.ADJUDICATING
        await self._emit({"event": "stage", "stage": "adjudication", "status": "started"})

        evidence = state.artifacts.get("evidence_by_subject", {})
        _share_claim_evidence_with_subjects(state, evidence)
        state.review_queue = await self.adjudicator.run(state.claims, state.elements, evidence)

        from truestory.models.enums import Verdict

        await self._emit(
            {
                "event": "adjudication_complete",
                "green": sum(1 for c in state.claims if c.verdict is Verdict.VERIFIED),
                "amber": sum(1 for c in state.claims if c.is_amber),
                "red": sum(1 for c in state.claims if c.verdict is Verdict.CONTRADICTED),
                "grey": sum(1 for c in state.claims if c.verdict is Verdict.OPINION),
                "counsel": len(state.review_queue),
            }
        )

    # ── stage 7 ──────────────────────────────────────────────────────────────
    async def _stage_remedy(self, state: RunState) -> None:
        state.status = RunStatus.REMEDIATING
        await self._emit({"event": "stage", "stage": "remedy", "status": "started"})

        assert state.document is not None
        state.remedies = await self.remedy.run(
            state.claims,
            state.elements,
            truth_claim_framing=state.document.truth_claim_framing,
        )

        await self._emit(
            {
                "event": "remedies_ready",
                "proposed": len(state.remedies),
                "verified": sum(1 for r in state.remedies if r.verified),
            }
        )

    # ── stage 8 ──────────────────────────────────────────────────────────────
    def _outage_warnings(self, state: RunState) -> list[str]:
        """What to say on the front page when a provider stopped answering.

        A research provider that leaves service mid run does not produce a
        weaker report, it produces a report about nothing, and the difference
        has to be stated where a reader cannot miss it. Every subject in a run
        against a drained Parallel account came back "no record found either
        way", which is the same sentence a genuinely clean subject produces.

        The count is included because the ratio is the whole story: two failed
        subjects out of two hundred is a footnote, and two hundred out of two
        hundred means the report is empty and must not be filed.
        """
        warnings: list[str] = []
        outages = getattr(self.registry, "outages", {}) or {}
        for provider, detail in outages.items():
            warnings.append(
                f"RESEARCH PROVIDER OUT OF SERVICE: {provider} stopped answering during "
                f"this run and every subject it had not yet reached went unchecked. "
                f"Reported: {detail[:160]}. Findings below are not evidence that the "
                f"record is silent; the record was not searched. This report is not "
                f"fileable until the run is repeated against a working provider."
            )

        failed = sum(1 for c in state.claims if getattr(c, "research_failed", False))
        if failed:
            total = len(state.claims) or 1
            warnings.append(
                f"{failed} of {total} claims were never checked because research did not "
                f"run for them. They are shown as unsupported, which here means unchecked "
                f"rather than searched and not found."
            )
        return warnings

    async def _stage_report(self, state: RunState, started: float) -> None:
        state.status = RunStatus.REPORTING
        await self._emit({"event": "stage", "stage": "report", "status": "started"})

        assert state.document is not None
        duration = asyncio.get_event_loop().time() - started

        state.summary = build_summary(
            run_id=state.run_id,
            project_id=state.project_id,
            document=state.document,
            claims=state.claims,
            elements=state.elements,
            remedies=state.remedies,
            monitors=state.monitors,
            cost_cents=self.budget.ledger.spent_cents,
            model_cost_cents=self.budget.ledger.model_cents,
            duration_seconds=duration,
            cache_hit_rate=self.registry.cache_hit_rate,
            fallback_rate=self.registry.fallback_rate,
            coverage_warnings=self.budget.coverage_warnings() + self._outage_warnings(state),
        )

        state.artifacts["report"] = self.reporter.run(
            state.document,
            state.claims,
            state.elements,
            state.remedies,
            state.monitors,
            state.summary,
        )
        state.status = RunStatus.COMPLETE

        await self._emit({"event": "run_complete", **state.summary.to_dict()})

    # ── progress ─────────────────────────────────────────────────────────────
    async def _emit(self, payload: dict[str, Any]) -> None:
        if self.on_progress:
            try:
                await self.on_progress(payload)
            except Exception:
                log.debug("progress callback failed", exc_info=True)

    async def _emit_passthrough(self, payload: dict[str, Any]) -> None:
        await self._emit(payload)

    async def aclose(self) -> None:
        await self.registry.aclose()


#: Element types whose name is supposed to denote something real, and whose
#: claims are therefore worth checking. A phone number or a licence plate has
#: no identity to resolve.
_IDENTIFIABLE_TYPES = frozenset(
    {
        "REAL_PERSON_DEPICTED",
        "REAL_PERSON_IDENTIFIABLE",
        "PERSON_NAME_FICTIONAL",
        "REAL_EVENT",
        "ORGANIZATION",
        "BUSINESS_NAME",
        "BRAND_PRODUCT",
        "REAL_LOCATION",
    }
)

_PERSON_TYPES_FOR_IDENTITY = frozenset(
    {"REAL_PERSON_DEPICTED", "REAL_PERSON_IDENTIFIABLE", "PERSON_NAME_FICTIONAL"}
)


def _identifiable_subjects(
    elements: list[ClearableElement],
) -> list[tuple[str, str, bool]]:
    """(name, hints, is_person) for every subject worth identifying.

    The hints are the script's own context — the professions, places and
    attached claims around the name — and they are what separates the cricketer
    from the film of the same name.
    """
    out: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for element in elements:
        if str(element.element_type) not in _IDENTIFIABLE_TYPES:
            continue
        name = (element.canonical_form or "").strip()
        if len(name) < 3 or name.casefold() in seen:
            continue
        seen.add(name.casefold())

        # The script's own words around the name. A line of dialogue and the
        # surrounding action are exactly what tells a researcher that this
        # Dhoni is the cricketer rather than the film about him.
        hint_parts = [o.context for o in element.occurrences[:2] if o.context]
        hint_parts.extend(c.claim_text for c in (element.claims or [])[:3])
        hint_parts.extend(element.aliases[:2])
        out.append(
            (
                name,
                " ".join(hint_parts)[:400],
                str(element.element_type) in _PERSON_TYPES_FOR_IDENTITY,
            )
        )
    return out


#: Element types whose name is expected to be invented. A collision on one of
#: these is the finding; a collision on a person the script presents as real is
#: an uncertain identification, which is a reason to research carefully.
_INVENTED_BY_DESIGN = frozenset({"PERSON_NAME_FICTIONAL"})


def _blocks_research(identity: dict[str, Any], element_type: str) -> bool:
    """Whether this identity finding means the claim cannot be checked at all.

    The reason this gate exists is specific: searching a *name* returns whoever
    shares it, so a claim about a person nobody bears the name of must not be
    researched, because every source returned would be about somebody else.
    That argument is about people. It does not hold for anything else, and
    applying it to everything is what made this gate suppress research on true,
    well documented claims.

    A four line Titanic scene produced the subjects "the sinking", "sank on 15
    April 1912" and "sank on its third voyage" — predicates that ingest typed
    as REAL_EVENT. Identity dutifully searched for a real entity named "sank on
    its third voyage", found none, and blocked the claim. "The Titanic struck
    an iceberg" was returned unsupported with zero citations, never having been
    researched at all.

    So the block is now scoped to person subjects. A claim whose subject is an
    event, an organisation or a phrase is researched on its own words: the
    claim text names the Titanic whatever the ledger filed it under, and a
    thin subject is a reason to research carefully, not a reason to refuse.
    """
    status = identity.get("status")
    if status == IdentityStatus.UNIDENTIFIED:
        return element_type in _PERSON_TYPES_FOR_IDENTITY
    if status == IdentityStatus.COLLISION:
        return element_type in _INVENTED_BY_DESIGN
    return False


def _settle_unresearchable(claim: FactualClaim, identity: dict[str, Any]) -> None:
    """Close a claim whose subject nobody can be, without researching it.

    Deliberately not UNSUPPORTED. Unsupported means the record was searched and
    said nothing, which is a statement about the record. This is a statement
    about the claim: there is no real subject for a source to be about, so no
    amount of searching could produce one and pretending otherwise is how a
    swimmer's results page ends up under a screenplay character.
    """
    from truestory.models.enums import Verdict

    status = identity.get("status")
    if status == IdentityStatus.COLLISION:
        rationale = (
            "This is an invented character whose name several real people share. Nothing "
            "asserted about it is a factual claim about any of them, so it is not verified "
            "against the record; the name itself goes to the collision check instead."
        )
    else:
        rationale = (
            "No real subject of this name was found in the structured knowledge base or "
            "on the open web, so this asserts nothing that a source could confirm or "
            "contradict. Not researched, and no sources attached: any source returned "
            "for this name would be about somebody else."
        )

    claim.verdict = Verdict.UNVERIFIABLE
    claim.confidence = 0.0
    claim.rationale = rationale
    claim.evidence = []
    claim.identity = identity
    claim.needs_counsel = False
    claim.attribution = {
        "assessed": 0,
        "kept": 0,
        "dropped_irrelevant": 0,
        "dropped_unquotable": 0,
        "notes": ["Not researched: the subject could not be identified as real."],
    }


def _with_framing(document: ScriptDocument, framing: bool) -> ScriptDocument:
    return ScriptDocument(
        script_id=document.script_id,
        title=document.title,
        draft_version=document.draft_version,
        script_hash=document.script_hash,
        page_count=document.page_count,
        scenes=document.scenes,
        characters=document.characters,
        truth_claim_framing=framing,
        truth_claim_evidence=document.truth_claim_evidence
        or "Set explicitly in the project configuration.",
        source_format=document.source_format,
    )


# =============================================================================
# ADK deployment wrapper
# =============================================================================


def build_adk_pipeline(project: ProjectConfig) -> Any:
    """Wrap the same eight stages in ADK workflow agents for Agent Engine.

    The mapping is one to one on purpose. SequentialAgent for the spine because
    stage order is fixed by the domain, ParallelAgent for the fan out because
    concurrency is infrastructure rather than a decision, LoopAgent for the
    remedy loop because its termination condition is objective: does the
    proposal verify.
    """
    from google.adk.agents import LoopAgent, ParallelAgent, SequentialAgent

    pipeline = TrueStoryPipeline(project)

    ingest_stage = _as_adk_agent("ingest", pipeline._stage_ingest)
    claims_stage = _as_adk_agent("claim_extractor", pipeline._stage_claims)
    ledger_stage = _as_adk_agent("ledger", pipeline._stage_ledger)
    router_stage = _as_adk_agent("risk_router", pipeline._stage_route)
    adjudicate_stage = _as_adk_agent("adjudicator", pipeline._stage_adjudicate)
    report_stage = _as_adk_agent("report", pipeline._stage_report)

    research_stage = ParallelAgent(
        name="research_swarm",
        sub_agents=[_as_adk_agent("swarm", pipeline._stage_research)],
    )
    remedy_stage = LoopAgent(
        name="remedy_loop",
        max_iterations=pipeline.remedy.max_iterations,
        sub_agents=[_as_adk_agent("remedy", pipeline._stage_remedy)],
    )

    return SequentialAgent(
        name="TrueStoryPipeline",
        sub_agents=[
            ingest_stage,
            claims_stage,
            ledger_stage,
            router_stage,
            research_stage,
            adjudicate_stage,
            remedy_stage,
            report_stage,
        ],
    )


def _as_adk_agent(name: str, stage: Callable[..., Awaitable[None]]) -> Any:
    """Adapt one pipeline stage to the ADK custom agent interface.

    Kept thin deliberately. The stage logic lives in the plain classes above so
    that it is testable without an ADK runtime, and this adapter only bridges
    the session state.
    """
    from google.adk.agents import BaseAgent

    class _StageAgent(BaseAgent):  # type: ignore[misc]
        async def _run_async_impl(self, ctx: Any) -> Any:
            state = ctx.session.state.get("run_state")
            await stage(state)
            ctx.session.state["run_state"] = state
            yield ctx.make_event(author=name, content=f"{name} complete")

    return _StageAgent(name=name)


async def run_pipeline(
    source: Path | str,
    project: ProjectConfig | None = None,
    *,
    on_progress: ProgressCallback = None,
) -> RunState:
    """Convenience entry point used by the CLI, the API and the eval harness."""
    config = project or ProjectConfig(project_id="default")
    pipeline = TrueStoryPipeline(config, on_progress=on_progress)
    try:
        return await pipeline.run(source)
    finally:
        if settings.mode is not settings.mode.MOCK:
            await pipeline.aclose()


def _share_claim_evidence_with_subjects(
    state: RunState, evidence: dict[str, list[Evidence]]
) -> None:
    """Let an element see what its own claims found out about it.

    An element and the claims filed under it are researched as separate
    subjects, and the results were never pooled. So a run could resolve Apollo
    11 against Wikidata, verify three claims about Apollo 11 with citations,
    and still report the Apollo 11 element as RESEARCH_FAILED, because its own
    lookup happened to come back thin. Two questions about the same thing, one
    answered, and the answer thrown away.

    The report a reviewer reads is the one that said "research failed" beside a
    subject the run had in fact researched successfully, which reads as a
    broken tool and undercounts coverage on the front page.

    Nothing is invented here and no gate is relaxed. Evidence that already
    passed the attribution gate for a claim is made visible to the subject that
    claim is about, and every downstream check runs against it unchanged.
    """
    if not evidence:
        return

    claims_by_element: dict[str, list[FactualClaim]] = {}
    for claim in state.claims:
        if claim.subject_element_id:
            claims_by_element.setdefault(claim.subject_element_id, []).append(claim)

    shared = 0
    for element in state.elements:
        own = [e for e in evidence.get(element.element_id, []) if e.is_usable]
        if own:
            continue  # its own lookup answered; nothing to borrow

        inherited: list[Evidence] = []
        seen: set[str] = set()
        for claim in claims_by_element.get(element.element_id, []):
            for item in evidence.get(claim.claim_id, []):
                if item.is_usable and item.evidence_id not in seen:
                    seen.add(item.evidence_id)
                    inherited.append(item)

        if inherited:
            evidence.setdefault(element.element_id, []).extend(inherited)
            shared += 1

    if shared:
        log.info("evidence sharing: %s elements answered by their own claims", shared)
