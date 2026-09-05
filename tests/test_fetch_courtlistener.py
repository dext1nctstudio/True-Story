"""The CourtListener fetch script's own logic, tested without the network.

The script was run once by hand against the live API and read for sanity --
that is a smoke test, not coverage. What it actually needs pinned is the part
that turns a messy live response into the honest summary the README promises:
dedup, date parsing, and the resolution-rate arithmetic. And separately, the
one behaviour that was only ever observed by luck in that manual run rather
than exercised on purpose: a 429 from the API must degrade to a partial
result, never crash the whole fetch.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "eval" / "precedent_corpus" / "fetch_courtlistener.py"
)


def _load_module():
    """Import the script by path. It lives outside the package on purpose:
    it is a one off research tool, not runtime code, and importing it by path
    keeps it that way rather than promoting it into `truestory`."""
    spec = importlib.util.spec_from_file_location("fetch_courtlistener", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cl():
    return _load_module()


def _today_minus(days: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=days)).isoformat()


def _row(docket_id: int, query: str = "q1", **kw) -> dict:
    base = {
        "docket_id": docket_id,
        "caseName": f"Case {docket_id}",
        "court_citation_string": "C.D. Cal.",
        "cause": "28:1332 Diversity-Libel",
        "dateFiled": None,
        "dateTerminated": None,
        "docketNumber": f"2:24-cv-{docket_id:05d}",
        "docket_absolute_url": f"/docket/{docket_id}/case/",
        "_query_label": query,
        "_query": "test query",
    }
    base.update(kw)
    return base


# ── date parsing ─────────────────────────────────────────────────────────────
def test_a_normal_date_parses(cl) -> None:
    assert cl._parse_date("2019-08-28") is not None


def test_a_datetime_style_string_is_truncated_to_the_date(cl) -> None:
    """CourtListener has returned both bare dates and ISO datetimes across its
    endpoints. Truncating to the first 10 characters must not silently drop a
    record that has a time component."""
    assert cl._parse_date("2019-08-28T00:00:00Z") == cl._parse_date("2019-08-28")


def test_none_parses_to_none(cl) -> None:
    assert cl._parse_date(None) is None


def test_an_empty_string_parses_to_none(cl) -> None:
    assert cl._parse_date("") is None


def test_garbage_parses_to_none_rather_than_raising(cl) -> None:
    """A field this script does not control must never crash the summary over
    one malformed row."""
    assert cl._parse_date("not a date") is None


# ── dedup ────────────────────────────────────────────────────────────────────
def test_the_same_docket_found_by_two_queries_counts_once(cl) -> None:
    """A defamation-over-a-biopic case is relevant to more than one search
    term. Counting it under both would inflate filing volume for whichever
    shape happens to share vocabulary with another."""
    rows = [_row(1, query="claim_negative_living"), _row(1, query="publicity_rights")]
    deduped = cl._dedupe(rows)
    assert len(deduped) == 1


def test_the_first_query_to_find_a_docket_is_the_one_kept(cl) -> None:
    rows = [_row(1, query="first"), _row(1, query="second")]
    assert cl._dedupe(rows)[0]["_query_label"] == "first"


def test_a_row_with_no_docket_id_is_dropped_rather_than_kept_as_a_phantom(cl) -> None:
    """Search results without a resolvable docket occasionally come back from
    the API (e.g. a malformed or partial index entry). Keeping one would
    silently corrupt every count downstream."""
    rows = [_row(1), {"docket_id": None, "_query_label": "q"}]
    deduped = cl._dedupe(rows)
    assert len(deduped) == 1
    assert deduped[0]["docket_id"] == 1


def test_distinct_dockets_are_all_kept(cl) -> None:
    rows = [_row(1), _row(2), _row(3)]
    assert len(cl._dedupe(rows)) == 3


# ── the summary arithmetic ──────────────────────────────────────────────────
def test_a_terminated_docket_contributes_its_actual_duration(cl) -> None:
    rows = [_row(1, dateFiled="2020-01-01", dateTerminated="2020-04-10")]
    summary = cl._summarise(rows)
    assert summary["median_days_to_resolution"] == 100


def test_the_median_is_the_middle_value_not_the_mean(cl) -> None:
    """A mean would be dragged by one very long running suit. The median is
    the honest single number for 'how long does this typically take'."""
    rows = [
        _row(1, dateFiled="2020-01-01", dateTerminated="2020-01-11"),  # 10 days
        _row(2, dateFiled="2020-01-01", dateTerminated="2020-01-21"),  # 20 days
        _row(3, dateFiled="2020-01-01", dateTerminated="2022-01-01"),  # ~730 days
    ]
    summary = cl._summarise(rows)
    assert summary["median_days_to_resolution"] == 20


def test_a_docket_older_than_the_study_window_and_never_terminated_is_unresolved(
    cl,
) -> None:
    old_untermianted = _row(1, dateFiled=_today_minus(cl.STUDY_WINDOW_DAYS + 30))
    summary = cl._summarise([old_untermianted])
    assert summary["still_open_past_4_years"] == 1
    assert summary["too_recent_to_classify"] == 0


def test_a_recently_filed_open_docket_is_too_recent_not_unresolved(cl) -> None:
    """A suit filed last month with no termination date has not failed to
    resolve. It simply has not had time to. Counting it as 'unresolved' would
    understate the resolution rate for reasons that have nothing to do with
    how these disputes actually play out."""
    recent = _row(1, dateFiled=_today_minus(30))
    summary = cl._summarise([recent])
    assert summary["too_recent_to_classify"] == 1
    assert summary["still_open_past_4_years"] == 0


def test_a_docket_with_no_filing_date_at_all_is_silently_excluded(cl) -> None:
    """Not every result carries a filing date. It must not be miscounted as
    either resolved or unresolved; it is simply outside what can be measured."""
    no_date = _row(1)  # dateFiled defaults to None
    summary = cl._summarise([no_date])
    assert summary["resolved_within_window"] == 0
    assert summary["still_open_past_4_years"] == 0
    assert summary["too_recent_to_classify"] == 0


def test_the_resolution_rate_divides_by_classifiable_dockets_only(cl) -> None:
    """The rate must exclude 'too recent to classify' from its denominator,
    or a batch of very recent filings would silently deflate a rate that has
    nothing to do with them yet."""
    rows = [
        _row(1, dateFiled="2018-01-01", dateTerminated="2018-06-01"),  # resolved
        _row(2, dateFiled=_today_minus(30)),  # too recent, must not count
    ]
    summary = cl._summarise(rows)
    assert summary["resolution_rate_of_classifiable"] == 1.0


def test_zero_classifiable_dockets_does_not_divide_by_zero(cl) -> None:
    rows = [_row(1, dateFiled=_today_minus(10))]  # only "too recent"
    summary = cl._summarise(rows)
    assert summary["resolution_rate_of_classifiable"] is None


def test_an_empty_dataset_summarises_without_raising(cl) -> None:
    summary = cl._summarise([])
    assert summary["total_dockets"] == 0
    assert summary["median_days_to_resolution"] is None


def test_court_and_query_breakdowns_are_counted(cl) -> None:
    rows = [_row(1, query="a"), _row(2, query="a"), _row(3, query="b")]
    summary = cl._summarise(rows)
    assert summary["by_query"]["a"] == 2
    assert summary["by_query"]["b"] == 1
    assert summary["by_court"]["C.D. Cal."] == 3


# ── network failure must degrade, never crash the whole fetch ──────────────
def test_a_rate_limit_on_one_query_keeps_whatever_was_already_collected(cl, monkeypatch) -> None:
    """Observed live during the manual run against the real API on
    'life_rights_dispute' and it happened to work. That was luck, not
    verification -- this forces the same failure on purpose."""
    calls = {"n": 0}

    class _FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            import json

            return json.dumps(self._payload).encode()

    def fake_urlopen(req, timeout=20):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse({"results": [_row(1)], "next": "http://next-page"})
        raise urllib.error.URLError("429 Too Many Requests")

    monkeypatch.setattr(cl.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cl.time, "sleep", lambda _seconds: None)

    results = cl._fetch_query("test_label", "test query", pages=3)

    # The first page succeeded and must not be thrown away because the
    # second page failed.
    assert len(results) == 1
    assert results[0]["_query_label"] == "test_label"


def test_a_query_that_fails_on_its_first_page_returns_empty_not_an_exception(
    cl, monkeypatch
) -> None:
    def always_fails(req, timeout=20):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cl.urllib.request, "urlopen", always_fails)

    results = cl._fetch_query("test_label", "test query", pages=2)
    assert results == []
