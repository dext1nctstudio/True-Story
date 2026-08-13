"""Parallel Monitor provider. Living Clearance.

A clearance report is a photograph. Rights are a film.

Monitor runs a query on a schedule, deduplicates automatically, and delivers
new events by webhook. That converts a one off deliverable into a subscription,
which is both the product's recurring revenue story and the fix for a failure
mode with a long history: music licensed on a ten year term, the term lapsing
quietly after cancellation, and the show going out in syndication with sound
alikes for thirty years because nobody was watching the expiry date.

For adapted reality productions the monitors also watch the facts, not just the
rights. A depicted person dies and publicity rights change by state. A related
suit is filed. A new record surfaces that contradicts a claim this system
already marked verified.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence, MonitorHandle
from truestory.providers.base import ProviderError, ResearchProvider, ResearchRequest

_CADENCE_TO_CRON: dict[str, str] = {
    "daily": "0 6 * * *",
    "weekly": "0 6 * * 1",
    "monthly": "0 6 1 * *",
    "quarterly": "0 6 1 */3 *",
}


class ParallelMonitorProvider(ResearchProvider):
    name = "parallel_monitor"
    supports_citations = True
    supports_async = True
    unit_cost_cents = 0.3  # per check, lite cadence

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
                timeout=httpx.Timeout(60.0),
                headers={"x-api-key": self.api_key, "content-type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── creating a watch ─────────────────────────────────────────────────────
    async def watch(
        self,
        subject_id: str,
        query: str,
        cadence: str = "monthly",
        *,
        reason: str = "",
        expiry_hint: datetime | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> MonitorHandle:
        """Create a recurring watch and return the handle stored in Firestore."""
        effective = self._tighten_for_expiry(cadence, expiry_hint)

        payload: dict[str, Any] = {
            "query": query,
            "schedule": _CADENCE_TO_CRON.get(effective, _CADENCE_TO_CRON["monthly"]),
            "processor": "lite",
            "deduplicate": True,
            "webhook": {
                "url": settings.parallel_webhook_url,
                "event_types": ["monitor.event"],
            },
            "metadata": {"subject_id": subject_id, "reason": reason},
        }
        if output_schema:
            payload["result_schema"] = output_schema

        try:
            resp = await self._http().post("/v1beta/monitors", json=payload)
            if resp.status_code >= 400:
                raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            provider_id = body.get("monitor_id", "")
        except Exception as exc:  # noqa: BLE001
            # A failed monitor is a manifest entry that says so. It never
            # silently reduces to no watch at all, because the whole promise of
            # Living Clearance is that somebody is looking.
            provider_id = ""
            reason = f"{reason} (creation failed: {exc})".strip()

        return MonitorHandle(
            monitor_id=f"mon_{uuid.uuid4().hex[:16]}",
            subject_id=subject_id,
            provider_monitor_id=provider_id,
            query=query,
            cadence=effective,
            reason=reason,
            expiry_hint=expiry_hint,
            active=bool(provider_id),
        )

    @staticmethod
    def _tighten_for_expiry(cadence: str, expiry_hint: datetime | None) -> str:
        """Inside the expiry window, check weekly regardless of the default.

        The point of the whole subsystem is to alert before the licence lapses
        rather than after, so the cadence follows the term rather than the
        element type once the term is known.
        """
        if expiry_hint is None:
            return cadence
        days_remaining = (expiry_hint - datetime.now(UTC)).days
        if days_remaining <= 180:
            return "weekly"
        return cadence

    async def unwatch(self, provider_monitor_id: str) -> bool:
        try:
            resp = await self._http().delete(f"/v1beta/monitors/{provider_monitor_id}")
            return resp.status_code < 400
        except Exception:  # noqa: BLE001
            return False

    # ── inbound events ───────────────────────────────────────────────────────
    def event_to_evidence(self, subject_id: str, event: dict[str, Any]) -> Evidence:
        """Map a monitor callback into the same envelope everything else uses.

        A monitor event re enters the pipeline at the Adjudicator, so an
        expired licence or a newly filed suit is adjudicated against the same
        rubric as the original finding. There is no second, weaker code path
        for things that happen after delivery.
        """
        citations = [
            Citation(
                url=c.get("url", ""),
                title=c.get("title") or c.get("url", ""),
                excerpt=(c.get("excerpt") or "")[:1000],
                source_type=c.get("source_type", "secondary"),
            )
            for c in (event.get("citations") or [])
            if c.get("url")
        ]

        return Evidence(
            evidence_id=Evidence.make_id(
                subject_id, event.get("event_id", "monitor_event"), self.name
            ),
            subject_id=subject_id,
            question=event.get("query", "monitored subject"),
            finding=event.get("data", event),
            citations=citations,
            reasoning=event.get("summary", "New event observed on a monitored subject."),
            confidence=float(event.get("confidence", 0.7)),
            provider=self.name,
            schema_version=event.get("schema", "monitor_event_v1"),
            cost_cents=self.unit_cost_cents,
        )

    async def investigate(self, request: ResearchRequest) -> Evidence:
        """Monitor is a scheduling primitive, so a direct call creates the watch."""
        handle = await self.watch(
            subject_id=request.subject_id,
            query=request.question,
            cadence=request.context or "monthly",
            output_schema=request.output_schema,
        )
        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=handle.to_dict(),
            citations=[
                Citation(
                    url="https://parallel.ai/monitor",
                    title="Monitor created",
                    excerpt=f"Recurring watch established at {handle.cadence} cadence.",
                    source_type="tertiary",
                )
            ],
            reasoning=f"Watch created: {handle.reason or 'ongoing rights and facts surveillance'}.",
            confidence=1.0 if handle.active else 0.0,
            provider=self.name,
            schema_version="monitor_handle_v1",
            cost_cents=self.unit_cost_cents,
        )
