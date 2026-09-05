"""Firestore. Run state, and the source of the live UI.

Collection layout mirrors the ownership model exactly, which is what lets the
security rules be simple enough to be correct:

    /projects/{id}
    /projects/{id}/runs/{run_id}
    /projects/{id}/runs/{run_id}/elements/{element_id}
    /projects/{id}/runs/{run_id}/claims/{claim_id}
    /projects/{id}/runs/{run_id}/evidence/{evidence_id}
    /projects/{id}/monitors/{monitor_id}
    /review_queue/{item_id}

Per project isolation is enforced in the security rules rather than only in
application code, because an authorisation check that lives solely in a service
is one deploy away from being bypassed.

Real time listeners drive the server sent event stream for free. The overlay
fills in live because Firestore already pushes, not because we built a second
notification path.

An in memory backend with the identical interface keeps mock mode and CI free
of any cloud dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from truestory.config import settings

log = logging.getLogger("truestory.storage.firestore")


class RunStore:
    """Interface implemented by both backends."""

    def create_run(self, project_id: str, run_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def update_run(self, project_id: str, run_id: str, patch: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        """Every persisted run for a project, newest first."""
        raise NotImplementedError

    def put_subject(
        self, project_id: str, run_id: str, kind: str, subject_id: str, payload: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    def list_subjects(self, project_id: str, run_id: str, kind: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def batch_put_subjects(
        self, project_id: str, run_id: str, kind: str, payloads: dict[str, dict[str, Any]]
    ) -> None:
        raise NotImplementedError

    def put_monitor(self, project_id: str, monitor_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_monitors(self, project_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def find_monitor_by_provider_id(self, provider_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def queue_review(self, item_id: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def list_review_queue(self, project_id: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def audit(self, action: str, principal: str, subject_id: str, detail: dict[str, Any]) -> None:
        raise NotImplementedError


# =============================================================================
# in memory
# =============================================================================


class MemoryRunStore(RunStore):
    """Zero dependency backend. The default in mock mode and in CI."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._subjects: dict[str, dict[str, dict[str, Any]]] = {}
        self._monitors: dict[str, dict[str, Any]] = {}
        self._review: dict[str, dict[str, Any]] = {}
        self.audit_log: list[dict[str, Any]] = []

    @staticmethod
    def _key(project_id: str, run_id: str, suffix: str = "") -> str:
        return f"{project_id}/{run_id}{'/' + suffix if suffix else ''}"

    def create_run(self, project_id: str, run_id: str, payload: dict[str, Any]) -> None:
        self._runs[self._key(project_id, run_id)] = {
            **payload,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def update_run(self, project_id: str, run_id: str, patch: dict[str, Any]) -> None:
        key = self._key(project_id, run_id)
        self._runs.setdefault(key, {}).update(
            {**patch, "updated_at": datetime.now(UTC).isoformat()}
        )

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(self._key(project_id, run_id))

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        prefix = f"{project_id}/"
        rows = [v for k, v in self._runs.items() if k.startswith(prefix)]
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    def put_subject(
        self, project_id: str, run_id: str, kind: str, subject_id: str, payload: dict[str, Any]
    ) -> None:
        self._subjects.setdefault(self._key(project_id, run_id, kind), {})[subject_id] = payload

    def list_subjects(self, project_id: str, run_id: str, kind: str) -> list[dict[str, Any]]:
        return list(self._subjects.get(self._key(project_id, run_id, kind), {}).values())

    def batch_put_subjects(
        self, project_id: str, run_id: str, kind: str, payloads: dict[str, dict[str, Any]]
    ) -> None:
        self._subjects.setdefault(self._key(project_id, run_id, kind), {}).update(payloads)

    def put_monitor(self, project_id: str, monitor_id: str, payload: dict[str, Any]) -> None:
        self._monitors[f"{project_id}/{monitor_id}"] = payload

    def list_monitors(self, project_id: str) -> list[dict[str, Any]]:
        return [v for k, v in self._monitors.items() if k.startswith(f"{project_id}/")]

    def find_monitor_by_provider_id(self, provider_id: str) -> dict[str, Any] | None:
        for monitor in self._monitors.values():
            if monitor.get("provider_monitor_id") == provider_id:
                return monitor
        return None

    def queue_review(self, item_id: str, payload: dict[str, Any]) -> None:
        self._review[item_id] = payload

    def list_review_queue(self, project_id: str | None = None) -> list[dict[str, Any]]:
        items = list(self._review.values())
        if project_id:
            items = [i for i in items if i.get("project_id") == project_id]
        return items

    def audit(self, action: str, principal: str, subject_id: str, detail: dict[str, Any]) -> None:
        self.audit_log.append(
            {
                "action": action,
                "principal": principal,
                "subject_id": subject_id,
                "detail": detail,
                "at": datetime.now(UTC).isoformat(),
            }
        )


# =============================================================================
# durable local JSON
# =============================================================================


class LocalJsonRunStore(MemoryRunStore):
    """The laptop backend: MemoryRunStore semantics with an atomic JSON file.

    Local live mode used to fall back to :class:`MemoryRunStore` whenever
    Firestore was unavailable. The application still said ``live`` because
    provider mode and storage mode are separate, but restarting the API erased
    the docket. This backend keeps the zero-dependency local workflow while
    making a browser reload and a server restart mean what users expect.
    """

    VERSION = 1

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.path = path or (settings.cache_dir / "run_store.json")
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != self.VERSION:
                raise ValueError("unsupported local run-store version")
            self._runs = dict(payload.get("runs") or {})
            self._subjects = dict(payload.get("subjects") or {})
            self._monitors = dict(payload.get("monitors") or {})
            self._review = dict(payload.get("review") or {})
            self.audit_log = list(payload.get("audit_log") or [])
        except Exception as exc:
            # A damaged local index must not prevent the API starting. Keep it
            # in place for diagnosis and begin with an empty in-memory view.
            log.warning("could not read local run store %s: %s", self.path, exc)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": self.VERSION,
                    "runs": self._runs,
                    "subjects": self._subjects,
                    "monitors": self._monitors,
                    "review": self._review,
                    "audit_log": self.audit_log,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def create_run(self, project_id: str, run_id: str, payload: dict[str, Any]) -> None:
        super().create_run(project_id, run_id, payload)
        self._flush()

    def update_run(self, project_id: str, run_id: str, patch: dict[str, Any]) -> None:
        super().update_run(project_id, run_id, patch)
        self._flush()

    def put_subject(
        self, project_id: str, run_id: str, kind: str, subject_id: str, payload: dict[str, Any]
    ) -> None:
        super().put_subject(project_id, run_id, kind, subject_id, payload)
        self._flush()

    def batch_put_subjects(
        self, project_id: str, run_id: str, kind: str, payloads: dict[str, dict[str, Any]]
    ) -> None:
        super().batch_put_subjects(project_id, run_id, kind, payloads)
        self._flush()

    def put_monitor(self, project_id: str, monitor_id: str, payload: dict[str, Any]) -> None:
        super().put_monitor(project_id, monitor_id, payload)
        self._flush()

    def queue_review(self, item_id: str, payload: dict[str, Any]) -> None:
        super().queue_review(item_id, payload)
        self._flush()

    def audit(self, action: str, principal: str, subject_id: str, detail: dict[str, Any]) -> None:
        super().audit(action, principal, subject_id, detail)
        self._flush()


# =============================================================================
# firestore
# =============================================================================


class FirestoreRunStore(RunStore):
    """The deployed backend."""

    def __init__(self, client: Any = None) -> None:
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(
                project=settings.gcp_project or None, database=settings.firestore_database
            )
        self.db = client

    # ── runs ─────────────────────────────────────────────────────────────────
    def _run_ref(self, project_id: str, run_id: str) -> Any:
        return (
            self.db.collection("projects").document(project_id).collection("runs").document(run_id)
        )

    def create_run(self, project_id: str, run_id: str, payload: dict[str, Any]) -> None:
        from google.cloud import firestore

        self._run_ref(project_id, run_id).set({**payload, "created_at": firestore.SERVER_TIMESTAMP})

    def update_run(self, project_id: str, run_id: str, patch: dict[str, Any]) -> None:
        from google.cloud import firestore

        self._run_ref(project_id, run_id).set(
            {**patch, "updated_at": firestore.SERVER_TIMESTAMP}, merge=True
        )

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        snapshot = self._run_ref(project_id, run_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        docs = self.db.collection("projects").document(project_id).collection("runs").stream()
        rows = [d.to_dict() for d in docs]
        return sorted(rows, key=lambda r: str(r.get("created_at") or ""), reverse=True)

    # ── subjects ─────────────────────────────────────────────────────────────
    def put_subject(
        self, project_id: str, run_id: str, kind: str, subject_id: str, payload: dict[str, Any]
    ) -> None:
        self._run_ref(project_id, run_id).collection(kind).document(subject_id).set(payload)

    def list_subjects(self, project_id: str, run_id: str, kind: str) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self._run_ref(project_id, run_id).collection(kind).stream()]

    def batch_put_subjects(
        self, project_id: str, run_id: str, kind: str, payloads: dict[str, dict[str, Any]]
    ) -> None:
        """Write a whole stage in batches. A feature run is a few hundred writes."""
        collection = self._run_ref(project_id, run_id).collection(kind)
        batch = self.db.batch()
        for i, (subject_id, payload) in enumerate(payloads.items(), start=1):
            batch.set(collection.document(subject_id), payload)
            if i % 400 == 0:  # Firestore caps a batch at five hundred writes
                batch.commit()
                batch = self.db.batch()
        batch.commit()

    # ── monitors ─────────────────────────────────────────────────────────────
    def put_monitor(self, project_id: str, monitor_id: str, payload: dict[str, Any]) -> None:
        (
            self.db.collection("projects")
            .document(project_id)
            .collection("monitors")
            .document(monitor_id)
            .set(payload)
        )

    def list_monitors(self, project_id: str) -> list[dict[str, Any]]:
        return [
            d.to_dict()
            for d in self.db.collection("projects")
            .document(project_id)
            .collection("monitors")
            .stream()
        ]

    def find_monitor_by_provider_id(self, provider_id: str) -> dict[str, Any] | None:
        """Resolve an inbound webhook back to the subject it concerns."""
        results = (
            self.db.collection_group("monitors")
            .where("provider_monitor_id", "==", provider_id)
            .limit(1)
            .stream()
        )
        for doc in results:
            return doc.to_dict()
        return None

    # ── review queue ─────────────────────────────────────────────────────────
    def queue_review(self, item_id: str, payload: dict[str, Any]) -> None:
        self.db.collection("review_queue").document(item_id).set(payload)

    def list_review_queue(self, project_id: str | None = None) -> list[dict[str, Any]]:
        collection = self.db.collection("review_queue")
        query = collection.where("project_id", "==", project_id) if project_id else collection
        return [d.to_dict() for d in query.stream()]

    # ── audit ────────────────────────────────────────────────────────────────
    def audit(self, action: str, principal: str, subject_id: str, detail: dict[str, Any]) -> None:
        """Every adjudication, override and unmasking is recorded.

        Unmasking in particular. The system holds identifying information about
        living private individuals, and revealing it is a governed act with a
        named principal attached, not a UI toggle.
        """
        from google.cloud import firestore

        self.db.collection("audit").add(
            {
                "action": action,
                "principal": principal,
                "subject_id": subject_id,
                "detail": detail,
                "at": firestore.SERVER_TIMESTAMP,
            }
        )
        log.info("audit action=%s principal=%s subject=%s", action, principal, subject_id)


# =============================================================================
# selection
# =============================================================================

_store: RunStore | None = None


def get_store() -> RunStore:
    """Firestore when deployed, durable JSON locally, memory in tests/mock."""
    global _store
    if _store is not None:
        return _store

    if settings.offline:
        _store = MemoryRunStore()
    elif settings.env_name == "local" and not settings.firestore_emulator:
        # Provider mode remains LIVE. This only selects local durability and
        # avoids turning an unavailable optional Firestore API into data loss.
        _store = LocalJsonRunStore()
    elif not settings.gcp_project:
        _store = LocalJsonRunStore()
    else:
        try:
            store = FirestoreRunStore()
            # The client builds lazily, so construction succeeds even when the
            # API is disabled or unreachable and the failure only lands on the
            # first write, mid run, past this fallback. One cheap read here
            # turns that into a clean degrade at startup.
            next(iter(store.db.collections()), None)
            _store = store
        except Exception as exc:
            log.warning("firestore unavailable, using local run store: %s", exc)
            _store = LocalJsonRunStore()
    return _store


def set_store(store: RunStore) -> None:
    """Injection point for tests."""
    global _store
    _store = store
