"""The deterministic post checks, exercised directly.

The Adjudicator's model call is what produces a verdict; these rules are what
decide whether the system is allowed to keep it. They are the difference
between a research tool and something an underwriter can rely on, so they are
tested against the model's output rather than through it.
"""

from __future__ import annotations

import pytest

from truestory.agents.adjudicator import Adjudicator
from truestory.models.claims import FactualClaim
from truestory.models.enums import ClaimType, Polarity, RiskTier, Verdict
from truestory.models.evidence import Citation, Evidence


def _claim(tier: RiskTier = RiskTier.HIGH, alive: bool | None = False) -> FactualClaim:
    claim = FactualClaim(
        claim_id="cl_1",
        subject_element_id="el_1",
        subject_name="Margaret Holloway",
        claim_text="She was refused a licence in 1931.",
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
        risk_tier=tier,
    )
    claim.subject_alive = alive
    return claim


def _evidence(urls: list[str], finding: dict | None = None) -> Evidence:
    return Evidence(
        evidence_id="ev_1",
        subject_id="cl_1",
        question="q",
        finding=finding or {},
        citations=[Citation.classified(u, excerpt="passage") for u in urls],
        reasoning="",
        confidence=0.95,
        provider="parallel_task:core",
        schema_version="claim_verification_v1",
    )


@pytest.fixture
def adjudicator() -> Adjudicator:
    return Adjudicator()


def test_contradiction_on_a_recognised_record_stands(adjudicator):
    """The headline output has to be reachable, or the product does nothing."""
    evidence = [
        _evidence(
            [
                "https://www.courtlistener.com/docket/1",
                "https://www.bbc.co.uk/news/1",
            ],
            finding={"verdict": "contradicted"},
        )
    ]
    verdict, confidence, escalation = adjudicator._post_check_claim(
        _claim(), Verdict.CONTRADICTED, 0.93, evidence, False
    )
    assert verdict is Verdict.CONTRADICTED
    assert confidence > 0.7
    # A contradiction about a dead subject is not a mandatory escalation, but
    # nothing here should have downgraded the verdict itself.
    assert escalation is None or "primary" not in escalation


def test_contradiction_on_an_unrecognised_host_is_downgraded(adjudicator):
    evidence = [
        _evidence(
            ["https://some-blog.example.xyz/a", "https://another.example.test/b"],
            finding={"verdict": "contradicted"},
        )
    ]
    verdict, _, escalation = adjudicator._post_check_claim(
        _claim(), Verdict.CONTRADICTED, 0.93, evidence, False
    )
    assert verdict is Verdict.UNSUPPORTED
    assert escalation and "primary" in escalation.lower()


def test_forum_sources_cannot_carry_a_verdict_about_a_person(adjudicator):
    evidence = [_evidence(["https://www.reddit.com/r/x/1"], finding={"verdict": "supported"})]
    verdict, confidence, escalation = adjudicator._post_check_claim(
        _claim(), Verdict.VERIFIED, 0.95, evidence, False
    )
    assert verdict is Verdict.UNSUPPORTED
    assert confidence <= 0.4
    assert escalation and "user generated" in escalation.lower()


def test_a_single_domain_does_not_corroborate_a_high_tier_claim(adjudicator):
    evidence = [
        _evidence(
            ["https://www.nytimes.com/a", "https://www.nytimes.com/b"],
            finding={"verdict": "supported"},
        )
    ]
    _, _, escalation = adjudicator._post_check_claim(
        _claim(tier=RiskTier.HIGH), Verdict.VERIFIED, 0.95, evidence, False
    )
    assert escalation and "independent" in escalation.lower()


def test_confidence_may_not_exceed_what_corroboration_supports(adjudicator):
    thin = [_evidence(["https://www.imdb.com/name/nm1"], finding={"verdict": "supported"})]
    _, confidence, _ = adjudicator._post_check_claim(_claim(), Verdict.VERIFIED, 0.99, thin, False)
    assert confidence < 0.7


def test_the_model_disagreeing_with_its_own_research_escalates(adjudicator):
    evidence = [
        _evidence(
            [
                "https://www.courtlistener.com/docket/1",
                "https://www.bbc.co.uk/news/1",
            ],
            finding={"verdict": "contradicted"},
        )
    ]
    _, confidence, escalation = adjudicator._post_check_claim(
        _claim(), Verdict.VERIFIED, 0.95, evidence, False
    )
    assert escalation and "research payload" in escalation
    assert confidence <= 0.55


def test_a_contradicted_living_subject_always_reaches_a_human(adjudicator):
    """The claim that gets filed. No confidence score is allowed to skip this."""
    evidence = [
        _evidence(
            ["https://www.courtlistener.com/docket/1", "https://apnews.com/article/1"],
            finding={"verdict": "contradicted"},
        )
    ]
    _, _, escalation = adjudicator._post_check_claim(
        _claim(alive=True), Verdict.CONTRADICTED, 0.99, evidence, False
    )
    assert escalation and "living person" in escalation
