"""Identity resolution: who a name denotes, before anything is researched.

Every case here is one the live pipeline got wrong at some point, and each
wrong answer had a cost:

  invented subject researched  -> a swimmer's results page became evidence for
                                  a screenplay character
  real subject blocked         -> eight true claims about a famous living
                                  cricketer were closed unresearched
  wrong entity resolved        -> "India" resolved to Indian Railways and the
                                  research went looking for the wrong thing

The ranking is exercised without the network, against candidates shaped like
the ones Wikidata actually returned.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from truestory.agents.identity import (
    IdentityResolver,
    IdentityStatus,
    _best_match,
    _kind_word,
    _label_affinity,
    _simplify,
)
from truestory.providers.wikidata import EntityCandidate


def _candidate(qid: str, label: str, description: str, sitelinks: int, **kw) -> EntityCandidate:
    return EntityCandidate(
        qid=qid,
        label=label,
        description=description,
        sitelinks=sitelinks,
        instance_of=kw.get("instance_of", ["Q5"]),
        occupations=kw.get("occupations", []),
    )


# =============================================================================
# ranking
# =============================================================================


def test_prominence_beats_a_description_that_repeats_the_name():
    """The Indian Railways failure.

    Ranking by how much the script's context overlaps the candidate's own
    description rewarded any item whose description repeats the name. A search
    for India scored a railway company above the country.
    """
    hints = "India played Sri Lanka in the 2011 ICC Cricket World Cup final in Mumbai"
    candidates = [
        _candidate("Q819425", "Indian Railways", "state-owned railway company of India", 60),
        _candidate("Q668", "India", "country in South Asia", 300),
    ]
    assert _best_match(candidates, hints, "India").qid == "Q668"


def test_an_obscure_exact_label_does_not_beat_the_real_subject():
    """The BccI failure. An exact label match with no prominence is not a match."""
    hints = "BCCI described Dhoni as hailing from Ranchi, Jharkhand"
    candidates = [
        _candidate("Q49822129", "BccI", "", 0),
        _candidate("Q2907539", "Board of Control for Cricket in India", "cricket board", 30),
    ]
    assert _best_match(candidates, hints, "BCCI").qid == "Q2907539"


def test_context_separates_two_equally_named_subjects():
    """The script says a cricket final; one candidate is a film of the same name."""
    hints = "cricket captain scored 91 not out in the final"
    candidates = [
        _candidate(
            "Q18127580",
            "M.S.Dhoni: The Untold Story",
            "2016 Hindi film",
            17,
            instance_of=["Q11424"],
        ),
        _candidate(
            "Q470774",
            "Mahendra Singh Dhoni",
            "Indian cricket player",
            47,
            occupations=["cricketer"],
        ),
    ]
    assert _best_match(candidates, hints, "MS Dhoni").qid == "Q470774"


@pytest.mark.parametrize(
    ("label", "name", "expected"),
    [
        ("India", "India", 2.0),
        ("Indian Railways", "India", 1.0),
        ("Board of Control for Cricket in India", "BCCI", 0.0),
    ],
)
def test_label_affinity(label, name, expected):
    assert _label_affinity(_candidate("Q1", label, "", 0), name) == expected


# =============================================================================
# name normalisation
# =============================================================================


def test_a_script_name_is_simplified_the_way_a_catalogue_holds_it():
    """One missing qualifier had a real event declared an invention."""
    assert _simplify("2011 ICC Cricket World Cup final") == "2011 Cricket World Cup final"
    assert _simplify("the FIFA World Cup") == "World Cup"


def test_simplify_refuses_to_return_a_stub():
    assert _simplify("the ICC") == ""


def test_the_web_question_names_the_right_kind_of_thing():
    """Asking whether there is an organisation called a cup final gets nonsense."""
    assert "event" in _kind_word("2011 Cricket World Cup final", False)
    assert _kind_word("Maya Rowan", True) == "person"


# =============================================================================
# the decision
# =============================================================================


@pytest.fixture
def online(monkeypatch):
    """Exercise the real decision path.

    The suite runs in mock mode, where identity resolution short circuits so
    that no test makes an outbound call. These tests are about the decision
    itself, so the module sees an online settings object and every outbound
    call it would make is stubbed by the test.
    """
    monkeypatch.setattr(
        "truestory.agents.identity.settings",
        SimpleNamespace(
            offline=False,
            model_identity="gemini-2.5-flash",
            use_vertex=False,
            gcp_project="",
            gcp_location="us-central1",
        ),
    )


async def test_a_name_nobody_bears_is_unidentified(monkeypatch, online):
    resolver = IdentityResolver()

    async def no_hits(name, limit=7):
        return []

    async def no_web(name, hints, is_person):
        return ("NO_RECORD: the search results show no such person.", ["example.gov"])

    monkeypatch.setattr(resolver.wikidata, "search", no_hits)
    monkeypatch.setattr(resolver, "_web_second_opinion", no_web)

    verdict = await resolver.resolve("Dr. Maya Rowan", hints="Oceanic Safety Board")
    assert verdict.status == IdentityStatus.UNIDENTIFIED
    assert verdict.researchable is False


async def test_absence_from_the_knowledge_base_alone_is_not_absence(monkeypatch, online):
    """Plenty of real private individuals have no entry. One vote is not enough."""
    resolver = IdentityResolver()

    async def no_hits(name, limit=7):
        return []

    async def found_on_web(name, hints, is_person):
        return ("EXISTS: a documented local official of that name.", ["cityofx.gov"])

    monkeypatch.setattr(resolver.wikidata, "search", no_hits)
    monkeypatch.setattr(resolver, "_web_second_opinion", found_on_web)

    verdict = await resolver.resolve("Helen Marsh", hints="city engineer")
    assert verdict.status == IdentityStatus.RESOLVED


async def test_a_failed_check_never_concludes_absence(monkeypatch, online):
    """An outage must not turn into a finding that somebody does not exist."""
    resolver = IdentityResolver()

    async def no_hits(name, limit=7):
        return []

    async def failed(name, hints, is_person):
        return ("", [])

    monkeypatch.setattr(resolver.wikidata, "search", no_hits)
    monkeypatch.setattr(resolver, "_web_second_opinion", failed)

    verdict = await resolver.resolve("Somebody Real", hints="")
    assert verdict.status == IdentityStatus.RESOLVED


async def test_mock_mode_makes_no_outbound_call():
    """The contract: a fresh clone with no credentials calls nothing.

    Identity resolution would otherwise reach Wikidata on every run, including
    in CI, and an unchecked identity has to block nothing downstream.
    """
    resolver = IdentityResolver()
    verdict = await resolver.resolve("Anybody At All", hints="")
    assert verdict.status == IdentityStatus.UNCHECKED
    assert verdict.researchable is False
