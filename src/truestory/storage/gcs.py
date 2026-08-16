"""Cloud Storage. Scripts, captured evidence pages, and rendered reports.

Retention is the interesting part. Evidence is held for seven years by default
because that matches the tail on a claims made errors and omissions policy. A
claim arriving in year six needs the evidence the production relied on in year
one, captured at the timestamp it was read, not a fresh lookup against a web
that has moved.

A local filesystem backend with the same interface keeps development and CI
free of any cloud dependency.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from truestory.config import REPO_ROOT, settings

log = logging.getLogger("truestory.storage.gcs")

#: Matches the claims made tail on a standard three year policy plus margin.
EVIDENCE_RETENTION_DAYS = 2555


class BlobStore:
    def put(self, bucket: str, path: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get(self, bucket: str, path: str) -> bytes | None:
        raise NotImplementedError

    def exists(self, bucket: str, path: str) -> bool:
        raise NotImplementedError

    def signed_url(self, bucket: str, path: str, minutes: int = 60) -> str:
        raise NotImplementedError


class LocalBlobStore(BlobStore):
    """Filesystem backed. Bucket names become directories."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (REPO_ROOT / ".truestory_blobs")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, path: str) -> Path:
        return self.root / bucket / path

    def put(self, bucket: str, path: str, data: bytes, content_type: str) -> str:
        target = self._path(bucket, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    def get(self, bucket: str, path: str) -> bytes | None:
        target = self._path(bucket, path)
        return target.read_bytes() if target.exists() else None

    def exists(self, bucket: str, path: str) -> bool:
        return self._path(bucket, path).exists()

    def signed_url(self, bucket: str, path: str, minutes: int = 60) -> str:
        return f"file://{self._path(bucket, path)}"


class GcsBlobStore(BlobStore):
    def __init__(self, client: Any = None) -> None:
        if client is None:
            from google.cloud import storage

            client = storage.Client(project=settings.gcp_project or None)
        self.client = client

    def put(self, bucket: str, path: str, data: bytes, content_type: str) -> str:
        blob = self.client.bucket(bucket).blob(path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{bucket}/{path}"

    def get(self, bucket: str, path: str) -> bytes | None:
        blob = self.client.bucket(bucket).blob(path)
        return blob.download_as_bytes() if blob.exists() else None

    def exists(self, bucket: str, path: str) -> bool:
        return self.client.bucket(bucket).blob(path).exists()

    def signed_url(self, bucket: str, path: str, minutes: int = 60) -> str:
        """Time limited access.

        Used for the underwriter role, which receives the final package read
        only and watermarked and is an external party outside the production's
        trust boundary.
        """
        from datetime import timedelta

        return (
            self.client.bucket(bucket)
            .blob(path)
            .generate_signed_url(expiration=timedelta(minutes=minutes), version="v4")
        )


# =============================================================================
# object paths
# =============================================================================


def script_path(project_id: str, run_id: str, filename: str) -> str:
    return f"projects/{project_id}/runs/{run_id}/script/{filename}"


def evidence_path(project_id: str, evidence_id: str) -> str:
    return f"projects/{project_id}/evidence/{evidence_id}.md"


def report_path(project_id: str, run_id: str, artifact: str) -> str:
    return f"projects/{project_id}/runs/{run_id}/reports/{artifact}"


# =============================================================================
# helpers
# =============================================================================

_store: BlobStore | None = None


def get_blob_store() -> BlobStore:
    global _store
    if _store is not None:
        return _store
    if settings.offline or not settings.gcp_project:
        _store = LocalBlobStore()
    else:
        try:
            _store = GcsBlobStore()
        except Exception as exc:
            log.warning("gcs unavailable, using local blob store: %s", exc)
            _store = LocalBlobStore()
    return _store


def store_evidence_page(project_id: str, evidence_id: str, markdown: str) -> str:
    """Preserve a captured page.

    A finding that cites a page which later changes is worth much less at claim
    time than one that cites a page the production captured on the day it read
    it, so the archived copy travels with the report.
    """
    return get_blob_store().put(
        settings.bucket_evidence or "truestory-evidence",
        evidence_path(project_id, evidence_id),
        markdown.encode("utf-8"),
        "text/markdown",
    )


def store_report(
    project_id: str, run_id: str, artifact: str, data: bytes, content_type: str
) -> str:
    return get_blob_store().put(
        settings.bucket_reports or "truestory-reports",
        report_path(project_id, run_id, artifact),
        data,
        content_type,
    )


def set_blob_store(store: BlobStore) -> None:
    global _store
    _store = store
