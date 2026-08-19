"""Content addressed cache. Three jobs, all of them load bearing.

  1. Draft over draft economics. Element and claim identifiers are content
     hashes, so draft nine only researches what actually changed against draft
     eight. Roughly a ninety five percent reduction on a typical revision, and
     the reason per episode series pricing works at all.

  2. A free, deterministic demo. Warm the cache once on a paid live run, and
     every recorded take afterwards costs nothing and returns byte identical
     results. Standard production practice, not a shortcut, and it removes the
     single largest source of demo day fragility.

  3. Reproducible evaluation. The Litigation Set has to give the same answer
     twice or the number means nothing.

The backend is a local directory during development and a GCS prefix in
deployment. Both satisfy the same interface, so nothing above this file knows
which is in use.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import ResearchProvider, ResearchRequest


class CacheBackend:
    """Minimal key value surface. Implemented locally and on GCS."""

    def get(self, key: str) -> dict[str, Any] | None:  # pragma: no cover - interface
        raise NotImplementedError

    def put(self, key: str, value: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    def has(self, key: str) -> bool:
        return self.get(key) is not None


class LocalCacheBackend(CacheBackend):
    """A directory of JSON files, one per research answer."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.cache_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Shard by prefix so a full feature run does not produce one flat
        # directory with several thousand entries in it.
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


class GcsCacheBackend(CacheBackend):
    """The same cache, shared across every worker and every recording take."""

    def __init__(self, bucket: str | None = None, prefix: str = "cache/") -> None:
        from google.cloud import storage

        self.bucket_name = bucket or settings.bucket_evidence
        self.prefix = prefix
        self._client = storage.Client(project=settings.gcp_project or None)
        self._bucket = self._client.bucket(self.bucket_name)

    def get(self, key: str) -> dict[str, Any] | None:
        blob = self._bucket.blob(f"{self.prefix}{key}.json")
        if not blob.exists():
            return None
        try:
            return json.loads(blob.download_as_text())
        except Exception:
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        blob = self._bucket.blob(f"{self.prefix}{key}.json")
        blob.upload_from_string(
            json.dumps(value, indent=2, default=str), content_type="application/json"
        )


class CachedProvider(ResearchProvider):
    """Wraps another provider and serves repeat questions for nothing."""

    name = "cached"
    supports_citations = True
    supports_async = False
    unit_cost_cents = 0.0

    def __init__(
        self,
        inner: ResearchProvider | None = None,
        backend: CacheBackend | None = None,
        *,
        write_through: bool = True,
        max_age_days: int | None = None,
    ) -> None:
        self.inner = inner
        self.backend = backend or LocalCacheBackend()
        self.write_through = write_through
        # Facts move. A verified claim about a living person, answered from a
        # six month old envelope, is a stale answer presented as a current one,
        # and the retrieval date in the report would then be a fiction. Live
        # runs re research anything past the ceiling; replay and mock keep
        # every entry, because a byte identical rerun is the whole point there.
        self.max_age_days = (
            max_age_days if max_age_days is not None else settings.cache_max_age_days
        )
        self.hits = 0
        self.misses = 0
        self.expired = 0

    def _usable(self, entry: dict[str, Any] | None) -> bool:
        """Whether a cached entry may answer for the current mode.

        Mock and live share one cache keyspace, so a single mock run seeds every
        subject with a fixture. Because selection consults the cache before
        anything else, those fixtures then answer every later live run for
        nothing: no provider call, no spend, and verdicts that look real but
        came from a fixture. A live run may only be served real provenance.
        """
        if entry is None:
            return False
        if settings.offline:
            return True
        if entry.get("provider") == "mock":
            return False
        return not self._is_stale(entry)

    def _is_stale(self, entry: dict[str, Any]) -> bool:
        """Whether this envelope is older than a live run may rely on."""
        if not settings.is_live or self.max_age_days <= 0:
            return False
        stamp = entry.get("retrieved_at")
        if not stamp:
            return False
        try:
            retrieved = datetime.fromisoformat(str(stamp))
        except ValueError:
            return False
        if retrieved.tzinfo is None:
            retrieved = retrieved.replace(tzinfo=UTC)
        stale = (datetime.now(UTC) - retrieved).days > self.max_age_days
        if stale:
            self.expired += 1
        return stale

    def has(self, request: ResearchRequest) -> bool:
        return self._usable(self.backend.get(request.cache_key()))

    async def investigate(self, request: ResearchRequest) -> Evidence:
        key = request.cache_key()
        hit = self.backend.get(key)
        if not self._usable(hit):
            hit = None

        if hit is not None:
            self.hits += 1
            return _evidence_from_dict(hit, cached=True)

        self.misses += 1

        if self.inner is None:
            return Evidence.failed(
                request.subject_id,
                request.question,
                self.name,
                "cache miss and no upstream provider configured",
            )

        evidence = await self.inner.investigate(request)

        # A failed lookup is never cached. Retrying next run is correct: the
        # failure was ours or the network's, not the record's.
        if self.write_through and evidence.is_usable:
            self.backend.put(key, evidence.to_dict())

        return evidence

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


def _evidence_from_dict(data: dict[str, Any], *, cached: bool = False) -> Evidence:
    """Rehydrate an envelope, marking it as served from cache.

    `cost_cents` is zeroed on a hit so the live meter shows what this run
    actually spent rather than what the work would have cost. The saved amount
    is recoverable from the telemetry table when the unit economics slide wants
    it.
    """
    citations = [
        Citation(
            url=c.get("url", ""),
            title=c.get("title", ""),
            excerpt=c.get("excerpt", ""),
            accessed_at=_parse_dt(c.get("accessed_at")),
            source_type=c.get("source_type", "secondary"),
            publisher=c.get("publisher"),
            published_at=_parse_optional_dt(c.get("published_at")),
            # Entries written before the pedigree fields existed are
            # reclassified on read rather than served with an unknown class,
            # so an old cache does not quietly disable the source rules.
            **_pedigree(c),
        )
        for c in data.get("citations", [])
    ]
    return Evidence(
        evidence_id=data["evidence_id"],
        subject_id=data["subject_id"],
        question=data["question"],
        finding=data.get("finding", {}),
        citations=citations,
        reasoning=data.get("reasoning", ""),
        confidence=float(data.get("confidence", 0.0)),
        provider=data.get("provider", "cache"),
        schema_version=data.get("schema_version", "unknown"),
        is_fallback=bool(data.get("is_fallback", False)),
        cost_cents=0.0 if cached else float(data.get("cost_cents", 0.0)),
        latency_ms=int(data.get("latency_ms", 0)),
        cached=cached,
        retrieved_at=_parse_dt(data.get("retrieved_at")),
        error=data.get("error"),
    )


def _pedigree(citation: dict[str, Any]) -> dict[str, Any]:
    """Pedigree fields, reclassified when the cached entry predates them."""
    if citation.get("source_class") and citation.get("source_class") != "unknown":
        return {
            "source_class": citation["source_class"],
            "trust": float(citation.get("trust", 0.5)),
            "verified_source": bool(citation.get("verified_source", False)),
        }
    from truestory.providers.source_quality import assess

    verdict = assess(citation.get("url", ""), citation.get("source_type"))
    return {
        "source_class": verdict.source_class,
        "trust": verdict.trust,
        "verified_source": verdict.verified,
    }


def _parse_optional_dt(value: Any) -> datetime | None:
    return _parse_dt(value) if value else None


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)
