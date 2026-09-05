"""A run's real work happens in an in-process BackgroundTasks callback, not a
durable queue. If the process restarts mid-run -- a redeploy, a free tier
spin-down -- that callback is just gone, and the run's stored status stays
wherever it last landed forever, since nothing else ever revisits it. Found
live: a run submitted shortly before a deploy stayed QUEUED for hours with
nothing processing it.

`_reconcile_orphaned_runs` runs once at API startup and fails every
non-terminal run it finds, since a fresh process cannot be running a run it
never started -- anything still QUEUED/INGESTING/etc. at boot is orphaned by
construction.
"""

from __future__ import annotations

from truestory.api.main import _reconcile_orphaned_runs
from truestory.models.enums import RunStatus
from truestory.storage import MemoryRunStore, set_store


def test_queued_run_from_a_prior_process_is_marked_failed() -> None:
    store = MemoryRunStore()
    store.create_run(
        "demo",
        "run_stuck",
        {"run_id": "run_stuck", "project_id": "demo", "status": str(RunStatus.QUEUED)},
    )
    set_store(store)

    _reconcile_orphaned_runs()

    run = store.get_run("demo", "run_stuck")
    assert run is not None
    assert run["status"] == str(RunStatus.FAILED)
    assert "restarted" in run["error"]


def test_run_mid_pipeline_is_also_marked_failed() -> None:
    """Not just QUEUED -- any non-terminal status is orphaned at boot."""
    store = MemoryRunStore()
    store.create_run(
        "demo",
        "run_mid",
        {"run_id": "run_mid", "project_id": "demo", "status": str(RunStatus.ADJUDICATING)},
    )
    set_store(store)

    _reconcile_orphaned_runs()

    run = store.get_run("demo", "run_mid")
    assert run is not None
    assert run["status"] == str(RunStatus.FAILED)
    assert "ADJUDICATING" in run["error"]


def test_completed_and_failed_runs_are_left_alone() -> None:
    store = MemoryRunStore()
    store.create_run(
        "demo",
        "run_done",
        {"run_id": "run_done", "project_id": "demo", "status": str(RunStatus.COMPLETE)},
    )
    store.create_run(
        "demo",
        "run_already_failed",
        {
            "run_id": "run_already_failed",
            "project_id": "demo",
            "status": str(RunStatus.FAILED),
            "error": "original failure reason",
        },
    )
    set_store(store)

    _reconcile_orphaned_runs()

    assert store.get_run("demo", "run_done")["status"] == str(RunStatus.COMPLETE)
    assert store.get_run("demo", "run_already_failed")["error"] == "original failure reason"


def test_a_broken_store_does_not_crash_startup() -> None:
    class ExplodingStore(MemoryRunStore):
        def list_all_runs(self):  # type: ignore[override]
            raise RuntimeError("firestore is unreachable")

    set_store(ExplodingStore())

    _reconcile_orphaned_runs()  # must not raise
