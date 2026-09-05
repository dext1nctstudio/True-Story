"""Adjudication and remedy fan out rather than queue.

Ingest, claims, identity and the research swarm were all converted from serial
loops to bounded fan out. Adjudication and remedy were not, and they sit at the
end of the pipeline on the most expensive model in the system. Measured on a
two page script against a fully warm research cache: research finished in 269
seconds and the run took 938, nearly all of the remainder spent deciding one
subject at a time.

These tests assert the shape rather than the wall clock, because a timing
assertion in CI is a flake waiting to happen. If the stage is concurrent, calls
overlap; if it is serial, they cannot.
"""

from __future__ import annotations

import asyncio

import pytest

from truestory.agents.adjudicator import Adjudicator
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClaimType, ElementType, Polarity, RiskTier


class _OverlapRecorder:
    """Counts how many calls were in flight at once."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0

    async def __call__(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            return {
                "verdict": "UNSUPPORTED",
                "status": "CLEAR",
                "confidence": 0.1,
                "rationale": "stub",
                "supporting_evidence_ids": [],
            }
        finally:
            self.in_flight -= 1


def _claims(n: int) -> list[FactualClaim]:
    return [
        FactualClaim(
            claim_id=f"cl_{i}",
            subject_element_id="el_1",
            subject_name="Margaret Holloway",
            claim_text=f"claim {i}",
            claim_type=ClaimType.CONDUCT,
            polarity=Polarity.NEUTRAL,
            risk_tier=RiskTier.LOW,
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_claim_adjudication_overlaps(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _OverlapRecorder()
    adjudicator = Adjudicator()
    monkeypatch.setattr(adjudicator, "_call_model_for_claim", recorder)

    claims = _claims(6)
    # One usable Evidence per claim, so each reaches the model call.
    from truestory.models.evidence import Citation, Evidence

    evidence = {
        c.claim_id: [
            Evidence(
                evidence_id=f"ev_{c.claim_id}",
                subject_id=c.claim_id,
                question="q",
                finding={},
                citations=[
                    Citation.classified("https://www.gov.uk/a", excerpt="a passage that is long")
                ],
                reasoning="",
                confidence=0.8,
                provider="mock",
                schema_version="claim_verification_v1",
            )
        ]
        for c in claims
    }
    for records in evidence.values():
        for record in records:
            object.__setattr__(record.citations[0], "stance", "supports")
            object.__setattr__(record.citations[0], "quote_verified", True)

    await adjudicator.run(claims, [], evidence)

    assert recorder.peak > 1, "claim adjudication ran one call at a time"


@pytest.mark.asyncio
async def test_element_adjudication_overlaps(monkeypatch: pytest.MonkeyPatch) -> None:
    from truestory.models.evidence import Citation, Evidence

    recorder = _OverlapRecorder()
    adjudicator = Adjudicator()
    monkeypatch.setattr(adjudicator, "_call_model_for_element", recorder)

    elements = [
        ClearableElement(
            element_id=f"el_{i}",
            element_type=ElementType.ORGANIZATION,
            canonical_form=f"Org {i}",
        )
        for i in range(6)
    ]
    evidence = {}
    for element in elements:
        citation = Citation.classified("https://www.gov.uk/a", excerpt="a passage that is long")
        object.__setattr__(citation, "stance", "supports")
        object.__setattr__(citation, "quote_verified", True)
        evidence[element.element_id] = [
            Evidence(
                evidence_id=f"ev_{element.element_id}",
                subject_id=element.element_id,
                question="q",
                finding={},
                citations=[citation],
                reasoning="",
                confidence=0.8,
                provider="mock",
                schema_version="claim_verification_v1",
            )
        ]

    await adjudicator.run([], elements, evidence)

    assert recorder.peak > 1, "element adjudication ran one call at a time"


@pytest.mark.asyncio
async def test_one_failing_subject_does_not_end_the_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single subject that raises must not take the rest of the run with it.

    Serially this was a bare `await` and any exception propagated out of the
    stage. Concurrently it would cancel its siblings, which is worse, so the
    fan out guards each subject.
    """
    adjudicator = Adjudicator()
    seen: list[str] = []

    async def flaky(claim: FactualClaim, *args: object, **kwargs: object) -> dict[str, object]:
        seen.append(claim.claim_id)
        if claim.claim_id == "cl_2":
            raise RuntimeError("vertex said no")
        return {
            "verdict": "UNSUPPORTED",
            "confidence": 0.1,
            "rationale": "stub",
            "supporting_evidence_ids": [],
        }

    monkeypatch.setattr(adjudicator, "_call_model_for_claim", flaky)
    claims = _claims(5)

    await adjudicator.run(claims, [], {})

    # Every claim was attempted; none was cancelled by its neighbour.
    assert len(claims) == 5
