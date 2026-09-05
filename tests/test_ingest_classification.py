"""What the offline tagger decides a capitalised or quoted string is.

`_tag_deterministic` is documented as low precision, and it is. It is also not
only a mock mode convenience: it is the fallback when the model pass raises and
when the model returns unparseable output, so what it decides can reach a live
report.

Two misclassifications found on a real run are pinned here.
"""

from __future__ import annotations

import pytest

from truestory.agents.ingest import IngestAgent, _caps_element_type, _read_source
from truestory.models.enums import ElementType
from truestory.models.spans import Scene


def _scene(text: str, characters: list[str] | None = None) -> Scene:
    return Scene(
        scene_no=1,
        heading="INT. ROOM - DAY",
        start_page=1.0,
        end_page=1.0,
        text=text,
        characters=characters or [],
    )


def _types(scene: Scene, **kw) -> dict[str, ElementType]:
    spans = IngestAgent()._tag_deterministic(scene, **kw)
    return {s.surface_form: s.element_type for s in spans}


def test_long_pasted_screenplay_is_content_not_a_filename() -> None:
    screenplay = (
        "Title: Litigation reconstruction 001\n\n"
        "INT. INTERNATIONAL CHESS TOURNAMENT - DAY (1968)\n\n"
        "COMMENTATOR\nNona Gaprindashvili has never faced men.\n"
    ) * 30

    text, source_format = _read_source(screenplay)

    assert text == screenplay
    assert source_format == "txt"


# ── quoted text is not a song ───────────────────────────────────────────────
def test_a_quoted_claim_about_a_person_is_not_a_music_cue() -> None:
    """The bug this file exists for.

    The cue pattern accepted any quoted run followed by a capitalised word,
    which is the shape of every quoted line in a script. This sentence became a
    MUSIC_CUE and routed to music_rights_v1 at HIGH instead of to claim
    verification at CRITICAL.
    """
    scene = _scene('This sentence says, "MS Dhoni scored 97 in the 2011 World Cup final."')
    assert ElementType.MUSIC_CUE not in _types(scene).values()


def test_quoted_dialogue_is_not_a_music_cue() -> None:
    scene = _scene('She turns. "I never said that to Marcus," she tells him.')
    assert ElementType.MUSIC_CUE not in _types(scene).values()


# ── but a real cue still is ─────────────────────────────────────────────────
def test_the_by_artist_form_is_still_a_cue() -> None:
    scene = _scene('MUSIC: "Sweet Home Alabama" by Lynyrd Skynyrd')
    assert _types(scene).get("Sweet Home Alabama") is ElementType.MUSIC_CUE


def test_a_music_word_in_the_line_is_still_a_cue() -> None:
    scene = _scene('The jukebox plays "Wichita Lineman."')
    assert _types(scene).get("Wichita Lineman") is ElementType.MUSIC_CUE


def test_a_cue_wrapping_across_a_line_break_is_still_caught() -> None:
    """The reason the cue scan runs over the scene rather than line by line."""
    scene = _scene('The radio comes on.\n\n"Tangled Up In\nBlue" by Bob Dylan')
    assert ElementType.MUSIC_CUE in _types(scene).values()


def test_a_quoted_sentence_is_rejected_even_beside_a_music_word() -> None:
    """Length and internal punctuation still disqualify a title."""
    scene = _scene(
        'The radio is on. He says, "She told me she had never once been to the '
        'house on Ridge Road."'
    )
    assert ElementType.MUSIC_CUE not in _types(scene).values()


# ── a capitalised phrase is not always a person ─────────────────────────────
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ICC CRICKET WORLD CUP", ElementType.REAL_EVENT),
        ("THE HARTFORD CHAMPIONSHIP", ElementType.REAL_EVENT),
        ("MERIDIAN BROADCASTING COMPANY", ElementType.ORGANIZATION),
        ("STATE ATHLETICS FEDERATION", ElementType.ORGANIZATION),
    ],
)
def test_institutions_and_occasions_are_not_depicted_people(
    name: str, expected: ElementType
) -> None:
    assert _caps_element_type(name, ElementType.REAL_PERSON_DEPICTED) is expected


@pytest.mark.parametrize("name", ["DHONI", "ANIKA", "RAVI", "GAUTAM GAMBHIR", "REYES"])
def test_a_surname_is_still_a_person(name: str) -> None:
    """An acronym rule was tried here and removed.

    Five capital letters is what a screenplay surname looks like, so the rule
    reclassified DHONI as an institution. A person misread as an organisation
    loses CRITICAL person routing, which is the product.
    """
    assert _caps_element_type(name, ElementType.REAL_PERSON_DEPICTED) is (
        ElementType.REAL_PERSON_DEPICTED
    )


def test_a_character_who_speaks_is_a_person_whatever_the_rules_say() -> None:
    """A cue block is the format stating a name is a person."""
    assert (
        _caps_element_type(
            "ATHLETICS FEDERATION",
            ElementType.REAL_PERSON_DEPICTED,
            frozenset({"ATHLETICS FEDERATION"}),
        )
        is ElementType.REAL_PERSON_DEPICTED
    )


def test_a_speaker_from_another_scene_is_still_a_person_here() -> None:
    """Scoping the cue check to one scene classified a lead as an institution.

    DHONI speaks in no scene of the evidence fixture and is named in action
    lines throughout, which is what exposed the acronym rule. A character who
    speaks anywhere must count everywhere.
    """
    scene = _scene("DHONI walks to the crease. The crowd rises.", characters=[])
    types = _types(scene, truth_claim_framing=True, speakers=frozenset({"DHONI"}))
    # The span carries a normalised surface form, so match on it case blind.
    by_name = {k.upper(): v for k, v in types.items()}
    assert by_name.get("DHONI") is ElementType.REAL_PERSON_DEPICTED


def test_the_script_wide_speaker_set_reaches_the_tagger() -> None:
    """Wired from run(), so the whole draft's cues inform every scene."""
    agent = IngestAgent()
    document = agent.parse(
        "INT. ROOM - DAY\n\nANIKA\nHe scored ninety one.\n\n"
        "INT. STUDIO - NIGHT\n\nANIKA walks in.\n"
    )
    assert "ANIKA" in document.characters
