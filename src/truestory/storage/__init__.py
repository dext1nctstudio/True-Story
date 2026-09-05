"""State.

    Firestore   runs, claims, elements, evidence, monitors, review queue
    BigQuery    cost telemetry, evaluation results, precedent corpus
    GCS         scripts, captured evidence pages, rendered reports
    Secrets     Secret Manager, never environment variables in deployment

Every backend has an offline twin with an identical interface, which is why the
whole pipeline runs on a laptop with no credentials and CI needs no cloud
project at all.
"""

from truestory.storage.bigquery import TelemetrySink, get_sink, render_query
from truestory.storage.firestore import (
    FirestoreRunStore,
    LocalJsonRunStore,
    MemoryRunStore,
    RunStore,
    get_store,
    set_store,
)
from truestory.storage.gcs import (
    BlobStore,
    GcsBlobStore,
    LocalBlobStore,
    get_blob_store,
    set_blob_store,
    store_evidence_page,
    store_report,
)
from truestory.storage.secrets import get_secret, redact

__all__ = [
    "BlobStore",
    "FirestoreRunStore",
    "GcsBlobStore",
    "LocalBlobStore",
    "LocalJsonRunStore",
    "MemoryRunStore",
    "RunStore",
    "TelemetrySink",
    "get_blob_store",
    "get_secret",
    "get_sink",
    "get_store",
    "redact",
    "render_query",
    "set_blob_store",
    "set_store",
    "store_evidence_page",
    "store_report",
]
