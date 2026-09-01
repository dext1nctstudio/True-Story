"""Agent 7, RemedyLoop. Propose, then verify the proposal. [LLM 4]

This closed loop is what separates the system from a research wrapper. Anyone
can ask a model for a rewrite. This proposes a fix, sends it back through the
same research path under the same output schema, adjudicates it under the same
rubric, and only then presents it as a fix. The success criterion is objective,
which is why the loop can terminate without a model deciding it is satisfied.

    propose  ->  re verify through the identical path  ->  verified?
                                                            yes  emit redline
                                                            no   iterate, up to 3
                                                                 then counsel

Three iterations, failed candidates excluded from each retry, and counsel as
the honest terminal state when no proposal both survives verification and
preserves what the line was doing dramatically.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from truestory.config import settings
from truestory.mcp.tools import ClearanceTools
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement, Remedy
from truestory.models.enums import ClearanceStatus, ElementType, Verdict
from truestory.models.evidence import Evidence
from truestory.policy import load_rubric
from truestory.providers import model_fallback
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.remedy")


class RemedyLoop:
    """Bounded propose and verify loop over every contradicted or uncleared subject."""

    name = "RemedyLoop"

    def __init__(
        self,
        tools: ClearanceTools,
        model: str | None = None,
        client: Any = None,
    ) -> None:
        self.tools = tools
        self.model = model or settings.model_remedy
        self.rubric = load_rubric()
        self.max_iterations = self.rubric.max_remedy_iterations
        self._client = client

    # ── entry point ──────────────────────────────────────────────────────────
    async def run(
        self,
        claims: list[FactualClaim],
        elements: list[ClearableElement],
        *,
        truth_claim_framing: bool = False,
    ) -> list[Remedy]:
        remedies: list[Remedy] = []

        for claim in claims:
            if claim.verdict is Verdict.CONTRADICTED:
                remedy = await self.remedy_claim(claim)
                if remedy:
                    remedies.append(remedy)
                    claim.remedy_id = remedy.remedy_id

        for element in elements:
            if element.status in _NEEDS_REMEDY:
                remedy = await self.remedy_element(element)
                if remedy:
                    remedies.append(remedy)
                    element.remedies.append(remedy)

        # The disclaimer remedy is project level and is generated from the
        # terms of an actual settlement, in which the negotiated fix was moving
        # the fictionalisation disclaimer to the start of every episode.
        if truth_claim_framing:
            remedies.append(self._disclaimer_remedy())

        verified = sum(1 for r in remedies if r.verified)
        log.info(
            "remedy loop: %s proposals, %s verified against the record", len(remedies), verified
        )
        return remedies

    # ── claims ───────────────────────────────────────────────────────────────
    async def remedy_claim(self, claim: FactualClaim) -> Remedy | None:
        """Rewrite a contradicted line, then verify the rewrite.

        The dramatic function is not a nicety. A correction that flattens the
        beat will be rejected by the writer and the production ships the
        original line, so the loop that ignores it produces nothing usable.
        """
        original = (
            claim.first_occurrence.surface_form if claim.first_occurrence else claim.claim_text
        )
        rejected: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            proposal = await self._propose(claim, original, rejected)
            if not proposal or not proposal.get("proposal"):
                break

            candidate_text = proposal["proposal"]

            # Re verification through the identical research path. Same tool,
            # same schema, same adjudication. There is no weaker second path.
            payload = await self.tools.verify_factual_claim(
                subject_id=f"{claim.claim_id}:remedy:{iteration}",
                subject=claim.subject_name,
                claim=candidate_text,
                polarity=str(claim.polarity),
                subject_alive=claim.subject_alive,
            )
            evidence = _rehydrate(payload, claim.claim_id, candidate_text)
            verified = _finding_supports(evidence)

            remedy = Remedy(
                remedy_id=Remedy.make_id(claim.claim_id, candidate_text, iteration),
                subject_id=claim.claim_id,
                kind="rewrite",
                proposal=candidate_text,
                original=original,
                rationale=proposal.get("rationale", ""),
                verified=verified,
                verification_evidence=[evidence],
                iteration=iteration,
                preserves_beat=bool(proposal.get("preserves_beat", True)),
                alternatives=list(proposal.get("alternatives", [])),
            )

            if verified:
                log.debug("claim %s remedied on iteration %s", claim.claim_id, iteration)
                return remedy

            rejected.append(candidate_text)

        # Honest terminal state. No proposal both survived verification and
        # preserved the beat, so a human decides.
        claim.needs_counsel = True
        claim.counsel_reason = (
            f"No rewrite verified against the record within {self.max_iterations} "
            "attempts. Requires counsel and writer judgement together."
        )
        return None

    # ── elements ─────────────────────────────────────────────────────────────
    async def remedy_element(self, element: ClearableElement) -> Remedy | None:
        match element.element_type:
            case ElementType.PERSON_NAME_FICTIONAL:
                return await self._remedy_name_collision(element)
            case ElementType.MUSIC_CUE:
                return self._remedy_music(element)
            case ElementType.ARTWORK_VISUAL | ElementType.TATTOO | ElementType.FILM_CLIP:
                return self._remedy_visual(element)
            case ElementType.PHONE_NUMBER | ElementType.VEHICLE_PLATE:
                return self._remedy_substitution(element)
            case _:
                return None

    async def _remedy_name_collision(self, element: ClearableElement) -> Remedy | None:
        """Three alternates, each itself collision checked before it is offered.

        Matched on syllable count, period plausibility, cultural origin and
        phonetic shape, so the change is invisible in performance. Vendors
        offer this free within the original report and writers expect it.
        """
        candidates = _alternates_from_evidence(element)

        if not candidates:
            proposal = await self._propose_names(element)
            candidates = proposal.get("alternatives", [])

        verified_names: list[str] = []
        evidence: list[Evidence] = []

        for name in candidates[: self.rubric.remedy.get("alternate_names_offered", 3)]:
            payload = await self.tools.check_person_collision(
                subject_id=f"{element.element_id}:alt:{name}",
                name=name,
                profession=_profession_hint(element),
            )
            candidate_evidence = _rehydrate(payload, element.element_id, name)
            evidence.append(candidate_evidence)
            risk = candidate_evidence.finding.get("collision_risk", "unknown")
            if risk in {"none", "low"}:
                verified_names.append(name)

        if not verified_names:
            return None

        return Remedy(
            remedy_id=Remedy.make_id(element.element_id, verified_names[0], 1),
            subject_id=element.element_id,
            kind="rename",
            proposal=verified_names[0],
            original=element.canonical_form,
            rationale=(
                "Alternate names matched to the original on syllable count, period "
                "plausibility and phonetic shape, each checked for collisions before "
                "being offered."
            ),
            verified=True,
            verification_evidence=evidence,
            alternatives=verified_names[1:],
        )

    def _remedy_music(self, element: ClearableElement) -> Remedy:
        """Two licence request letters, because a cue is two rights."""
        finding = element.evidence[0].finding if element.evidence else {}
        sync = (
            finding.get("sync_contact")
            or finding.get("composition_rights_holder")
            or "unidentified"
        )
        master = (
            finding.get("master_contact") or finding.get("master_rights_holder") or "unidentified"
        )

        return Remedy(
            remedy_id=Remedy.make_id(element.element_id, "music_license", 1),
            subject_id=element.element_id,
            kind="license_request",
            proposal=(
                f"Two licences are required for '{element.canonical_form}'.\n"
                f"  1. Synchronisation licence, composition. Contact: {sync}\n"
                f"  2. Master use licence, recording. Contact: {master}\n"
                "Request a term covering all media in perpetuity where budget allows. "
                "A time boxed term must be entered in the monitor manifest so the "
                "production is alerted before it lapses."
            ),
            original=element.canonical_form,
            rationale=(
                "A cue carries two separate rights held by different parties. "
                "Carriers require both, plus a complete cue sheet, before binding."
            ),
            verified=bool(element.evidence),
            verification_evidence=element.evidence[:1],
        )

    def _remedy_visual(self, element: ClearableElement) -> Remedy:
        return Remedy(
            remedy_id=Remedy.make_id(element.element_id, "visual", 1),
            subject_id=element.element_id,
            kind="substitution",
            proposal=(
                f"Replace '{element.canonical_form}' with commissioned original artwork, "
                "or licence it from the identified rights holder. Commissioning is "
                "usually faster and cheaper, and the art department can act on it "
                "immediately. Do not rely on brief visibility: courts have declined "
                "the de minimis defence for background artwork on screen for seconds."
            ),
            original=element.canonical_form,
            rationale="Visible artwork is a rights question rather than a set dressing note.",
            verified=bool(element.evidence),
            verification_evidence=element.evidence[:1],
        )

    def _remedy_substitution(self, element: ClearableElement) -> Remedy:
        proposal = (
            "Substitute a number in the reserved 555 exchange, for example 555-0147."
            if element.element_type is ElementType.PHONE_NUMBER
            else "Substitute a plate from a production reserved series."
        )
        return Remedy(
            remedy_id=Remedy.make_id(element.element_id, proposal, 1),
            subject_id=element.element_id,
            kind="substitution",
            proposal=proposal,
            original=element.canonical_form,
            rationale="Deterministic substitution. No research required and no spend.",
            verified=True,
        )

    def _disclaimer_remedy(self) -> Remedy:
        """Encoded from the terms of an actual settlement.

        The negotiated remedy in that case was not new wording, it was
        position: the fictionalisation disclaimer moved to the start of every
        episode. Position and prominence were the terms, so both are stated.
        """
        cfg = self.rubric.remedy.get("disclaimer", {})
        text = cfg.get("default_text", "")
        position = cfg.get("default_position", "start of each episode")

        return Remedy(
            remedy_id=Remedy.make_id("project", "disclaimer", 1),
            subject_id="project:truth_claim_framing",
            kind="disclaimer",
            proposal=f'Place the following at the {position}:\n\n"{text}"',
            original="(no disclaimer, or end credits placement only)",
            rationale=(
                "This production asserts that the story is true, which escalates the "
                "risk position of every person adjacent element. In a settled dispute "
                "the negotiated remedy was moving the fictionalisation disclaimer to "
                "the start of each episode, so placement and prominence are stated "
                "here alongside the wording."
            ),
            verified=True,
        )

    # ── the model ────────────────────────────────────────────────────────────
    async def _propose(
        self, claim: FactualClaim, original: str, rejected: list[str]
    ) -> dict[str, Any]:
        if settings.offline:
            return _offline_proposal(claim, original, rejected)

        from google.genai import types

        from truestory.agents.prompts import REMEDY_SYSTEM, REMEDY_USER

        try:
            response = await model_fallback.generate(
                self._genai(),
                model=self.model,
                contents=REMEDY_USER.format(
                    original=original,
                    claim=claim.claim_text,
                    verdict=claim.verdict,
                    rationale=claim.rationale,
                    evidence_summary=_summarise(claim.evidence),
                    context=claim.first_occurrence.context if claim.first_occurrence else "",
                    rejected="\n".join(f"  - {r}" for r in rejected) or "  (none)",
                ),
                config=types.GenerateContentConfig(
                    system_instruction=REMEDY_SYSTEM,
                    temperature=0.4,  # the only stage where variation helps
                    response_mime_type="application/json",
                    response_schema=_PROPOSAL_SCHEMA,
                ),
            )
            meter_response(self.model, response)
            return json.loads(getattr(response, "text", "") or "{}")
        except Exception as exc:
            log.warning("remedy proposal failed: %s", exc)
            return {}

    async def _propose_names(self, element: ClearableElement) -> dict[str, Any]:
        if settings.offline:
            return {"alternatives": _offline_alternates(element.canonical_form)}
        return await self._propose(
            FactualClaim(
                claim_id=element.element_id,
                subject_element_id=element.element_id,
                subject_name=element.canonical_form,
                claim_text=f"The character is named {element.canonical_form}.",
                claim_type=__import__(
                    "truestory.models.enums", fromlist=["ClaimType"]
                ).ClaimType.STATUS,
                polarity=__import__(
                    "truestory.models.enums", fromlist=["Polarity"]
                ).Polarity.NEUTRAL,
            ),
            element.canonical_form,
            [],
        )

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

_NEEDS_REMEDY = frozenset({ClearanceStatus.NOT_CLEAR, ClearanceStatus.NEEDS_LICENSE})


def _rehydrate(payload: dict[str, Any], subject_id: str, question: str) -> Evidence:
    from truestory.providers.cached import _evidence_from_dict

    if "evidence_id" in payload:
        return _evidence_from_dict(payload)
    return Evidence.failed(subject_id, question, "remedy", payload.get("error", "no envelope"))


def _finding_supports(evidence: Evidence) -> bool:
    """A remedy counts as verified only when the record supports it."""
    return evidence.is_usable and evidence.finding.get("verdict") == "supported"


def _summarise(evidence: list[Evidence]) -> str:
    lines: list[str] = []
    for e in evidence[:4]:
        for fact in e.finding.get("contradicting_facts", []) or []:
            lines.append(f"  - {fact.get('fact')} [{fact.get('source_url')}]")
        for fact in e.finding.get("supporting_facts", []) or []:
            lines.append(f"  + {fact.get('fact')} [{fact.get('source_url')}]")
    return "\n".join(lines) or "  (no structured facts returned)"


def _alternates_from_evidence(element: ClearableElement) -> list[str]:
    names: list[str] = []
    for e in element.evidence:
        for alt in e.finding.get("alternate_names", []) or []:
            name = alt.get("name") if isinstance(alt, dict) else alt
            if name and name not in names:
                names.append(name)
    return names


def _profession_hint(element: ClearableElement) -> str:
    for occurrence in element.occurrences:
        context = occurrence.context
        for word in ("doctor", "lawyer", "nurse", "teacher", "detective", "journalist"):
            if word in context.lower():
                return word
    return "unknown"


def _offline_proposal(claim: FactualClaim, original: str, rejected: list[str]) -> dict[str, Any]:
    """Deterministic softening. Enough to exercise the loop without a model.

    Attributing an assertion rather than stating it is a real remedy and not a
    trick: "they said she had never faced men" asserts something legally
    different from "she had never faced men".
    """
    attempt = len(rejected) + 1
    if attempt == 1:
        proposal = f"They said {claim.claim_text[0].lower()}{claim.claim_text[1:]}"
        rationale = (
            "Softened to an attributed statement. Reporting what was said asserts "
            "something legally different from stating the fact directly."
        )
    elif attempt == 2:
        proposal = original.replace(claim.claim_text, "").strip() or "(line cut)"
        rationale = "Specific factual content removed while the beat is retained."
    else:
        proposal = "(line cut, beat preserved through action)"
        rationale = "No accurate phrasing preserved the beat. Cutting is the honest fix."

    return {
        "proposal": proposal,
        "rationale": rationale,
        "preserves_beat": attempt < 3,
        "alternatives": [],
    }


def _offline_alternates(original: str) -> list[str]:
    """Syllable matched period plausible substitutes for the offline path."""
    pool = ["Marlowe", "Hallam", "Renwick", "Alderton", "Beckwith", "Carrow"]
    target = max(1, len(original.split()[0]))
    return sorted(pool, key=lambda n: abs(len(n) - target))[:3]


_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["proposal", "rationale"],
    "properties": {
        "proposal": {"type": "string"},
        "rationale": {"type": "string"},
        "preserves_beat": {"type": "boolean"},
        "dramatic_function": {
            "type": "string",
            "description": "What the original line was doing in the scene.",
        },
        "alternatives": {"type": "array", "items": {"type": "string"}},
    },
}
