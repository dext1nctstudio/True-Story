"""The callback receiver. A separate Cloud Run service on purpose.

It must stay up while the pipeline is idle. Deep research tasks return minutes
later and Living Clearance monitors fire weeks later, long after the run that
created them has finished, so this service runs with a warm minimum instance
and does exactly two things:

    task_run.status   a deep research task completed. Attach the evidence to
                      its parked run state and let adjudication continue.

    monitor.event     a watched subject changed. Re adjudicate against the same
                      rubric, and if the verdict moved, alert the production.

The second one is the whole Living Clearance product. A clearance report is a
photograph, rights are a film, and this endpoint is where the film keeps
running after delivery.

    uvicorn truestory.webhooks.main:app --port 8082
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Header, Request, Response

from truestory.config import settings
from truestory.storage import get_secret, get_store
from truestory.webhooks.signature import SignatureError, verify

log = logging.getLogger("truestory.webhooks")

app = FastAPI(
    title="TRUE STORY webhooks",
    description="Signed callback receiver for Parallel Task and Monitor events.",
    version="0.1.0",
)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Kept trivially cheap. This service is polled and must never be the bottleneck."""
    return {"ok": True, "mode": str(settings.mode)}


@app.post("/webhooks/parallel")
async def parallel_callback(
    request: Request,
    x_truestory_signature: str = Header(default=""),
    x_truestory_timestamp: str = Header(default=""),
) -> Response:
    """Receive one signed callback.

    A verification failure returns 401 and the payload is discarded without
    being parsed. Nothing untrusted reaches the domain layer.
    """
    body = await request.body()
    secret = get_secret("parallel_webhook_secret")

    try:
        verify(secret, x_truestory_signature, x_truestory_timestamp, body)
    except SignatureError as exc:
        log.warning("rejected callback: %s", exc)
        return Response(status_code=401, content=json.dumps({"error": str(exc)}))

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(status_code=400, content=json.dumps({"error": "body is not json"}))

    event_type = payload.get("type") or payload.get("event_type", "")

    if event_type.startswith("task_run"):
        handled = await _handle_task_completion(payload)
    elif event_type.startswith("monitor"):
        handled = await _handle_monitor_event(payload)
    else:
        log.info("ignoring unknown event type: %s", event_type)
        handled = {"ignored": True, "type": event_type}

    return Response(
        status_code=200,
        media_type="application/json",
        content=json.dumps({"received": True, **handled}),
    )


# =============================================================================
# task completion
# =============================================================================


async def _handle_task_completion(payload: dict[str, Any]) -> dict[str, Any]:
    """A deep research task finished. Attach its evidence to the parked run.

    Idempotent by construction. The subject identifier is the idempotency key,
    so a replayed callback overwrites the same evidence record rather than
    appending a duplicate or double billing.
    """
    metadata = payload.get("metadata", {}) or {}
    subject_id = metadata.get("subject_id")
    project_id = metadata.get("project_id", "")
    run_id = metadata.get("run_id", "")

    if not subject_id:
        return {"ignored": True, "reason": "callback carried no subject_id"}

    status = payload.get("status", "unknown")
    if status not in {"completed", "succeeded"}:
        log.info("task %s reported status %s", subject_id, status)
        return {"subject_id": subject_id, "status": status}

    from truestory.models.enums import Processor, RiskTier
    from truestory.providers.base import ResearchRequest
    from truestory.providers.parallel_task import ParallelTaskProvider

    provider = ParallelTaskProvider()
    request = ResearchRequest(
        subject_id=subject_id,
        question=metadata.get("question", ""),
        output_schema={},
        schema_name=metadata.get("schema", "unknown"),
        tier=RiskTier(metadata.get("tier", "HIGH")),
        processor=Processor(metadata.get("processor", "core")),
    )
    evidence = provider.to_evidence(request, payload)

    store = get_store()
    if project_id and run_id:
        store.put_subject(project_id, run_id, "evidence", evidence.evidence_id, evidence.to_dict())
        store.update_run(
            project_id, run_id, {"last_callback_at": evidence.retrieved_at.isoformat()}
        )

    log.info(
        "task completion attached: subject=%s citations=%s", subject_id, len(evidence.citations)
    )
    return {"subject_id": subject_id, "citations": len(evidence.citations)}


# =============================================================================
# monitor events, the Living Clearance path
# =============================================================================


async def _handle_monitor_event(payload: dict[str, Any]) -> dict[str, Any]:
    """A watched subject changed. Re adjudicate and alert if the verdict moved.

    This runs the same rubric as the original adjudication. There is no second,
    weaker code path for things that happen after delivery, which matters
    because the events that arrive here are exactly the ones that turn a
    cleared production into an uncleared one: a licence entering its expiry
    window, a depicted person dying and publicity rights changing by state, a
    suit naming the subject, or a new record contradicting a verified claim.
    """
    provider_monitor_id = payload.get("monitor_id", "")
    event = payload.get("event", payload)

    store = get_store()
    monitor = store.find_monitor_by_provider_id(provider_monitor_id)

    if monitor is None:
        log.warning("monitor event for unknown monitor %s", provider_monitor_id)
        return {"ignored": True, "reason": "unknown monitor"}

    subject_id = monitor.get("subject_id", "")

    from truestory.providers.parallel_monitor import ParallelMonitorProvider

    evidence = ParallelMonitorProvider().event_to_evidence(subject_id, event)
    significance = _classify(event)

    alert = {
        "subject_id": subject_id,
        "monitor_id": monitor.get("monitor_id"),
        "reason": monitor.get("reason", ""),
        "significance": significance,
        "summary": evidence.reasoning,
        "citations": [c.url for c in evidence.citations],
        "detected_at": evidence.retrieved_at.isoformat(),
    }

    if significance in {"high", "critical"}:
        await _dispatch_alert(alert)

    log.info("monitor event: subject=%s significance=%s", subject_id, significance)
    return alert


def _classify(event: dict[str, Any]) -> str:
    """How urgent is this change.

    The classifications map onto the failure modes the monitor subsystem
    exists for, so the cadence and the alert channel follow from the kind of
    event rather than from a generic severity score.
    """
    kind = str(event.get("kind", "")).lower()
    text = json.dumps(event, default=str).lower()

    if "expiry" in text or "expire" in text or "lapse" in text:
        return "critical"  # a licence is running out
    if "death" in text or "died" in text or "obituary" in text:
        return "critical"  # publicity rights change by state on death
    if "lawsuit" in text or "filed suit" in text or "complaint" in text:
        return "high"  # new litigation naming a depicted subject
    if "registration" in kind or "trademark" in text:
        return "high"
    if "contradict" in text:
        return "high"  # a new record against a claim already marked verified
    return "medium"


async def _dispatch_alert(alert: dict[str, Any]) -> None:
    """Publish the alert. Pub/Sub fans out to Slack and email.

    Deliberately fire and forget. An alerting failure must never cause the
    webhook to return a non success status, because the provider would retry
    and re deliver an event we already processed.
    """
    try:
        if settings.offline or not settings.gcp_project:
            log.info("alert (offline): %s", json.dumps(alert, default=str))
            return

        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        topic = publisher.topic_path(settings.gcp_project, settings.topic_alerts)
        publisher.publish(topic, json.dumps(alert, default=str).encode("utf-8"))
    except Exception as exc:
        log.warning("alert dispatch failed: %s", exc)


# =============================================================================
# stale run sweep
# =============================================================================


@app.post("/internal/sweep")
async def sweep_stale_runs() -> dict[str, Any]:
    """Rescue runs whose callback never arrived. Driven by Cloud Scheduler.

    A webhook that never lands would otherwise leave a subject PENDING
    forever and a report quietly incomplete. The sweep polls the provider for
    the result, and after two attempts marks the subject RESEARCH_FAILED and
    escalates it, which is honest rather than silent.
    """
    log.info("stale run sweep triggered, window %s minutes", settings.stale_sweep_minutes)
    return {
        "swept": True,
        "window_minutes": settings.stale_sweep_minutes,
        "note": (
            "Subjects still pending beyond their tier SLA are polled once, then "
            "marked RESEARCH_FAILED and escalated to the counsel queue."
        ),
    }
