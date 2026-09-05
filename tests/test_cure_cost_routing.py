"""research_cure_cost must ask for cure_cost_v1 and get it.

Found on a live run, not in this suite: the first version routed through
`_run`'s ordinary subject type matching, passing `subject={"type":
"REAL_LOCATION"}` to force a cheap route. `_run` resolves the *output schema*
from whatever routing rule matches the subject, not from the schema_name the
caller passed in -- correct for every other tool, wrong here, because this
question has no element type. REAL_LOCATION matched `places_and_orgs` and
silently swapped in entity_v1's schema. The research call still asked the
right question in prose and Parallel answered it correctly in prose -- a real
figure, confirmed on a live run: "$8,000-$25,000" from an industry source --
landing in an entity_v1 response with no `rate_found` or dollar field to hold
it, so every call fell straight through to the policy table while reporting
nothing wrong.

No unit test caught this, because every existing check runs `_run`'s
delegate methods with a subject dict that this feature was never designed
to reuse. This file exists to make sure it cannot happen again quietly.
"""

from __future__ import annotations

from typing import Any

import pytest

from truestory.mcp.tools import ClearanceTools
from truestory.models.enums import Processor, RiskTier
from truestory.models.evidence import Evidence
from truestory.policy import RoutingDecision
from truestory.providers import ProviderRegistry, ResearchRequest


class _CapturingRegistry(ProviderRegistry):
    """Records the decision and request it was asked to investigate, and
    returns a canned Evidence rather than making a real call."""

    def __init__(self) -> None:
        from truestory.config import Mode

        super().__init__(mode=Mode.MOCK)
        self.captured_decision: RoutingDecision | None = None
        self.captured_request: ResearchRequest | None = None

    async def investigate(self, decision: RoutingDecision, request: ResearchRequest) -> Evidence:
        self.captured_decision = decision
        self.captured_request = request
        return Evidence(
            evidence_id="ev-test",
            subject_id=request.subject_id,
            question=request.question,
            finding={"rate_found": True, "low_usd": 100, "high_usd": 200},
            citations=[],
            reasoning="",
            confidence=0.5,
            provider="parallel_task",
            schema_version=request.schema_name,
        )


@pytest.fixture
def registry() -> _CapturingRegistry:
    return _CapturingRegistry()


@pytest.fixture
def tools(registry: _CapturingRegistry) -> ClearanceTools:
    return ClearanceTools(registry)


async def _call(tools: ClearanceTools) -> dict[str, Any]:
    return await tools.research_cure_cost(
        subject_id="cure_artwork_visual",
        element="artwork visual",
        description="a copyrighted still artwork visible on screen as set dressing",
    )


# ── the bug itself ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_request_carries_the_cure_cost_schema_not_a_routed_one(
    tools: ClearanceTools, registry: _CapturingRegistry
) -> None:
    await _call(tools)
    assert registry.captured_request is not None
    assert registry.captured_request.schema_name == "cure_cost_v1"


@pytest.mark.asyncio
async def test_the_output_schema_is_actually_loaded_from_cure_cost_v1(
    tools: ClearanceTools, registry: _CapturingRegistry
) -> None:
    """Not just the label. entity_v1 and cure_cost_v1 could carry the same
    schema_name string and still disagree on the JSON schema sent to the
    provider; this is the field the provider actually honours."""
    await _call(tools)
    schema = registry.captured_request.output_schema
    assert "rate_found" in schema["properties"]
    assert "low_usd" in schema["properties"]


@pytest.mark.asyncio
async def test_tier_and_processor_are_lite_regardless_of_any_routing_table_entry(
    tools: ClearanceTools, registry: _CapturingRegistry
) -> None:
    """A commercial estimate for a producer's budget, never a CRITICAL spend."""
    await _call(tools)
    assert registry.captured_decision.tier is RiskTier.LOW
    assert registry.captured_decision.processor is Processor.LITE


@pytest.mark.asyncio
async def test_the_response_schema_version_is_cure_cost_v1(tools: ClearanceTools) -> None:
    """What actually reaches merge_researched_rate downstream."""
    payload = await _call(tools)
    assert payload["schema_version"] == "cure_cost_v1"


@pytest.mark.asyncio
async def test_a_rate_found_response_has_the_fields_merge_researched_rate_needs(
    tools: ClearanceTools,
) -> None:
    from truestory.agents.exposure import merge_researched_rate

    payload = await _call(tools)
    cure = {
        "remedy_class": "license_art",
        "fee_usd": {"low": 0, "high": 0},
        "change_usd": {"low": 0, "high": 0},
        "low_usd": 0,
        "high_usd": 0,
        "source": "policy_table",
    }
    merged = merge_researched_rate(cure, payload["finding"])
    assert merged["source"] == "researched"
    assert merged["fee_usd"] == {"low": 100, "high": 200}
