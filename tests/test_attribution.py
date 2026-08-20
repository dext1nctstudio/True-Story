"""The attribution gate.

This is the module that decides whether a source becomes evidence, and the
failures it exists to prevent were all observed on live APIs rather than
imagined:

  * Google's grounding returned ntsb.gov, kauai.gov and honolulu.gov for a
    question about a person who does not exist.
  * Parallel returned a teenage swimmer's results page as the basis for the
    same question, having correctly answered "no record".
  * The correct ESPNcricinfo scorecard line was then rejected by an early
    version of the verifier, because a page capture wraps names in markdown
    links and the comparison treated the link as part of the wording.

If these tests fail, either invented sources reach a legal document or true
ones are thrown away. Both are shipping blockers.
"""

from __future__ import annotations

import pytest

from truestory.agents.attribution import (
    MIN_QUOTE_CHARS,
    AttributionGate,
    verify_quote,
)
from truestory.models.evidence import Citation

# =============================================================================
# quote verification
# =============================================================================

PAGE = """\
# 2011 Cricket World Cup Final

India 277 for 4 ([Gambhir](https://espn.com/g) 97, [Dhoni](https://espn.com/d) 91*)
beat Sri Lanka 274 for 6 (Jayawardene 103*) by six wickets, with 10 balls remaining.

**Player of the match**: MS Dhoni
"""


def test_a_real_quote_verifies():
    assert verify_quote("beat Sri Lanka 274 for 6 (Jayawardene 103*) by six wickets", PAGE)


def test_markdown_links_do_not_break_a_real_quote():
    """The failure that threw away the correct scorecard on a live run."""
    assert verify_quote("India 277 for 4 (Gambhir 97, Dhoni 91*) beat Sri Lanka", PAGE)


def test_an_elided_quotation_verifies_as_its_parts_in_order():
    assert verify_quote("India 277 for 4 (Gambhir 97 ... by six wickets", PAGE)


def test_a_changed_number_does_not_verify():
    """The whole point. 97 and 91 are the difference between the fixtures."""
    assert not verify_quote("India 277 for 4 (Gambhir 97, Dhoni 97*) beat Sri Lanka", PAGE)


def test_an_invented_sentence_does_not_verify():
    assert not verify_quote("Dhoni was dismissed for a duck in the 2011 final", PAGE)


def test_a_paraphrase_does_not_verify():
    assert not verify_quote("India defeated Sri Lanka by six wickets in the final", PAGE)


def test_reordered_words_do_not_verify():
    assert not verify_quote("by six wickets India 277 for 4 Gambhir 97", PAGE)


def test_a_quote_too_short_to_prove_anything_is_rejected():
    assert not verify_quote("India", PAGE)
    assert not verify_quote("x" * (MIN_QUOTE_CHARS - 1), PAGE)


def test_nothing_verifies_against_an_empty_page():
    assert not verify_quote("India 277 for 4 by six wickets", "")


# =============================================================================
# the gate
# =============================================================================


def _citation(url: str, excerpt: str = "") -> Citation:
    return Citation.classified(url, excerpt=excerpt)


@pytest.mark.asyncio
async def test_a_source_with_no_readable_text_is_not_evidence():
    """A URL with nothing behind it is a link, not a source."""
    gate = AttributionGate()
    report = await gate.assess(
        proposition="MS Dhoni scored 91 not out in the 2011 final.",
        subject="MS Dhoni",
        citations=[_citation("https://example.gov/record")],
    )
    assert report.kept == 0
    assert report.dropped_unquotable == 1
    assert report.citations == []


@pytest.mark.asyncio
async def test_an_unrelated_source_is_dropped_offline():
    """The Maya Rowan shape: a real page that is about something else."""
    gate = AttributionGate()
    report = await gate.assess(
        proposition="Dr Maya Rowan was dismissed from the Oceanic Safety Board in March 2023.",
        subject="Dr Maya Rowan",
        citations=[
            _citation(
                "https://www.swimcloud.com/swimmer/2182030/",
                excerpt=(
                    "March 7, 2025 NT AAC February BB-B-C Meet. Results for the county "
                    "age group championships are listed below by event and finishing time."
                ),
            )
        ],
    )
    assert report.kept == 0
    assert report.citations == []


@pytest.mark.asyncio
async def test_a_supporting_source_survives_with_its_quote(monkeypatch):
    """What a kept citation must carry: a stance and a span that is really there."""
    gate = AttributionGate()

    async def fake_call(proposition, subject, candidates):
        return {
            1: {
                "index": 1,
                "stance": "supports",
                "quote": "beat Sri Lanka 274 for 6 (Jayawardene 103*) by six wickets",
                "reason": "The scorecard states the margin.",
                "about_subject": True,
            }
        }

    monkeypatch.setattr(gate, "_call_model", fake_call)
    report = await gate.assess(
        proposition="India won the 2011 final by six wickets.",
        subject="India",
        citations=[_citation("https://www.espncricinfo.com/x", excerpt=PAGE)],
    )

    assert report.kept == 1
    kept = report.citations[0]
    assert kept.stance == "supports"
    assert kept.quote_verified is True
    assert kept.is_attributed is True


@pytest.mark.asyncio
async def test_a_fabricated_quote_is_refused_however_confident(monkeypatch):
    """The model says the source says it, and cannot point at where."""
    gate = AttributionGate()

    async def fake_call(proposition, subject, candidates):
        return {
            1: {
                "index": 1,
                "stance": "contradicts",
                "quote": "The scorecard records that Dhoni was dismissed for a duck.",
                "reason": "Stated in the source.",
                "about_subject": True,
            }
        }

    monkeypatch.setattr(gate, "_call_model", fake_call)
    report = await gate.assess(
        proposition="MS Dhoni scored 91 not out.",
        subject="MS Dhoni",
        citations=[_citation("https://www.espncricinfo.com/x", excerpt=PAGE)],
    )

    assert report.kept == 0
    assert report.dropped_unquotable == 1
    assert report.citations == []


@pytest.mark.asyncio
async def test_a_source_about_a_namesake_is_dropped(monkeypatch):
    """Same name is not same subject, even with a genuine quote."""
    gate = AttributionGate()

    async def fake_call(proposition, subject, candidates):
        return {
            1: {
                "index": 1,
                "stance": "supports",
                "quote": "beat Sri Lanka 274 for 6 (Jayawardene 103*) by six wickets",
                "reason": "Mentions the name.",
                "about_subject": False,
            }
        }

    monkeypatch.setattr(gate, "_call_model", fake_call)
    report = await gate.assess(
        proposition="A different Dhoni scored 91.",
        subject="Dhoni",
        citations=[_citation("https://www.espncricinfo.com/x", excerpt=PAGE)],
    )

    assert report.kept == 0
    assert report.dropped_irrelevant == 1


@pytest.mark.asyncio
async def test_a_failed_gate_produces_no_evidence(monkeypatch):
    """Fail closed. An unassessed source is not evidence."""
    gate = AttributionGate()

    async def fake_call(proposition, subject, candidates):
        return {}

    monkeypatch.setattr(gate, "_call_model", fake_call)
    report = await gate.assess(
        proposition="India won the 2011 final by six wickets.",
        subject="India",
        citations=[_citation("https://www.espncricinfo.com/x", excerpt=PAGE)],
    )
    assert report.citations == []
