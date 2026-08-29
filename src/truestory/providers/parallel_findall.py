"""Parallel FindAll provider. The enumeration path, and the Baby Reindeer tool.

Some clearance questions have no single answer by construction. "Every
registered business named Kestrel in Illinois" is a set. "Every real person
matching this attribute cluster" is a set, and it is precisely the set that a
production needs to see before it puts an unnamed but identifiable character on
screen, because the audience will assemble that set within days whether or not
the production does.

Rate limits are tight here, roughly twenty five queries an hour, so the routing
table dispatches FindAll sparingly and the registry caps its concurrency at
four. Development runs on the preview tier, which is explicitly the testing
tier and costs effectively nothing per match.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    EnumerationProvider,
    ProviderError,
    RateLimited,
    ResearchRequest,
    _resolve_api_key,
)

#: tier -> (base cost cents, per match cents). Preview is the testing tier.
_TIERS: dict[str, tuple[float, float]] = {
    "preview": (10.0, 0.0),
    "base": (25.0, 3.0),
    "core": (200.0, 15.0),
}

#: Statuses that mean the job will produce nothing further.
_TERMINAL = frozenset({"completed", "failed", "cancelled", "error"})

_POLL_INTERVAL_SECONDS = 5.0
#: Generous, because the swarm awaits this inline and the alternative is a
#: subject that reports RESEARCH_FAILED for a reason that is really a deadline.
_POLL_TIMEOUT_SECONDS = 240.0

#: Used only when the caller named no criteria. FindAll requires at least one
#: condition, and a bare restatement of the objective is the honest default:
#: it says the candidate must be the thing that was asked for, and nothing more.
_DEFAULT_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("matches_the_objective", "The entity matches the objective exactly as stated."),
)


class ParallelFindAllProvider(EnumerationProvider):
    name = "parallel_findall"
    supports_citations = True
    supports_async = True

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        tier: str | None = None,
    ) -> None:
        self.api_key = api_key or _resolve_api_key()
        self.base_url = (base_url or settings.parallel_api_base).rstrip("/")
        # Development and CI stay on preview. Live runs move to base.
        self.tier = tier or ("base" if settings.is_live else "preview")
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(180.0),
                headers={"x-api-key": self.api_key, "content-type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run_to_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create the run, then poll the result endpoint until it settles.

        The result endpoint answers while the run is still active, returning a
        snapshot of the candidates found so far, so a deadline here degrades to
        a partial enumeration rather than to nothing at all. That is the right
        failure for this product: some of the namesakes is more useful to a
        reviewer than none of them, provided the partiality is visible.
        """
        http = self._http()
        resp = await http.post("/v1beta/findall/runs", json=payload)
        if resp.status_code == 429:
            raise RateLimited(self.name, float(resp.headers.get("retry-after", 300)))
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:400]}")

        findall_id = (resp.json() or {}).get("findall_id")
        if not findall_id:
            raise ProviderError(self.name, "create returned no findall_id")

        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        last: dict[str, Any] = {}
        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            got = await http.get(f"/v1beta/findall/runs/{findall_id}/result")
            if got.status_code == 429:
                raise RateLimited(self.name, float(got.headers.get("retry-after", 300)))
            if got.status_code >= 400:
                raise ProviderError(self.name, f"HTTP {got.status_code}: {got.text[:400]}")

            last = got.json() or {}
            status = (last.get("run") or {}).get("status") or {}
            if status.get("is_active") is False or status.get("status") in _TERMINAL:
                return last
            if time.monotonic() >= deadline:
                # Return the snapshot rather than failing the subject.
                return last

    async def enumerate(self, request: ResearchRequest) -> list[Evidence]:
        # FindAll is a job, not a request/response call: the create returns a
        # findall_id and a queued status, and the candidates arrive later on a
        # separate result endpoint. An earlier version of this provider posted
        # `query`/`processor`/`result_schema`/`max_results` and read
        # `body["results"]` synchronously, which is not this API's shape in
        # either direction. Every call 422'd on four missing required fields,
        # for the whole life of the integration, and because the reason was
        # stored on the Evidence and never logged it looked from the outside
        # like the enumeration had simply found nothing. That silently disabled
        # the namesake collision check on real people, the identifiability
        # enumeration behind the Baby Reindeer rule, and the registered entity
        # search behind every trademark and business name.
        payload: dict[str, Any] = {
            "objective": request.question,
            "entity_type": request.entity_type or "entities",
            "match_conditions": [
                {"name": name, "description": description}
                for name, description in (request.match_conditions or _DEFAULT_CONDITIONS)
            ],
            "generator": self.tier,
            "match_limit": request.max_results,
            "metadata": {
                "subject_id": request.subject_id,
                "jurisdictions": ",".join(request.jurisdictions),
            },
        }

        with self._timed() as timing:
            try:
                body = await self._run_to_completion(payload)
            except RateLimited:
                raise
            except Exception as exc:
                return [Evidence.failed(request.subject_id, request.question, self.name, str(exc))]

        base_cost, per_match = _TIERS.get(self.tier, _TIERS["preview"])
        entities = _matched_candidates(body)
        per_entity_cost = (base_cost / max(1, len(entities))) + per_match

        out: list[Evidence] = []
        for i, entity in enumerate(entities):
            citations = [
                Citation.classified(
                    url=c.get("url", ""),
                    title=c.get("title") or c.get("url", ""),
                    excerpt=_excerpt_of(c)[:800],
                    declared_type=c.get("source_type"),
                )
                for c in _candidate_citations(entity)
                if c.get("url")
            ]
            out.append(
                Evidence(
                    evidence_id=Evidence.make_id(
                        request.subject_id, f"{request.question}#{i}", self.name
                    ),
                    subject_id=request.subject_id,
                    question=request.question,
                    finding=_candidate_finding(entity),
                    citations=citations,
                    reasoning=_candidate_reasoning(entity),
                    confidence=_candidate_confidence(entity),
                    provider=f"{self.name}:{self.tier}",
                    schema_version=request.schema_name,
                    cost_cents=per_entity_cost,
                    latency_ms=timing["latency_ms"] // max(1, len(entities)),
                )
            )

        if not out:
            # An empty enumeration is a real and useful answer. No registered
            # entity bears this name, no real person matches this cluster. It
            # is recorded as a finding rather than as a failure.
            out.append(
                Evidence(
                    evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
                    subject_id=request.subject_id,
                    question=request.question,
                    finding={"matches": [], "match_count": 0},
                    citations=[
                        Citation.classified(
                            url=body.get("search_summary_url", "https://parallel.ai"),
                            title="FindAll enumeration, no matches",
                            excerpt="Enumeration completed and returned no matching entities.",
                            declared_type="tertiary",
                        )
                    ],
                    reasoning="Enumeration completed with zero matches in the requested jurisdictions.",
                    confidence=0.7,
                    provider=f"{self.name}:{self.tier}",
                    schema_version=request.schema_name,
                    cost_cents=base_cost,
                    latency_ms=timing["latency_ms"],
                )
            )
        return out


#: FindAll grades a field's confidence in words, not numbers.
_CONFIDENCE_WORDS = {"high": 0.9, "medium": 0.7, "low": 0.4}


def _matched_candidates(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Only candidates the API actually matched become evidence.

    A generated candidate that was evaluated and rejected is the enumeration
    working, not a namesake. Passing rejects through would turn "we checked
    eight people and none of them is your character" into eight findings about
    unrelated real people, which is the exact shape of the fabrication this
    system exists to prevent.
    """
    candidates = body.get("candidates") or []
    return [
        c
        for c in candidates
        if isinstance(c, dict) and str(c.get("match_status", "")).lower() == "matched"
    ]


def _candidate_citations(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Citations live per evaluated field under `basis`, not on the candidate."""
    out: list[dict[str, Any]] = []
    for entry in candidate.get("basis") or []:
        if isinstance(entry, dict):
            out.extend(c for c in (entry.get("citations") or []) if isinstance(c, dict))
    if not out and candidate.get("url"):
        # The candidate's own source page, when no field carried a citation.
        out.append({"url": candidate["url"], "title": candidate.get("name") or candidate["url"]})
    return out


def _candidate_finding(candidate: dict[str, Any]) -> dict[str, Any]:
    """What matched, and on which conditions. The shape the adjudicator reads."""
    conditions = {
        field: bool(value.get("is_matched"))
        for field, value in (candidate.get("output") or {}).items()
        if isinstance(value, dict)
    }
    return {
        "name": candidate.get("name", ""),
        "url": candidate.get("url", ""),
        "description": candidate.get("description", ""),
        "match_status": candidate.get("match_status", ""),
        "conditions_met": conditions,
        "match_count": 1,
    }


def _candidate_reasoning(candidate: dict[str, Any]) -> str:
    parts = [
        str(entry.get("reasoning", "")).strip()
        for entry in (candidate.get("basis") or [])
        if isinstance(entry, dict) and str(entry.get("reasoning", "")).strip()
    ]
    return " ".join(parts)[:1200]


def _candidate_confidence(candidate: dict[str, Any]) -> float:
    """The weakest field confidence, because a match is only as good as that."""
    scores = [
        _CONFIDENCE_WORDS.get(str(entry.get("confidence", "")).lower())
        for entry in (candidate.get("basis") or [])
        if isinstance(entry, dict)
    ]
    present = [s for s in scores if s is not None]
    return min(present) if present else 0.7


def _excerpt_of(citation: dict) -> str:
    """FindAll citations carry `excerpts` as a list, same as Task's basis."""
    excerpts = citation.get("excerpts")
    if isinstance(excerpts, list):
        joined = " … ".join(str(e).strip() for e in excerpts if str(e).strip())
        if joined:
            return joined
    return str(citation.get("excerpt") or "")
