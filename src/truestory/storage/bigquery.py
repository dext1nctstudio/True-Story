"""BigQuery. Telemetry, evaluation results, and the precedent corpus.

Three tables, three purposes:

    cost_telemetry    one row per Evidence. Every unit economics number in the
                      pitch is a query against this table rather than an
                      estimate, including cost per script, cost per claim type,
                      cache hit rate, fallback rate, and the counsel escalation
                      rate that a studio buyer asks about first.

    eval_results      Litigation Set and labelled script runs, versioned by
                      rubric so a rubric change is visible as a change in
                      measured accuracy rather than a vibe.

    precedent_corpus  past adjudications with embeddings. Vector search over
                      this is precedent retrieval: this element type, in this
                      jurisdiction, has been cleared forty times before and
                      here is the pattern. It compounds with use, which is the
                      part of the moat that is not in the repository.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from truestory.config import settings
from truestory.models.evidence import Evidence

log = logging.getLogger("truestory.storage.bigquery")

# =============================================================================
# schemas
# =============================================================================

COST_TELEMETRY_SCHEMA: list[dict[str, str]] = [
    {"name": "run_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "project_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "evidence_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "subject_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "subject_kind", "type": "STRING", "mode": "NULLABLE"},
    {"name": "element_type", "type": "STRING", "mode": "NULLABLE"},
    {"name": "claim_type", "type": "STRING", "mode": "NULLABLE"},
    {"name": "risk_tier", "type": "STRING", "mode": "NULLABLE"},
    {"name": "provider", "type": "STRING", "mode": "REQUIRED"},
    {"name": "processor", "type": "STRING", "mode": "NULLABLE"},
    {"name": "schema_version", "type": "STRING", "mode": "NULLABLE"},
    {"name": "cost_cents", "type": "FLOAT", "mode": "REQUIRED"},
    {"name": "latency_ms", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "confidence", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "citation_count", "type": "INTEGER", "mode": "NULLABLE"},
    {"name": "cached", "type": "BOOLEAN", "mode": "REQUIRED"},
    {"name": "is_fallback", "type": "BOOLEAN", "mode": "REQUIRED"},
    {"name": "errored", "type": "BOOLEAN", "mode": "REQUIRED"},
    {"name": "retrieved_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
]

EVAL_RESULTS_SCHEMA: list[dict[str, str]] = [
    {"name": "eval_run_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "suite", "type": "STRING", "mode": "REQUIRED"},
    {"name": "case_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "case_name", "type": "STRING", "mode": "NULLABLE"},
    {"name": "expected_flagged", "type": "BOOLEAN", "mode": "NULLABLE"},
    {"name": "actual_flagged", "type": "BOOLEAN", "mode": "NULLABLE"},
    {"name": "expected_verdict", "type": "STRING", "mode": "NULLABLE"},
    {"name": "actual_verdict", "type": "STRING", "mode": "NULLABLE"},
    {"name": "expected_tier", "type": "STRING", "mode": "NULLABLE"},
    {"name": "actual_tier", "type": "STRING", "mode": "NULLABLE"},
    {"name": "correct", "type": "BOOLEAN", "mode": "REQUIRED"},
    {"name": "evidence_supports", "type": "BOOLEAN", "mode": "NULLABLE"},
    {"name": "rubric_version", "type": "STRING", "mode": "NULLABLE"},
    {"name": "routing_version", "type": "STRING", "mode": "NULLABLE"},
    {"name": "notes", "type": "STRING", "mode": "NULLABLE"},
    {"name": "run_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
]

PRECEDENT_CORPUS_SCHEMA: list[dict[str, str]] = [
    {"name": "precedent_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "element_type", "type": "STRING", "mode": "REQUIRED"},
    {"name": "jurisdiction", "type": "STRING", "mode": "NULLABLE"},
    {"name": "canonical_form", "type": "STRING", "mode": "NULLABLE"},
    {"name": "question", "type": "STRING", "mode": "REQUIRED"},
    {"name": "status_or_verdict", "type": "STRING", "mode": "REQUIRED"},
    {"name": "rationale", "type": "STRING", "mode": "NULLABLE"},
    {"name": "conditions", "type": "STRING", "mode": "REPEATED"},
    {"name": "confidence", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "counsel_confirmed", "type": "BOOLEAN", "mode": "NULLABLE"},
    {"name": "embedding", "type": "FLOAT", "mode": "REPEATED"},
    {"name": "recorded_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
]


class TelemetrySink:
    """Buffered writer. Never blocks the pipeline and never fails a run."""

    def __init__(self, client: Any = None, *, enabled: bool | None = None) -> None:
        self.enabled = (
            enabled if enabled is not None else bool(settings.gcp_project and not settings.offline)
        )
        self._client = client
        self._buffer: list[dict[str, Any]] = []
        self.rows_written = 0

    def _bq(self) -> Any:
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=settings.gcp_project or None)
        return self._client

    def _table(self, name: str) -> str:
        return f"{settings.gcp_project}.{settings.bq_dataset}.{name}"

    # ── cost ─────────────────────────────────────────────────────────────────
    def record_evidence(
        self,
        run_id: str,
        project_id: str,
        evidence: Evidence,
        *,
        subject_kind: str = "unknown",
        element_type: str | None = None,
        claim_type: str | None = None,
        risk_tier: str | None = None,
    ) -> None:
        provider, _, processor = evidence.provider.partition(":")
        self._buffer.append(
            {
                "run_id": run_id,
                "project_id": project_id,
                "evidence_id": evidence.evidence_id,
                "subject_id": evidence.subject_id,
                "subject_kind": subject_kind,
                "element_type": element_type,
                "claim_type": claim_type,
                "risk_tier": risk_tier,
                "provider": provider,
                "processor": processor or None,
                "schema_version": evidence.schema_version,
                "cost_cents": evidence.cost_cents,
                "latency_ms": evidence.latency_ms,
                "confidence": evidence.effective_confidence,
                "citation_count": len(evidence.citations),
                "cached": evidence.cached,
                "is_fallback": evidence.is_fallback,
                "errored": evidence.error is not None,
                "retrieved_at": evidence.retrieved_at.isoformat(),
            }
        )
        if len(self._buffer) >= 200:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        rows, self._buffer = self._buffer, []

        if not self.enabled:
            log.debug("telemetry disabled, discarding %s rows", len(rows))
            return

        try:
            errors = self._bq().insert_rows_json(self._table(settings.bq_table_cost), rows)
            if errors:
                log.warning("telemetry insert reported errors: %s", errors[:3])
            else:
                self.rows_written += len(rows)
        except Exception as exc:  # noqa: BLE001 - telemetry never fails a run
            log.warning("telemetry insert failed: %s", exc)

    # ── evaluation ───────────────────────────────────────────────────────────
    def record_eval(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        stamped = [{**r, "run_at": r.get("run_at", datetime.now(UTC).isoformat())} for r in rows]
        if not self.enabled:
            log.info("eval telemetry disabled, %s rows held locally", len(stamped))
            return
        try:
            self._bq().insert_rows_json(self._table(settings.bq_table_eval), stamped)
        except Exception as exc:  # noqa: BLE001
            log.warning("eval insert failed: %s", exc)

    # ── precedent ────────────────────────────────────────────────────────────
    def record_precedent(self, rows: list[dict[str, Any]]) -> None:
        """Feed the corpus that vector search retrieves against.

        This is the asset that compounds. The pipeline is open source, the
        rulebook and the calibrated corpus behind it are not.
        """
        if not rows or not self.enabled:
            return
        try:
            self._bq().insert_rows_json(self._table(settings.bq_table_precedent), rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("precedent insert failed: %s", exc)


# =============================================================================
# the analytics queries the pitch is built on
# =============================================================================

QUERIES: dict[str, str] = {
    "cost_per_run": """
        SELECT run_id,
               COUNT(*)                              AS subjects,
               ROUND(SUM(cost_cents) / 100, 4)       AS cost_usd,
               ROUND(AVG(latency_ms))                AS avg_latency_ms,
               ROUND(AVG(CAST(cached AS INT64)), 4)  AS cache_hit_rate
        FROM `{project}.{dataset}.{cost_table}`
        GROUP BY run_id
        ORDER BY MIN(retrieved_at) DESC
    """,
    "cost_by_tier": """
        SELECT risk_tier,
               COUNT(*)                        AS subjects,
               ROUND(SUM(cost_cents) / 100, 4) AS cost_usd,
               ROUND(AVG(confidence), 3)       AS avg_confidence
        FROM `{project}.{dataset}.{cost_table}`
        GROUP BY risk_tier
        ORDER BY cost_usd DESC
    """,
    # The number a studio buyer asks about first: how much human work is left.
    "counsel_escalation_rate": """
        SELECT DATE(retrieved_at)                                        AS day,
               COUNTIF(confidence < 0.75) / NULLIF(COUNT(*), 0)          AS below_threshold_rate,
               COUNTIF(is_fallback)       / NULLIF(COUNT(*), 0)          AS fallback_rate,
               COUNTIF(errored)           / NULLIF(COUNT(*), 0)          AS failure_rate
        FROM `{project}.{dataset}.{cost_table}`
        GROUP BY day
        ORDER BY day DESC
    """,
    # The draft over draft economics that make per episode series pricing work.
    "cache_savings": """
        SELECT run_id,
               COUNTIF(cached)                          AS cached_subjects,
               COUNT(*)                                 AS total_subjects,
               ROUND(COUNTIF(cached) / COUNT(*), 4)     AS hit_rate
        FROM `{project}.{dataset}.{cost_table}`
        GROUP BY run_id
        ORDER BY hit_rate DESC
    """,
    "litigation_set_accuracy": """
        SELECT suite,
               rubric_version,
               COUNT(*)                                     AS cases,
               COUNTIF(correct)                             AS correct,
               ROUND(COUNTIF(correct) / COUNT(*), 4)        AS accuracy
        FROM `{project}.{dataset}.{eval_table}`
        GROUP BY suite, rubric_version
        ORDER BY MAX(run_at) DESC
    """,
}


def render_query(name: str) -> str:
    return QUERIES[name].format(
        project=settings.gcp_project,
        dataset=settings.bq_dataset,
        cost_table=settings.bq_table_cost,
        eval_table=settings.bq_table_eval,
    )


_sink: TelemetrySink | None = None


def get_sink() -> TelemetrySink:
    global _sink
    if _sink is None:
        _sink = TelemetrySink()
    return _sink
