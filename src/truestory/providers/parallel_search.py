"""Parallel Search provider. The interrogation path.

Search is a single round trip: a natural language objective in, LLM optimised
excerpts out, in under five seconds. It is the wrong tool for the two hundred
subject fan out and exactly the right tool for the question a user asks while
looking at the overlay, which is always some version of "why is this line red".

Cheap enough that the interactive path is a rounding error against the run.
"""

from __future__ import annotations

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
    unit_cost_cents = 0.1  # base rate, rises with additional results

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        mode: str = "one_shot",
    ) -> None:
        self.api_key = api_key or settings.parallel_api_key
        self.base_url = (base_url or settings.parallel_api_base).rstrip("/")
        self.mode = mode  # one_shot | advanced
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
            "search_queries": [],  # let the service derive them from the objective
            "processor": self.mode,
            "max_results": request.max_results,
            "max_chars_per_result": 1500,
        }

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1beta/search", json=payload)
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
            Citation(
                url=r.get("url", ""),
                title=r.get("title") or r.get("url", ""),
                excerpt=" ".join(r.get("excerpts", []))[:1200],
                source_type="secondary",
            )
            for r in results
            if r.get("url")
        ]

        cost = self.unit_cost_cents + max(0, len(results) - 1) * 0.1
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
