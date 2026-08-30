"""Replay a model stage whose output must not drift between runs.

Two stages of this pipeline decide what everything downstream is *about*, and
both are language model calls: ingest names the spans, and claim extraction
words the claims. Neither is deterministic, even at temperature zero. Measured
on the same script three times, ingest returned 36, 34 and 44 spans, and the
same claim came back as "in the 2011 World Cup final" one run and "in the 2011
Cricket World Cup final" the next.

That drift is not cosmetic. A claim's identity is a hash of its own wording, so
a rephrasing produces a new `claim_id`, a new research cache key, a new
research question, and a different set of sources. On one run a claim verified
against two citations; on the next the reworded version found nothing citable
and was reported as a failure. Same script, same code, different report.

For a document counsel signs and an underwriter relies on, a run that cannot
be reproduced is a defect on its own, separately from any question of whether
the verdicts are right.

Keyed on the exact prompt bytes. This is a replay, never a fuzzy match: two
prompts that differ by one character are different questions and must never
share an entry.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from truestory.config import settings

log = logging.getLogger("truestory.stage_cache")


class StagePromptCache:
    """Store and replay one model stage's raw response, keyed by its prompt."""

    def __init__(self, namespace: str, version: str) -> None:
        #: Bumped when the prompt or the response schema changes in a way that
        #: makes a stored response wrong rather than merely older. It is part
        #: of the key, so a bump retires every entry in this namespace.
        self.version = version
        self.namespace = namespace
        self._backend: Any = None

    def _store(self) -> Any:
        if self._backend is None:
            from truestory.providers.cached import LocalCacheBackend

            self._backend = LocalCacheBackend(settings.cache_dir / self.namespace)
        return self._backend

    def key(self, model: str, prompt: str) -> str:
        raw = f"{self.version}|{model}|{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def get(self, model: str, prompt: str) -> str | None:
        try:
            entry = self._store().get(self.key(model, prompt))
        except Exception:  # pragma: no cover - a cache miss is never fatal
            return None
        if isinstance(entry, dict):
            text = entry.get("text")
            return str(text) if text else None
        return None

    def put(self, model: str, prompt: str, text: str) -> None:
        if not text:
            return
        try:
            self._store().put(self.key(model, prompt), {"model": model, "text": text})
        except Exception as exc:  # pragma: no cover
            log.debug("%s response not cached: %s", self.namespace, exc)
