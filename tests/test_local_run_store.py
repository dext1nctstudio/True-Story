"""Local live runs survive process replacement without requiring Firestore."""

from __future__ import annotations

from pathlib import Path

from truestory.storage.firestore import LocalJsonRunStore


def test_run_and_subjects_survive_a_new_store_instance(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    first = LocalJsonRunStore(path)
    first.create_run(
        "demo",
        "run-1",
        {"run_id": "run-1", "project_id": "demo", "status": "QUEUED"},
    )
    first.update_run("demo", "run-1", {"status": "COMPLETE"})
    first.batch_put_subjects(
        "demo",
        "run-1",
        "claims",
        {"claim-1": {"claim_id": "claim-1", "verdict": "UNSUPPORTED"}},
    )

    restored = LocalJsonRunStore(path)

    assert restored.get_run("demo", "run-1")["status"] == "COMPLETE"  # type: ignore[index]
    assert restored.list_runs("demo")[0]["run_id"] == "run-1"
    assert restored.list_subjects("demo", "run-1", "claims") == [
        {"claim_id": "claim-1", "verdict": "UNSUPPORTED"}
    ]


def test_local_store_keeps_projects_isolated(tmp_path: Path) -> None:
    store = LocalJsonRunStore(tmp_path / "runs.json")
    store.create_run("project-a", "run-a", {"run_id": "run-a"})
    store.create_run("project-b", "run-b", {"run_id": "run-b"})

    assert [row["run_id"] for row in store.list_runs("project-a")] == ["run-a"]
    assert [row["run_id"] for row in store.list_runs("project-b")] == ["run-b"]


def test_audit_and_monitor_records_are_durable(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    store = LocalJsonRunStore(path)
    store.audit("create_project", "person@example.com", "demo", {"title": "Demo"})
    store.put_monitor("demo", "monitor-1", {"monitor_id": "monitor-1"})

    restored = LocalJsonRunStore(path)

    assert restored.audit_log[0]["action"] == "create_project"
    assert restored.list_monitors("demo") == [{"monitor_id": "monitor-1"}]
