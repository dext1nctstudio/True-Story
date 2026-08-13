"""Agent 4, RiskRouter. Deterministic, zero LLM.

The entire agent is a lookup against policy/routing.yaml. It is auditable, it
is unit testable, and it is explainable to a judge in one sentence, which is
exactly what principle P1 demands.

The escalation is where the domain knowledge shows. A production that asserts
"this is a true story" raises the risk tier of every person adjacent subject by
one full step, because courts treated that framing itself as evidence bearing
on reckless disregard for falsity. One rule in a configuration file
implementing a doctrine two federal courts applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClaimType, ElementType, Processor, RiskTier, Verdict
from truestory.policy import RoutingDecision, load_routing

log = logging.getLogger("truestory.router")


@dataclass(slots=True)
class RoutingPlan:
    """Everything the swarm needs, plus the pre flight cost projection."""

    claim_routes: dict[str, RoutingDecision]
    element_routes: dict[str, RoutingDecision]
    truth_claim_framing: bool
    escalated_subjects: int = 0
    skipped_opinions: int = 0
    deterministic_only: int = 0

    @property
    def researched_subjects(self) -> int:
        return sum(
            1
            for d in [*self.claim_routes.values(), *self.element_routes.values()]
            if d.researched
        )

    def projected_cost_usd(self) -> float:
        return round(
            sum(
                d.estimated_cost_usd
                for d in [*self.claim_routes.values(), *self.element_routes.values()]
            ),
            4,
        )

    def tier_histogram(self) -> dict[str, int]:
        hist: dict[str, int] = {}
        for d in [*self.claim_routes.values(), *self.element_routes.values()]:
            hist[str(d.tier)] = hist.get(str(d.tier), 0) + 1
        return hist

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims_routed": len(self.claim_routes),
            "elements_routed": len(self.element_routes),
            "researched_subjects": self.researched_subjects,
            "truth_claim_framing": self.truth_claim_framing,
            "escalated_subjects": self.escalated_subjects,
            "skipped_opinions": self.skipped_opinions,
            "deterministic_only": self.deterministic_only,
            "projected_cost_usd": self.projected_cost_usd(),
            "tiers": self.tier_histogram(),
        }


class RiskRouter:
    """Assign a tier, a processor, a schema and side effects to every subject."""

    name = "RiskRouter"

    def __init__(self) -> None:
        self.policy = load_routing()

    def run(
        self,
        elements: list[ClearableElement],
        claims: list[FactualClaim],
        *,
        truth_claim_framing: bool = False,
    ) -> RoutingPlan:
        project = {"truth_claim_framing": truth_claim_framing}
        plan = RoutingPlan(
            claim_routes={}, element_routes={}, truth_claim_framing=truth_claim_framing
        )

        for claim in claims:
            decision = self._route_claim(claim, project)
            plan.claim_routes[claim.claim_id] = decision
            self._apply_to_claim(claim, decision)

            if decision.escalated_by:
                plan.escalated_subjects += 1
            if not decision.researched:
                plan.skipped_opinions += 1

        for element in elements:
            decision = self._route_element(element, project)
            plan.element_routes[element.element_id] = decision
            self._apply_to_element(element, decision)

            if decision.escalated_by:
                plan.escalated_subjects += 1
            if decision.provider == "deterministic_rules":
                plan.deterministic_only += 1

        log.info(
            "routing: %s subjects, %s researched, %s escalated by truth claim framing, "
            "projected $%.2f",
            len(claims) + len(elements),
            plan.researched_subjects,
            plan.escalated_subjects,
            plan.projected_cost_usd(),
        )
        return plan

    # ── claims ───────────────────────────────────────────────────────────────
    def _route_claim(
        self, claim: FactualClaim, project: dict[str, Any]
    ) -> RoutingDecision:
        subject = {
            "kind": "claim",
            "type": str(claim.claim_type),
            "polarity": str(claim.polarity),
            "subject_alive": claim.subject_alive,
            "occurrence_count": claim.occurrence_count,
        }
        decision = self.policy.match(subject)
        return self.policy.apply_project_escalations(decision, subject, project)

    @staticmethod
    def _apply_to_claim(claim: FactualClaim, decision: RoutingDecision) -> None:
        claim.risk_tier = decision.tier
        if decision.schema_name:
            claim.schema_name = decision.schema_name

        # An opinion is settled here, before any spend. Defamation law protects
        # it, so it is never researched and never coloured.
        if claim.claim_type is ClaimType.CHARACTERIZATION and not decision.researched:
            claim.verdict = Verdict.OPINION
            claim.confidence = 1.0
            claim.rationale = (
                "Characterisation rather than a verifiable factual assertion. "
                "Not researched."
            )

    # ── elements ─────────────────────────────────────────────────────────────
    def _route_element(
        self, element: ClearableElement, project: dict[str, Any]
    ) -> RoutingDecision:
        subject = {
            "type": str(element.element_type),
            "occurrence_count": element.occurrence_count,
            "in_dialogue": element.in_dialogue,
            "has_claims": bool(element.claims),
        }
        decision = self.policy.match(subject)
        return self.policy.apply_project_escalations(decision, subject, project)

    @staticmethod
    def _apply_to_element(element: ClearableElement, decision: RoutingDecision) -> None:
        element.risk_tier = decision.tier
        element.processor = decision.processor or Processor.LITE
        if decision.schema_name:
            element.schema_name = decision.schema_name
        element.also = list(decision.also)
        element.escalated_by = list(decision.escalated_by)

    # ── explanation ──────────────────────────────────────────────────────────
    def explain(self, subject: dict[str, Any]) -> str:
        """One sentence answering why a subject got the tier it got.

        A producer looking at a two dollar bill will eventually ask why one
        throwaway line went to the most expensive processor. This is the
        answer, and it is generated from the same table that made the decision.
        """
        decision = self.policy.match(subject)
        parts = [
            f"Matched rule '{decision.rule_id}', which assigns tier {decision.tier}"
        ]
        if decision.processor:
            parts.append(f"using the {decision.processor} processor")
        if decision.schema_name:
            parts.append(f"against schema {decision.schema_name}")
        if decision.also:
            parts.append(f"with side effects {', '.join(decision.also)}")
        if decision.escalated_by:
            parts.append(f"escalated by {', '.join(decision.escalated_by)}")
        if decision.note:
            parts.append(f"Rule note: {decision.note}")
        return ". ".join(parts) + "."


# =============================================================================
# deterministic resolution, no research at all
# =============================================================================

_FIVE_FIVE_FIVE = frozenset({"555"})


def resolve_deterministic(element: ClearableElement) -> tuple[str, str]:
    """Phone numbers, plates and handles. Rules, not research, and zero spend.

    Returns (status, rationale). These subjects are a meaningful share of a
    typical script and researching any of them would be waste.
    """
    if element.element_type is ElementType.PHONE_NUMBER:
        digits = "".join(c for c in element.canonical_form if c.isdigit())
        exchange = digits[3:6] if len(digits) >= 10 else ""
        if exchange in _FIVE_FIVE_FIVE:
            return (
                "CLEAR",
                "Uses the 555 exchange reserved for fictional use. No research required.",
            )
        return (
            "NOT_CLEAR",
            "Not a reserved fictional number. Substitute a 555 exchange number, "
            "or clear the real number with its subscriber.",
        )

    if element.element_type is ElementType.VEHICLE_PLATE:
        return (
            "NOT_CLEAR",
            "Visible plate numbers should use a production reserved series. "
            "Substitute rather than research.",
        )

    if element.element_type is ElementType.URL_HANDLE:
        value = element.canonical_form
        if value.endswith(".invalid") or ".example." in value or value.endswith(".example"):
            return ("CLEAR", "Uses a reserved example domain. No research required.")
        return (
            "NEEDS_COUNSEL",
            "Real domain or handle shown on screen. Substitute a reserved example "
            "domain, or clear the use with the owner.",
        )

    return ("PENDING", "No deterministic rule applies to this element type.")
