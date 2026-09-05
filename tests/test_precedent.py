"""Precedent retrieval over reviewed court-source records.

Two failure modes are worse here than returning nothing.

Retrieving the wrong case invites a reviewer to reason from a matter that does
not apply, which is worse than asking them to reason from scratch. And
retrieving only the losses turns every finding into a disaster, which is the
paranoia engine `cases.yaml` opens by warning against. Both are tested.
"""

from __future__ import annotations

import pytest

from truestory.agents.precedent import PrecedentIndex, load_precedents
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClaimType, ElementType, Polarity, RiskTier


@pytest.fixture
def index() -> PrecedentIndex:
    return PrecedentIndex.load()


def _element(
    element_type: ElementType,
    *,
    alive: bool | None = None,
    negative_claims: int = 0,
) -> ClearableElement:
    return ClearableElement(
        element_id="el-1",
        element_type=element_type,
        canonical_form="Subject",
        risk_tier=RiskTier.HIGH,
        subject_alive=alive,
        claims=[
            FactualClaim(
                claim_id=f"cl-{i}",
                subject_element_id="el-1",
                subject_name="Subject",
                claim_text="conduct",
                claim_type=ClaimType.CONDUCT,
                polarity=Polarity.NEGATIVE,
            )
            for i in range(negative_claims)
        ],
    )


def _claim(
    *,
    polarity: Polarity = Polarity.NEGATIVE,
    alive: bool | None = True,
    claim_type: ClaimType = ClaimType.CONDUCT,
) -> FactualClaim:
    return FactualClaim(
        claim_id="cl-1",
        subject_element_id="el-1",
        subject_name="Subject",
        claim_text="She ordered the interrogations to continue overnight.",
        claim_type=claim_type,
        polarity=polarity,
        subject_alive=alive,
    )


# ── the corpus loads ────────────────────────────────────────────────────────
def test_every_case_in_the_corpus_becomes_a_matchable_shape(index: PrecedentIndex) -> None:
    assert len(index.shapes) == 6
    assert {s.case_id for s in index.shapes} == {
        "LS-001", "LS-003", "LS-101", "LS-103", "LS-104", "LS-202"
    }


def test_the_side_of_each_case_is_read_from_the_corpus(index: PrecedentIndex) -> None:
    """`failure_mode: null` is how the corpus marks the cases the studios won."""
    by_id = {s.case_id: s for s in index.shapes}
    assert by_id["LS-001"].side == "plaintiff"
    assert by_id["LS-101"].side == "defence"
    assert by_id["LS-103"].side == "defence"


def test_a_missing_corpus_yields_an_empty_index_rather_than_an_error(tmp_path) -> None:
    """Retrieval is an enrichment. Its absence degrades a run, never fails one."""
    empty = PrecedentIndex.load(tmp_path / "does_not_exist.yaml")
    assert empty.shapes == []
    assert empty.for_claim(_claim()) == []


# ── shape matching ──────────────────────────────────────────────────────────
def test_a_negative_claim_about_a_living_person_finds_the_shape_that_gets_filed_on(
    index: PrecedentIndex,
) -> None:
    matches = index.for_claim(_claim())

    assert "LS-001" in {m.case_id for m in matches}
    match = next(m for m in matches if m.case_id == "LS-001")
    assert set(match.matched_on) >= {"polarity", "subject_alive"}


def test_a_neutral_claim_does_not_retrieve_the_defamation_shape(index: PrecedentIndex) -> None:
    matches = index.for_claim(_claim(polarity=Polarity.NEUTRAL))
    assert "LS-001" not in {m.case_id for m in matches}


def test_a_person_carrying_several_negative_claims_finds_the_density_case(
    index: PrecedentIndex,
) -> None:
    """LS-003 is about density across one person, not any single line."""
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True, negative_claims=3)
    matches = index.for_element(element)

    assert "LS-003" in {m.case_id for m in matches}


def test_a_person_with_no_negative_claims_is_not_the_density_shape(index: PrecedentIndex) -> None:
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True)
    assert "LS-003" not in {m.case_id for m in index.for_element(element)}


@pytest.mark.parametrize(
    ("element_type", "expected_case"),
    [
        (ElementType.ARTWORK_VISUAL, "LS-202"),
        (ElementType.TRADEMARK_LOGO, "LS-101"),
        (ElementType.REAL_PERSON_IDENTIFIABLE, "LS-104"),
    ],
)
def test_each_element_type_retrieves_its_own_case(
    index: PrecedentIndex, element_type: ElementType, expected_case: str
) -> None:
    matches = index.for_element(_element(element_type))
    assert expected_case in {m.case_id for m in matches}


def test_a_music_cue_does_not_retrieve_person_cases(index: PrecedentIndex) -> None:
    """`named` is meaningless for a song, and asking anyway pulled in people."""
    matches = index.for_element(_element(ElementType.MUSIC_CUE))
    assert matches == []


def test_truth_claim_framing_strengthens_the_identifiability_match(
    index: PrecedentIndex,
) -> None:
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True, negative_claims=3)
    without = next(m for m in index.for_element(element) if m.case_id == "LS-003")
    with_framing = next(
        m for m in index.for_element(element, truth_claim_framing=True) if m.case_id == "LS-003"
    )
    assert with_framing.score > without.score


# ── balance, and the guardrails ─────────────────────────────────────────────
def test_a_living_person_with_negative_claims_is_shown_both_sides(
    index: PrecedentIndex,
) -> None:
    """The finding type where balance matters most.

    Shown three losses and no counterweight, a reviewer reads a disaster. This
    is the case that forced min_score down from 5 to 4.
    """
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True, negative_claims=3)
    sides = {m.side for m in index.for_element(element)}

    assert sides == {"plaintiff", "defence"}


def test_retrieval_is_capped_so_a_reviewer_reads_it(index: PrecedentIndex) -> None:
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True, negative_claims=3)
    assert len(index.for_element(element)) <= index.matching["max_matches_per_finding"]


def test_every_match_carries_court_metadata_and_a_checked_passage(index: PrecedentIndex) -> None:
    for match in index.for_claim(_claim()):
        row = match.to_dict()
        assert match.verified is True
        assert row["court"]
        assert row["docket_number"]
        assert row["source_url"].startswith("https://")
        assert row["quoted_passage"]
        assert "Source passage checked" in row["caveat"]


def test_verified_status_requires_both_a_source_and_a_passage(tmp_path) -> None:
    corpus = tmp_path / "bad.yaml"
    corpus.write_text(
        """
cases:
  - id: BAD-1
    name: Looks verified but is not
    side: plaintiff
    verification: {status: verified}
    source: {url: https://example.test/order}
    shape: {kind: claim, polarity: negative, subject_alive: true, named: true}
""",
        encoding="utf-8",
    )
    loaded = PrecedentIndex.load(corpus)
    assert loaded.shapes[0].verified is False


def test_a_match_says_which_dimensions_agreed(index: PrecedentIndex) -> None:
    """A lawyer can argue with 'polarity and subject_alive'. Not with 0.87."""
    for match in index.for_claim(_claim()):
        assert match.matched_on
        assert all(isinstance(d, str) for d in match.matched_on)


def test_ordering_is_stable_across_calls(index: PrecedentIndex) -> None:
    """A report must not reshuffle its own citations between drafts."""
    element = _element(ElementType.REAL_PERSON_DEPICTED, alive=True, negative_claims=2)
    first = [m.case_id for m in index.for_element(element)]
    second = [m.case_id for m in index.for_element(element)]
    assert first == second


def test_weights_come_from_the_corpus_so_an_attorney_can_change_them() -> None:
    index = load_precedents()
    assert index.matching["weights"]["element_type"] == 4
    assert index.matching["min_score"] == 4
