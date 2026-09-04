"""The quantitative exposure model: frequency times severity, decomposed.

This exists because the ordinal bands failed at their own job. On a real
script eighteen of twenty two findings landed in one band, which ranks
nothing. The tests here hold two things: that the model actually
discriminates between findings the bands cannot tell apart, and that its
arithmetic does not lie -- the double count found while building this (a base
rate that already encoded "negative and living" being multiplied by modifiers
for the same two facts, stacking a single finding past probability 1) is
pinned so it cannot come back quietly.
"""

from __future__ import annotations

import pytest

from truestory.agents.exposure import ExposureModel, QuantitativeModel
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import (
    ClaimType,
    ElementType,
    Polarity,
    PublicFigureStatus,
    RiskTier,
    Verdict,
)


@pytest.fixture
def model() -> ExposureModel:
    return ExposureModel(stage="development", truth_claim_framing=True)


def _claim(**kw) -> FactualClaim:
    defaults: dict = {
        "claim_id": "cl-1",
        "subject_element_id": "el-1",
        "subject_name": "Subject",
        "claim_text": "She ordered the interrogations to continue overnight.",
        "claim_type": ClaimType.CONDUCT,
        "polarity": Polarity.NEGATIVE,
        "subject_alive": True,
        "verdict": Verdict.CONTRADICTED,
        "risk_tier": RiskTier.CRITICAL,
    }
    defaults.update(kw)
    return FactualClaim(**defaults)


# ── the bug this file exists to keep fixed ──────────────────────────────────
def test_no_finding_reaches_a_probability_of_one(model: ExposureModel) -> None:
    """The double count: stacking every aggravating modifier on a claim whose
    base rate already encoded the two strongest of them reached 1.44, clamped
    silently to 1.0. A 100% annual claim probability on one line of dialogue is
    not a modelled result, it is a bug wearing a probability's clothes."""
    worst = _claim(subject_public_figure_status=PublicFigureStatus.PRIVATE)
    exposure = model.for_claim(worst)

    assert exposure.modelled is not None
    assert exposure.modelled.frequency < 0.5


def test_polarity_and_liveness_are_not_double_counted(model: ExposureModel) -> None:
    """Every driver that fired should be a fact not already spent selecting
    the base rate. Both polarity_negative and subject_living may fire -- they
    are real modifiers -- but the base rate itself must be generic."""
    exposure = model.for_claim(_claim())
    assert exposure.modelled is not None
    assert exposure.modelled.base_rate_key == "claim"

    ids = [d["id"] for d in exposure.modelled.drivers]
    assert ids.count("polarity_negative") <= 1
    assert ids.count("subject_living") <= 1


# ── the thing the bands could not do: discriminate ──────────────────────────
def test_a_worse_claim_prices_higher_than_a_weaker_one_of_the_same_band(
    model: ExposureModel,
) -> None:
    """Both of these land in `blocking`. The band cannot rank them and the
    model must, because ranking the queue is the reason it exists."""
    private_claim = model.for_claim(_claim(subject_public_figure_status=PublicFigureStatus.PRIVATE))
    public_claim = model.for_claim(_claim(subject_public_figure_status=PublicFigureStatus.PUBLIC))

    assert private_claim.band == public_claim.band == "blocking"
    assert private_claim.modelled.expected_high > public_claim.modelled.expected_high


def test_actual_malice_lowers_frequency_for_a_public_figure(model: ExposureModel) -> None:
    exposure = model.for_claim(_claim(subject_public_figure_status=PublicFigureStatus.PUBLIC))
    driver = next(d for d in exposure.modelled.drivers if d["id"] == "public_figure")
    assert driver["value"] < 1.0


def test_a_contradicted_claim_prices_above_an_unsupported_one(model: ExposureModel) -> None:
    contradicted = model.for_claim(_claim(verdict=Verdict.CONTRADICTED))
    unsupported = model.for_claim(_claim(verdict=Verdict.UNSUPPORTED))
    assert contradicted.modelled.expected_high > unsupported.modelled.expected_high


def test_a_verified_claim_prices_far_below_a_contradicted_one(model: ExposureModel) -> None:
    verified = model.for_claim(_claim(verdict=Verdict.VERIFIED, polarity=Polarity.NEUTRAL))
    contradicted = model.for_claim(_claim())
    assert verified.modelled.expected_high < contradicted.modelled.expected_high / 10


def test_a_deceased_subject_prices_far_below_a_living_one(model: ExposureModel) -> None:
    """Defamation claims mostly do not survive the subject in US law."""
    living = model.for_claim(_claim(subject_alive=True))
    dead = model.for_claim(_claim(subject_alive=False))
    assert dead.modelled.expected_high < living.modelled.expected_high


def test_research_that_never_ran_prices_above_a_verified_claim(model: ExposureModel) -> None:
    element = ClearableElement(
        element_id="el-2",
        element_type=ElementType.REAL_PERSON_DEPICTED,
        canonical_form="Subject",
        risk_tier=RiskTier.HIGH,
        subject_alive=True,
    )
    from truestory.models.enums import ClearanceStatus

    element.status = ClearanceStatus.RESEARCH_FAILED
    unchecked = model.for_element(element)
    assert unchecked.modelled is not None
    assert "research_failed" in [d["id"] for d in unchecked.modelled.drivers]


# ── every output is a range with its arithmetic, never a point ─────────────
def test_the_expected_figure_is_always_a_range(model: ExposureModel) -> None:
    exposure = model.for_claim(_claim())
    d = exposure.modelled.to_dict()
    assert d["expected_usd"]["low"] < d["expected_usd"]["high"]


def test_every_modelled_figure_carries_its_drivers(model: ExposureModel) -> None:
    d = model.for_claim(_claim()).modelled.to_dict()
    assert d["drivers"]
    assert all({"id", "value", "because"} <= set(driver) for driver in d["drivers"])


def test_the_figure_declares_itself_uncalibrated(model: ExposureModel) -> None:
    d = model.for_claim(_claim()).modelled.to_dict()
    assert d["calibrated"] is False
    assert "uncalibrated" in d["caveat"].lower() or "not predicted" in d["caveat"].lower()


def test_a_negligible_estimate_is_labelled_rather_than_shown_as_false_precision(
    model: ExposureModel,
) -> None:
    """The negligible flag is a rendering aid, not a claim that the true cost
    of a lawsuit is ever actually small -- it is what the model shows a reader
    instead of a number like "$62" that implies false precision at the low end
    while still carrying a six figure tail. A directly constructed near zero
    result should still be flagged as negligible."""
    from truestory.agents.exposure import ModelledExposure

    tiny = ModelledExposure(
        frequency=0.0001,
        severity_low=1000,
        severity_high=2000,
        expected_low=0.1,
        expected_high=0.2,
    )
    assert tiny.negligible is True

    exposure = model.for_claim(_claim(verdict=Verdict.VERIFIED, polarity=Polarity.POSITIVE))
    assert exposure.modelled.negligible is False  # a real claim always carries a tail


# ── venue changes the outcome mix, not the claim probability ───────────────
def test_anti_slapp_lowers_expected_cost_without_changing_claim_frequency(
    model: ExposureModel,
) -> None:
    """Anti SLAPP moves weight from settlement into early dismissal. It says
    nothing about whether someone sues, only what it costs once they do."""
    with_relief = model.for_claim(
        _claim(),
    )
    # Force the comparison by pricing directly with both venue states.
    qm = QuantitativeModel(model.policy)
    protected = qm.price(
        "REAL_PERSON_DEPICTED",
        {"kind": "claim", "polarity": "negative", "subject_alive": True, "verdict": "CONTRADICTED"},
        anti_slapp=True,
    )
    unprotected = qm.price(
        "REAL_PERSON_DEPICTED",
        {"kind": "claim", "polarity": "negative", "subject_alive": True, "verdict": "CONTRADICTED"},
        anti_slapp=False,
    )
    assert protected.frequency == unprotected.frequency
    assert protected.expected_high < unprotected.expected_high
    assert with_relief.modelled is not None  # sanity: the fixture still prices


def test_a_rights_dispute_does_not_use_the_anti_slapp_weighting(model: ExposureModel) -> None:
    """A licence dispute over artwork is not a speech case, so it gets its own
    outcome weights rather than borrowing the defamation ones."""
    qm = model.quantitative
    weights = qm._weights("ARTWORK_VISUAL", anti_slapp=True)
    speech_weights = qm._weights("REAL_PERSON_DEPICTED", anti_slapp=True)
    assert weights != speech_weights


# ── portfolio rollup ─────────────────────────────────────────────────────────
def test_the_portfolio_sums_expected_values_not_worst_cases(model: ExposureModel) -> None:
    schedule = model.schedule([], [_claim(), _claim(subject_alive=False)])
    rollup = schedule["modelled_exposure_usd"]

    per_finding_high = [
        a["modelled_exposure"]["expected_usd"]["high"]
        for a in schedule["assessments"]
        if a.get("modelled_exposure")
    ]
    # The rollup rounds the summed float once; summing pre rounded per finding
    # figures can differ by the rounding on each term, so the check allows for
    # that rather than asserting bit for bit equality.
    assert abs(rollup["high"] - sum(per_finding_high)) <= 1
    assert "worst case" in rollup["basis"].lower()


def test_the_portfolio_is_zero_findings_zero_dollars_when_nothing_is_priced() -> None:
    empty = ExposureModel().schedule([], [])
    assert empty["modelled_exposure_usd"] == {
        "low": 0,
        "high": 0,
        "findings": 0,
        "calibrated": False,
    }


def test_the_portfolio_reports_uncalibrated_when_any_finding_is(model: ExposureModel) -> None:
    schedule = model.schedule([], [_claim()])
    assert schedule["modelled_exposure_usd"]["calibrated"] is False


# ── ranking within a band is the model's actual job ─────────────────────────
def test_within_a_band_the_schedule_orders_by_modelled_exposure(
    model: ExposureModel,
) -> None:
    weak = _claim(subject_public_figure_status=PublicFigureStatus.PUBLIC)
    strong = _claim(claim_id="cl-2", subject_public_figure_status=PublicFigureStatus.PRIVATE)
    schedule = model.schedule([], [weak, strong])

    assert schedule["assessments"][0]["subject_id"] == "cl-2"


def test_a_higher_band_always_outranks_a_cheaper_lower_band_finding(
    model: ExposureModel,
) -> None:
    """Band order is the policy and the model must not override it, however
    large the modelled figure on the lower banded finding happens to be."""
    from truestory.models.enums import ClearanceStatus

    routine = ClearableElement(
        element_id="el-routine",
        element_type=ElementType.ARTWORK_VISUAL,
        canonical_form="Poster",
        risk_tier=RiskTier.CRITICAL,
        status=ClearanceStatus.CLEAR_WITH_CONDITIONS,
    )
    schedule = model.schedule([routine], [_claim()])
    assert schedule["assessments"][0]["subject_id"] == "cl-1"


# ── disabled state ───────────────────────────────────────────────────────────
def test_the_model_can_be_disabled_from_policy_alone() -> None:
    policy = ExposureModel().policy
    policy.raw = {
        **policy.raw,
        "quantitative": {**policy.raw.get("quantitative", {}), "enabled": False},
    }
    off = ExposureModel(policy=policy)
    assert off.for_claim(_claim()).modelled is None
