"""A demo or a test pass against a project with months of history opens on a
docket of runs that have nothing to do with the session in front of you.

`TRUESTORY_HIDE_STORED_RUNS` hides those from the project run list and leaves
everything else alone: the runs stay in the store, this process's own runs
still list, and a direct link to any hidden run still resolves.
"""

from __future__ import annotations

import asyncio

import pytest

from truestory.api import main
from truestory.api.security import Principal
from truestory.models.enums import Role
from truestory.storage import MemoryRunStore, set_store


@pytest.fixture
def store_with_history() -> MemoryRunStore:
    store = MemoryRunStore()
    store.create_run(
        "demo",
        "run_old",
        {
            "run_id": "run_old",
            "project_id": "demo",
            "status": "COMPLETE",
            "script": {"title": "Something from months ago"},
        },
    )
    set_store(store)
    return store


@pytest.fixture
def counsel() -> Principal:
    return Principal(subject="dev@localhost", role=Role.COUNSEL, project_ids=("demo",))


def _list(principal: Principal) -> dict:
    return asyncio.run(main.list_runs("demo", principal))


def test_stored_runs_are_listed_by_default(store_with_history, counsel, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "hide_stored_runs", False)

    payload = _list(counsel)

    assert [r["run_id"] for r in payload["runs"]] == ["run_old"]
    assert "stored_hidden" not in payload


def test_the_flag_hides_them(store_with_history, counsel, monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "hide_stored_runs", True)

    payload = _list(counsel)

    assert payload["runs"] == []
    assert payload["stored_hidden"] is True


def test_the_flag_does_not_hide_this_process_own_runs(
    store_with_history, counsel, monkeypatch
) -> None:
    """Hiding history must not hide the run the user just started."""
    monkeypatch.setattr(main.settings, "hide_stored_runs", True)
    state = main.RunState(run_id="run_live", project_id="demo")
    monkeypatch.setitem(main._RUNS, "run_live", state)

    payload = _list(counsel)

    assert [r["run_id"] for r in payload["runs"]] == ["run_live"]


def test_a_hidden_run_is_still_readable_by_id(store_with_history, counsel, monkeypatch) -> None:
    """The runs are hidden from one list, not withdrawn from the store."""
    monkeypatch.setattr(main.settings, "hide_stored_runs", True)

    run = asyncio.run(main.get_run("run_old", counsel))

    assert run["run_id"] == "run_old"
    assert run["restored"] is True
