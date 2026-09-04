"""The exposure model.

The thing being guarded here is a temptation rather than a bug. The obvious
feature is a predicted damages figure per finding, it would be the most
requested number in the product, and it cannot be built honestly from a public
record made almost entirely of confidential settlements. Several tests below
exist only to keep it from creeping back in.
"""

from __future__ import annotations

import pytest

from truestory.agents.exposure import ExposureModel
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import (
    ClaimType,
    ClearanceStatus,
    ElementType,
    Polarity,
    RiskTier,
    Verdict,
)
from truestory.policy import load_exposure


@pytest.fixture
def model() -> ExposureModel:
    return ExposureModel(stage="development")


def _element(
    element_type: ElementType = ElementType.TRADEMARK_LOGO,
    *,
    status: ClearanceStatus = ClearanceStatus.NOT_CLEAR,
    needs_counsel: bool = False,
    alive: bool | None = None,
    jurisdictions: list[str] | None = None,
) -> ClearableElement:
    return ClearableElement(
        element_id="el-1",
        element_type=element_type,
        canonical_form="Subject",
        risk_tier=RiskTier.HIGH,
        status=status,
        needs_counsel=needs_counsel,
        subject_alive=alive,
        jurisdictions=jurisdictions or [],
    )


def _claim(
    *,
    verdict: Verdict = Verdict.CONTRADICTED,
    polarity: Polarity = Polarity.NEGATIVE,
    alive: bool | None = True,
) -> FactualClaim:
    return FactualClaim(
        claim_id="cl-1",
        subject_element_id="el-1",
        subject_name="Subject",
        claim_text="She ordered the interrogations to continue overnight.",
        claim_type=ClaimType.CONDUCT,
        polarity=polarity,
        subject_alive=alive,
        verdict=verdict,
    )


# ── bands ───────────────────────────────────────────────────────────────────
def test_a_false_disparaging_claim_about_the_living_is_blocking(model: ExposureModel) -> None:
    """The shape of every marquee case in the litigation set."""
    exposure = model.for_claim(_claim())
    assert exposure.band == "blocking"
    assert exposure.rule_id == "contradicted_negative_living"


def test_an_unsupported_negative_claim_needs_counsel_not_a_block(model: ExposureModel) -> None:
    """Not provably false, and therefore not defensible either."""
    exposure = model.for_claim(_claim(verdict=Verdict.UNSUPPORTED))
    assert exposure.band == "counsel_required"


def test_a_contradicted_claim_about_the_dead_does_not_block(model: ExposureModel) -> None:
    exposure = model.for_claim(_claim(alive=False))
    assert exposure.band == "counsel_required"


def test_research_that_never_ran_outranks_a_finding_that_was_checked(
    model: ExposureModel,
) -> None:
    """An unchecked record must never queue below a checked one."""
    unchecked = model.for_element(_element(status=ClearanceStatus.RESEARCH_FAILED))
    licensed = model.for_element(_element(status=ClearanceStatus.NEEDS_LICENSE))
    assert unchecked.band_rank > licensed.band_rank


def test_a_licence_is_negotiable_rather_than_a_legal_problem(model: ExposureModel) -> None:
    exposure = model.for_element(_element(status=ClearanceStatus.NEEDS_LICENSE))
    assert exposure.band == "negotiable"


def test_conditions_attached_is_routine_because_that_is_the_correct_answer(
    model: ExposureModel,
) -> None:
    """Protected expressive use. Conditions are art department notes."""
    exposure = model.for_element(_element(status=ClearanceStatus.CLEAR_WITH_CONDITIONS))
    assert exposure.band == "routine"


def test_every_band_states_what_it_means_for_a_producer(model: ExposureModel) -> None:
    assert model.for_claim(_claim()).band_means


# ── statutory anchors ───────────────────────────────────────────────────────
def test_copyright_figures_are_quoted_with_their_provision(model: ExposureModel) -> None:
    exposure = model.for_element(_element(ElementType.ARTWORK_VISUAL))
    anchor = next(a for a in exposure.anchors if a["id"] == "copyright_statutory_damages")

    assert anchor["provision"] == "17 U.S.C. 504(c)"
    assert anchor["floor_usd"] == 750
    assert anchor["willful_ceiling_usd"] == 150000


def test_the_living_persons_statute_is_not_quoted_for_a_deceased_subject(
    model: ExposureModel,
) -> None:
    """Attaching the wrong statute is worse than attaching none."""
    dead = model.for_element(_element(ElementType.REAL_PERSON_DEPICTED, alive=False))
    ids = {a["id"] for a in dead.anchors}

    assert "publicity_rights_california" not in ids
    assert "publicity_rights_california_deceased" in ids


def test_an_unknown_mortality_draws_neither_publicity_statute(model: ExposureModel) -> None:
    """Not knowing is not a match. It is not knowing."""
    unknown = model.for_element(_element(ElementType.REAL_PERSON_DEPICTED, alive=None))
    ids = {a["id"] for a in unknown.anchors}

    assert "publicity_rights_california" not in ids
    assert "publicity_rights_california_deceased" not in ids


def test_no_counterfeiting_ceiling_is_quoted_beside_a_brand(model: ExposureModel) -> None:
    """The Lanham Act's statutory damages are for counterfeiting.

    A production use is not counterfeiting, and printing a two million dollar
    ceiling next to a coffee cup would be alarming and wrong.
    """
    exposure = model.for_element(_element(ElementType.BRAND_PRODUCT))
    anchor = next(a for a in exposure.anchors if a["id"] == "lanham_act_remedies")

    assert anchor["floor_usd"] is None
    assert anchor["ceiling_usd"] is None


def test_every_anchor_carries_the_unverified_caveat(model: ExposureModel) -> None:
    for element_type in (ElementType.ARTWORK_VISUAL, ElementType.MUSIC_CUE):
        for anchor in model.for_element(_element(element_type)).anchors:
            assert anchor["verified"] is False
            assert "not confirmed against a primary source" in anchor["caveat"]


# ── cost to cure ────────────────────────────────────────────────────────────
def test_a_licence_fee_does_not_multiply_with_the_production_stage() -> None:
    """The first version of this table multiplied the fee and priced a song at
    three million dollars. A synchronisation licence costs what it costs."""
    development = ExposureModel(stage="development").for_element(_element(ElementType.MUSIC_CUE))
    post = ExposureModel(stage="post").for_element(_element(ElementType.MUSIC_CUE))

    assert development.cure is not None and post.cure is not None
    assert development.cure["fee_usd"] == post.cure["fee_usd"]


def test_the_cost_of_changing_finished_material_does_multiply() -> None:
    development = ExposureModel(stage="development").for_element(_element(ElementType.MUSIC_CUE))
    post = ExposureModel(stage="post").for_element(_element(ElementType.MUSIC_CUE))

    assert post.cure["change_usd"]["high"] > development.cure["change_usd"]["high"]


def test_fixing_a_name_is_free_in_development_and_not_in_post() -> None:
    """The entire argument for clearing early, as a number."""
    development = ExposureModel(stage="development").for_element(
        _element(ElementType.PERSON_NAME_FICTIONAL)
    )
    post = ExposureModel(stage="post").for_element(_element(ElementType.PERSON_NAME_FICTIONAL))

    assert development.cure["high_usd"] < post.cure["high_usd"]


def test_a_depicted_person_prices_as_a_rewrite_not_as_life_rights() -> None:
    """Life rights are a commercial choice about a principal subject.

    Pricing them as the cure for every named person produced an eight million
    dollar estimate on a script with eighteen of them: alarming, and meaningless.
    """
    exposure = ExposureModel().for_element(_element(ElementType.REAL_PERSON_DEPICTED))
    assert exposure.cure["remedy_class"] == "rewrite"


def test_a_routine_finding_is_not_priced(model: ExposureModel) -> None:
    """Costing a fix for something that needs no fixing is noise in a budget."""
    exposure = model.for_element(_element(status=ClearanceStatus.CLEAR_WITH_CONDITIONS))
    assert exposure.cure is None


def test_a_cure_always_declares_itself_an_estimate(model: ExposureModel) -> None:
    assert model.for_element(_element(ElementType.MUSIC_CUE)).cure["estimate"] is True


# ── venue ───────────────────────────────────────────────────────────────────
def test_one_unprotected_forum_removes_the_anti_slapp_benefit(model: ExposureModel) -> None:
    """A production distributed into a state without relief can be sued there.

    PA is deliberately not in jurisdictions.yaml's state table, so it falls
    through to the default of no relief. That fallthrough is the common case:
    the table lists nine states and there are fifty.
    """
    both = model.for_element(_element(jurisdictions=["CA", "PA"]))
    assert both.venue["anti_slapp_available"] is False
    assert "PA" in both.venue["without_anti_slapp"]
    assert "CA" in both.venue["with_anti_slapp"]


def test_a_forum_that_shifts_fees_is_reported_as_such(model: ExposureModel) -> None:
    exposure = model.for_element(_element(jurisdictions=["CA"]))
    assert exposure.venue["anti_slapp_available"] is True
    assert "anti slapp" in exposure.venue["note"].lower()


# ── the rollup, and what it refuses to say ──────────────────────────────────
def test_the_schedule_sorts_the_worst_finding_first(model: ExposureModel) -> None:
    schedule = model.schedule([_element(status=ClearanceStatus.CLEAR_WITH_CONDITIONS)], [_claim()])
    assert schedule["assessments"][0]["band"] == "blocking"


def test_statutory_floors_are_never_summed_into_the_exposure_total(
    model: ExposureModel,
) -> None:
    """The guardrail that survived the model's addition.

    A quantitative exposure total is now produced deliberately -- see
    test_exposure_quantitative.py -- but it must never be built by summing
    statutory floors. Those are alternatives a claimant may elect, not a bill,
    and the modelled total is frequency times severity, not a floor sum.
    """
    schedule = model.schedule([_element(ElementType.ARTWORK_VISUAL)], [_claim()])

    anchors = schedule["assessments"][0]["statutory_anchors"]
    floor_sum = sum(a["floor_usd"] for a in anchors if a.get("floor_usd"))
    modelled_low = schedule["modelled_exposure_usd"]["low"]

    assert floor_sum > 0  # the anchor exists and would be a temptation
    assert modelled_low != floor_sum
    assert "cost_to_cure_usd" in schedule
    assert "modelled_exposure_usd" in schedule


def test_the_rollup_says_what_its_number_is_and_is_not(model: ExposureModel) -> None:
    schedule = model.schedule([_element(ElementType.MUSIC_CUE)], [])
    basis = schedule["cost_to_cure_usd"]["basis"]

    assert schedule["cost_to_cure_usd"]["estimate"] is True
    assert "not an exposure figure" in basis


def test_every_assessment_carries_the_disclaimer(model: ExposureModel) -> None:
    for assessment in model.schedule([_element()], [_claim()])["assessments"]:
        assert "ordinal, not monetary" in assessment["disclaimer"]


# ── policy is data ──────────────────────────────────────────────────────────
def test_the_bands_and_figures_live_in_yaml_where_an_attorney_can_change_them() -> None:
    policy = load_exposure()
    assert set(policy.bands) == {"routine", "negotiable", "counsel_required", "blocking"}
    assert policy.band_rules[0]["id"] == "research_never_ran"


def test_an_unknown_production_stage_falls_back_rather_than_failing() -> None:
    assert ExposureModel(stage="nonsense").stage == "development"
