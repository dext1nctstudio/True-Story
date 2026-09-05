"""Monitors for marks, pinned to the register record rather than the word.

Monitor deduplicates events. It does not deduplicate irrelevance, so a watch on
the string "Kestrel" delivers a bird, a consultancy and three bands every month
for the commercial life of the title, and a reviewer learns to ignore the
alerts. These tests hold the line that a mark the register answered is watched
by its registration number.
"""

from __future__ import annotations

from truestory.agents.swarm import _monitor_query, _monitor_reason
from truestory.models.elements import ClearableElement
from truestory.models.enums import ElementType, RiskTier
from truestory.models.evidence import Evidence
from truestory.policy.loader import load_routing


def _element(element_type: ElementType = ElementType.TRADEMARK_LOGO) -> ClearableElement:
    return ClearableElement(
        element_id="el-1",
        element_type=element_type,
        canonical_form="Kestrel",
        risk_tier=RiskTier.HIGH,
    )


def _register_evidence(
    *,
    registration_numbers: list[str] | None = None,
    owner: str | None = "Kestrel Holdings LLC",
) -> Evidence:
    """What registry_lookup returns. `registry_context` is its fingerprint."""
    return Evidence(
        evidence_id="ev-1",
        subject_id="el-1",
        question="MARK: Kestrel",
        finding={
            "mark_registered": True,
            "owner": owner,
            "registration_numbers": (
                ["4712345"] if registration_numbers is None else registration_numbers
            ),
            "registry_context": {"records_found": 1, "live_records": 1},
        },
        citations=[],
        reasoning="",
        confidence=0.92,
        provider="registry_lookup",
        schema_version="trademark_v1",
    )


def _research_evidence() -> Evidence:
    """What Parallel Task returns. No registry_context, so nothing to pin to."""
    return Evidence(
        evidence_id="ev-2",
        subject_id="el-1",
        question="MARK: Kestrel",
        finding={"mark_registered": True, "owner": "Kestrel Holdings LLC"},
        citations=[],
        reasoning="",
        confidence=0.7,
        provider="parallel_task:base",
        schema_version="trademark_v1",
    )


# ── the pinned watch ────────────────────────────────────────────────────────
def test_a_mark_the_register_answered_is_watched_by_its_registration_number() -> None:
    query = _monitor_query(_element(), _register_evidence())

    assert "4712345" in query
    assert "Kestrel Holdings LLC" in query
    # The events that actually change a clearance position.
    for event in ("renewal", "cancellation", "assignment", "opposition"):
        assert event in query.lower()


def test_the_manifest_says_why_a_pinned_watch_exists() -> None:
    reason = _monitor_reason(_element(), _register_evidence())
    assert "register record" in reason.lower()


def test_every_mark_type_is_pinned_not_just_the_two_that_were_named() -> None:
    """BRAND_PRODUCT routes through the same rule and was falling through."""
    for element_type in (
        ElementType.TRADEMARK_LOGO,
        ElementType.BUSINESS_NAME,
        ElementType.BRAND_PRODUCT,
    ):
        query = _monitor_query(_element(element_type), _register_evidence())
        assert "4712345" in query, element_type


# ── the fallback, which must stay a real watch ──────────────────────────────
def test_research_prose_falls_back_to_the_broad_watch_rather_than_none() -> None:
    """Unkeyed and non US marks still get watched, just less precisely."""
    query = _monitor_query(_element(), _research_evidence())

    assert "Kestrel" in query
    assert "4712345" not in query


def test_no_evidence_at_all_still_produces_a_watch() -> None:
    query = _monitor_query(_element(), None)
    assert "Kestrel" in query


def test_a_failed_lookup_is_not_treated_as_a_register_answer() -> None:
    failed = Evidence.failed("el-1", "MARK: Kestrel", "registry_lookup", "timeout")
    query = _monitor_query(_element(), failed)

    assert "4712345" not in query
    assert "Kestrel" in query


def test_a_mark_on_the_register_with_no_live_registration_is_not_pinned() -> None:
    """Nothing to watch by number. A pending application has no registration."""
    query = _monitor_query(_element(), _register_evidence(registration_numbers=[]))

    assert "Kestrel" in query
    assert "registration(s)" not in query


def test_a_missing_owner_does_not_render_as_none() -> None:
    query = _monitor_query(_element(), _register_evidence(owner=None))

    assert "None" not in query
    assert "registered proprietor" in query


# ── cadence ─────────────────────────────────────────────────────────────────
def test_the_three_mark_types_share_one_cadence() -> None:
    routing = load_routing()
    cadences = {
        str(t): routing.monitor_cadence(t)
        for t in (
            ElementType.TRADEMARK_LOGO,
            ElementType.BUSINESS_NAME,
            ElementType.BRAND_PRODUCT,
        )
    }
    assert set(cadences.values()) == {"quarterly"}, cadences
