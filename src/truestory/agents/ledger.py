"""Agent 3, LedgerAgent. Spans and claims to canonical entities. No LLM.

This is the hardest engineering in the build and it deserves a dedicated owner
from day one. Naive extraction on a feature yields two thousand or more spans.
The ledger must collapse them to roughly two hundred and fifty to three hundred
and fifty real research subjects, because the difference between those two
numbers is the difference between a two dollar run and a twenty dollar one, and
between a readable report and an unreadable one.

Four stages, all deterministic:

  1. Normalise      casefold, strip honorifics, canonicalise formats
  2. Coreference    "Dr. Reyes", "MIGUEL REYES", "MIGUEL" are one entity
  3. Deduplicate    one subject, many occurrence pointers
  4. Enrich         jurisdictions, modality, occurrence statistics

The screenplay format hands us the coreference problem half solved. Character
cue blocks, the all capitals names above dialogue, are unambiguous ground truth
that ordinary prose never provides.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ElementType, Modality
from truestory.models.spans import RawSpan, ScriptDocument

log = logging.getLogger("truestory.ledger")

_HONORIFICS = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "doctor", "prof", "professor", "sir",
     "dame", "lord", "lady", "rev", "father", "sister", "captain", "capt",
     "sergeant", "sgt", "detective", "det", "officer", "judge", "senator",
     "governor", "president", "general", "colonel", "col", "lieutenant", "lt"}
)

_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "esq"})

_CORP_SUFFIXES = frozenset(
    {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
     "co", "company", "plc", "gmbh", "sa", "bv", "ag", "pty"}
)

#: Cue block decorations that are not part of the character's name.
_CUE_DECORATIONS = re.compile(r"\s*\((?:V\.?O\.?|O\.?S\.?|CONT'?D|CONTD|OFF)\)\s*", re.I)


class LedgerAgent:
    """Collapse raw spans into the canonical clearance ledger."""

    name = "LedgerAgent"

    def __init__(self, jurisdictions: list[str] | None = None) -> None:
        self.jurisdictions = jurisdictions or ["US"]

    # ── entry point ──────────────────────────────────────────────────────────
    def run(
        self,
        spans: list[RawSpan],
        claims: list[FactualClaim],
        document: ScriptDocument,
    ) -> list[ClearableElement]:
        canonical_map = self._build_coreference_map(spans, document)
        elements = self._collapse(spans, canonical_map)
        self._attach_claims(elements, claims, canonical_map)
        self._enrich(elements)

        # Enrichment can retype an element, which means two entries that were
        # distinct at grouping time are now the same subject. Re collapsing is
        # cheap and prevents the same person appearing twice in the ledger,
        # once under each type, which would double bill the research and read
        # as a bug to anyone looking at the report.
        elements = self._remerge(elements)

        log.info(
            "ledger: %s spans -> %s elements (%.1fx reduction), %s claims attached",
            len(spans),
            len(elements),
            len(spans) / max(1, len(elements)),
            sum(len(e.claims) for e in elements),
        )
        return elements

    # ── stage 1 and 2: normalise and corefer ─────────────────────────────────
    def _build_coreference_map(
        self, spans: list[RawSpan], document: ScriptDocument
    ) -> dict[str, str]:
        """Map every surface form to its canonical form.

        The index is built over every person mention in the script, not only
        over the cue blocks. That matters because the fullest form of a name
        usually appears once, in an action line introducing the character,
        while the cue block and the dialogue use the short form throughout.
        Indexing only cues would leave "Margaret" and "Margaret Holloway" as
        two separate research subjects, which is both a doubled bill and an
        obvious defect in the report.

        Cue blocks remain the strongest signal available and are the reason
        this works at all. An all capitals name on its own line above dialogue
        is the format stating unambiguously that these tokens name one
        character, which ordinary prose never provides.
        """
        canonical: dict[str, str] = {}

        person_types = {
            ElementType.PERSON_NAME_FICTIONAL,
            ElementType.REAL_PERSON_DEPICTED,
        }

        # ── gather every person surface form ─────────────────────────────────
        forms: list[str] = [
            _CUE_DECORATIONS.sub("", c).strip() for c in document.characters
        ]
        forms.extend(
            span.surface_form for span in spans if span.element_type in person_types
        )

        display: dict[str, str] = {}
        for form in forms:
            key = normalise(form)
            if not key:
                continue
            candidate = canonicalise(form, ElementType.REAL_PERSON_DEPICTED)
            # Keep the fullest rendering seen for this key.
            if len(candidate) > len(display.get(key, "")):
                display[key] = candidate

        # ── index the multi token names by their parts ───────────────────────
        by_first: dict[str, list[str]] = defaultdict(list)
        by_last: dict[str, list[str]] = defaultdict(list)

        for key, rendered in display.items():
            parts = key.split()
            if len(parts) < 2:
                continue
            by_first[parts[0]].append(rendered)
            by_last[parts[-1]].append(rendered)

        # ── resolve ──────────────────────────────────────────────────────────
        for key, rendered in display.items():
            parts = key.split()

            if len(parts) == 1:
                # A bare mention resolves only when exactly one fuller name
                # claims it. Two characters sharing a surname is common in
                # family dramas, and merging them would be a far worse error
                # than leaving both in the ledger.
                first = _prefer_full(by_first.get(parts[0], []))
                last = _prefer_full(by_last.get(parts[0], []))
                if len(first) == 1:
                    canonical[key] = first[0]
                    continue
                if len(last) == 1:
                    canonical[key] = last[0]
                    continue

            canonical[key] = rendered

        # Non person spans canonicalise by their own type rules.
        for span in spans:
            if span.element_type in person_types:
                continue
            key = normalise(span.surface_form)
            if key and key not in canonical:
                canonical[key] = canonicalise(span.surface_form, span.element_type)

        return canonical

    # ── stage 3: deduplicate ─────────────────────────────────────────────────
    def _collapse(
        self, spans: list[RawSpan], canonical_map: dict[str, str]
    ) -> list[ClearableElement]:
        grouped: dict[str, ClearableElement] = {}

        for span in spans:
            canonical_form = canonical_map.get(
                normalise(span.surface_form),
                canonicalise(span.surface_form, span.element_type),
            )
            element_id = ClearableElement.make_id(
                span.element_type, canonical_form, self.jurisdictions
            )

            element = grouped.get(element_id)
            if element is None:
                element = ClearableElement(
                    element_id=element_id,
                    element_type=span.element_type,
                    canonical_form=canonical_form,
                    jurisdictions=list(self.jurisdictions),
                )
                grouped[element_id] = element

            if span.surface_form not in element.aliases and span.surface_form != canonical_form:
                element.aliases.append(span.surface_form)
            element.occurrences.append(span.to_occurrence())

        return list(grouped.values())

    # ── claims ───────────────────────────────────────────────────────────────
    def _attach_claims(
        self,
        elements: list[ClearableElement],
        claims: list[FactualClaim],
        canonical_map: dict[str, str],
    ) -> None:
        """Re point claims from span identifiers to canonical element identifiers.

        Claims are extracted per span, so forty mentions of one person produce
        claims scattered across forty subject identifiers. Re pointing them is
        what makes the per person rollup, and therefore the amber density rule,
        possible at all.
        """
        by_name: dict[str, ClearableElement] = {}
        for element in elements:
            by_name[normalise(element.canonical_form)] = element
            for alias in element.aliases:
                by_name.setdefault(normalise(alias), element)

        for claim in claims:
            key = normalise(claim.subject_name)
            target = by_name.get(key)

            if target is None:
                canonical = canonical_map.get(key)
                if canonical:
                    target = by_name.get(normalise(canonical))

            if target is None:
                continue

            claim.subject_element_id = target.element_id
            claim.subject_name = target.canonical_form

            # Re identify against the canonical subject so that the same claim
            # about the same person is one cache entry across drafts.
            claim.claim_id = FactualClaim.make_id(target.element_id, claim.claim_text)

            if not any(c.claim_id == claim.claim_id for c in target.claims):
                target.claims.append(claim)

        # Re identification above can collide two claims that were distinct
        # when the extractor deduped them: one sentence reached through two
        # spans resolves to one canonical element, and both then hash to the
        # same id. The per element list is already guarded, but the caller's
        # list is not, so the run would serve the same claim_id twice.
        self._collapse_claims(claims)

    @staticmethod
    def _collapse_claims(claims: list[FactualClaim]) -> None:
        """Collapse claims that share an id after re identification, in place.

        Occurrences are merged rather than dropped: the same assertion made in
        two places is one research subject and two places to light up.
        """
        merged: dict[str, FactualClaim] = {}
        for claim in claims:
            existing = merged.get(claim.claim_id)
            if existing is None:
                merged[claim.claim_id] = claim
                continue
            for occurrence in claim.asserted_in:
                if occurrence not in existing.asserted_in:
                    existing.asserted_in.append(occurrence)
        if len(merged) != len(claims):
            claims[:] = list(merged.values())

    # ── re collapse after retyping ───────────────────────────────────────────
    def _remerge(self, elements: list[ClearableElement]) -> list[ClearableElement]:
        merged: dict[str, ClearableElement] = {}

        for element in elements:
            key = ClearableElement.make_id(
                element.element_type, element.canonical_form, element.jurisdictions
            )
            existing = merged.get(key)

            if existing is None:
                element.element_id = key
                merged[key] = element
                continue

            # Fold the duplicate in, keeping every occurrence, alias and claim.
            existing.occurrences.extend(element.occurrences)
            for alias in element.aliases:
                if alias not in existing.aliases:
                    existing.aliases.append(alias)
            for claim in element.claims:
                if not any(c.claim_id == claim.claim_id for c in existing.claims):
                    claim.subject_element_id = existing.element_id
                    existing.claims.append(claim)

        for element in merged.values():
            element.occurrences.sort(key=lambda o: (o.scene_no, o.line_no))

        return list(merged.values())

    # ── stage 4: enrich ──────────────────────────────────────────────────────
    def _enrich(self, elements: list[ClearableElement]) -> None:
        for element in elements:
            element.occurrences.sort(key=lambda o: (o.scene_no, o.line_no))

            # Dialogue and action carry different legal weight. A brand named
            # in dialogue is an endorsement question. The same brand in a set
            # description is an art department question.
            if any(o.modality is Modality.SCRIPT_DIALOGUE for o in element.occurrences):
                element.aliases = element.aliases  # kept explicit for clarity
            if element.element_type is ElementType.PERSON_NAME_FICTIONAL and element.claims:
                # A "fictional" name carrying factual claims about a real
                # person was mistyped upstream. Promote it rather than lose it.
                element.element_type = ElementType.REAL_PERSON_DEPICTED
                log.debug("promoted %s to REAL_PERSON_DEPICTED", element.canonical_form)


# =============================================================================
# normalisation
# =============================================================================


def _prefer_full(candidates: list[str]) -> list[str]:
    """Collapse a candidate set to its fullest form when they nest.

    A script naming a character both "MARGARET" and "MARGARET HOLLOWAY"
    produces two candidates for the bare mention, which the ambiguity guard
    would otherwise refuse to resolve. They are not two people. When every
    candidate is a prefix of the longest one, the longest is the canonical
    identity and the short form resolves to it.

    Genuinely distinct people sharing a name part still fail the nesting test
    and stay separate, which is the case the guard exists for.
    """
    if len(candidates) <= 1:
        return candidates

    longest = max(candidates, key=len)
    longest_key = normalise(longest)
    if all(normalise(c) in longest_key for c in candidates):
        return [longest]
    return candidates


def normalise(text: str) -> str:
    """Aggressive comparison key. Never displayed, only compared."""
    cleaned = _CUE_DECORATIONS.sub(" ", text)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned.casefold())
    tokens = [t for t in cleaned.split() if t and t not in _HONORIFICS and t not in _SUFFIXES]
    return " ".join(tokens)


def canonicalise(surface: str, element_type: ElementType) -> str:
    """The display form. Readable, stable, and stripped of noise."""
    cleaned = _CUE_DECORATIONS.sub(" ", surface).strip().strip(".,;:'\"")

    if element_type in {
        ElementType.PERSON_NAME_FICTIONAL,
        ElementType.REAL_PERSON_DEPICTED,
        ElementType.REAL_PERSON_IDENTIFIABLE,
    }:
        tokens = [t for t in cleaned.split() if t.strip(".").casefold() not in _HONORIFICS]
        return " ".join(t.title() if t.isupper() else t for t in tokens) or cleaned

    if element_type in {ElementType.BUSINESS_NAME, ElementType.ORGANIZATION}:
        tokens = cleaned.split()
        while tokens and tokens[-1].strip(".,").casefold() in _CORP_SUFFIXES:
            tokens.pop()
        # "Kestrel Holdings, Inc." leaves a dangling comma once the suffix
        # goes, and a trailing comma is enough to split one company into two
        # research subjects.
        if tokens:
            tokens[-1] = tokens[-1].rstrip(",;")
        return " ".join(tokens).strip() or cleaned

    if element_type is ElementType.PHONE_NUMBER:
        return re.sub(r"[^\d]", "", cleaned)

    if element_type is ElementType.URL_HANDLE:
        return cleaned.casefold().rstrip("/")

    return cleaned
