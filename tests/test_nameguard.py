"""The guardrail that stops a claim being filed against a unit of frequency.

Every case in here is derived from an observed failure or from the family of
failures around it. The headline one:

    ingest tags "her" as a person span
    identity searches Wikidata for `her`
    Wikidata returns hertz, the SI unit, 97 Wikipedia editions
    97 clears PROMINENCE_SITELINKS, so the subject is marked identified
    "The Air Ministry refused her a licence in 1931" is filed as a
    defamation grade factual claim about a unit of frequency

The tests are deliberately exhaustive over pronouns rather than sampling two,
because the failure was not specific to "her". Every English pronoun resolves
to a prominent Wikidata entity, and a guard that catches three of them and
misses "them" is not a guard.
"""

from __future__ import annotations

import pytest

from truestory.agents.nameguard import (
    PRONOUNS,
    is_nameable,
    is_pronoun,
    label_matches,
    rejects_person_candidate,
)

# =============================================================================
# the observed failures, by name
# =============================================================================

#: Surface form -> what Wikidata actually returned for it, with sitelink count,
#: recorded live on 1 September 2026. Every one of these is above
#: PROMINENCE_SITELINKS and would have been adopted as an identity.
OBSERVED_PRONOUN_MATCHES = [
    ("her", "hertz", 97),
    ("she", "Sheffield", 122),
    ("they", "They-sous-Vaudemont", 36),
    ("him", "Himachal Pradesh", 139),
    ("his", "historian", 109),
    ("it", "Italy", 408),
]


@pytest.mark.parametrize(("surface", "wikidata_label", "sitelinks"), OBSERVED_PRONOUN_MATCHES)
def test_observed_pronoun_matches_are_refused(surface, wikidata_label, sitelinks):
    """Each of these was a real Wikidata hit prominent enough to be adopted."""
    assert sitelinks >= 5, "the case is only interesting because it clears the threshold"
    # Two independent guards, either of which is sufficient.
    assert is_pronoun(surface)
    assert not is_nameable(surface)[0]
    assert not label_matches(surface, wikidata_label)


def test_every_pronoun_is_refused_as_a_subject():
    """Not a sample. The whole list, because 'them' fails the same way 'her' did."""
    for pronoun in PRONOUNS:
        ok, why = is_nameable(pronoun)
        assert not ok, f"{pronoun!r} would become a research subject"
        assert why, f"{pronoun!r} was dropped without a stated reason"


def test_pronoun_detection_is_case_insensitive():
    """A screenplay character cue is upper case, so SHE arrives exactly as she does."""
    for form in ("she", "She", "SHE", "  SHE  ", "she.", '"she"'):
        assert is_pronoun(form), f"{form!r} not caught"


# =============================================================================
# real names must still survive
# =============================================================================

REAL_SUBJECTS = [
    "Jesse Owens",
    "Larry Snyder",
    "Marty Glickman",
    "Leni Riefenstahl",
    "MS Dhoni",
    "Margaret Holloway",
    "Harold Vance",
    "Air Ministry",
    "BCCI",
    "The Way You Look Tonight",
    "Pennies from Heaven",
    "adidas",
]


@pytest.mark.parametrize("name", REAL_SUBJECTS)
def test_real_subjects_are_still_nameable(name):
    """A guard that blocks pronouns and also blocks Jesse Owens is not a fix."""
    ok, why = is_nameable(name)
    assert ok, f"{name!r} was refused: {why}"


def test_one_word_proper_names_survive():
    """Single token names are common in scripts and must not be swept up."""
    for name in ("Dhoni", "Riefenstahl", "Sheffield", "Owens"):
        assert is_nameable(name)[0]


# =============================================================================
# the answer has to resemble the question
# =============================================================================


def test_label_matches_accepts_identity_and_containment():
    assert label_matches("Jesse Owens", "Jesse Owens")
    # The B7 shape: an invented character whose name is contained in a real
    # person's. Containment is allowed here on purpose; prominence and the
    # collision path are what refuse it downstream.
    assert label_matches("Harold Vance", "Harold Sines Vance")
    # A script writes the long form, a catalogue holds the short one.
    assert label_matches("the 2011 ICC Cricket World Cup final", "2011 Cricket World Cup Final")


def test_label_matches_refuses_near_miss_strings():
    """The character level near miss is the whole failure mode."""
    assert not label_matches("her", "hertz")
    assert not label_matches("she", "Sheffield")
    assert not label_matches("his", "historian")
    assert not label_matches("it", "Italy")


def test_label_matches_refuses_the_icc_collision():
    """Recorded in the README: ICC came back as the International Code Council.

    The acronym path lets both candidates through to hint disambiguation, which
    is correct, because ICC genuinely is ambiguous. What must not happen is a
    non acronym near miss being treated as a match.
    """
    assert not label_matches("International Cricket Council", "International Code Council")


def test_acronyms_still_resolve():
    assert label_matches("BCCI", "Board of Control for Cricket in India")
    assert label_matches("ICC", "International Cricket Council")


# =============================================================================
# asking for a person and being handed a city
# =============================================================================


def test_non_human_candidate_is_refused_for_a_person():
    """The `or real` fallback that accepted hertz is what this replaces."""
    assert rejects_person_candidate(candidate_is_human=False, is_person=True)


def test_non_human_candidate_is_fine_when_no_person_was_asked_for():
    """An organization or a location span legitimately resolves to a non human."""
    assert not rejects_person_candidate(candidate_is_human=False, is_person=False)
    assert not rejects_person_candidate(candidate_is_human=True, is_person=True)


# =============================================================================
# descriptions that name nobody
# =============================================================================


@pytest.mark.parametrize(
    "description",
    ["the man", "a woman", "the reporter", "an officer", "someone", "nobody", "the crowd"],
)
def test_bare_descriptions_are_not_names(description):
    """Researching "the man" returns whatever the web thinks a man is."""
    assert not is_nameable(description)[0]


def test_a_described_but_identifiable_person_is_still_nameable():
    """Identifiability is an attribute cluster, and must not be swept up here.

    "the heavy man in evening dress" is the REAL_PERSON_IDENTIFIABLE path and
    resolves by attributes rather than by name, so it must survive this guard
    and be refused later by identity resolution instead.
    """
    assert is_nameable("the heavy man in evening dress")[0]


# =============================================================================
# the wider sweep
#
# Everything below was found by pointing the guard at strings a screenplay
# actually contains and asking Wikidata what each one resolves to. Nine more
# leaks turned up after the pronouns were closed, every one of them a real
# entity prominent enough to be adopted. The two lists are held together
# because the only way to be wrong is to move one of them.
# =============================================================================

#: Strings a screenplay produces that are not subjects, with what Wikidata
#: returned for each on 1 September 2026.
FORMAT_NOISE = [
    ("FADE IN", None),
    ("FADE OUT", None),
    ("CUT TO", "Cut to the Feeling, 6 editions"),
    ("CONTINUOUS", None),
    ("THE END", "The End, 22 editions"),
    ("DAY", "day, 254 editions"),
    ("NIGHT", "night, 195 editions"),
    ("LATER", None),
    ("MOMENTS LATER", "Moments Later"),
    ("TITLE CARD", None),
    ("SUPER", None),
    ("V.O.", "VOF de Kunst, 12 editions"),
    ("O.S.", None),
    ("CONT'D", None),
    ("INT. AERODROME OFFICE", None),
    ("1931", "1931, 204 editions"),
    ("2011", "2011, 247 editions"),
    ("the dark", None),
    ("a ledger", "A ledger of Charles Ackers"),
    ("a wireless set", None),
    ("a wall of charts", None),
    ("a small crowd", None),
    ("the wing", None),
    ("the paper", None),
    ("one question", "One Question, 4 editions"),
    ("the second seat", None),
]


@pytest.mark.parametrize(("noise", "wikidata_hit"), FORMAT_NOISE)
def test_screenplay_noise_is_never_a_subject(noise, wikidata_hit):
    """A script is mostly formatting, and formatting resolves.

    `DAY` appears in every scene heading ever written and carries 254 Wikipedia
    editions, which is more than Jesse Owens.
    """
    ok, why = is_nameable(noise)
    assert not ok, f"{noise!r} would be researched as a subject (Wikidata: {wikidata_hit})"
    assert why


#: The other half. Every real subject in both demo scripts, plus the shapes
#: most likely to be swept up by a rule aimed at the list above.
REAL_SUBJECTS_WIDE = [
    "Jesse Owens",
    "Larry Snyder",
    "Marty Glickman",
    "Luz Long",
    "Leni Riefenstahl",
    "Harold Vance",
    "MS Dhoni",
    "Margaret Holloway",
    "CHIEF ENGINEER DAVIES",
    "Air Ministry",
    "BCCI",
    "Ranchi",
    "Croydon",
    "Le Bourget",
    "adidas",
    "Schneider Trophy",
    "The Way You Look Tonight",
    "Pennies from Heaven",
    "2011 Cricket World Cup Final",
    "the Watergate break in",
]


@pytest.mark.parametrize("name", REAL_SUBJECTS_WIDE)
def test_the_sweep_does_not_catch_real_subjects(name):
    """The failure mode of every rule above is catching something real."""
    ok, why = is_nameable(name)
    assert ok, f"{name!r} was refused: {why}"


def test_an_article_led_attribute_cluster_survives():
    """The one article led phrase that must reach research.

    "the heavy man in evening dress" carries no name and resolves by profession,
    place, event and act. Naming is not the legal trigger; identifiability is,
    so the description rule is bounded at four words to let this through. This
    test exists because an earlier version of that rule blocked it.
    """
    assert is_nameable("the heavy man in evening dress")[0]
    assert is_nameable("the reporter at the Atlanta paper")[0]


def test_a_capitalised_name_survives_an_article():
    """ "the Watergate break in" is a real event and keeps its capital."""
    assert is_nameable("the Watergate break in")[0]
    assert is_nameable("the 2011 Cricket World Cup")[0]


def test_every_rejection_states_a_reason():
    """A silently dropped subject and an unresearched one look identical outside."""
    for bad in ("her", "the man", "", "x", "someone"):
        ok, why = is_nameable(bad)
        assert not ok
        assert why and len(why) > 10, f"{bad!r} rejected without a usable reason"
