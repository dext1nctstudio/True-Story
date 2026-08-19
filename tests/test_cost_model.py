"""The cost model.

Every figure the product puts on screen about money resolves here: the meter,
the projection, the report footer and the pre flight calculator. A price that
is wrong in this file is wrong in all four, so the published rates are pinned
against the source they were verified from.

    Parallel   https://docs.parallel.ai/getting-started/pricing
    Gemini     https://ai.google.dev/gemini-api/docs/pricing
    verified   19 August 2026
"""

from __future__ import annotations

import pytest

from truestory.models.enums import Processor, RiskTier
from truestory.providers.budget import BudgetGovernor
from truestory.providers.model_cost import cost_cents, price_for

# =============================================================================
# published unit prices
# =============================================================================


@pytest.mark.parametrize(
    ("processor", "usd"),
    [
        (Processor.LITE, 0.005),
        (Processor.BASE, 0.010),
        (Processor.CORE, 0.025),
        (Processor.PRO, 0.100),
        (Processor.ULTRA, 0.300),
    ],
)
def test_task_processor_list_prices(processor, usd):
    assert processor.usd_per_run == pytest.approx(usd)


def test_extract_is_priced_per_url_not_per_task():
    """$1 per 1000 URLs. This was 0.5 cents, five times the real rate."""
    from truestory.providers.parallel_extract import ParallelExtractProvider

    assert ParallelExtractProvider.unit_cost_cents == pytest.approx(0.1)


def test_search_is_priced_per_request():
    from truestory.providers.parallel_search import ParallelSearchProvider

    assert ParallelSearchProvider.unit_cost_cents == pytest.approx(0.1)


# =============================================================================
# model tokens
# =============================================================================


def test_pro_crosses_a_tier_at_two_hundred_thousand_prompt_tokens():
    small = cost_cents("gemini-2.5-pro", 100_000, 1_000)
    large = cost_cents("gemini-2.5-pro", 300_000, 1_000)
    assert large / 300_000 > small / 100_000  # the per token rate rose


def test_flash_lite_is_not_priced_as_flash():
    """Longest prefix wins, or flash-lite is billed at four times its rate."""
    assert price_for("gemini-2.5-flash-lite").input_per_m == pytest.approx(0.10)
    assert price_for("gemini-2.5-flash").input_per_m == pytest.approx(0.30)


def test_cached_prompt_tokens_are_billed_at_the_cached_rate():
    uncached = cost_cents("gemini-2.5-pro", 100_000, 2_000)
    cached = cost_cents("gemini-2.5-pro", 100_000, 2_000, cached_tokens=90_000)
    assert cached < uncached / 2


def test_an_unknown_model_is_priced_as_the_most_expensive_one():
    """Never zero. Silently free spend is the failure this guards."""
    assert cost_cents("some-unreleased-model", 1_000, 1_000) > 0


# =============================================================================
# the governor
# =============================================================================


def test_a_cache_hit_records_the_saving_rather_than_losing_it():
    governor = BudgetGovernor(ceiling_usd=5.0)
    governor.record(0.0, RiskTier.HIGH, "cache", cached=True, list_price_cents=2.5)
    assert governor.ledger.spent_cents == 0
    assert governor.ledger.cache_saved_cents == pytest.approx(2.5)


def test_model_spend_is_reported_beside_research_and_not_inside_it():
    governor = BudgetGovernor(ceiling_usd=5.0)
    governor.record(2.0, RiskTier.HIGH, "parallel_task:core")
    governor.record_model("gemini-2.5-pro", 100_000, 2_000)

    snapshot = governor.snapshot()
    assert snapshot["spent_cents"] == pytest.approx(2.0)
    assert snapshot["model_cents"] > 0
    assert snapshot["total_cents"] == pytest.approx(
        snapshot["spent_cents"] + snapshot["model_cents"]
    )
    # The ceiling governs research only. Model tokens must not consume it.
    assert governor.remaining_cents == pytest.approx(governor.ceiling_cents - 2.0)


def test_the_projection_travels_with_the_meter():
    governor = BudgetGovernor(ceiling_usd=5.0)
    governor.project([(Processor.CORE, RiskTier.CRITICAL), (Processor.LITE, RiskTier.MEDIUM)])
    projection = governor.snapshot()["projection"]

    assert projection["subjects"] == 2
    assert projection["projected_usd"] == pytest.approx(0.03)
    assert projection["by_processor"]["core"]["subjects"] == 1


def test_unit_economics_compare_against_the_low_end_of_the_manual_range():
    governor = BudgetGovernor(ceiling_usd=5.0)
    governor.record(200.0, RiskTier.HIGH, "parallel_task:core")  # $2.00

    economics = governor.economics(subjects=200, claims=150, pages=105)
    assert economics["per_subject_usd"] == pytest.approx(0.01)
    assert economics["times_cheaper"] == pytest.approx(
        economics["manual_baseline"]["report_usd_low"] / 2.0, rel=0.01
    )


def test_critical_work_draws_on_a_reserve_nothing_else_can_reach():
    governor = BudgetGovernor(ceiling_usd=1.0, reserve_critical_usd=0.5)
    governor.record(60.0, RiskTier.HIGH, "parallel_task:base")  # 60c of 100c spent

    assert governor.available_for(RiskTier.CRITICAL) == pytest.approx(40.0)
    assert governor.available_for(RiskTier.LOW) == pytest.approx(0.0)
