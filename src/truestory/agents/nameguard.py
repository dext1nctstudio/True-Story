"""Whether a string can denote a named subject, and whether a knowledge base
entry can be that subject.

This module exists because of one live run. The ingest stage tagged the pronoun
"her" as a person span, the identity stage searched Wikidata for `her`, and
Wikidata answered with **hertz, the SI unit of frequency**, carried by 97
Wikipedia editions. Ninety-seven editions clears the prominence threshold, so
the subject was marked `identified`, described as `living`, and the sentence
"The Air Ministry refused her a licence in 1931" was filed as a defamation
grade factual claim about a unit of frequency.

It was not an isolated match. Every English pronoun resolves to a prominent
entity:

    her  -> hertz (97 editions)          him -> Himachal Pradesh (139)
    she  -> Sheffield (122)              his -> historian (109)
    they -> They-sous-Vaudemont (36)     it  -> Italy (408)

Three separate failures had to line up, and all three are fixed here:

  1. **A pronoun became a subject.** `_is_predicate` in ingest already guards
     against verb phrases, but only for types in `_MUST_BE_NAMEABLE`, on the
     stated assumption that "a person or a place is always a name". A pronoun
     is the counterexample.
  2. **A non-human was accepted as a person.** `identity._resolve` filtered
     candidates to humans and then wrote `or real`, so when no human candidate
     existed the filter fell back to the unfiltered list. Asking for a person
     and accepting an SI unit is not a degraded answer, it is a wrong one.
  3. **Nothing checked that the answer resembled the question.** `hertz` was
     adopted for `her` because the search engine ranked it first. A knowledge
     base search is a fuzzy string match; treating its top hit as an identity
     is how "ICC" became the International Code Council on an earlier run.

The rule in `label_matches` would have caught that ICC case too, which is the
argument for it being here rather than in a pronoun blocklist.
"""

from __future__ import annotations

import re

#: Every form that refers without naming. A screenplay is written in these:
#: a character is named once in a cue and then referred to by pronoun on every
#: line after, which is why this list is load bearing rather than defensive.
PRONOUNS = frozenset(
    {
        # personal, subject and object
        "i",
        "me",
        "you",
        "he",
        "him",
        "she",
        "her",
        "it",
        "we",
        "us",
        "they",
        "them",
        # possessive
        "my",
        "mine",
        "your",
        "yours",
        "his",
        "hers",
        "its",
        "our",
        "ours",
        "their",
        "theirs",
        # reflexive
        "myself",
        "yourself",
        "himself",
        "herself",
        "itself",
        "ourselves",
        "yourselves",
        "themselves",
        # demonstrative and relative
        "this",
        "that",
        "these",
        "those",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        # indefinite
        "someone",
        "somebody",
        "anyone",
        "anybody",
        "everyone",
        "everybody",
        "no one",
        "nobody",
        "one",
        "ones",
        "other",
        "others",
        "another",
        "each",
        "either",
        "neither",
        "both",
        "all",
        "some",
        "any",
        "none",
    }
)

#: Bare common nouns with an article. "the man" names nobody, and researching
#: it returns whatever the web thinks a man is.
_GENERIC_HEADS = frozenset(
    {
        "man",
        "woman",
        "boy",
        "girl",
        "child",
        "person",
        "people",
        "guy",
        "lady",
        "gentleman",
        "figure",
        "stranger",
        "voice",
        "narrator",
        "crowd",
        "someone",
        "father",
        "mother",
        "son",
        "daughter",
        "brother",
        "sister",
        "wife",
        "husband",
        "friend",
        "doctor",
        "nurse",
        "officer",
        "soldier",
        "driver",
        "reporter",
        "editor",
        "coach",
        "player",
        "official",
        "worker",
        "student",
    }
)

#: The vocabulary of the format rather than of the story. Every one of these is
#: a real Wikidata entity: `DAY` carries 254 Wikipedia editions, `THE END` 22,
#: `CUT TO` matches a pop single. A screenplay is full of them and none of them
#: is a subject anyone is making a claim about.
_SCREENPLAY_VOCABULARY = frozenset(
    {
        "fade in",
        "fade out",
        "fade to black",
        "cut to",
        "smash cut",
        "match cut",
        "dissolve to",
        "continuous",
        "later",
        "moments later",
        "day",
        "night",
        "dawn",
        "dusk",
        "morning",
        "evening",
        "afternoon",
        "the end",
        "end",
        "title card",
        "super",
        "insert",
        "montage",
        "flashback",
        "intercut",
        "v.o.",
        "vo",
        "o.s.",
        "os",
        "cont'd",
        "contd",
        "beat",
        "pause",
        "the following",
        "present day",
        "sometime later",
        "meanwhile",
    }
)

#: Dropped before comparing a query with a knowledge base label, so
#: "the 2011 ICC Cricket World Cup final" can still match "2011 Cricket World
#: Cup Final".
_MATCH_STOPWORDS = frozenset({"the", "a", "an", "of", "for", "in", "at", "on", "and", "to"})

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall((text or "").casefold()) if t not in _MATCH_STOPWORDS}


def is_pronoun(text: str) -> bool:
    """Whether this surface form refers without naming.

    Case insensitive on purpose. A screenplay character cue is upper case, so
    `SHE` reaches here exactly as `she` does.
    """
    cleaned = " ".join((text or "").casefold().split()).strip(".,;:!?\"'()")
    return cleaned in PRONOUNS


def is_nameable(text: str) -> tuple[bool, str]:
    """Whether this string is the kind of thing that has a name.

    Returns the decision and the reason, because the reason is written onto the
    record when a span is dropped. A subject that is silently discarded and a
    subject that was never researched look identical from the outside, which is
    the confusion this product exists to remove.
    """
    cleaned = " ".join((text or "").split()).strip("\"'")
    if not cleaned:
        return False, "empty surface form"

    if is_pronoun(cleaned):
        return (
            False,
            f"{cleaned!r} is a pronoun: it refers without naming, so nothing can be looked up under it",
        )

    # A single character, or a bare number, names nothing.
    if len(cleaned.strip(".,;:")) < 2:
        return False, f"{cleaned!r} is too short to be a name"

    words = cleaned.split()
    lowered = [w.casefold().strip(".,;:") for w in words]

    # "the man", "a reporter": an article plus a common noun.
    if len(words) == 2 and lowered[0] in {"the", "a", "an"} and lowered[1] in _GENERIC_HEADS:
        return False, f"{cleaned!r} is a description rather than a name"

    # A bare common noun on its own, lower case, is a role and not a person.
    if len(words) == 1 and lowered[0] in _GENERIC_HEADS and cleaned.islower():
        return False, f"{cleaned!r} is a generic role rather than a name"

    folded = " ".join(lowered).strip()

    # The vocabulary of the format. "DAY" is a real Wikidata entity carrying
    # 254 Wikipedia editions, and it appears in every scene heading ever
    # written. Compared with the dots removed as well, because the word split
    # above strips a trailing full stop but not an internal one, so "V.O."
    # arrives here as "v.o" and missed the list on its first pass.
    if folded in _SCREENPLAY_VOCABULARY or folded.replace(".", "") in {
        v.replace(".", "") for v in _SCREENPLAY_VOCABULARY
    }:
        return False, f"{cleaned!r} is screenplay formatting vocabulary, not a subject"

    # A scene heading is a location line, not an entity. It reaches here
    # because ingest can tag the slug itself when a scene has no other subject.
    if folded.startswith(("int.", "ext.", "int ", "ext ", "int/ext", "i/e")):
        return False, f"{cleaned!r} is a scene heading rather than a subject"

    # A bare number or a year. "1931" is an entity with 204 Wikipedia editions
    # and denotes nothing anyone is making a claim about.
    if all(w.strip(".,;:").isdigit() for w in words):
        return False, f"{cleaned!r} is a bare number rather than a name"

    # Led by an article, nothing capitalised anywhere, and short: a piece of
    # set dressing rather than a name. "a ledger", "the dark", "the second
    # seat". A real name keeps its capital, so "the Watergate break in" and
    # "the 2011 Cricket World Cup" both survive.
    #
    # Bounded at four words deliberately. Beyond that an article led phrase is
    # an attribute cluster — "the heavy man in evening dress" — which is the
    # REAL_PERSON_IDENTIFIABLE path and the one case in this module that must
    # reach research without a name, because naming is not the legal trigger
    # and identifiability is.
    if (
        len(words) <= 4
        and lowered[0] in {"the", "a", "an", "one"}
        and not any(w[:1].isupper() for w in words)
    ):
        return False, f"{cleaned!r} is a description rather than a name"

    return True, ""


def _is_acronym_of(query: str, label: str) -> bool:
    """Whether `query` reads as the initials of `label`.

    Keeps "BCCI" resolving to "Board of Control for Cricket in India". Only
    applies to short upper case queries, and `is_pronoun` is checked before
    this is ever reached, so an upper case `SHE` cue never gets here.
    """
    q = "".join(ch for ch in query if ch.isalnum())
    if not (2 <= len(q) <= 6) or not q.isupper():
        return False

    # An acronym is built from the words that carry meaning, so "BCCI" comes
    # from Board, Control, Cricket, India and skips "of", "for" and "in".
    # Both readings are tried, because usage is not consistent: some marks
    # keep the joining words and some drop them.
    words = _WORD.findall(label.casefold())
    with_stopwords = "".join(w[0] for w in words if w)
    without_stopwords = "".join(w[0] for w in words if w and w not in _MATCH_STOPWORDS)
    return q.casefold() in (with_stopwords, without_stopwords)


def label_matches(query: str, label: str) -> bool:
    """Whether a knowledge base entry can plausibly be the thing that was asked for.

    A Wikidata search is a fuzzy string match and its top hit is a ranking, not
    an identification. This is the check that the answer resembles the question.

    The rule is containment in either direction over significant tokens:

        "Jesse Owens"    vs "Jesse Owens"            -> match, identical
        "Harold Vance"   vs "Harold Sines Vance"     -> match, query is contained
        "the 2011 ICC Cricket World Cup final"
                         vs "2011 Cricket World Cup Final"
                                                     -> match, label is contained
        "her"            vs "hertz"                  -> NO. Different tokens
        "she"            vs "Sheffield"              -> NO
        "ICC"            vs "International Code Council"
                                                     -> acronym, allowed through
                                                        to hint disambiguation

    Containment rather than similarity, because the failure being prevented is
    a near miss on characters. `her` and `hertz` are three characters apart and
    denote nothing in common.
    """
    # Containment alone cannot separate "they" from "They-sous-Vaudemont", a
    # real commune whose name opens with that token, from "Dhoni" against
    # "MS Dhoni", which is the same shape and must resolve. Nothing about the
    # strings distinguishes them, so the pronoun is refused by what it is
    # rather than by how it looks.
    if is_pronoun(query):
        return False

    asked, offered = _tokens(query), _tokens(label)
    if not asked or not offered:
        return False
    if asked <= offered or offered <= asked:
        return True
    if _is_initialled_name(query, label):
        return True
    return _is_acronym_of(query, label)


def label_matches_any(query: str, label: str, aliases: list[str] | None = None) -> bool:
    """`label_matches` against the item's label and every name it also goes by.

    Wikidata holds "MS Dhoni" as an alias rather than the label, so a check
    that reads only the label refuses the exact string the script wrote.
    """
    if label_matches(query, label):
        return True
    return any(label_matches(query, alias) for alias in (aliases or []))


def _is_initialled_name(query: str, label: str) -> bool:
    """Whether these are the same person's name, one written with initials.

    "MS Dhoni" and "Mahendra Singh Dhoni". "J.K. Rowling" and "Joanne Rowling".
    Extremely common for real people and invisible to token containment,
    because the initials share no token with the given names.

    Requires the surname to match exactly, so it cannot loosen anything else:
    `her` and `hertz` do not share a final token.
    """
    q_words = _WORD.findall(query.casefold())
    l_words = _WORD.findall(label.casefold())
    if len(q_words) < 2 or len(l_words) < 2:
        return False
    if q_words[-1] != l_words[-1]:
        return False

    # Everything before the surname on the query side must genuinely BE
    # initials, not merely reducible to them. Without that requirement
    # "International Cricket Council" matches "International Code Council",
    # because both reduce to "ic" plus a shared final word, and that is the
    # exact collision this module exists to refuse.
    leading = q_words[:-1]
    if not all(len(w) <= 2 for w in leading):
        return False

    q_initials = "".join(w[0] for w in leading)
    l_initials = "".join(w[0] for w in l_words[:-1])
    if not q_initials or not l_initials:
        return False

    # Either may be the longer form. "J.K. Rowling" against "Joanne Rowling"
    # carries an initial the catalogue label does not, because the K is not
    # part of the legal name; "MS Dhoni" against "Mahendra Singh Dhoni" is the
    # same relationship the other way up. Both are the same person written two
    # ways, and the shared surname is what makes the comparison meaningful.
    return q_initials.startswith(l_initials) or l_initials.startswith(q_initials)


def rejects_person_candidate(candidate_is_human: bool, is_person: bool) -> bool:
    """Whether a candidate must be refused because a person was asked for.

    Asking for a person and being handed a city is not a degraded answer that a
    confidence score can carry. It is the wrong kind of thing, and every
    downstream stage treats the subject as a person regardless: publicity
    rights, post mortem term, the living subject escalation.
    """
    return is_person and not candidate_is_human
