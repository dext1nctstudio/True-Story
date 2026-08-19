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

from typing import Any

import httpx

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    EnumerationProvider,
    ProviderError,
    RateLimited,
    ResearchRequest,
)

#: tier -> (base cost cents, per match cents). Preview is the testing tier.
_TIERS: dict[str, tuple[float, float]] = {
    "preview": (10.0, 0.0),
    "base": (25.0, 3.0),
    "core": (200.0, 15.0),
}


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
        self.api_key = api_key or settings.parallel_api_key
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

    async def enumerate(self, request: ResearchRequest) -> list[Evidence]:
        payload: dict[str, Any] = {
            "query": request.question,
            "processor": self.tier,
            "result_schema": request.output_schema,
            "max_results": request.max_results,
            "metadata": {
                "subject_id": request.subject_id,
                "jurisdictions": list(request.jurisdictions),
            },
        }

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1beta/findall/runs", json=payload)
                if resp.status_code == 429:
                    raise RateLimited(self.name, float(resp.headers.get("retry-after", 300)))
                if resp.status_code >= 400:
                    raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
            except RateLimited:
                raise
            except Exception as exc:
                return [Evidence.failed(request.subject_id, request.question, self.name, str(exc))]

        base_cost, per_match = _TIERS.get(self.tier, _TIERS["preview"])
        entities = body.get("results", []) or []
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
                for c in (entity.get("citations") or [])
                if c.get("url")
            ]
            out.append(
                Evidence(
                    evidence_id=Evidence.make_id(
                        request.subject_id, f"{request.question}#{i}", self.name
                    ),
                    subject_id=request.subject_id,
                    question=request.question,
                    finding=entity.get("data", entity),
                    citations=citations,
                    reasoning=entity.get("reasoning", ""),
                    confidence=float(entity.get("confidence", 0.7)),
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


def _excerpt_of(citation: dict) -> str:
    """FindAll citations carry `excerpts` as a list, same as Task's basis."""
    excerpts = citation.get("excerpts")
    if isinstance(excerpts, list):
        joined = " … ".join(str(e).strip() for e in excerpts if str(e).strip())
        if joined:
            return joined
    return str(citation.get("excerpt") or "")
