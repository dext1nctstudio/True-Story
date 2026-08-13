"""Principle P2: no verdict without evidence.

This is the safeguard the whole product rests on. A red line with no citation
is legally worthless and is itself a careless assertion about a real person, so
the invariant is enforced structurally in the model layer rather than by asking
a language model to behave.

If any test in this file starts failing, the product is unsafe to ship.
"""

from __future__ import annotations

import pytest

from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import (
    ClaimType,
    ClearanceStatus,
    ElementType,
    Polarity,
    Verdict,
)
from truestory.models.evidence import Citation, Evidence


def _claim() -> FactualClaim:
    return FactualClaim(
        claim_id="cl_test",
        subject_element_id="el_test",
        subject_name="Test Subject",
        claim_text="The subject was convicted in 1974.",
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
    )


def _evidence(*, citations: int = 1, error: str | None = None) -> Evidence:
    return Evidence(
        evidence_id="ev_test",
        subject_id="cl_test",
        question="Was the subject convicted in 1974?",
        finding={"verdict": "contradicted"},
        citations=[
            Citation(
                url=f"https://example.org/{i}",
                title="Record",
                excerpt="No conviction is recorded.",
                source_type="primary",
            )
            for i in range(citations)
        ],
        reasoning="The register shows no conviction.",
        confidence=0.9,
        provider="parallel_task:core",
        schema_version="claim_verification_v1",
        error=error,
    )


# =============================================================================
# the invariant
# =============================================================================


@pytest.mark.parametrize(
    "verdict",
    [Verdict.VERIFIED, Verdict.UNSUPPORTED, Verdict.CONTRADICTED, Verdict.UNVERIFIABLE],
)
def test_verdict_without_evidence_is_refused(verdict):
    """Every verdict except opinion requires a citation bearing record."""
    claim = _claim()
    with pytest.raises(ValueError, match="P2"):
        claim.record_verdict(verdict, 0.9, "reasoning", [])


def test_verdict_with_uncitable_evidence_is_refused():
    """An evidence record carrying no citation does not satisfy the invariant."""
    claim = _claim()
    empty = Evidence(
        evidence_id="ev_empty",
        subject_id="cl_test",
        question="q",
        finding={},
        citations=[],
        reasoning="",
        confidence=0.9,
        provider="parallel_task:core",
        schema_version="v1",
    )
    with pytest.raises(ValueError, match="P2"):
        claim.record_verdict(Verdict.CONTRADICTED, 0.9, "reasoning", [empty])


def test_verdict_with_errored_evidence_is_refused():
    """A failed lookup is recorded honestly and cannot support a verdict."""
    claim = _claim()
    failed = _evidence(error="timeout")
    with pytest.raises(ValueError, match="P2"):
        claim.record_verdict(Verdict.VERIFIED, 0.9, "reasoning", [failed])


def test_opinion_is_the_only_exemption():
    """Opinion is never researched, so it has nothing to cite."""
    claim = _claim()
    claim.record_verdict(Verdict.OPINION, 1.0, "Characterisation, not a factual claim.", [])
    assert claim.verdict is Verdict.OPINION


def test_verdict_with_evidence_is_recorded():
    claim = _claim()
    claim.record_verdict(Verdict.CONTRADICTED, 0.94, "The record shows otherwise.", [_evidence()])
    assert claim.verdict is Verdict.CONTRADICTED
    assert claim.citation_count == 1
    assert claim.adjudicated_at is not None


def test_element_status_without_evidence_is_refused():
    element = ClearableElement(
        element_id="el_test",
        element_type=ElementType.MUSIC_CUE,
        canonical_form="A Song",
    )
    with pytest.raises(ValueError, match="P2"):
        element.record_adjudication(ClearanceStatus.CLEAR, 0.9, "reasoning", [])


def test_research_failed_may_be_recorded_without_evidence():
    """An honest failure is a legitimate status and must be recordable."""
    element = ClearableElement(
        element_id="el_test",
        element_type=ElementType.MUSIC_CUE,
        canonical_form="A Song",
    )
    element.record_adjudication(
        ClearanceStatus.RESEARCH_FAILED, 0.0, "Research did not complete.", []
    )
    assert element.status is ClearanceStatus.RESEARCH_FAILED


# =============================================================================
# degrading honestly
# =============================================================================


def test_fallback_evidence_is_confidence_capped():
    """Principle P5. A grounded fallback never presents as a full research run."""
    evidence = Evidence(
        evidence_id="ev_fb",
        subject_id="cl_test",
        question="q",
        finding={},
        citations=[Citation(url="https://example.org", title="t", excerpt="e")],
        reasoning="r",
        confidence=0.95,
        provider="gemini_grounded",
        schema_version="v1",
        is_fallback=True,
    )
    assert evidence.confidence == 0.95
    assert evidence.effective_confidence == 0.6


def test_non_fallback_confidence_is_untouched():
    assert _evidence().effective_confidence == 0.9


def test_failed_evidence_reports_itself_unusable():
    failed = Evidence.failed("cl_test", "q", "parallel_task", "429 rate limited")
    assert not failed.is_usable
    assert failed.confidence == 0.0
    assert failed.error is not None


# =============================================================================
# content addressing
# =============================================================================


def test_claim_id_is_stable_across_whitespace_and_case():
    """The same sentence in draft one and draft nine is the same claim.

    This is what makes draft over draft caching free and what makes per
    episode series economics work at all.
    """
    a = FactualClaim.make_id("el_1", "She was convicted in 1974.")
    b = FactualClaim.make_id("el_1", "  she was CONVICTED in 1974.  ")
    assert a == b


def test_claim_id_differs_by_subject():
    a = FactualClaim.make_id("el_1", "She was convicted in 1974.")
    b = FactualClaim.make_id("el_2", "She was convicted in 1974.")
    assert a != b


def test_element_id_is_stable_and_jurisdiction_aware():
    a = ClearableElement.make_id(ElementType.MUSIC_CUE, "A Song", ["US", "GB"])
    b = ClearableElement.make_id(ElementType.MUSIC_CUE, "  a song  ", ["GB", "US"])
    c = ClearableElement.make_id(ElementType.MUSIC_CUE, "A Song", ["US"])
    assert a == b, "case and ordering must not change identity"
    assert a != c, "jurisdiction changes the research question, so it changes identity"


def test_evidence_id_is_deterministic():
    a = Evidence.make_id("cl_1", "question", "parallel_task:core")
    b = Evidence.make_id("cl_1", "question", "parallel_task:core")
    assert a == b


# =============================================================================
# the epistemic distinction
# =============================================================================


def test_unsupported_and_unverifiable_are_amber_but_not_contradicted():
    """Unsupported is not false. Collapsing the two would be the very error
    this product exists to prevent."""
    for verdict in (Verdict.UNSUPPORTED, Verdict.UNVERIFIABLE):
        claim = _claim()
        claim.record_verdict(verdict, 0.5, "No record either way.", [_evidence()])
        assert claim.is_amber
        assert claim.verdict is not Verdict.CONTRADICTED
        assert claim.color() == "amber"


def test_contradicted_renders_red_and_verified_renders_green():
    contradicted = _claim()
    contradicted.record_verdict(Verdict.CONTRADICTED, 0.9, "r", [_evidence()])
    assert contradicted.color() == "red"

    verified = _claim()
    verified.record_verdict(Verdict.VERIFIED, 0.9, "r", [_evidence()])
    assert verified.color() == "green"


def test_unadjudicated_claim_never_renders_green():
    """An unresearched claim must not look cleared."""
    assert _claim().color() == "pending"


def test_escalation_cocktail_is_detected():
    claim = _claim()
    claim.subject_alive = True
    assert claim.is_escalation_cocktail

    claim.subject_alive = False
    assert not claim.is_escalation_cocktail
