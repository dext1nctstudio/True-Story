"""The routing table.

These are the highest value tests in the suite. The router has no model in it
at all, which means its behaviour is fully specifiable, and a silent
misrouting is the failure mode that would do the most damage: a CRITICAL
subject quietly downgraded to a cheap lookup produces a report that looks
complete and is not.
"""

from __future__ import annotations

import pytest

from truestory.models.enums import ElementType, Polarity, Processor, RiskTier, Verdict
from truestory.policy import load_routing


@pytest.fixture(scope="module")
def policy():
    return load_routing()


# =============================================================================
# the escalation cocktail
# =============================================================================


def test_negative_claim_about_living_person_is_critical(policy):
    """The shape of every marquee case in the Litigation Set."""
    decision = policy.match(
        {"kind": "claim", "polarity": "negative", "subject_alive": True}
    )
    assert decision.tier is RiskTier.CRITICAL
    assert decision.processor is Processor.CORE
    assert decision.schema_name == "claim_verification_v1"
    assert decision.post.get("if_not_verified") == "NEEDS_COUNSEL"


def test_negative_claim_about_deceased_person_is_not_critical(policy):
    """The dead do not sue for defamation, and the tier reflects that."""
    decision = policy.match(
        {"kind": "claim", "polarity": "negative", "subject_alive": False}
    )
    assert decision.tier is not RiskTier.CRITICAL


def test_neutral_claim_takes_the_default_claim_rule(policy):
    decision = policy.match({"kind": "claim", "polarity": "neutral"})
    assert decision.tier is RiskTier.HIGH
    assert decision.rule_id == "claim_default"


# =============================================================================
# opinion filtering
# =============================================================================


def test_characterization_is_never_researched(policy):
    """Defamation law protects opinion, so it must cost nothing.

    This is the single most legally motivated rule in the system and also the
    largest budget control on a character driven script.
    """
    decision = policy.match({"kind": "claim", "type": "CHARACTERIZATION"})
    assert decision.tier is RiskTier.NONE
    assert not decision.researched
    assert decision.estimated_cost_usd == 0.0


def test_opinion_is_not_escalated_by_truth_claim_framing(policy):
    """A true story framing must not turn an opinion into a research subject."""
    subject = {"kind": "claim", "type": "CHARACTERIZATION"}
    decision = policy.apply_project_escalations(
        policy.match(subject), subject, {"truth_claim_framing": True}
    )
    assert decision.tier is RiskTier.NONE
    assert decision.estimated_cost_usd == 0.0


# =============================================================================
# the truth claim escalation
# =============================================================================


def test_truth_claim_framing_escalates_person_adjacent_elements(policy):
    """One rule implementing a doctrine two federal courts applied."""
    subject = {"type": str(ElementType.PERSON_NAME_FICTIONAL), "occurrence_count": 1}

    base = policy.match(subject)
    escalated = policy.apply_project_escalations(
        base, subject, {"truth_claim_framing": True}
    )

    assert base.tier is RiskTier.MEDIUM
    assert escalated.tier is RiskTier.HIGH
    assert "truth_claim_framing" in escalated.escalated_by


def test_escalation_deepens_the_processor_too(policy):
    """A higher tier that still used a lite lookup would be escalation in name only."""
    subject = {"type": str(ElementType.PERSON_NAME_FICTIONAL), "occurrence_count": 1}
    escalated = policy.apply_project_escalations(
        policy.match(subject), subject, {"truth_claim_framing": True}
    )
    assert escalated.processor is Processor.BASE


def test_escalation_saturates_at_critical(policy):
    """Already critical stays critical rather than overflowing."""
    subject = {"type": str(ElementType.REAL_PERSON_DEPICTED)}
    escalated = policy.apply_project_escalations(
        policy.match(subject), subject, {"truth_claim_framing": True}
    )
    assert escalated.tier is RiskTier.CRITICAL


def test_non_person_elements_are_not_escalated(policy):
    """The doctrine concerns people. A music cue is not a person."""
    subject = {"type": str(ElementType.MUSIC_CUE)}
    base = policy.match(subject)
    escalated = policy.apply_project_escalations(
        base, subject, {"truth_claim_framing": True}
    )
    assert escalated.tier == base.tier
    assert not escalated.escalated_by


def test_no_escalation_without_framing(policy):
    subject = {"type": str(ElementType.PERSON_NAME_FICTIONAL), "occurrence_count": 1}
    decision = policy.apply_project_escalations(
        policy.match(subject), subject, {"truth_claim_framing": False}
    )
    assert decision.tier is RiskTier.MEDIUM
    assert not decision.escalated_by


# =============================================================================
# element routing
# =============================================================================


@pytest.mark.parametrize(
    ("element_type", "expected_tier"),
    [
        (ElementType.REAL_PERSON_DEPICTED, RiskTier.CRITICAL),
        (ElementType.REAL_PERSON_IDENTIFIABLE, RiskTier.CRITICAL),
        (ElementType.ARTWORK_VISUAL, RiskTier.CRITICAL),
        (ElementType.TATTOO, RiskTier.CRITICAL),
        (ElementType.MUSIC_CUE, RiskTier.HIGH),
        (ElementType.TRADEMARK_LOGO, RiskTier.HIGH),
        (ElementType.REAL_LOCATION, RiskTier.MEDIUM),
        (ElementType.PHONE_NUMBER, RiskTier.LOW),
    ],
)
def test_element_tiers(policy, element_type, expected_tier):
    assert policy.match({"type": str(element_type)}).tier is expected_tier


def test_identifiability_enumerates_matching_people(policy):
    """The Baby Reindeer path. No name required, and FindAll does the work."""
    decision = policy.match({"type": str(ElementType.REAL_PERSON_IDENTIFIABLE)})
    assert decision.schema_name == "identifiability_v1"
    assert "findall_matching_persons" in decision.also


def test_music_cue_always_opens_a_monitor(policy):
    """Licences expire quietly, years after the report is filed."""
    assert "monitor" in policy.match({"type": str(ElementType.MUSIC_CUE)}).also


def test_recurring_fictional_name_is_treated_as_a_lead(policy):
    """A name repeated through a script is a name an audience will search."""
    once = policy.match({"type": str(ElementType.PERSON_NAME_FICTIONAL), "occurrence_count": 1})
    often = policy.match({"type": str(ElementType.PERSON_NAME_FICTIONAL), "occurrence_count": 9})
    assert once.tier is RiskTier.MEDIUM
    assert often.tier is RiskTier.HIGH


def test_deterministic_elements_cost_nothing(policy):
    """Phone numbers and plates are rules, not research."""
    for element_type in (
        ElementType.PHONE_NUMBER,
        ElementType.VEHICLE_PLATE,
        ElementType.URL_HANDLE,
    ):
        decision = policy.match({"type": str(element_type)})
        assert decision.provider == "deterministic_rules"
        assert decision.estimated_cost_usd == 0.0


# =============================================================================
# integrity
# =============================================================================


def test_policy_validates_clean(policy):
    """A malformed rule silently downgrades a subject. CI gates on this."""
    assert policy.validate() == []


def test_every_rule_declaring_research_declares_a_schema(policy):
    """An unschema'd research call returns prose the adjudicator cannot use."""
    for rule in policy.rules:
        if rule.provider not in {"none", "deterministic_rules"}:
            assert rule.schema_name, f"rule {rule.rule_id} researches with no schema"


def test_routing_is_deterministic(policy):
    """Same subject, same answer, every time. Principle P1."""
    subject = {"type": str(ElementType.REAL_PERSON_DEPICTED)}
    decisions = [policy.match(subject) for _ in range(20)]
    assert len({(d.rule_id, d.tier, d.processor) for d in decisions}) == 1


def test_unknown_subject_falls_through_to_defaults(policy):
    """Never returns None. An unrouted subject would be silently dropped."""
    decision = policy.match({"type": "SOMETHING_INVENTED"})
    assert decision.rule_id == "__default__"
    assert decision.tier is RiskTier.MEDIUM


# =============================================================================
# deterministic resolution
# =============================================================================


def test_five_five_five_number_clears_without_research():
    from truestory.agents.router import resolve_deterministic
    from truestory.models.elements import ClearableElement

    element = ClearableElement(
        element_id="el_test",
        element_type=ElementType.PHONE_NUMBER,
        canonical_form="3125550147",
    )
    status, rationale = resolve_deterministic(element)
    assert status == "CLEAR"
    assert "555" in rationale


def test_real_number_does_not_clear():
    from truestory.agents.router import resolve_deterministic
    from truestory.models.elements import ClearableElement

    element = ClearableElement(
        element_id="el_test",
        element_type=ElementType.PHONE_NUMBER,
        canonical_form="3122040147",
    )
    status, _ = resolve_deterministic(element)
    assert status == "NOT_CLEAR"


# =============================================================================
# tier arithmetic
# =============================================================================


def test_tier_escalate_and_degrade_saturate():
    assert RiskTier.CRITICAL.escalate() is RiskTier.CRITICAL
    assert RiskTier.NONE.degrade() is RiskTier.NONE
    assert RiskTier.MEDIUM.escalate() is RiskTier.HIGH
    assert RiskTier.HIGH.degrade() is RiskTier.MEDIUM


def test_verdict_vocabulary_is_closed():
    """Five verdicts, and unsupported is not contradicted."""
    assert {str(v) for v in Verdict} == {
        "VERIFIED",
        "UNSUPPORTED",
        "CONTRADICTED",
        "UNVERIFIABLE",
        "OPINION",
    }


def test_polarity_vocabulary_is_closed():
    assert {str(p) for p in Polarity} == {"positive", "neutral", "negative"}
