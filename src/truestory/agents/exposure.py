"""The exposure model. What a finding could cost, without inventing a number.

The obvious feature here is a damages estimate per finding, and it is the one
thing this module will not produce. The reasoning is set out at length in the
header of `policy/exposure.yaml`; in short, settlements in this industry are
overwhelmingly confidential, so the only amounts in the public record are the
outliers that reached the trade press. A model fitted to those over predicts on
every ordinary matter, and a dollar figure printed next to a line of dialogue
becomes a reserve figure the moment a producer reads it.

So this answers the question a producer is actually asking -- what do I fix
first, and what will fixing it cost me -- with three things that are knowable
and one ordering that is honest about being ordinal.

    band        routine, negotiable, counsel_required, blocking. How to sort a
                review queue by consequence without inventing a currency.

    anchors     published statutory figures, quoted with the provision they
                come from. A floor and a ceiling that a statute sets is not a
                prediction of what a claim is worth, and it is the number
                counsel reasons from.

    venue       whether the forum offers anti SLAPP relief with fee shifting,
                which decides whether a weak claim is cheap or expensive to
                defend. Already recorded per state in jurisdictions.yaml.

    cure        what the fix costs, which is a quote rather than a forecast
                about somebody else's behaviour. The one estimate here, and it
                is labelled as one everywhere it renders.

Deterministic throughout. No model call, no research call, no spend. Every
threshold and every figure lives in `policy/exposure.yaml` where a clearance
attorney can read it and argue with it, which is the same choice rubric.yaml
already makes for the adjudicator's post checks.

Nothing downstream reads an assessment as a signal. It does not move a status,
it does not change a tier, and it does not feed the remedy loop. It is the
schedule a person reads after the system has finished deciding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.policy import ExposurePolicy, load_exposure, load_jurisdictions

log = logging.getLogger("truestory.exposure")

#: Where the production is, which dominates what a fix costs. A rename is free
#: in development and a reshoot after picture lock.
PRODUCTION_STAGES = ("development", "pre_production", "production", "post", "delivered")


@dataclass(frozen=True, slots=True)
class Exposure:
    """One finding's exposure picture. Four facts and no forecast."""

    subject_id: str
    band: str
    band_rank: int
    band_means: str
    rule_id: str
    because: str

    #: Published provisions that bear on this finding, quoted with their source.
    anchors: list[dict[str, Any]] = field(default_factory=list)
    #: Order of magnitude cost of the fix. The only estimate in the record.
    cure: dict[str, Any] | None = None
    #: Whether the forum shifts fees on a meritless claim.
    venue: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "band": self.band,
            "band_rank": self.band_rank,
            "band_means": self.band_means,
            "rule_id": self.rule_id,
            "because": self.because,
            "statutory_anchors": self.anchors,
            "cost_to_cure": self.cure,
            "venue": self.venue,
            "disclaimer": (
                "Severity is ordinal, not monetary. Statutory figures are quoted "
                "from the provisions named and are not a prediction of what any "
                "claim is worth. Cost to cure is an order of magnitude estimate. "
                "None of this is legal advice."
            ),
        }


class ExposureModel:
    """Assess findings against the exposure policy."""

    name = "ExposureModel"

    def __init__(
        self,
        policy: ExposurePolicy | None = None,
        *,
        stage: str = "development",
    ) -> None:
        self.policy = policy or load_exposure()
        self.jurisdictions = load_jurisdictions()
        self.stage = stage if stage in PRODUCTION_STAGES else "development"

    # ── one finding ──────────────────────────────────────────────────────────
    def for_element(self, element: ClearableElement) -> Exposure:
        facts = {
            "status": str(element.status),
            "needs_counsel": element.needs_counsel,
            "subject_alive": element.subject_alive,
            "tier": str(element.risk_tier),
            # An element inherits polarity from the claims made about it, which
            # is what makes a person carrying negative claims a different
            # exposure from the same person carrying none.
            "polarity": (
                "negative"
                if any(str(c.polarity).lower() == "negative" for c in element.claims)
                else None
            ),
            "verdict": None,
        }
        element_type = str(element.element_type)
        return self._assess(element.element_id, facts, element_type, element.jurisdictions)

    def for_claim(self, claim: FactualClaim) -> Exposure:
        facts = {
            "status": None,
            "needs_counsel": claim.needs_counsel,
            "subject_alive": claim.subject_alive,
            "tier": str(claim.risk_tier),
            "polarity": str(claim.polarity),
            "verdict": str(claim.verdict) if claim.verdict else None,
        }
        # A claim is an assertion about a person, so it draws the publicity
        # rights anchors rather than the copyright ones.
        return self._assess(claim.claim_id, facts, "REAL_PERSON_DEPICTED", [])

    def _assess(
        self,
        subject_id: str,
        facts: dict[str, Any],
        element_type: str,
        jurisdictions: list[str],
    ) -> Exposure:
        band, rule_id, because = self.policy.band_for(facts)
        anchors = self.policy.anchors_for(element_type, facts)

        # A cure is only worth pricing where something needs curing. Costing a
        # fix for a finding that is already clear is noise in a schedule a
        # producer is reading to decide what to spend money on.
        cure = self.policy.cure_estimate(element_type, self.stage) if band != "routine" else None

        return Exposure(
            subject_id=subject_id,
            band=band,
            band_rank=self.policy.rank(band),
            band_means=self.policy.band_meaning(band),
            rule_id=rule_id,
            because=because,
            anchors=[_anchor_view(a) for a in anchors],
            cure=cure,
            venue=self._venue(jurisdictions),
        )

    def _venue(self, jurisdictions: list[str]) -> dict[str, Any]:
        """Whether any forum in play shifts fees on a meritless claim.

        Any, not all. A production distributed into a state without anti SLAPP
        relief can be sued there, so the absence of protection anywhere in the
        set is the fact that matters rather than its presence somewhere.
        """
        states = [j for j in jurisdictions if j and j.upper() != "US"]
        if not states:
            available = self.jurisdictions.anti_slapp_available(None)
            return {
                "anti_slapp_available": available,
                "note": self.policy.venue_note(available),
                "jurisdictions": [],
            }

        protected = [s for s in states if self.jurisdictions.anti_slapp_available(s)]
        unprotected = [s for s in states if s not in protected]
        available = not unprotected

        return {
            "anti_slapp_available": available,
            "note": self.policy.venue_note(available),
            "jurisdictions": states,
            "with_anti_slapp": protected,
            "without_anti_slapp": unprotected,
        }

    # ── the run ──────────────────────────────────────────────────────────────
    def schedule(
        self, elements: list[ClearableElement], claims: list[FactualClaim]
    ) -> dict[str, Any]:
        """Every finding's exposure, plus the rollup a producer reads first.

        The rollup deliberately reports a cure range and no exposure total.
        Summing statutory floors across findings would produce exactly the
        fabricated aggregate this module exists to avoid: the floors are
        alternatives a claimant may elect, not a bill.
        """
        assessments = [self.for_element(e) for e in elements] + [self.for_claim(c) for c in claims]
        assessments.sort(key=lambda a: (-a.band_rank, a.subject_id))

        by_band: dict[str, int] = {}
        for a in assessments:
            by_band[a.band] = by_band.get(a.band, 0) + 1

        priced = [a.cure for a in assessments if a.cure]
        return {
            "stage": self.stage,
            "by_band": by_band,
            "blocking": by_band.get("blocking", 0),
            "counsel_required": by_band.get("counsel_required", 0),
            "cost_to_cure_usd": {
                "low": sum(int(c["low_usd"]) for c in priced),
                "high": sum(int(c["high_usd"]) for c in priced),
                "priced_findings": len(priced),
                "estimate": True,
                "basis": (
                    "Order of magnitude, at the "
                    f"{self.stage.replace('_', ' ')} stage. Sums the cost of "
                    "fixing every finding that needs fixing. It is not an "
                    "exposure figure and no exposure figure is produced."
                ),
            },
            "assessments": [a.to_dict() for a in assessments],
        }


def _anchor_view(anchor: dict[str, Any]) -> dict[str, Any]:
    """One provision, as it should be read: figures attached to their source.

    `verify` travels with every anchor. The corpus convention from
    jurisdictions.yaml applies here too, and a statutory damages figure that
    reaches a deliverable unchecked is exactly the sort of confident wrong
    number this whole product exists to prevent.
    """
    return {
        "id": anchor.get("id"),
        "provision": anchor.get("provision"),
        "jurisdiction": anchor.get("jurisdiction"),
        "basis": anchor.get("basis"),
        "floor_usd": anchor.get("floor_usd"),
        "ceiling_usd": anchor.get("ceiling_usd"),
        "willful_ceiling_usd": anchor.get("willful_ceiling_usd"),
        "innocent_floor_usd": anchor.get("innocent_floor_usd"),
        "note": " ".join(str(anchor.get("note", "")).split()),
        "verified": str(anchor.get("verify", "required")).lower() != "required",
        "caveat": (
            "Quoted from the provision named, not confirmed against a primary "
            "source in this repository, and not a prediction of what a claim is "
            "worth. Confirm before it appears in a deliverable."
        ),
    }
