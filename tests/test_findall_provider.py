"""The FindAll provider, and the request body the API actually requires.

This file exists because the integration was written against an API shape that
does not exist and nobody noticed for the life of the project. Every call
returned HTTP 422 with four required fields missing, and because the reason was
recorded on the Evidence and never logged, the failure presented as an
enumeration that found nothing. That silently disabled:

  * the namesake collision check on every real person depicted (CRITICAL),
  * the identifiability enumeration behind the Baby Reindeer rule (CRITICAL),
  * the registered entity search behind every mark and business name (HIGH).

The first test below is the one that would have caught it on day one: it asserts
the shape of the outgoing request rather than the behaviour of the code around
it. If a field name drifts again, this fails offline, for free, in CI.
"""

from __future__ import annotations

import json

import httpx
import pytest

from truestory.mcp.tools import _ENUMERATION_KINDS
from truestory.providers.base import Processor, ResearchRequest, RiskTier
from truestory.providers.parallel_findall import ParallelFindAllProvider

# The four fields the live API returned "Field required" for, verified against
# a real 422 on 2026-08-22 and against the published FindAll reference.
REQUIRED_FIELDS = ("objective", "entity_type", "match_conditions", "generator")

CREATED = {"findall_id": "findall_test", "status": {"status": "queued", "is_active": True}}

RESULT = {
    "run": {
        "findall_id": "findall_test",
        "status": {"status": "completed", "is_active": False, "termination_reason": "done"},
    },
    "candidates": [
        {
            "candidate_id": "c1",
            "name": "Jill Nakamura",
            "url": "https://example.gov/register/1",
            "description": "A real person bearing the name.",
            "match_status": "matched",
            "output": {"bears_the_name": {"value": "yes", "is_matched": True}},
            "basis": [
                {
                    "field": "bears_the_name",
                    "citations": [
                        {
                            "title": "Register entry",
                            "url": "https://example.gov/register/1",
                            "excerpts": ["Jill Nakamura, registered 2004."],
                        }
                    ],
                    "reasoning": "The register lists the name.",
                    "confidence": "high",
                }
            ],
        },
        {
            "candidate_id": "c2",
            "name": "Someone Else",
            "url": "https://example.com/other",
            "match_status": "rejected",
            "basis": [{"field": "bears_the_name", "confidence": "low", "reasoning": "Different."}],
        },
    ],
}


def _request(**overrides) -> ResearchRequest:
    base = {
        "subject_id": "el_1",
        "question": "Find real people known by the name Jill.",
        "output_schema": {},
        "schema_name": "person_collision_v1",
        "tier": RiskTier.HIGH,
        "processor": Processor.BASE,
        "jurisdictions": ("US",),
        "max_results": 5,
        "entity_type": "people",
        "match_conditions": (("bears_the_name", "The person is known by the name Jill."),),
    }
    base.update(overrides)
    return ResearchRequest(**base)


def _provider(sent: list[httpx.Request], *, create_status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "POST":
            return httpx.Response(create_status, json=CREATED)
        return httpx.Response(200, json=RESULT)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        base_url="https://api.parallel.ai",
    )
    return ParallelFindAllProvider(api_key="k", client=client, tier="preview")


# =============================================================================
# the request body
# =============================================================================


@pytest.mark.asyncio
async def test_the_create_body_carries_every_required_field(monkeypatch):
    """The regression. Four missing fields 422'd every call ever made."""
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    sent: list[httpx.Request] = []
    await _provider(sent).enumerate(_request())

    post = next(r for r in sent if r.method == "POST")
    body = json.loads(post.content)
    for field in REQUIRED_FIELDS:
        assert field in body, f"FindAll rejects a body without {field!r}"


@pytest.mark.asyncio
async def test_the_create_body_does_not_send_the_invented_fields(monkeypatch):
    """`query` and `processor` were never this API's field names."""
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    sent: list[httpx.Request] = []
    await _provider(sent).enumerate(_request())

    body = json.loads(next(r for r in sent if r.method == "POST").content)
    for stale in ("query", "processor", "result_schema", "max_results"):
        assert stale not in body


@pytest.mark.asyncio
async def test_match_conditions_are_named_pairs(monkeypatch):
    """FindAll evaluates each condition separately, which is what makes a match
    auditable. It requires at least one."""
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    sent: list[httpx.Request] = []
    await _provider(sent).enumerate(_request())

    conditions = json.loads(next(r for r in sent if r.method == "POST").content)["match_conditions"]
    assert conditions and all({"name", "description"} <= set(c) for c in conditions)


@pytest.mark.asyncio
async def test_a_caller_naming_no_conditions_still_sends_one(monkeypatch):
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    sent: list[httpx.Request] = []
    await _provider(sent).enumerate(_request(match_conditions=(), entity_type=""))

    body = json.loads(next(r for r in sent if r.method == "POST").content)
    assert body["match_conditions"]
    assert body["entity_type"]


# =============================================================================
# create, then poll
# =============================================================================


@pytest.mark.asyncio
async def test_results_are_read_from_the_result_endpoint(monkeypatch):
    """The create returns a job id, not candidates. Reading `results` off the
    create response was the second half of the same wrong contract."""
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    sent: list[httpx.Request] = []
    out = await _provider(sent).enumerate(_request())

    assert any(r.method == "POST" and r.url.path.endswith("/findall/runs") for r in sent)
    assert any(r.method == "GET" and r.url.path.endswith("/result") for r in sent)
    assert out and out[0].citations


@pytest.mark.asyncio
async def test_only_matched_candidates_become_evidence(monkeypatch):
    """A rejected candidate is the enumeration working, not a namesake.

    Passing rejects through would turn "we checked two people and neither is
    your character" into a finding about an unrelated real person.
    """
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    out = await _provider([]).enumerate(_request())

    names = [e.finding.get("name") for e in out]
    assert names == ["Jill Nakamura"]
    assert "Someone Else" not in names


@pytest.mark.asyncio
async def test_citations_and_confidence_come_off_the_basis(monkeypatch):
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    out = await _provider([]).enumerate(_request())

    ev = out[0]
    assert ev.citations[0].url == "https://example.gov/register/1"
    assert "registered 2004" in ev.citations[0].excerpt
    assert ev.confidence == pytest.approx(0.9)
    assert "register lists the name" in ev.reasoning


@pytest.mark.asyncio
async def test_a_create_error_fails_the_subject_with_its_reason(monkeypatch):
    """Fail closed, and say why. The reason being invisible is what let a dead
    integration look like an empty result set for the life of the project."""
    monkeypatch.setattr("truestory.providers.parallel_findall._POLL_INTERVAL_SECONDS", 0)
    out = await _provider([], create_status=422).enumerate(_request())

    assert len(out) == 1
    assert out[0].error
    assert "422" in out[0].error


# =============================================================================
# the three enumerations are three different questions
# =============================================================================


def test_each_enumeration_kind_names_its_population():
    """A namesake search that asks for "entities" gets companies."""
    assert _ENUMERATION_KINDS["findall_similar_persons"]["entity_type"] == "people"
    assert _ENUMERATION_KINDS["findall_matching_persons"]["entity_type"] == "people"
    assert _ENUMERATION_KINDS["findall_registered_entities"]["entity_type"] == "companies"


def test_every_enumeration_kind_is_fully_specified():
    for kind, spec in _ENUMERATION_KINDS.items():
        assert spec["entity_type"], kind
        assert spec["conditions"], kind
        assert "{pattern}" in spec["objective"], kind
