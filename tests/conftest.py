"""Shared test fixtures.

Every test runs in mock mode. No network, no credentials, no spend, and the
suite is fast enough to run on every save.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("TRUESTORY_MODE", "mock")
os.environ.setdefault("TRUESTORY_LOG_LEVEL", "warning")

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def demo_script() -> Path:
    return REPO_ROOT / "demo" / "screenplay" / "the_long_shadow.fountain"


@pytest.fixture
def tiny_script(tmp_path: Path) -> Path:
    """A minimal draft carrying one of everything the pipeline cares about."""
    path = tmp_path / "tiny.fountain"
    path.write_text(
        "Title: Tiny\n\n"
        "TITLE CARD: THIS IS A TRUE STORY.\n\n"
        "INT. OFFICE - DAY\n\n"
        "HELEN VOSS stands by the window. She was convicted of fraud in 1974.\n"
        "She was a difficult woman. Call 312-555-0147.\n\n"
        "HELEN\n"
        "I was never charged.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def no_framing_script(tmp_path: Path) -> Path:
    """The same shape without the truth claim, to isolate the escalation."""
    path = tmp_path / "plain.fountain"
    path.write_text(
        "Title: Plain\n\n"
        "INT. OFFICE - DAY\n\n"
        "HELEN VOSS stands by the window. She was convicted of fraud in 1974.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def registry():
    from truestory.providers import BudgetGovernor, ProviderRegistry

    return ProviderRegistry(budget=BudgetGovernor())


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Point the content addressed cache at a scratch directory per test.

    Without this, one test warms the cache and a later test silently reads its
    answers, which would make the suite order dependent.
    """
    from truestory import config

    monkeypatch.setattr(
        type(config.settings), "cache_dir", property(lambda self: tmp_path / "cache")
    )
