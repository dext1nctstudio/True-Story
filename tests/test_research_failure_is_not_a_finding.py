"""A failure to research must never read as a finding about the record.

This is the highest severity class of bug this system can have, and it shipped.

A live run against a Parallel account with no credit returned
``HTTP 402: Insufficient credit in account`` to every single request. Each
failure was caught per subject, and each was rendered to the reviewer as:

    UNSUPPORTED, 0% confidence
    "No record found either way. This is not a finding of falsity."
    "Research returned no citable source. The system declines to make this
     call rather than guessing."

Nothing declined anything. Nothing was asked. Every one of those sentences is
what a *correctly working* run says about a subject the public record genuinely
does not cover, so a clearance report produced by a drained account is
indistinguishable from a clean one. A production could have taken that to an
insurer.

The element path had guarded this since the beginning. The claim path never
had. These tests hold both, plus the layers underneath: a provider that reports
an account level fault leaves service instead of failing two hundred subjects
one at a time, and the run says so on the front page.
"""

from __future__ import annotations

import pytest

from truestory.models.claims import FactualClaim
from truestory.models.enums import ClaimType, Polarity, RiskTier, Verdict
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    ProviderError,
    ProviderOutOfService,
    ProviderUnavailable,
    RateLimited,
)


def _claim(text: str = "Dhoni was born in Ranchi.") -> FactualClaim:
    return FactualClaim(
        claim_id="c1",
        subject_element_id="e1",
        subject_name="MS Dhoni",
        claim_text=text,
        claim_type=ClaimType.STATUS,
        polarity=Polarity.NEUTRAL,
        risk_tier=RiskTier.HIGH,
    )


def _failed(error: str) -> Evidence:
    return Evidence.failed("c1", "q", "parallel_task:base", error)


def _usable() -> Evidence:
    return Evidence(
        evidence_id="ev1",
        subject_id="c1",
        question="q",
        finding={"verdict": "VERIFIED"},
        citations=[Citation(url="https://example.org/a", title="A", excerpt="x" * 50)],
        reasoning="the record supports it",
        confidence=0.9,
        provider="parallel_task:base",
        schema_version="claim_verification_v1",
    )


# =============================================================================
# the failure classification, at the provider boundary
# =============================================================================

#: Every status a research API returns that means "your account", not "your
#: question". Each answers identically for the next subject, so each must take
#: the provider out of service rather than becoming one subject's result.
ACCOUNT_LEVEL_STATUSES = [
    (402, "Insufficient credit in account, please check your plan and billing details"),
    (401, "Invalid API key"),
    (403, "Forbidden: this key is not permitted to call the Task API"),
]


@pytest.mark.parametrize(("status", "message"), ACCOUNT_LEVEL_STATUSES)
def test_account_level_failures_are_out_of_service(status, message):
    """402 is the one that shipped. 401 and 403 fail exactly the same way."""
    exc = ProviderOutOfService("parallel_task", f"HTTP {status}: {message}")
    assert isinstance(exc, ProviderUnavailable), "must trigger the fallback path"
    assert isinstance(exc, ProviderError)
    assert str(status) in str(exc)


def test_out_of_service_is_distinguishable_from_rate_limiting():
    """Rate limiting is transient and retryable. A drained account is neither.

    Retrying a 402 with backoff spends the whole run discovering the same fact
    two hundred times.
    """
    limited = RateLimited("parallel_task", 30.0)
    drained = ProviderOutOfService("parallel_task", "HTTP 402: Insufficient credit")
    assert limited.retryable is True
    assert not isinstance(limited, ProviderUnavailable)
    assert isinstance(drained, ProviderUnavailable)


def test_a_normal_http_error_is_not_out_of_service():
    """A 422 on one malformed request must not take the provider down."""
    exc = ProviderError("parallel_task", "HTTP 422: metadata.jurisdictions must be a string")
    assert not isinstance(exc, ProviderOutOfService)


# =============================================================================
# the adjudicator: an unchecked claim is not a checked one
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "message"), ACCOUNT_LEVEL_STATUSES)
async def test_a_claim_whose_research_failed_says_so(status, message):
    """The exact bug. Every one of these rendered as 'no record found either way'."""
    from truestory.agents.adjudicator import Adjudicator

    claim = _claim()
    evidence = [_failed(f"parallel_task: HTTP {status}: {message}")]

    await Adjudicator().adjudicate_claim(claim, evidence)

    assert claim.research_failed is True, "an unchecked claim must be marked unchecked"
    assert claim.needs_counsel is True
    lowered = claim.rationale.lower()
    assert "did not run" in lowered or "infrastructure" in lowered
    # The sentences that made a drained account look like a clean report.
    assert "declines to make this call" not in lowered
    assert "no record found either way" not in lowered
    assert "not a finding of falsity" not in lowered


@pytest.mark.asyncio
async def test_a_genuinely_silent_record_still_reads_as_silent():
    """The guard must not fire when research ran and found nothing.

    A real private individual with no public record is the ordinary case, and
    reporting it as a malfunction is the over correction that made the element
    path show a column of failure badges for getting the right answer.
    """
    from truestory.agents.adjudicator import Adjudicator

    claim = _claim()
    # Ran, retrieved sources, none bore on the claim. No error anywhere.
    claim.attribution = {"assessed": 6, "kept": 0, "dropped_irrelevant": 6}

    await Adjudicator().adjudicate_claim(claim, [])

    assert claim.research_failed is False
    assert claim.verdict is Verdict.UNSUPPORTED
    assert "silent" in claim.rationale.lower()


@pytest.mark.asyncio
async def test_research_failure_does_not_override_real_evidence():
    """One provider erroring while another succeeded is not a failed claim."""
    from truestory.agents.adjudicator import Adjudicator

    claim = _claim()
    await Adjudicator().adjudicate_claim(claim, [_failed("timeout"), _usable()])

    assert claim.research_failed is False, "usable evidence exists; this claim was checked"


@pytest.mark.asyncio
async def test_a_timeout_is_also_never_a_finding():
    """Not only billing. Any reason research did not run gets the same treatment."""
    from truestory.agents.adjudicator import Adjudicator

    for error in (
        "timeout awaiting Parallel Task",
        "unexpected: ConnectError: connection refused",
        "parallel_task: HTTP 503: upstream unavailable",
    ):
        claim = _claim()
        await Adjudicator().adjudicate_claim(claim, [_failed(error)])
        assert claim.research_failed is True, f"{error!r} rendered as a finding"


# =============================================================================
# the run: the front page has to say it
# =============================================================================


def test_an_outage_produces_a_blocking_coverage_warning():
    """Two hundred unchecked subjects must not be a footnote."""
    from truestory.agents.pipeline import ProjectConfig, RunState, TrueStoryPipeline

    pipeline = TrueStoryPipeline(ProjectConfig(project_id="p"))
    pipeline.registry.outages["parallel_task"] = (
        "parallel_task: HTTP 402: Insufficient credit in account"
    )

    state = RunState(run_id="r1", project_id="p")
    state.claims = [_claim(), _claim("second")]
    state.claims[0].research_failed = True
    state.claims[1].research_failed = True

    warnings = pipeline._outage_warnings(state)
    joined = " ".join(warnings).lower()

    assert warnings, "an outage must reach the front page"
    assert "out of service" in joined
    assert "402" in joined
    assert "not fileable" in joined, "the report must state it cannot be filed"
    assert "2 of 2" in joined, "the ratio is the whole story"


def test_no_outage_produces_no_warning():
    """A clean run must not carry a scary banner it has not earned."""
    from truestory.agents.pipeline import ProjectConfig, RunState, TrueStoryPipeline

    pipeline = TrueStoryPipeline(ProjectConfig(project_id="p"))
    state = RunState(run_id="r1", project_id="p")
    state.claims = [_claim()]

    assert pipeline._outage_warnings(state) == []


def test_research_failed_is_visible_to_the_interface():
    """The UI cannot render a distinction it is never sent."""
    claim = _claim()
    claim.research_failed = True
    assert claim.to_dict()["research_failed"] is True
