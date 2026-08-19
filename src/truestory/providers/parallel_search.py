"""Parallel Search provider. The interrogation path.

Search is a single round trip: a natural language objective in, LLM optimised
excerpts out, in under five seconds. It is the wrong tool for the two hundred
subject fan out and exactly the right tool for the question a user asks while
looking at the overlay, which is always some version of "why is this line red".

Cheap enough that the interactive path is a rounding error against the run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    ProviderError,
    RateLimited,
    ResearchProvider,
    ResearchRequest,
)


class ParallelSearchProvider(ResearchProvider):
    name = "parallel_search"
    supports_citations = True
    supports_async = False
    #: $1 per 1000 requests in turbo mode, $5 per 1000 in advanced, plus $1 per
    #: 1000 for each result past the tenth. Verified 19 August 2026 against
    #: https://docs.parallel.ai/getting-started/pricing
    unit_cost_cents = 0.1

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        mode: str = "advanced",
    ) -> None:
        self.api_key = api_key or settings.parallel_api_key
        self.base_url = (base_url or settings.parallel_api_base).rstrip("/")
        # The API takes `mode`, and the only two values it accepts are these.
        # "one_shot" was neither, so every interactive search 422'd.
        self.mode = mode if mode in {"turbo", "advanced"} else "advanced"
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0),
                headers={"x-api-key": self.api_key, "content-type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def investigate(self, request: ResearchRequest) -> Evidence:
        payload: dict[str, Any] = {
            "objective": request.question,
            # The service derives its own queries from the objective, and a
            # couple of literal ones alongside measurably improve recall on
            # name plus attribute questions, which is most of what gets asked
            # here. `search_queries` is required, so an empty list was a 422.
            "search_queries": list(request.search_queries) or _queries_from(request.question),
            "mode": self.mode,
            "max_results": request.max_results,
            "max_chars_per_result": 1500,
        }

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1/search", json=payload)
                if resp.status_code == 429:
                    raise RateLimited(self.name, float(resp.headers.get("retry-after", 15)))
                if resp.status_code >= 400:
                    raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
            except RateLimited:
                raise
            except Exception as exc:
                return Evidence.failed(request.subject_id, request.question, self.name, str(exc))

        results = body.get("results", [])
        citations = [
            Citation.classified(
                url=r.get("url", ""),
                title=r.get("title") or r.get("url", ""),
                excerpt=" … ".join(r.get("excerpts") or [])[:1200],
                declared_type="secondary",
                published_at=_parse_publish_date(r.get("publish_date")),
            )
            for r in results
            if r.get("url")
        ]

        # $1 per 1000 requests for the first ten results, then $1 per 1000 for
        # each result beyond that. Charging per result from the first one, as
        # this did, overstated an interactive search by roughly tenfold.
        cost = self.unit_cost_cents * (1 if self.mode == "turbo" else 5)
        cost += max(0, len(results) - _INCLUDED_RESULTS) * 0.1
        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding={"results": results, "result_count": len(results)},
            citations=citations,
            reasoning="Single round trip search. Excerpts returned without multi hop verification.",
            # Deliberately capped. Search excerpts are a lead, not a finding,
            # and must never present as equal to a Task verification run.
            confidence=0.55 if citations else 0.0,
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=cost,
            latency_ms=timing["latency_ms"],
        )


#: Results included in the base request price before per result charges start.
_INCLUDED_RESULTS = 10


def _queries_from(objective: str) -> list[str]:
    """Two literal queries derived from the objective.

    The API requires the field and answers better with a concrete query
    alongside the natural language objective. Taking the first line and the
    longest quoted or capitalised run is enough: the objective templates in
    mcp/tools.py already put the subject on the first line.
    """
    lines = [line.strip() for line in objective.splitlines() if line.strip()]
    if not lines:
        return [objective[:120]]
    queries = [lines[0][:180]]
    for line in lines[1:]:
        if ":" in line:
            value = line.split(":", 1)[1].strip()
            if len(value) > 8:
                queries.append(value[:180])
        if len(queries) >= 3:
            break
    return queries


def _parse_publish_date(value: Any) -> datetime | None:
    """Search results carry `publish_date`; a source's age governs its weight."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
