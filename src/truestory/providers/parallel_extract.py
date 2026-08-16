"""Parallel Extract provider. The evidence pack.

Extract turns a URL into clean markdown, including pages that only render under
JavaScript and documents that are really PDFs. Its job here is preservation
rather than discovery: a trademark register page, a court docket, an archive
record, captured at a known timestamp into the evidence pack.

That matters at claim time rather than at report time. A finding that cites a
page which has since changed is worth much less to an underwriter than a
finding that cites a page the production captured on the day it was read.
"""

from __future__ import annotations

from typing import Any

import httpx

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import ProviderError, ResearchProvider, ResearchRequest


class ParallelExtractProvider(ResearchProvider):
    name = "parallel_extract"
    supports_citations = True
    supports_async = False
    unit_cost_cents = 0.5

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or settings.parallel_api_key
        self.base_url = (base_url or settings.parallel_api_base).rstrip("/")
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(90.0),
                headers={"x-api-key": self.api_key, "content-type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def investigate(self, request: ResearchRequest) -> Evidence:
        """Here `question` carries the URL to capture, set by the tool layer."""
        url = request.context or request.question

        payload: dict[str, Any] = {
            "urls": [url],
            "excerpts": True,
            "full_content": True,
        }

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1beta/extract", json=payload)
                if resp.status_code >= 400:
                    raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
            except Exception as exc:
                return Evidence.failed(request.subject_id, url, self.name, str(exc))

        results = body.get("results", [])
        if not results:
            return Evidence.failed(request.subject_id, url, self.name, "no content extracted")

        page = results[0]
        content = page.get("full_content") or " ".join(page.get("excerpts", []))

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, url, self.name),
            subject_id=request.subject_id,
            question=f"Capture the page at {url} into the evidence pack.",
            finding={
                "url": url,
                "title": page.get("title"),
                "content_markdown": content,
                "char_count": len(content),
                # The captured markdown is written to GCS by the tool layer and
                # the object path is stamped back here, so the evidence
                # appendix can link the preserved copy alongside the live URL.
                "archived_object": None,
            },
            citations=[
                Citation(
                    url=url,
                    title=page.get("title") or url,
                    excerpt=content[:1200],
                    source_type="primary",
                )
            ],
            reasoning="Page captured verbatim for the evidence appendix.",
            confidence=0.95 if content else 0.0,
            provider=self.name,
            schema_version=request.schema_name,
            cost_cents=self.unit_cost_cents,
            latency_ms=timing["latency_ms"],
        )
