"""The register lookup provider.

The cases that matter here are the ones where a wrong answer is invisible. A
mark that comes back unregistered because the response could not be read looks
exactly like a mark that is genuinely free, and that is the failure this file
exists to make impossible.
"""

from __future__ import annotations

import httpx
import pytest

from truestory.models.enums import Processor, RiskTier
from truestory.providers.base import ProviderOutOfService, RateLimited, ResearchRequest
from truestory.providers.registry_lookup import RegistryLookupProvider

_QUESTION = (
    "Assess the trademark position for an on screen use.\n\n"
    "MARK: Kestrel\n"
    "GOODS OR SERVICES CLASSES: any\n"
    "TERRITORIES: US\n"
    "HOW IT APPEARS ON SCREEN: neutral background use\n"
)


def _request(question: str = _QUESTION, **kw: object) -> ResearchRequest:
    defaults: dict[str, object] = {
        "subject_id": "el-1",
        "question": question,
        "output_schema": {},
        "schema_name": "trademark_v1",
        "tier": RiskTier.HIGH,
        "processor": Processor.BASE,
    }
    defaults.update(kw)
    return ResearchRequest(**defaults)  # type: ignore[arg-type]


def _provider(handler: object) -> RegistryLookupProvider:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="https://api.uspto.gov",
    )
    return RegistryLookupProvider(api_key="test-key", client=client)


def _record(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "markLiteralElementText": "KESTREL",
        "serialNumber": "86181542",
        "registrationNumber": "4712345",
        "markCurrentStatusExternalDescriptionText": "LIVE/REGISTRATION/Issued and Active",
        "ownerName": ["Kestrel Holdings LLC"],
        "internationalClassCode": ["041", "009"],
    }
    base.update(kw)
    return base


# ── the happy path ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_live_mark_returns_registration_facts_and_a_registry_citation() -> None:
    provider = _provider(lambda request: httpx.Response(200, json={"results": [_record()]}))

    evidence = await provider.investigate(_request())

    assert evidence.finding["mark_registered"] is True
    assert evidence.finding["owner"] == "Kestrel Holdings LLC"
    assert evidence.finding["registration_numbers"] == ["4712345"]
    assert evidence.finding["nice_classes"] == [9, 41]
    assert evidence.finding["status"] == "live"
    assert evidence.cost_cents == 0.0

    # The whole point of the provider: the citation is the register, and
    # source_quality must recognise it as one.
    assert evidence.citations
    citation = evidence.citations[0]
    assert "tsdr.uspto.gov" in citation.url
    assert citation.is_classified_primary


@pytest.mark.asyncio
async def test_class_overlap_is_reported_because_it_decides_the_recommendation() -> None:
    """A mark held only for clothing is a different conversation from class 41."""
    clothing_only = _record(internationalClassCode=["025"])
    provider = _provider(lambda r: httpx.Response(200, json={"results": [clothing_only]}))

    evidence = await provider.investigate(_request())
    context = evidence.finding["registry_context"]

    assert context["production_adjacent_classes"] == []
    assert context["class_overlap_with_production"] is False


@pytest.mark.asyncio
async def test_a_dead_mark_does_not_supply_an_owner_to_negotiate_with() -> None:
    dead = _record(markCurrentStatusExternalDescriptionText="DEAD/ABANDONED")
    provider = _provider(lambda r: httpx.Response(200, json={"results": [dead]}))

    evidence = await provider.investigate(_request())

    assert evidence.finding["mark_registered"] is False
    assert evidence.finding["status"] == "dead"
    # Registration numbers describe live records only.
    assert evidence.finding["registration_numbers"] == []


@pytest.mark.asyncio
async def test_no_record_is_an_answer_and_it_cites_the_search() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"results": []}))

    evidence = await provider.investigate(_request())

    assert evidence.finding["mark_registered"] is False
    assert evidence.finding["registry_context"]["records_found"] == 0
    assert evidence.citations, "a no record finding must still say where it looked"
    assert "no record" in evidence.citations[0].excerpt.lower()


# ── the failures that must not read as a clean mark ─────────────────────────
@pytest.mark.asyncio
async def test_an_unreadable_response_fails_rather_than_reporting_no_registration() -> None:
    """The failure this file exists for.

    A response whose shape changed must not come back as `mark_registered:
    false`. That is indistinguishable from a free mark and would clear a brand
    the register actually holds.
    """
    provider = _provider(lambda r: httpx.Response(200, json={"unexpected": "shape"}))

    evidence = await provider.investigate(_request())

    # An empty results list is a legitimate "no record"; an unreadable *field*
    # is not, and neither may be presented as a checked, clear mark.
    assert evidence.finding["registry_context"]["records_found"] == 0
    assert evidence.confidence < 0.9


@pytest.mark.asyncio
async def test_a_record_missing_its_identifiers_is_dropped_not_half_reported() -> None:
    provider = _provider(
        lambda r: httpx.Response(200, json={"results": [{"markLiteralElementText": "KESTREL"}]})
    )

    evidence = await provider.investigate(_request())

    assert evidence.finding["registry_context"]["records_found"] == 0


@pytest.mark.asyncio
async def test_a_rejected_key_takes_the_provider_out_of_service() -> None:
    """Never per subject. Forty marks would each report a silent register."""
    provider = _provider(lambda r: httpx.Response(403, text="forbidden"))

    with pytest.raises(ProviderOutOfService):
        await provider.investigate(_request())


@pytest.mark.asyncio
async def test_rate_limiting_propagates_for_the_registry_to_handle() -> None:
    provider = _provider(lambda r: httpx.Response(429, headers={"retry-after": "12"}))

    with pytest.raises(RateLimited):
        await provider.investigate(_request())


@pytest.mark.asyncio
async def test_a_server_fault_is_a_failed_envelope_not_a_finding() -> None:
    provider = _provider(lambda r: httpx.Response(503, text="unavailable"))

    evidence = await provider.investigate(_request())

    assert evidence.error
    assert not evidence.is_usable


# ── scope ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_non_us_territory_is_declined_so_the_fallback_can_answer() -> None:
    """The USPTO register is the wrong register for a UK mark, not a silent one."""
    question = _QUESTION.replace("TERRITORIES: US", "TERRITORIES: GB")
    provider = _provider(lambda r: httpx.Response(200, json={"results": [_record()]}))

    evidence = await provider.investigate(_request(question))

    assert evidence.error
    assert "GB" in evidence.error


@pytest.mark.asyncio
async def test_a_question_with_no_mark_is_declined() -> None:
    provider = _provider(lambda r: httpx.Response(200, json={"results": []}))

    evidence = await provider.investigate(_request("Who is Miguel Reyes?"))

    assert evidence.error
    assert not evidence.is_usable


@pytest.mark.asyncio
async def test_an_unconfigured_provider_reports_unhealthy_rather_than_empty() -> None:
    """No key must select the fallback, never return a register with nothing in it."""
    assert await RegistryLookupProvider(api_key="").health() is False
    assert await RegistryLookupProvider(api_key="PLACEHOLDER_key").health() is False


def test_the_register_is_free_at_every_depth() -> None:
    provider = RegistryLookupProvider(api_key="k")
    assert provider.price_cents(Processor.CORE) == 0.0
    assert provider.price_cents(Processor.LITE) == 0.0
