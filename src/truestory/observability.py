"""Tracing, structured logging, and the cost meter feed.

Every Evidence record carries cost, latency, provider and cache status, which
means the observability story is not instrumentation bolted on afterwards. It
is the same data the report already needs, routed to a second destination.

What that buys, in the order a buyer asks for it:

    live cost meter          the best recurring visual in the demo
    cost per script          the unit economics slide, from real rows
    cache hit rate           the draft over draft argument, measured
    fallback rate            provider health, and report coverage quality
    counsel escalation rate  how much human work is left. The first question
                             any studio buyer asks.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any

from truestory.config import settings

_TRACER: Any = None


# =============================================================================
# logging
# =============================================================================


class JsonFormatter(logging.Formatter):
    """Structured logs so Cloud Logging fields are queryable rather than grep bait."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Plain text locally, structured JSON when deployed."""
    handler = logging.StreamHandler(sys.stdout)
    if settings.env_name == "local":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)-28s %(message)s", "%H:%M:%S")
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # These are chatty and say nothing useful about this system.
    for noisy in ("httpx", "urllib3", "google.auth", "google.api_core"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# =============================================================================
# tracing
# =============================================================================


def configure_tracing() -> Any:
    """Cloud Trace spans per pipeline stage. Silently skipped when offline."""
    global _TRACER
    if _TRACER is not None or settings.offline or not settings.gcp_project:
        return _TRACER

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.gcp_project))
        )
        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("truestory")
    except Exception as exc:  # noqa: BLE001 - observability never breaks a run
        logging.getLogger("truestory.observability").debug("tracing unavailable: %s", exc)
    return _TRACER


@contextmanager
def span(name: str, **attributes: Any) -> Any:
    """Trace one stage. A no op context manager when tracing is unavailable."""
    tracer = configure_tracing()
    started = time.perf_counter()

    if tracer is None:
        yield None
    else:
        with tracer.start_as_current_span(name) as active:
            for key, value in attributes.items():
                active.set_attribute(key, value)
            yield active

    elapsed_ms = (time.perf_counter() - started) * 1000
    logging.getLogger("truestory.timing").debug("%s took %.0fms", name, elapsed_ms)


# =============================================================================
# metrics
# =============================================================================


class RunMetrics:
    """In process counters, mirrored to BigQuery for anything durable."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.started_at = time.perf_counter()
        self.stage_durations: dict[str, float] = {}
        self.counters: dict[str, int] = {}
        self.cost_cents = 0.0

    @contextmanager
    def stage(self, name: str) -> Any:
        started = time.perf_counter()
        with span(f"truestory.{name}", run_id=self.run_id):
            yield
        self.stage_durations[name] = time.perf_counter() - started

    def increment(self, key: str, by: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + by

    def add_cost(self, cents: float) -> None:
        self.cost_cents += cents

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "cost_cents": round(self.cost_cents, 4),
            "cost_usd": round(self.cost_cents / 100, 4),
            "counters": dict(self.counters),
            "stages": {k: round(v, 3) for k, v in self.stage_durations.items()},
        }


def log_adjudication(
    subject_id: str, verdict: str, confidence: float, evidence_ids: list[str], principal: str = "system"
) -> None:
    """Every adjudication is logged with the evidence behind it.

    This is an audit obligation rather than debugging. When a production is
    asked, years later, on what basis it cleared a line, the answer has to be
    retrievable and has to name the evidence it rested on.
    """
    logger = logging.getLogger("truestory.audit")
    record = logging.LogRecord(
        name="truestory.audit",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=f"adjudication {subject_id} -> {verdict}",
        args=(),
        exc_info=None,
    )
    record.extra_fields = {  # type: ignore[attr-defined]
        "subject_id": subject_id,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_ids": evidence_ids,
        "principal": principal,
        "audit": True,
    }
    logger.handle(record)


def init() -> None:
    """Call once at process start."""
    configure_logging()
    configure_tracing()
