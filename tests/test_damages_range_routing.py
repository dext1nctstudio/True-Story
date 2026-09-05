"""The monetary-context lookup must use its dedicated schema and cheap route."""

from __future__ import annotations

import pytest

from truestory.config import Mode
from truestory.mcp.tools import ClearanceTools
from truestory.models.enums import Processor, RiskTier
from truestory.models.evidence import Evidence
from truestory.policy import RoutingDecision
from truestory.providers import ProviderRegistry, ResearchRequest


class _CapturingRegistry(ProviderRegistry):
    def __init__(self) -> None:
        super().__init__(mode=Mode.MOCK)
        self.decision: RoutingDecision | None = None
        self.request: ResearchRequest | None = None

    async def investigate(self, decision: RoutingDecision, request: ResearchRequest) -> Evidence:
        self.decision = decision
        self.request = request
        return Evidence(
            evidence_id="ev-damages",
            subject_id=request.subject_id,
            question=request.question,
            finding={
                "range_found": False,
                "source_kind": "none",
                "basis": "No public range.",
            },
            citations=[],
            reasoning="",
            confidence=0.4,
            provider="parallel_task:lite",
            schema_version=request.schema_name,
        )


@pytest.mark.asyncio
async def test_damages_lookup_uses_dedicated_schema_and_lite_route() -> None:
    registry = _CapturingRegistry()
    tools = ClearanceTools(registry)

    payload = await tools.research_damages_range(
        subject_id="shape-1",
        claim_type="defamation arising from an alleged false professional-history statement",
    )

    assert registry.request is not None
    assert registry.decision is not None
    assert registry.request.schema_name == "damages_range_v1"
    assert "defence_cost_usd" in registry.request.output_schema["properties"]
    assert registry.decision.tier is RiskTier.LOW
    assert registry.decision.processor is Processor.LITE
    assert registry.decision.provider == "parallel_task"
    assert payload["schema_version"] == "damages_range_v1"
