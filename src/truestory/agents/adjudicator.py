"""Agent 6, Adjudicator. Evidence to verdicts. [LLM 3]

The model here is structurally incapable of asserting anything it cannot point
to a source for. It may only speak by calling `record_verdict` or
`record_adjudication`, and both functions require a non empty list of evidence
identifiers. That is a schema constraint, not a prompt instruction, which is
the difference between a safeguard and a hope.

Everything consequential happens after the model. The deterministic post checks
in this file are the rubric, they run as plain code over the model's output,
and they are the reason the system knows when it does not know:

    confidence below threshold          -> counsel
    sources conflict                    -> counsel, both surfaced side by side
    contradicted plus a living subject  -> counsel, regardless of confidence
    critical adjudicated clear          -> human confirmation before it renders green
    any fallback evidence               -> confidence capped
    amber density per named person      -> the person escalates, not just the line

The human review queue is a feature. Every real clearance workflow ends with an
attorney, and a system that knows its own uncertainty is the one an enterprise
buyer trusts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from truestory.agents import corroboration as corr
from truestory.config import settings
from truestory.models.claims import ClaimRollup, FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import (
    ClearanceStatus,
    ElementType,
    Polarity,
    PublicFigureStatus,
    RiskTier,
    Verdict,
)
from truestory.models.evidence import Evidence
from truestory.policy import load_rubric
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.adjudicator")


# =============================================================================
# the forced function declarations
# =============================================================================
# min_items on the evidence array is the whole safeguard. The model cannot
# construct a valid call that asserts something with nothing behind it.

RECORD_VERDICT_DECLARATION: dict[str, Any] = {
    "name": "record_verdict",
    "description": (
        "Record the verdict on one atomic factual claim. Requires at least one "
        "supporting evidence identifier unless the verdict is OPINION."
    ),
    "parameters": {
        "type": "object",
        "required": ["claim_id", "verdict", "supporting_evidence_ids", "rationale", "confidence"],
        "properties": {
            "claim_id": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["VERIFIED", "UNSUPPORTED", "CONTRADICTED", "UNVERIFIABLE", "OPINION"],
            },
            "supporting_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Evidence records relied on. Never empty except for OPINION.",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Why this verdict follows from that evidence. State explicitly "
                    "when sources conflict or when the record is thin."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Calibrated. Used, not decorated. Below the rubric threshold "
                    "the subject goes to a human regardless of the verdict."
                ),
            },
            "sources_conflict": {"type": "boolean"},
            # Gemini function declarations take a single type plus `nullable`,
            # not a JSON Schema union. A ["boolean", "null"] here is rejected
            # before the call is made, so every claim falls back to UNSUPPORTED
            # and the whole report comes out amber with no verdict behind it.
            "subject_alive": {"type": "boolean", "nullable": True},
            "subject_public_figure_status": {
                "type": "string",
                "enum": ["public", "limited_purpose", "private", "unknown"],
            },
        },
    },
}

RECORD_ADJUDICATION_DECLARATION: dict[str, Any] = {
    "name": "record_adjudication",
    "description": "Record the clearance status of one non claim element.",
    "parameters": {
        "type": "object",
        "required": ["element_id", "status", "supporting_evidence_ids", "rationale", "confidence"],
        "properties": {
            "element_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": [
                    "CLEAR",
                    "CLEAR_WITH_CONDITIONS",
                    "NOT_CLEAR",
                    "NEEDS_LICENSE",
                    "NEEDS_COUNSEL",
                ],
            },
            "supporting_evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "rationale": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "conditions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Art department or production instructions where the element is "
                    "usable but constrained."
                ),
            },
            "sources_conflict": {"type": "boolean"},
        },
    },
}


class Adjudicator:
    """Turn evidence into verdicts, then apply the rubric over the top."""

    name = "Adjudicator"

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or settings.model_adjudicator
        self.rubric = load_rubric()
        self._client = client
        self.review_queue: list[dict[str, Any]] = []

    # ── entry point ──────────────────────────────────────────────────────────
    async def run(
        self,
        claims: list[FactualClaim],
        elements: list[ClearableElement],
        evidence_by_subject: dict[str, list[Evidence]],
    ) -> list[dict[str, Any]]:
        for claim in claims:
            if claim.verdict is Verdict.OPINION:
                continue  # settled at routing, no spend and no model call
            await self.adjudicate_claim(claim, evidence_by_subject.get(claim.claim_id, []))

        for element in elements:
            await self.adjudicate_element(element, evidence_by_subject.get(element.element_id, []))

        # Person level rules run last, because they read across claims.
        self._apply_amber_density(elements)

        log.info(
            "adjudication complete: %s claims, %s elements, %s counsel items",
            len(claims),
            len(elements),
            len(self.review_queue),
        )
        return self.review_queue

    # ── claims ───────────────────────────────────────────────────────────────
    async def adjudicate_claim(self, claim: FactualClaim, evidence: list[Evidence]) -> None:
        usable = [e for e in evidence if e.is_usable]

        if not usable:
            self._escalate_claim(
                claim,
                Verdict.UNSUPPORTED,
                "Research returned no citable source. The system declines to make "
                "this call rather than guessing.",
                confidence=0.0,
                reason="no usable evidence",
                evidence=evidence,
            )
            return

        # What the record actually holds, counted before anything is decided:
        # independent domains, source pedigree, and the conclusion the research
        # payload reached in its own fields. The model sees this, and the post
        # checks below apply it whatever the model says.
        report = corr.analyse(usable)

        call = await self._call_model_for_claim(claim, usable, report)
        verdict = _parse_verdict(call.get("verdict"))
        confidence = float(call.get("confidence", 0.0))
        rationale = call.get("rationale", "")

        cited = [e for e in usable if e.evidence_id in set(call.get("supporting_evidence_ids", []))]
        if not cited:
            cited = usable  # the model named nothing valid, so cite everything

        claim.subject_alive = call.get("subject_alive", claim.subject_alive)
        claim.subject_public_figure_status = _parse_status(call.get("subject_public_figure_status"))

        # ── deterministic post checks ────────────────────────────────────────
        confidence = self._cap_for_fallback(confidence, cited)
        verdict, confidence, escalation = self._post_check_claim(
            claim, verdict, confidence, cited, bool(call.get("sources_conflict")), report
        )
        claim.corroboration = report.to_dict()

        try:
            claim.record_verdict(verdict, confidence, rationale, cited)
        except ValueError as exc:
            # The invariant in the model layer refused the call. That is the
            # safeguard working, so it escalates rather than silently passing.
            self._escalate_claim(
                claim, Verdict.UNSUPPORTED, str(exc), 0.0, "evidence invariant violated", evidence
            )
            return

        if escalation:
            reason, confirmation_only = _split_escalation(escalation)
            self._queue(
                claim.claim_id,
                "confirmation" if confirmation_only else "claim",
                reason,
                claim.subject_name,
            )
            # Only a genuine escalation marks the claim as needing counsel.
            # A confirmation is a sign off pass and does not colour the item.
            if not confirmation_only:
                claim.needs_counsel = True
                claim.counsel_reason = reason
            else:
                claim.awaiting_confirmation = True

    def _post_check_claim(
        self,
        claim: FactualClaim,
        verdict: Verdict,
        confidence: float,
        evidence: list[Evidence],
        sources_conflict: bool,
        report: corr.Corroboration | None = None,
    ) -> tuple[Verdict, float, str | None]:
        """The rubric as code. Runs after the model, never by it."""
        report = report or corr.analyse(evidence)

        # A verdict may never be more confident than its corroboration allows.
        # One tertiary source cannot produce a 0.95 however certain the model
        # sounded, and this is applied before every other check so that the
        # confidence threshold below sees the honest number.
        confidence = min(confidence, self.rubric.corroboration_cap(report.score))

        # Forums, social posts and content farms may corroborate a finding.
        # They may not settle one about a real person.
        if (
            self.rubric.low_trust_cannot_decide
            and report.low_trust_only
            and verdict in (Verdict.VERIFIED, Verdict.CONTRADICTED)
        ):
            return (
                Verdict.UNSUPPORTED,
                min(confidence, 0.4),
                (
                    "Every source is user generated or unattributable. Downgraded to "
                    "unsupported: this cannot settle a claim about a real person."
                ),
            )

        # A false factual claim about a living person is the claim that gets
        # filed. It goes to a human regardless of how confident the model was.
        if verdict is Verdict.CONTRADICTED and claim.subject_alive:
            return (
                verdict,
                confidence,
                ("Contradicted factual claim about a living person. Mandatory counsel review."),
            )

        # A contradiction is the heaviest thing this system says, so it must
        # rest on a primary source rather than a summary of one — and on a
        # source recognised as a record, not one that merely described itself
        # as primary. Before the classifier existed every citation defaulted to
        # "secondary", so this rule silently downgraded every red line in the
        # product to amber and the headline output was unreachable.
        strict = self.rubric.contradicted_requires_classified_primary
        primary_count = report.classified_primary_count if strict else report.primary_count
        if (
            verdict is Verdict.CONTRADICTED
            and self.rubric.contradicted_requires_primary_source
            and not primary_count
        ):
            return (
                Verdict.UNSUPPORTED,
                min(confidence, 0.6),
                (
                    "Contradiction rested on secondary sources only. Downgraded to "
                    "unsupported pending a primary source."
                ),
            )

        # The model's verdict against the conclusion its own research reached.
        # A disagreement here is the single most informative signal available
        # and it used to be discarded on the floor of the response parser.
        mismatch = corr.disagreement(str(verdict), report)
        if mismatch:
            return verdict, min(confidence, 0.55), mismatch

        if sources_conflict or report.conflict:
            return (
                verdict,
                min(confidence, 0.6),
                (
                    "Sources conflict. Both readings are surfaced side by side and the "
                    "system declines to choose."
                ),
            )

        # Corroboration, counted as distinct domains. Five URLs on one site are
        # one source, and a claim about a living person resting on one site is
        # not a checked claim.
        required_domains = self.rubric.min_independent_domains(claim.risk_tier)
        if report.independent_domains < required_domains:
            return (
                verdict,
                min(confidence, 0.7),
                (
                    f"Corroborated by {report.independent_domains} independent "
                    f"source{'' if report.independent_domains == 1 else 's'}, and tier "
                    f"{claim.risk_tier} requires {required_domains}."
                ),
            )

        if confidence < self.rubric.counsel_threshold:
            return (
                verdict,
                confidence,
                (
                    f"Confidence {confidence:.2f} is below the review threshold "
                    f"{self.rubric.counsel_threshold:.2f}."
                ),
            )

        if len(_all_citations(evidence)) < self.rubric.min_citations(claim.risk_tier):
            return verdict, confidence, (f"Fewer citations than tier {claim.risk_tier} requires.")

        # A private fact about a private person is outside what open source
        # research can settle, whatever the model thinks.
        if (
            verdict is Verdict.UNVERIFIABLE
            and claim.subject_public_figure_status is PublicFigureStatus.PRIVATE
        ):
            return (
                verdict,
                confidence,
                ("Unverifiable private matter concerning a private individual."),
            )

        # A CRITICAL subject coming back clean still needs a human to agree
        # before it renders green in a document an underwriter relies on.
        #
        # This is a confirmation, not an escalation, and the distinction is a
        # product decision rather than a technicality. If every verified claim
        # landed in the counsel queue, the queue would be the whole script and
        # the tool would have saved nobody any work. Confirmation is a fast
        # sign off pass. Escalation is a lawyer thinking hard about one line.
        if (
            claim.risk_tier is RiskTier.CRITICAL
            and verdict is Verdict.VERIFIED
            and self.rubric.critical_clear_requires_human
        ):
            return (
                verdict,
                confidence,
                _CONFIRM
                + (
                    "Critical tier claim verified by the system. Human confirmation "
                    "required before it renders as cleared."
                ),
            )

        return verdict, confidence, None

    # ── elements ─────────────────────────────────────────────────────────────
    async def adjudicate_element(self, element: ClearableElement, evidence: list[Evidence]) -> None:
        if element.element_type in _DETERMINISTIC:
            from truestory.agents.router import resolve_deterministic

            status_name, rationale = resolve_deterministic(element)
            element.status = ClearanceStatus(status_name)
            element.rationale = rationale
            element.confidence = 1.0
            if element.status is ClearanceStatus.NEEDS_COUNSEL:
                self._queue(element.element_id, "element", rationale, element.canonical_form)
                element.needs_counsel = True
            return

        usable = [e for e in evidence if e.is_usable]
        if not usable:
            # An element the swarm deliberately declined to research, because
            # it is a characterisation that defamation law protects, has not
            # failed anything. It arrives here already settled as CLEAR with
            # its reason written. Overwriting that as a research failure would
            # misstate what happened and count against coverage quality on the
            # front page of the report.
            if element.status is ClearanceStatus.CLEAR and element.rationale:
                return

            element.status = ClearanceStatus.RESEARCH_FAILED
            element.rationale = (
                "Research did not complete or returned no citable source. Counted "
                "against coverage quality on the report front page."
            )
            element.needs_counsel = True
            element.counsel_reason = "research failed"
            self._queue(element.element_id, "element", "Research failed", element.canonical_form)
            return

        report = corr.analyse(usable)
        call = await self._call_model_for_element(element, usable, report)
        status = _parse_status_enum(call.get("status"))
        confidence = self._cap_for_fallback(float(call.get("confidence", 0.0)), usable)
        cited = [
            e for e in usable if e.evidence_id in set(call.get("supporting_evidence_ids", []))
        ] or usable

        self._infer_person_facts(element, cited)
        status, confidence, escalation = self._post_check_element(
            element, status, confidence, cited, bool(call.get("sources_conflict")), report
        )
        element.corroboration = report.to_dict()

        try:
            element.record_adjudication(
                status,
                confidence,
                call.get("rationale", ""),
                cited,
                list(call.get("conditions", [])),
            )
        except ValueError as exc:
            element.status = ClearanceStatus.NEEDS_COUNSEL
            element.rationale = str(exc)
            element.needs_counsel = True
            self._queue(element.element_id, "element", str(exc), element.canonical_form)
            return

        if escalation:
            reason, confirmation_only = _split_escalation(escalation)
            self._queue(
                element.element_id,
                "confirmation" if confirmation_only else "element",
                reason,
                element.canonical_form,
            )
            if not confirmation_only:
                element.needs_counsel = True
                element.counsel_reason = reason
            else:
                element.awaiting_confirmation = True

        self._apply_masking(element)

    def _post_check_element(
        self,
        element: ClearableElement,
        status: ClearanceStatus,
        confidence: float,
        evidence: list[Evidence],
        sources_conflict: bool,
        report: corr.Corroboration | None = None,
    ) -> tuple[ClearanceStatus, float, str | None]:
        report = report or corr.analyse(evidence)

        # Same ceiling as a claim: a clearance position may not be more
        # confident than the sources behind it allow.
        confidence = min(confidence, self.rubric.corroboration_cap(report.score))

        if sources_conflict or report.conflict:
            return (
                ClearanceStatus.NEEDS_COUNSEL,
                min(confidence, 0.6),
                ("Sources conflict on the rights position. Both are surfaced side by side."),
            )

        # A licence requirement, a rights holder or a chain of title asserted
        # from forum posts is not a clearance position, whatever the model's
        # confidence. This is the same rule the claim path applies, stated for
        # the consequences that cost money rather than for a verdict colour.
        if (
            self.rubric.low_trust_cannot_decide
            and report.low_trust_only
            and status in _CONSEQUENTIAL_FOR_PERSON
        ):
            return (
                ClearanceStatus.NEEDS_COUNSEL,
                min(confidence, 0.4),
                (
                    "Every source is user generated or unattributable. A rights "
                    "position cannot rest on it."
                ),
            )

        # Corroboration, counted as distinct domains rather than URLs.
        required_domains = self.rubric.min_independent_domains(element.risk_tier)
        if status in _CONSEQUENTIAL_FOR_PERSON and report.independent_domains < required_domains:
            return (
                ClearanceStatus.NEEDS_COUNSEL,
                min(confidence, 0.6),
                (
                    f"Corroborated by {report.independent_domains} independent "
                    f"source{'' if report.independent_domains == 1 else 's'}, and tier "
                    f"{element.risk_tier} requires {required_domains} before a "
                    "consequential clearance position is recorded."
                ),
            )

        # Identity before consequence. Searching a name returns whoever shares
        # it, and a record that merely shares the name is not about this
        # subject. Asserting a licence requirement, a death, a domicile or an
        # estate on that basis is a fabricated finding about a real stranger,
        # which this system did produce: an invented character was matched to
        # an unrelated obituary and issued a publicity term to 2033 at 0.9
        # confidence. The model is instructed not to do this; the rubric is
        # what makes it so.
        if (
            element.element_type in _PERSON_TYPES
            and status in _CONSEQUENTIAL_FOR_PERSON
            and not _identity_confirmed(evidence)
        ):
            return (
                ClearanceStatus.NEEDS_COUNSEL,
                min(confidence, 0.5),
                (
                    "No source was confirmed to concern this person rather than someone "
                    "who shares the name. A rights position cannot rest on a name match."
                ),
            )

        # The same rule for a rights bearing work. Naming a licence, a rights
        # holder or a clearance for a work nobody located is a finding about a
        # specific owner who has not been found. The research says as much in
        # `work_identified`; this is what makes the report say it too.
        if (
            element.element_type in _WORK_TYPES
            and status in _CONSEQUENTIAL_FOR_PERSON
            and not _work_identified(evidence)
        ):
            return (
                ClearanceStatus.NEEDS_COUNSEL,
                min(confidence, 0.5),
                (
                    "The specific work was not identified, so its rights holder is "
                    "unknown. Whether a licence is required cannot be settled until it is."
                ),
            )

        # The Baby Reindeer post check. If the attribute cluster resolves to
        # real people, no confidence score makes that a machine's call.
        if element.element_type is ElementType.REAL_PERSON_IDENTIFIABLE:
            matches = sum(len(e.finding.get("matching_persons", []) or []) for e in evidence)
            if matches:
                return (
                    ClearanceStatus.NEEDS_COUNSEL,
                    confidence,
                    (
                        f"Attribute cluster resolves to {matches} real individuals. "
                        "Identifiability, not naming, is the legal trigger."
                    ),
                )

        if confidence < self.rubric.counsel_threshold:
            return (
                status,
                confidence,
                (f"Confidence {confidence:.2f} is below the review threshold."),
            )

        if (
            element.risk_tier is RiskTier.CRITICAL
            and status is ClearanceStatus.CLEAR
            and self.rubric.critical_clear_requires_human
        ):
            return (
                status,
                confidence,
                _CONFIRM
                + (
                    "Critical tier element cleared by the system. Human confirmation "
                    "required before it renders as cleared."
                ),
            )

        return status, confidence, None

    # ── the Fairstein rule ───────────────────────────────────────────────────
    def _apply_amber_density(self, elements: list[ClearableElement]) -> None:
        """Escalate the person, not just the line.

        The When They See Us case did not turn on one provably false sentence.
        It turned on a set of scenes attributing specific conduct to a named
        living person that the record could not support. Amber is the category
        that settles: not provably false, and therefore not defensible either.
        So density per person is itself a finding.
        """
        threshold, min_claims = self.rubric.amber_threshold()

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

            if rollup.researched_count < min_claims:
                continue
            if not rollup.exceeds_threshold(threshold):
                continue
            if element.subject_alive is False:
                continue  # the dead do not sue for defamation

            reason = (
                f"{rollup.amber_count} of {rollup.researched_count} researched claims "
                f"about {element.canonical_form} are unsupported by the record "
                f"({rollup.amber_density:.0%}, threshold {threshold:.0%}). Unsupported "
                "conduct density about a named living person."
            )
            element.needs_counsel = True
            element.counsel_reason = reason
            if element.status in (ClearanceStatus.CLEAR, ClearanceStatus.PENDING):
                element.status = ClearanceStatus.NEEDS_COUNSEL
            self._queue(element.element_id, "person", reason, element.canonical_form)

    # ── privacy ──────────────────────────────────────────────────────────────
    def _apply_masking(self, element: ClearableElement) -> None:
        """Privacy by default, principle P6.

        This system's output is assertions about real people. Built carelessly
        it becomes a defamation engine pointed at the people it exists to
        protect, so a living private individual is stored and never displayed
        until counsel unmasks with an audit record behind it.
        """
        if element.subject_alive is True and element.public_figure_status is (
            PublicFigureStatus.PRIVATE
        ):
            element.masked = True

        if element.element_type is ElementType.PERSON_NAME_FICTIONAL:
            for evidence in element.evidence:
                for match in evidence.finding.get("real_persons_matching", []) or []:
                    if match.get("alive") and match.get("prominence") in (None, "low"):
                        element.masked = True
                        return

    @staticmethod
    def _infer_person_facts(element: ClearableElement, evidence: list[Evidence]) -> None:
        for e in evidence:
            finding = e.finding
            if "alive" in finding and element.subject_alive is None:
                element.subject_alive = finding.get("alive")
            if "subject_alive" in finding and element.subject_alive is None:
                element.subject_alive = finding.get("subject_alive")
            raw_status = finding.get("public_figure_status") or finding.get(
                "subject_public_figure_status"
            )
            if raw_status and element.public_figure_status is PublicFigureStatus.UNKNOWN:
                element.public_figure_status = _parse_status(raw_status)

    def _cap_for_fallback(self, confidence: float, evidence: list[Evidence]) -> float:
        """Degrade honestly. A fallback answer never presents as a full one."""
        if any(e.is_fallback for e in evidence):
            return min(confidence, self.rubric.fallback_cap)
        return confidence

    # ── review queue ─────────────────────────────────────────────────────────
    def _escalate_claim(
        self,
        claim: FactualClaim,
        verdict: Verdict,
        rationale: str,
        confidence: float,
        reason: str,
        evidence: list[Evidence],
    ) -> None:
        claim.verdict = verdict
        claim.confidence = confidence
        claim.rationale = rationale
        claim.evidence = evidence
        claim.needs_counsel = True
        claim.counsel_reason = reason
        self._queue(claim.claim_id, "claim", reason, claim.subject_name)

    def _queue(self, subject_id: str, kind: str, reason: str, label: str) -> None:
        self.review_queue.append(
            {
                "subject_id": subject_id,
                "kind": kind,
                "label": label,
                "reason": reason,
                "assigned_to": None,
                "resolution": None,
            }
        )

    # ── model calls ──────────────────────────────────────────────────────────
    async def _call_model_for_claim(
        self,
        claim: FactualClaim,
        evidence: list[Evidence],
        report: corr.Corroboration | None = None,
    ) -> dict[str, Any]:
        if settings.offline:
            return _offline_claim_verdict(claim, evidence)
        return await self._forced_call(
            _claim_prompt(claim, evidence, report), RECORD_VERDICT_DECLARATION
        )

    async def _call_model_for_element(
        self,
        element: ClearableElement,
        evidence: list[Evidence],
        report: corr.Corroboration | None = None,
    ) -> dict[str, Any]:
        if settings.offline:
            return _offline_element_status(element, evidence)
        return await self._forced_call(
            _element_prompt(element, evidence, report), RECORD_ADJUDICATION_DECLARATION
        )

    async def _forced_call(self, prompt: str, declaration: dict[str, Any]) -> dict[str, Any]:
        """Forced function calling. The model has no other way to respond."""
        from google.genai import types

        from truestory.agents.prompts import ADJUDICATOR_SYSTEM

        try:
            response = await self._genai().aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ADJUDICATOR_SYSTEM,
                    temperature=0.0,
                    tools=[types.Tool(function_declarations=[declaration])],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY",  # a function call is the only legal output
                            allowed_function_names=[declaration["name"]],
                        )
                    ),
                ),
            )
            meter_response(self.model, response)
        except Exception as exc:
            log.warning("adjudication model call failed: %s", exc)
            return {"confidence": 0.0, "rationale": f"Model call failed: {exc}"}

        for candidate in getattr(response, "candidates", []) or []:
            for part in getattr(candidate.content, "parts", []) or []:
                call = getattr(part, "function_call", None)
                if call and call.name == declaration["name"]:
                    return dict(call.args)

        return {"confidence": 0.0, "rationale": "Model returned no function call."}

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
        return self._client


# =============================================================================
# helpers
# =============================================================================

#: Marker prefix distinguishing a routine sign off from a real escalation.
#: A confirmation is a human agreeing with a clean result. An escalation is a
#: lawyer deciding something the system declined to decide.
_CONFIRM = "\x00confirm\x00"


def _split_escalation(raw: str) -> tuple[str, bool]:
    """Return (reason, is_confirmation_only)."""
    if raw.startswith(_CONFIRM):
        return raw[len(_CONFIRM) :], True
    return raw, False


_PERSON_TYPES = frozenset({ElementType.REAL_PERSON_DEPICTED, ElementType.REAL_PERSON_IDENTIFIABLE})

#: Statuses that assert something consequential about a subject's rights.
#: Reaching one of these requires the record to have been tied to the subject.
_CONSEQUENTIAL_FOR_PERSON = frozenset(
    {
        ClearanceStatus.NEEDS_LICENSE,
        ClearanceStatus.NOT_CLEAR,
        ClearanceStatus.CLEAR,
        ClearanceStatus.CLEAR_WITH_CONDITIONS,
    }
)

#: Rights bearing works. A licence position on one of these is a statement
#: about a specific work with a specific owner, so the work has to have been
#: identified first. Each schema already records whether it was.
_WORK_TYPES = frozenset(
    {
        ElementType.ARTWORK_VISUAL,
        ElementType.TATTOO,
        ElementType.FILM_CLIP,
        ElementType.MUSIC_CUE,
        ElementType.PRINT_QUOTE,
    }
)


def _identity_confirmed(evidence: list[Evidence]) -> bool:
    """Whether any record was tied to the subject on more than the name.

    Reads the schema field the research is asked to populate. Absent or false
    means the provider either could not establish identity or was not asked,
    and either way nothing consequential may rest on it.
    """
    for record in evidence:
        finding = record.finding or {}
        if finding.get("identity_confirmed") is True and finding.get("identity_basis"):
            return True
    return False


def _work_identified(evidence: list[Evidence]) -> bool:
    """Whether the specific work was located, per its own schema's field.

    `visual_copyright_v1` asks `work_identified`, `quote_attribution_v1` asks
    `quote_documented`, and a music cue is identified once it has a title of
    record. All three were already being answered and none was being read: a
    photograph came back `work_identified: false`, with no creator and no
    rights holder, and was still issued a licence requirement at 0.9.
    """
    for record in evidence:
        finding = record.finding or {}
        if finding.get("work_identified") is True or finding.get("quote_documented") is True:
            return True
        if finding.get("title_of_record"):
            return True
    return False


_DETERMINISTIC = frozenset(
    {ElementType.PHONE_NUMBER, ElementType.VEHICLE_PLATE, ElementType.URL_HANDLE}
)


def _claim_prompt(
    claim: FactualClaim, evidence: list[Evidence], report: corr.Corroboration | None = None
) -> str:
    return (
        f"CLAIM ID: {claim.claim_id}\n"
        f"SUBJECT: {claim.subject_name}\n"
        f"CLAIM: {claim.claim_text}\n"
        f"CLAIM TYPE: {claim.claim_type}\n"
        f"REPUTATIONAL POLARITY: {claim.polarity}\n"
        f"RISK TIER: {claim.risk_tier}\n\n"
        f"{_pedigree_block(report)}"
        "EVIDENCE:\n" + _format_evidence(evidence)
    )


def _element_prompt(
    element: ClearableElement, evidence: list[Evidence], report: corr.Corroboration | None = None
) -> str:
    return (
        f"ELEMENT ID: {element.element_id}\n"
        f"TYPE: {element.element_type}\n"
        f"CANONICAL FORM: {element.canonical_form}\n"
        f"OCCURRENCES: {element.occurrence_count}\n"
        f"JURISDICTIONS: {', '.join(element.jurisdictions)}\n"
        f"RISK TIER: {element.risk_tier}\n\n"
        f"{_pedigree_block(report)}"
        "EVIDENCE:\n" + _format_evidence(evidence)
    )


def _pedigree_block(report: corr.Corroboration | None) -> str:
    """State what the sources are worth before the model reads them.

    Without this the model sees six URLs and treats them as six sources. It is
    told the count that actually matters, which domains they resolve to, and
    whether any of them is a record rather than a description of one.
    """
    if report is None or report.citation_count == 0:
        return ""
    lines = [
        "SOURCE PEDIGREE (counted, not asserted):",
        f"  independent domains: {report.independent_domains}"
        f" ({', '.join(report.domains[:6]) or 'none'})",
        f"  recognised primary records: {report.classified_primary_count}"
        f" of {report.citation_count} citations",
        f"  user generated or unattributable sources: {report.low_trust_count}",
        f"  research payload's own conclusion: {report.record_signal.lower()}",
    ]
    if report.record_quality:
        lines.append(f"  record quality: {report.record_quality}")
    if report.conflict:
        lines.append("  the payload returned both supporting AND contradicting findings")
    if report.single_source:
        lines.append("  WARNING: every citation resolves to a single domain")
    return "\n".join(lines) + "\n\n"


def _format_evidence(evidence: list[Evidence]) -> str:
    blocks: list[str] = []
    for e in evidence:
        sources = "\n".join(
            f"      - [{c.source_type}/{c.source_class}"
            f"{'' if c.verified_source else ', unrecognised host'}]"
            f" {c.title} ({c.url})\n        {c.excerpt[:300]}"
            for c in e.citations[:6]
        )
        blocks.append(
            f"  EVIDENCE ID: {e.evidence_id}\n"
            f"  PROVIDER: {e.provider}{' (FALLBACK)' if e.is_fallback else ''}\n"
            f"  PROVIDER CONFIDENCE: {e.effective_confidence:.2f}\n"
            f"  FINDING: {json.dumps(e.finding, default=str)[:1500]}\n"
            f"  REASONING: {e.reasoning[:600]}\n"
            f"  SOURCES:\n{sources or '      (none)'}"
        )
    return "\n\n".join(blocks) or "  (no evidence)"


def _all_citations(evidence: list[Evidence]) -> list[Any]:
    return [c for e in evidence for c in e.citations]


def _parse_verdict(raw: Any) -> Verdict:
    try:
        return Verdict(str(raw))
    except ValueError:
        return Verdict.UNSUPPORTED


def _parse_status(raw: Any) -> PublicFigureStatus:
    try:
        return PublicFigureStatus(str(raw))
    except ValueError:
        return PublicFigureStatus.UNKNOWN


def _parse_status_enum(raw: Any) -> ClearanceStatus:
    try:
        return ClearanceStatus(str(raw))
    except ValueError:
        return ClearanceStatus.NEEDS_COUNSEL


# ── offline adjudication ─────────────────────────────────────────────────────
# Deterministic mapping from the mock provider's structured finding onto a
# verdict, so that mock mode produces a coherent overlay and exercises every
# post check without a model in the loop.


def _offline_claim_verdict(claim: FactualClaim, evidence: list[Evidence]) -> dict[str, Any]:
    finding = evidence[0].finding if evidence else {}
    raw = str(finding.get("verdict", "no_record"))
    verdict = {
        "supported": "VERIFIED",
        "contradicted": "CONTRADICTED",
        "no_record": "UNSUPPORTED",
        "not_a_factual_claim": "OPINION",
    }.get(raw, "UNSUPPORTED")

    return {
        "claim_id": claim.claim_id,
        "verdict": verdict,
        "supporting_evidence_ids": [e.evidence_id for e in evidence],
        "rationale": (
            f"Offline adjudication from the {raw} finding returned by the mock "
            f"provider. Record quality reported as {finding.get('record_quality', 'unknown')}."
        ),
        "confidence": max((e.effective_confidence for e in evidence), default=0.0),
        "sources_conflict": bool(
            finding.get("supporting_facts") and finding.get("contradicting_facts")
        ),
        "subject_alive": finding.get("subject_alive", claim.subject_alive),
        "subject_public_figure_status": finding.get("subject_public_figure_status", "unknown"),
    }


def _offline_element_status(element: ClearableElement, evidence: list[Evidence]) -> dict[str, Any]:
    finding = evidence[0].finding if evidence else {}

    if finding.get("collision_risk") in {"high", "medium"}:
        status = "NOT_CLEAR"
    elif finding.get("identifiability_risk") in {"high", "medium"}:
        status = "NEEDS_COUNSEL"
    elif (
        finding.get("public_domain_status") == "in_copyright"
        or finding.get("copyright_status") == "in_copyright"
    ):
        status = "NEEDS_LICENSE"
    else:
        status = "CLEAR"

    return {
        "element_id": element.element_id,
        "status": status,
        "supporting_evidence_ids": [e.evidence_id for e in evidence],
        "rationale": "Offline adjudication from the mock provider finding.",
        "confidence": max((e.effective_confidence for e in evidence), default=0.0),
        "conditions": [],
        "sources_conflict": False,
    }


def polarity_is_negative(claim: FactualClaim) -> bool:
    return claim.polarity is Polarity.NEGATIVE
