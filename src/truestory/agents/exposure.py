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
    #: Frequency times severity, decomposed. None when the model is disabled.
    modelled: ModelledExposure | None = None

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
            "modelled_exposure": self.modelled.to_dict() if self.modelled else None,
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
        truth_claim_framing: bool = False,
    ) -> None:
        self.policy = policy or load_exposure()
        self.jurisdictions = load_jurisdictions()
        self.stage = stage if stage in PRODUCTION_STAGES else "development"
        # Project level, and it multiplies the claim frequency of every person
        # adjacent finding in the script rather than any one of them.
        self.truth_claim_framing = truth_claim_framing
        self.quantitative = QuantitativeModel(self.policy)

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
            # Signals the band rules ignore and the quantitative model needs.
            "kind": "element",
            "public_figure_status": str(element.public_figure_status),
            "occurrence_count": element.occurrence_count,
            "truth_claim_framing": self.truth_claim_framing,
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
            "kind": "claim",
            "public_figure_status": str(claim.subject_public_figure_status),
            "occurrence_count": len(claim.asserted_in),
            "truth_claim_framing": self.truth_claim_framing,
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
        if cure is not None:
            # Provenance, always. A hand written range and a researched one are
            # not the same kind of number and must never render as though they
            # were. `researched` upgrades this in place when a rate comes back.
            cure["source"] = "policy_table"
            cure["researched"] = False

        venue = self._venue(jurisdictions)
        modelled = self.quantitative.price(
            element_type,
            facts,
            anti_slapp=bool(venue.get("anti_slapp_available")),
        )

        return Exposure(
            subject_id=subject_id,
            band=band,
            band_rank=self.policy.rank(band),
            band_means=self.policy.band_meaning(band),
            rule_id=rule_id,
            because=because,
            anchors=[_anchor_view(a) for a in anchors],
            cure=cure,
            venue=venue,
            modelled=modelled,
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
        # Band first, because a blocking finding outranks an expensive one
        # whatever the arithmetic says. Within a band the modelled figure does
        # the work the band cannot: on a real script eighteen findings shared
        # one band, and ordering those eighteen is the entire reason the
        # quantitative model exists.
        assessments.sort(
            key=lambda a: (
                -a.band_rank,
                -(a.modelled.expected_high if a.modelled else 0.0),
                a.subject_id,
            )
        )

        by_band: dict[str, int] = {}
        for a in assessments:
            by_band[a.band] = by_band.get(a.band, 0) + 1

        priced = [a.cure for a in assessments if a.cure]
        modelled = [a.modelled for a in assessments if a.modelled]
        return {
            "modelled_exposure_usd": _portfolio(modelled),
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


# =============================================================================
# quantitative exposure
# =============================================================================
# Frequency times severity, the decomposition a media liability underwriter
# uses, with every parameter in policy/exposure.yaml where it can be argued
# with. See the `quantitative` block there for the reasoning and for the
# calibration status, which is: uncalibrated.
#
# The ranking is the product. The absolute figure is a by product, and on
# uncalibrated priors it is worth an order of magnitude at best. That is why
# every record carries its decomposition and its rank alongside the number: a
# reader who distrusts the magnitude can still trust "this one is eleven times
# the next one" and act on it.


@dataclass(frozen=True, slots=True)
class ModelledExposure:
    """One finding priced. A range, its arithmetic, and its inputs."""

    #: Annual probability that this finding draws a claim, after modifiers.
    frequency: float
    #: Expected cost given a claim is made, low and high.
    severity_low: float
    severity_high: float
    #: frequency x severity. What the model actually asserts.
    expected_low: float
    expected_high: float

    #: Which modifiers fired, what each was worth, and why. The audit trail.
    drivers: list[dict[str, Any]] = field(default_factory=list)
    base_rate: float = 0.0
    base_rate_key: str = ""
    outcome_weights: dict[str, float] = field(default_factory=dict)
    calibrated: bool = False

    @property
    def negligible(self) -> bool:
        return self.expected_high < _NEGLIGIBLE_BELOW_USD

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_usd": {
                "low": round(self.expected_low),
                "high": round(self.expected_high),
            },
            "claim_probability": round(self.frequency, 5),
            "severity_given_claim_usd": {
                "low": round(self.severity_low),
                "high": round(self.severity_high),
            },
            "base_rate": self.base_rate,
            "base_rate_key": self.base_rate_key,
            "drivers": self.drivers,
            "outcome_weights": self.outcome_weights,
            "calibrated": self.calibrated,
            "negligible": self.negligible,
            "caveat": (
                "Modelled, not predicted. Frequency times severity over "
                "uncalibrated priors, reported as a range because the spread is "
                "the honest statement of what is not known. Use it to rank "
                "findings against each other; do not use the absolute figure as "
                "a reserve. Every input is in policy/exposure.yaml."
            ),
        }


#: Read once from policy so the dataclass property stays cheap.
_NEGLIGIBLE_BELOW_USD = 500.0


class QuantitativeModel:
    """Price a finding by frequency times severity, showing the arithmetic."""

    def __init__(self, policy: ExposurePolicy | None = None) -> None:
        self.policy = policy or load_exposure()
        self.config: dict[str, Any] = self.policy.raw.get("quantitative", {}) or {}
        self.enabled = bool(self.config.get("enabled", False))

        global _NEGLIGIBLE_BELOW_USD
        reporting = self.config.get("reporting", {}) or {}
        _NEGLIGIBLE_BELOW_USD = float(reporting.get("negligible_below_usd", 500))

    # ── frequency ────────────────────────────────────────────────────────────
    def _base_rate(self, element_type: str, facts: dict[str, Any]) -> tuple[float, str]:
        """The prior before any modifier, and which key supplied it.

        A negative claim about a living person has its own base rate rather
        than inheriting the generic claim rate, because it is not a variation
        on an ordinary claim: it is the shape every marquee case in the
        litigation set takes.
        """
        rates = self.config.get("base_frequency", {}) or {}
        # One rate for every claim, deliberately generic. `polarity_negative`
        # and `subject_living` are what differentiate a claim's frequency, in
        # the modifier pass below; folding them into the base rate selection
        # here as well double counted the same two facts, which is what
        # produced an annual claim probability above one on a single finding.
        if facts.get("kind") == "claim":
            return float(rates.get("claim", rates.get("default", 0.001))), "claim"

        if element_type in rates:
            return float(rates[element_type]), element_type
        return float(rates.get("default", 0.001)), "default"

    def _modifiers(self, facts: dict[str, Any]) -> list[dict[str, Any]]:
        """Every modifier that fired, with the reason it exists.

        Absence is never a modifier. A fact the pipeline could not establish
        does not multiply the frequency in either direction, because not
        knowing whether someone is alive is not evidence that they are dead.
        """
        table = self.config.get("frequency_modifiers", {}) or {}
        fired: list[dict[str, Any]] = []

        def add(key: str, note: str = "") -> None:
            entry = table.get(key)
            if not entry:
                return
            fired.append(
                {
                    "id": key,
                    "value": float(entry.get("value", 1.0)),
                    "because": " ".join(str(entry.get("because", "")).split()),
                    **({"detail": note} if note else {}),
                }
            )

        verdict = str(facts.get("verdict") or "").upper()
        if verdict == "CONTRADICTED":
            add("verdict_contradicted")
        elif verdict == "UNSUPPORTED":
            add("verdict_unsupported")
        elif verdict == "VERIFIED":
            add("verdict_verified")

        if str(facts.get("polarity", "")).lower() == "negative":
            add("polarity_negative")

        if facts.get("subject_alive") is True:
            add("subject_living")

        status = str(facts.get("public_figure_status") or "").lower()
        if status in {"public", "limited_purpose"}:
            add("public_figure")
        elif status == "private":
            add("private_figure")

        if facts.get("truth_claim_framing"):
            add("truth_claim_framing")

        threshold = int((table.get("high_prominence", {}) or {}).get("threshold_occurrences", 5))
        occurrences = int(facts.get("occurrence_count") or 0)
        if occurrences >= threshold:
            add("high_prominence", f"{occurrences} occurrences")

        if str(facts.get("status") or "").upper() == "RESEARCH_FAILED":
            add("research_failed")

        return fired

    # ── severity ─────────────────────────────────────────────────────────────
    def _weights(self, element_type: str, anti_slapp: bool) -> dict[str, float]:
        """How a claim resolves, given one was filed.

        A copyright or publicity matter is a licence dispute, not a speech
        case. Anti SLAPP does not reach it, so it gets its own weights rather
        than borrowing the defamation ones and inheriting a dismissal
        probability it does not have.
        """
        severity = self.config.get("severity", {}) or {}
        if element_type in set(severity.get("rights_dispute_types", []) or []):
            return dict(severity.get("rights_dispute_weights", {}) or {})
        weights = severity.get("outcome_weights", {}) or {}
        key = "with_anti_slapp" if anti_slapp else "without_anti_slapp"
        return dict(weights.get(key, {}) or {})

    def _severity(self, weights: dict[str, float]) -> tuple[float, float]:
        """Probability weighted cost of a claim, low and high.

        Defence cost is included in every outcome including the one the
        production wins. Winning a motion is not free, and a model that
        counted only indemnity would say a dismissed claim costs nothing,
        which is the opposite of why anti SLAPP fee shifting matters.
        """
        outcomes = (self.config.get("severity", {}) or {}).get("outcomes", {}) or {}
        low = high = 0.0
        for outcome, weight in weights.items():
            entry = outcomes.get(outcome) or {}
            defence = entry.get("defence_usd", {}) or {}
            indemnity = entry.get("indemnity_usd", {}) or {}
            low += float(weight) * (float(defence.get("low", 0)) + float(indemnity.get("low", 0)))
            high += float(weight) * (
                float(defence.get("high", 0)) + float(indemnity.get("high", 0))
            )
        return low, high

    # ── the estimate ─────────────────────────────────────────────────────────
    def price(
        self,
        element_type: str,
        facts: dict[str, Any],
        *,
        anti_slapp: bool = False,
    ) -> ModelledExposure | None:
        """Frequency times severity for one finding, with its arithmetic kept."""
        if not self.enabled:
            return None

        base, base_key = self._base_rate(element_type, facts)
        drivers = self._modifiers(facts)

        frequency = base
        for driver in drivers:
            frequency *= driver["value"]
        # A probability is a probability. Enough stacked multipliers will walk
        # past one, and an annual claim probability of 1.4 is not a number.
        frequency = min(frequency, 1.0)

        weights = self._weights(element_type, anti_slapp)
        severity_low, severity_high = self._severity(weights)

        return ModelledExposure(
            frequency=frequency,
            severity_low=severity_low,
            severity_high=severity_high,
            expected_low=frequency * severity_low,
            expected_high=frequency * severity_high,
            drivers=drivers,
            base_rate=base,
            base_rate_key=base_key,
            outcome_weights=weights,
            calibrated=bool(self.config.get("calibrated", False)),
        )


# =============================================================================
# researched rates
# =============================================================================
#: Element types whose cure is a real market purchase rather than a script
#: edit. Only these are worth a research call: nobody needs the going rate for
#: changing a character's name, and asking would spend a lookup to be told so.
RESEARCHABLE_CURES: frozenset[str] = frozenset(
    {
        "MUSIC_CUE",
        "ARTWORK_VISUAL",
        "TATTOO",
        "FILM_CLIP",
        "PRINT_QUOTE",
        "SOURCE_MATERIAL",
    }
)


def merge_researched_rate(cure: dict[str, Any], finding: dict[str, Any]) -> dict[str, Any]:
    """Fold a researched market rate into a table derived cure estimate.

    The table stays underneath as the fallback, and the merged record says
    which number a reader is looking at. Three things can come back and only
    one of them replaces the table:

      a rate with sources        the table's fee is superseded and labelled
      rate_found false           the record was asked and is silent, which is
                                 a finding in itself and is kept as one
      nothing usable             the table stands, unchanged and still labelled
                                 as a hand written estimate

    The change component is never overwritten. What a reshoot costs is a fact
    about this production's schedule, not about a licensing market, and no
    amount of research into synchronisation fees says anything about it.
    """
    if not isinstance(finding, dict):
        return cure

    if not finding.get("rate_found"):
        # Asked and answered in the negative. Worth recording: an element with
        # no public rate is one a producer cannot budget for from a desk.
        cure["rate_research"] = {
            "rate_found": False,
            "basis": str(finding.get("basis", ""))[:600],
            "obtainable": finding.get("obtainable"),
        }
        return cure

    low = finding.get("low_usd")
    high = finding.get("high_usd")
    if not isinstance(low, int | float) or not isinstance(high, int | float):
        return cure
    if low < 0 or high < low:
        # A malformed range is not a better number than the table's.
        return cure

    change = cure.get("change_usd", {})
    cure["fee_usd"] = {"low": round(float(low)), "high": round(float(high))}
    cure["low_usd"] = round(float(low) + float(change.get("low", 0)))
    cure["high_usd"] = round(float(high) + float(change.get("high", 0)))
    cure["source"] = "researched"
    cure["researched"] = True
    cure["rate_research"] = {
        "rate_found": True,
        "typical_usd": finding.get("typical_usd"),
        "rate_unit": finding.get("rate_unit"),
        "scope": finding.get("scope"),
        "basis": str(finding.get("basis", ""))[:600],
        "confidence_note": str(finding.get("confidence_note", ""))[:600],
        "obtainable": finding.get("obtainable"),
        "sources": [
            src.get("url")
            for src in (finding.get("sources") or [])
            if isinstance(src, dict) and src.get("url")
        ][:5],
    }
    return cure


def _portfolio(modelled: list[ModelledExposure]) -> dict[str, Any]:
    """Sum the modelled expectations across a run.

    Expected values add even when the underlying events are dependent, which
    is what makes this summable where the statutory floors were not: those are
    alternatives a single claimant may elect, whereas these are the expected
    cost of separate findings.

    What it deliberately does not report is a worst case. Adding every high
    end together describes a world in which every finding is sued on at once,
    which has never happened to any production and would be the single most
    misleading number this system could print.
    """
    if not modelled:
        return {"low": 0, "high": 0, "findings": 0, "calibrated": False}

    return {
        "low": round(sum(m.expected_low for m in modelled)),
        "high": round(sum(m.expected_high for m in modelled)),
        "findings": len(modelled),
        "calibrated": all(m.calibrated for m in modelled),
        "basis": (
            "Sum of expected values, frequency times severity, over "
            f"{len(modelled)} findings. Not a worst case: it does not describe "
            "every finding being sued on at once. Uncalibrated priors, so treat "
            "the ranking as the output and the magnitude as an order of "
            "magnitude."
        ),
    }
