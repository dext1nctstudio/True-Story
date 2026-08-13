"""Parallel Task provider. The core verification and clearance research path.

Task is a multi hop research agent that takes an objective and an output
schema and returns structured, cited findings. It is the single most used
provider in the system: every factual claim and every CRITICAL element goes
through it, tier routed to a processor depth.

Two implementation notes that matter for the demo:

  * The `-fast` processor variants cost the same as the standard ones and skip
    live crawling. Latency drops enough that the on camera run stays
    synchronous, which is why the overlay fills in live instead of showing a
    spinner. Set PARALLEL_USE_FAST_VARIANTS=false for batch work where depth
    matters more than latency.

  * Deep processors are dispatched with a webhook callback and the run state is
    parked in Firestore. `investigate` awaits inline for lite and base, and
    returns a PENDING envelope for core and above when async dispatch is on.
"""

from __future__ import annotations

from typing import Any

import httpx

from truestory.config import settings
from truestory.models.enums import Processor
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import (
    ProviderError,
    RateLimited,
    ResearchProvider,
    ResearchRequest,
)


class ParallelTaskProvider(ResearchProvider):
    """Structured multi hop research with citations and calibrated confidence."""

    name = "parallel_task"
    supports_citations = True
    supports_async = True

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
        self._healthy = True

    # ── client ───────────────────────────────────────────────────────────────
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(settings.parallel_timeout_seconds),
                headers={
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "user-agent": "truestory/0.1 (clearance pipeline)",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            resp = await self._http().get("/v1/health", timeout=5.0)
            self._healthy = resp.status_code < 500
        except Exception:  # noqa: BLE001 - health probes never raise upward
            self._healthy = False
        return self._healthy

    # ── the call ─────────────────────────────────────────────────────────────
    async def investigate(self, request: ResearchRequest) -> Evidence:
        processor = settings.processor(str(request.processor))
        payload = self._build_payload(request, processor)

        with self._timed() as timing:
            try:
                resp = await self._http().post("/v1/tasks/runs", json=payload)

                if resp.status_code == 429:
                    raise RateLimited(self.name, float(resp.headers.get("retry-after", 30)))
                if resp.status_code >= 400:
                    raise ProviderError(
                        self.name,
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                        retryable=resp.status_code >= 500,
                    )

                body = resp.json()

            except RateLimited:
                raise
            except httpx.TimeoutException:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    "timeout awaiting Parallel Task",
                )
            except ProviderError as exc:
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    str(exc),
                )
            except Exception as exc:  # noqa: BLE001 - one bad subject, not one bad run
                return Evidence.failed(
                    request.subject_id,
                    request.question,
                    self._qualified_name(request.processor),
                    f"unexpected: {type(exc).__name__}: {exc}",
                )

        # Deep processors may return a handle rather than a result. The webhook
        # receiver completes the record when the callback lands.
        if body.get("status") in {"queued", "running"} and "run_id" in body:
            return self._pending(request, body["run_id"], timing["latency_ms"])

        return self.to_evidence(request, body, timing["latency_ms"])

    # ── payload ──────────────────────────────────────────────────────────────
    def _build_payload(self, request: ResearchRequest, processor: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "processor": processor,
            "input": request.question,
            "task_spec": {
                "output_schema": {
                    "type": "json",
                    "json_schema": request.output_schema,
                }
            },
            "metadata": {
                "subject_id": request.subject_id,
                "schema": request.schema_name,
                "tier": str(request.tier),
                "jurisdictions": list(request.jurisdictions),
                "env": settings.env_name,
            },
        }
        if request.idempotency_key:
            payload["metadata"]["idempotency_key"] = request.idempotency_key

        # Async dispatch for the deep processors. The receiver verifies the
        # signature on every inbound callback before it touches run state.
        if request.processor in (Processor.CORE, Processor.PRO, Processor.ULTRA):
            if settings.parallel_webhook_url:
                payload["webhook"] = {
                    "url": settings.parallel_webhook_url,
                    "event_types": ["task_run.status"],
                }
        return payload

    def _pending(self, request: ResearchRequest, run_id: str, latency_ms: int) -> Evidence:
        return Evidence(
            evidence_id=Evidence.make_id(
                request.subject_id, request.question, self._qualified_name(request.processor)
            ),
            subject_id=request.subject_id,
            question=request.question,
            finding={"status": "pending", "provider_run_id": run_id},
            citations=[],
            reasoning="Dispatched to Parallel Task. Awaiting webhook callback.",
            confidence=0.0,
            provider=self._qualified_name(request.processor),
            schema_version=request.schema_name,
            latency_ms=latency_ms,
            cost_cents=request.processor.usd_per_run * 100,
        )

    # ── response mapping ─────────────────────────────────────────────────────
    def to_evidence(
        self,
        request: ResearchRequest,
        body: dict[str, Any],
        latency_ms: int = 0,
    ) -> Evidence:
        """Map a Task response onto the Evidence envelope.

        This is the seam where the Basis framework does its work. Parallel
        returns citations, reasoning, excerpts and a calibrated confidence per
        output field, which is why the mapping is close to one to one rather
        than a scraping exercise. A partner whose core differentiator is
        evidence is the right partner for a product whose output is a statement
        that a line about a real person is false.
        """
        output = body.get("output", {})
        content = output.get("content", output) if isinstance(output, dict) else {}
        basis = output.get("basis", []) if isinstance(output, dict) else []

        citations = self._citations_from_basis(basis)
        confidence = self._confidence_from_basis(basis)
        reasoning = self._reasoning_from_basis(basis)

        return Evidence(
            evidence_id=Evidence.make_id(
                request.subject_id, request.question, self._qualified_name(request.processor)
            ),
            subject_id=request.subject_id,
            question=request.question,
            finding=content if isinstance(content, dict) else {"value": content},
            citations=citations,
            reasoning=reasoning,
            confidence=confidence,
            provider=self._qualified_name(request.processor),
            schema_version=request.schema_name,
            cost_cents=request.processor.usd_per_run * 100,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _citations_from_basis(basis: list[dict[str, Any]]) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[str] = set()
        for field_basis in basis:
            for cit in field_basis.get("citations", []) or []:
                url = cit.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                citations.append(
                    Citation(
                        url=url,
                        title=cit.get("title") or url,
                        excerpt=(cit.get("excerpt") or "")[:1200],
                        source_type=cit.get("source_type", "secondary"),
                        publisher=cit.get("publisher"),
                    )
                )
        return citations

    @staticmethod
    def _confidence_from_basis(basis: list[dict[str, Any]]) -> float:
        """Take the weakest field level confidence, not the average.

        An answer is only as good as its least supported component, and
        averaging is how an unsupported field hides behind four solid ones.
        """
        scores: list[float] = []
        for field_basis in basis:
            raw = field_basis.get("confidence")
            if isinstance(raw, int | float):
                scores.append(float(raw))
            elif isinstance(raw, str):
                scores.append({"high": 0.9, "medium": 0.7, "low": 0.4}.get(raw.lower(), 0.5))
        return min(scores) if scores else 0.5

    @staticmethod
    def _reasoning_from_basis(basis: list[dict[str, Any]]) -> str:
        parts = [
            f"{fb.get('field', 'output')}: {fb['reasoning']}"
            for fb in basis
            if fb.get("reasoning")
        ]
        return "\n".join(parts) if parts else "No reasoning trace returned."
