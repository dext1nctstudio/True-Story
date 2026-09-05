"""Research about outcomes stays distinct from an uncalibrated risk model."""

from __future__ import annotations

import pytest

from truestory.agents.exposure import ExposureModel, normalise_researched_exposure
from truestory.agents.pipeline import ProjectConfig, RunState, TrueStoryPipeline
from truestory.config import Mode
from truestory.models.claims import FactualClaim
from truestory.models.enums import ClaimType, Polarity, RiskTier, Verdict
from truestory.providers import ProviderRegistry


def _payload(finding: dict) -> dict:
    return {
        "finding": finding,
        "provider": "parallel_task:lite",
        "schema_version": "damages_range_v1",
        "confidence": 0.62,
        "retrieved_at": "2026-09-05T00:00:00+00:00",
        "citations": [
            {
                "url": "https://example.org/source",
                "title": "Media liability costs",
                "excerpt": "Defence can reach $250,000 before trial.",
                "source_type": "secondary",
            }
        ],
    }


def test_live_shape_result_is_defence_cost_only_not_a_damages_estimate() -> None:
    result = normalise_researched_exposure(
        _payload(
            {
                "range_found": False,
                "low_usd": None,
                "high_usd": None,
                "defence_cost_usd": {"low": None, "high": 250_000},
                "source_kind": "legal_commentary",
                "basis": "No public claimant-payment range was located.",
            }
        )
    )

    assert result["status"] == "defence_cost_only"
    assert result["range_found"] is False
    assert result["damages_usd"] is None
    assert result["defence_cost_usd"] == {"low": None, "high": 250_000}
    assert result["sources"][0]["url"] == "https://example.org/source"


def test_no_public_range_is_not_zero() -> None:
    result = normalise_researched_exposure(
        _payload(
            {
                "range_found": False,
                "defence_cost_usd": None,
                "source_kind": "none",
                "basis": "Settlements are confidential.",
            }
        )
    )

    assert result["status"] == "no_public_range"
    assert result["damages_usd"] is None
    assert result["defence_cost_usd"] is None


def test_complete_researched_range_is_preserved_with_outcome() -> None:
    result = normalise_researched_exposure(
        _payload(
            {
                "range_found": True,
                "outcome": "settled",
                "low_usd": 25_000,
                "high_usd": 100_000,
                "typical_usd": 50_000,
                "defence_cost_usd": {"low": 40_000, "high": 250_000},
                "source_kind": "insurance_industry_study",
                "basis": "A published loss study.",
                "sources": [{"url": "https://example.org/source", "title": "Same source"}],
            }
        )
    )

    assert result["status"] == "range_found"
    assert result["outcome"] == "settled"
    assert result["damages_usd"] == {"low": 25_000, "high": 100_000, "typical": 50_000}
    assert len(result["sources"]) == 1


def test_incomplete_or_inverted_claimant_range_is_rejected() -> None:
    for finding in (
        {"range_found": True, "low_usd": None, "high_usd": 100_000},
        {"range_found": True, "low_usd": 100_000, "high_usd": 25_000},
        {"range_found": True, "low_usd": "many", "high_usd": 25_000},
    ):
        result = normalise_researched_exposure(
            _payload({**finding, "source_kind": "legal_commentary", "basis": "Thin record."})
        )
        assert result["range_found"] is False
        assert result["damages_usd"] is None
        assert "not used" in result["basis"]


def test_boolean_is_not_accepted_as_a_dollar_value() -> None:
    result = normalise_researched_exposure(
        _payload(
            {
                "range_found": True,
                "low_usd": False,
                "high_usd": 10,
                "source_kind": "legal_commentary",
                "basis": "Malformed.",
            }
        )
    )
    assert result["damages_usd"] is None


@pytest.mark.asyncio
async def test_pipeline_attaches_research_without_overwriting_the_model() -> None:
    claim = FactualClaim(
        claim_id="cl-1",
        subject_element_id="el-1",
        subject_name="Real Person",
        claim_text="Real Person committed professional misconduct.",
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
        risk_tier=RiskTier.CRITICAL,
        verdict=Verdict.UNSUPPORTED,
        subject_alive=True,
        needs_counsel=True,
    )
    state = RunState(run_id="run-1", project_id="project-1", claims=[claim])
    state.exposure = ExposureModel().schedule([], [claim])
    before = state.exposure["assessments"][0]["modelled_exposure"]

    class _Tools:
        calls = 0

        async def research_damages_range(self, **_: object) -> dict:
            self.calls += 1
            return _payload(
                {
                    "range_found": False,
                    "defence_cost_usd": {"low": None, "high": 250_000},
                    "source_kind": "legal_commentary",
                    "basis": "No public claimant-payment range was located.",
                }
            )

    pipeline = TrueStoryPipeline(
        ProjectConfig(project_id="project-1"),
        registry=ProviderRegistry(mode=Mode.MOCK),
    )
    tools = _Tools()
    pipeline.tools = tools  # type: ignore[assignment]

    await pipeline._research_damages_ranges(state)

    assessment = state.exposure["assessments"][0]
    assert tools.calls == 1
    assert assessment["researched_exposure"]["status"] == "defence_cost_only"
    assert assessment["modelled_exposure"] == before
    assert state.exposure["research_summary"]["defence_cost_only"] == 1
