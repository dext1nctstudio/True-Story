"""Researched market rates, folded into the exposure model's cure estimate.

The cure table in exposure.yaml was written from general knowledge rather than
measured, which is a guess wearing a currency symbol. A synchronisation fee is
a real number with a market behind it, so it is asked of the record in the same
way a trademark registration is asked of the register.

What these tests hold is the seam between the two. A researched figure and a
hand written one must never render as the same kind of number, and research
that comes back empty must leave the table standing rather than zeroing it.
"""

from __future__ import annotations

import pytest

from truestory.agents.exposure import (
    RESEARCHABLE_CURES,
    ExposureModel,
    merge_researched_rate,
)
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClearanceStatus, ElementType, RiskTier
from truestory.policy import load_schema


def _cure(element_type: ElementType = ElementType.MUSIC_CUE, stage: str = "development"):
    element = ClearableElement(
        element_id="el-1",
        element_type=element_type,
        canonical_form="Subject",
        risk_tier=RiskTier.HIGH,
        status=ClearanceStatus.NEEDS_LICENSE,
    )
    cure = ExposureModel(stage=stage).for_element(element).cure
    assert cure is not None
    return dict(cure)


_GOOD = {
    "rate_found": True,
    "low_usd": 12000,
    "high_usd": 40000,
    "typical_usd": 22000,
    "rate_unit": "per_cue",
    "scope": "US streaming, five year term",
    "basis": "Two published licensing agent rate cards.",
    "obtainable": True,
    "sources": [{"url": "https://example.org/ratecard"}],
}


# ── provenance ──────────────────────────────────────────────────────────────
def test_a_table_figure_says_it_came_from_the_table() -> None:
    """The whole point. A guess must not look like a measurement."""
    cure = _cure()
    assert cure["source"] == "policy_table"
    assert cure["researched"] is False


def test_a_researched_figure_says_so_and_carries_its_sources() -> None:
    merged = merge_researched_rate(_cure(), _GOOD)

    assert merged["source"] == "researched"
    assert merged["researched"] is True
    assert merged["rate_research"]["sources"] == ["https://example.org/ratecard"]
    assert merged["rate_research"]["basis"]


# ── what research may and may not overwrite ─────────────────────────────────
def test_a_researched_rate_replaces_the_fee() -> None:
    merged = merge_researched_rate(_cure(), _GOOD)
    assert merged["fee_usd"] == {"low": 12000, "high": 40000}


def test_research_never_overwrites_the_cost_of_changing_finished_material() -> None:
    """A licensing market says nothing about this production's reshoot day."""
    table = _cure(stage="post")
    merged = merge_researched_rate(dict(table), _GOOD)

    assert merged["change_usd"] == table["change_usd"]
    assert merged["high_usd"] == 40000 + table["change_usd"]["high"]


def test_the_stage_still_drives_the_total_after_research() -> None:
    development = merge_researched_rate(_cure(stage="development"), _GOOD)
    post = merge_researched_rate(_cure(stage="post"), _GOOD)

    assert post["high_usd"] > development["high_usd"]
    assert post["fee_usd"] == development["fee_usd"]


# ── the failure modes ───────────────────────────────────────────────────────
def test_a_silent_record_leaves_the_table_standing() -> None:
    """`rate_found: false` is a real answer and must not render as zero."""
    table = _cure()
    merged = merge_researched_rate(dict(table), {"rate_found": False, "basis": "No rate card."})

    assert merged["source"] == "policy_table"
    assert merged["low_usd"] == table["low_usd"]
    assert merged["rate_research"]["rate_found"] is False


def test_an_inverted_range_cannot_displace_the_table() -> None:
    table = _cure()
    merged = merge_researched_rate(
        dict(table), {"rate_found": True, "low_usd": 900, "high_usd": 10}
    )

    assert merged["source"] == "policy_table"
    assert merged["high_usd"] == table["high_usd"]


def test_a_non_numeric_rate_cannot_displace_the_table() -> None:
    table = _cure()
    merged = merge_researched_rate(
        dict(table), {"rate_found": True, "low_usd": "cheap", "high_usd": None}
    )
    assert merged["source"] == "policy_table"


def test_a_garbage_payload_is_survived() -> None:
    table = _cure()
    assert merge_researched_rate(dict(table), None)["source"] == "policy_table"  # type: ignore[arg-type]


def test_unobtainable_at_any_price_is_recorded_separately_from_expensive() -> None:
    """An estate that refuses is a different problem from a large number."""
    merged = merge_researched_rate(_cure(), {**_GOOD, "obtainable": False})
    assert merged["rate_research"]["obtainable"] is False


# ── scope ───────────────────────────────────────────────────────────────────
def test_only_the_things_a_production_actually_buys_are_researched() -> None:
    """Nobody needs the going rate for changing a character's name."""
    assert "MUSIC_CUE" in RESEARCHABLE_CURES
    assert "FILM_CLIP" in RESEARCHABLE_CURES
    assert "PERSON_NAME_FICTIONAL" not in RESEARCHABLE_CURES
    assert "TRADEMARK_LOGO" not in RESEARCHABLE_CURES


@pytest.mark.parametrize("element_type", sorted(RESEARCHABLE_CURES))
def test_every_researchable_type_has_a_table_fallback(element_type: str) -> None:
    """Research can fail. The table underneath must cover all of them."""
    assert ExposureModel().policy.cure_estimate(element_type, "development") is not None


def test_the_schema_forbids_a_rate_with_no_stated_basis() -> None:
    """A number whose provenance is unstated is the thing being avoided."""
    schema = load_schema("cure_cost_v1")
    assert set(schema["required"]) == {"rate_found", "basis"}
