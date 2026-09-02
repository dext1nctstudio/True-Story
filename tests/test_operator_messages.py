"""Operator copy must be readable by the person deciding whether to file.

The interface used to show a production's counsel an HTTP status, a JSON blob
and a support ref_id on the document they were deciding whether to file. These
tests hold the line that it never does again, and that the copy still says the
one thing a raw error string cannot: whether the report is safe to use.
"""

from __future__ import annotations

import pytest

from truestory.api.messages import CoverageReport, classify, describe

#: The exact string the product was showing, kept verbatim as the fixture.
REAL_402 = (
    'parallel_task: HTTP 402: {"type":"error","error":{"ref_id":'
    '"b03c0f0bcc5774c8b662393d9200e8bb","message":"Insufficient credit in account, '
    'please check your plan and billing details"}}'
)

FAULTS = [
    (REAL_402, "no_credit"),
    ("parallel_task: HTTP 401: Invalid API key", "bad_key"),
    ("parallel_task: HTTP 403: Forbidden", "no_permission"),
    ("429 RESOURCE_EXHAUSTED quota exceeded", "rate_limited"),
    ("parallel run trun_abc still active after 420s", "too_slow"),
    ("Your default credentials were not found", "no_credentials"),
    ("HTTP 503 service unavailable", "provider_down"),
    ("something nobody anticipated", "unknown"),
]


@pytest.mark.parametrize(("fault", "expected"), FAULTS)
def test_every_fault_family_is_recognised(fault, expected):
    assert classify(fault) == expected


@pytest.mark.parametrize(("fault", "_kind"), FAULTS)
def test_no_operator_copy_ever_contains_machine_detail(fault, _kind):
    """The whole point. This is what reached a legal deliverable."""
    m = describe(fault, subjects_affected=3, subjects_total=10)
    prose = f"{m.headline} {m.meaning} {m.action}"

    assert "{" not in prose and "}" not in prose
    assert "ref_id" not in prose
    assert "HTTP" not in prose
    assert "parallel_task" not in prose
    for code in ("402", "401", "403", "429", "503"):
        assert code not in prose


@pytest.mark.parametrize(("fault", "_kind"), FAULTS)
def test_every_message_answers_all_three_questions(fault, _kind):
    """What happened, what it means here, and what to do about it."""
    m = describe(fault)
    for part in (m.headline, m.meaning, m.action):
        assert part and len(part) > 20, "a stub is not an answer"
        assert part.strip().endswith("."), "operator copy is sentences, not fragments"


@pytest.mark.parametrize(("fault", "_kind"), FAULTS)
def test_the_technical_detail_is_kept_not_discarded(fault, _kind):
    """An engineer still has to be able to find the ref_id."""
    assert describe(fault).detail, "demoted, not deleted"


def test_an_unknown_fault_still_produces_usable_copy():
    """The next fault will not be one of the seven above."""
    m = describe("kernel panic: the moon exploded")
    assert m.kind == "unknown"
    assert "run the draft again" in m.action.lower()
    assert m.blocks_filing is True, "an unrecognised fault must not be assumed harmless"


def test_the_distinction_a_raw_error_cannot_make():
    """Whether the report may be filed is the question the reader actually has."""
    assert describe(REAL_402).blocks_filing is True
    # A lookup that ran out of time fell back rather than leaving a hole, so it
    # degrades the report without invalidating it.
    assert describe("still active after 420s").blocks_filing is False


def test_the_sentence_form_carries_the_ratio_and_no_identifiers():
    m = describe(REAL_402, subjects_affected=37, subjects_total=51)
    sentence = m.as_sentence()
    assert "37 of 51 subjects" in sentence
    assert "ref_id" not in sentence and "402" not in sentence


def test_a_coverage_report_blocks_filing_if_any_message_does():
    report = CoverageReport()
    report.add(describe("still active after 420s"))
    assert report.blocks_filing is False

    report.add(describe(REAL_402))
    assert report.blocks_filing is True
    assert len(report.sentences()) == 2
