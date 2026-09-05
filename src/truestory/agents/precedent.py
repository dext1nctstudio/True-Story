"""Court-sourced precedent retrieval for clearance findings.

The runtime index is built from ``eval/precedent_corpus/verified_cases.yaml``.
Each record names the court and docket, links the underlying opinion or order,
and carries a short passage from that document.  Matching is deliberately
explainable: legal/factual shape is combined with lexical overlap against the
case's issues, holding, and sourced passage.  A precedent never changes a
clearance verdict; it is review context for counsel.

The separate sync command retrieves CourtListener data and validates that a
quoted passage occurs in court text.  Runtime matching is local and stable so
a report does not change merely because a third-party API is unavailable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from truestory.config import EVAL_DIR
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import PERSON_ADJACENT, ElementType

log = logging.getLogger("truestory.precedent")

#: The reviewed court-source corpus. Ships with the repository and is refreshed
#: by ``eval/precedent_corpus/sync_courtlistener.py``.
CASES_PATH = EVAL_DIR / "precedent_corpus" / "verified_cases.yaml"

#: Used when `cases.yaml` declares no `matching` block, so an older copy of the
#: corpus still retrieves rather than silently returning nothing.
_DEFAULT_MATCHING: dict[str, Any] = {
    "weights": {
        "element_type": 4,
        "claim_type": 2,
        "polarity": 2,
        "subject_alive": 2,
        "named": 2,
        "kind": 1,
        "truth_claim_framing": 1,
        "semantic_overlap": 2,
    },
    "min_score": 4,
    "max_matches_per_finding": 3,
    "both_sides_always": True,
}


@dataclass(frozen=True, slots=True)
class PrecedentShape:
    """One case in the corpus, reduced to the dimensions that can be matched.

    Every field is optional because the corpus is heterogeneous by design: a
    music licence case has no polarity and a claim case has no element type. A
    dimension the case does not state simply does not participate, which is
    the honest behaviour -- it is not evidence of a difference either.
    """

    case_id: str
    name: str
    #: plaintiff (the production lost or settled) or defence (the studio won).
    side: str
    outcome: str
    lesson: str
    verified: bool

    court: str = ""
    docket_number: str = ""
    citation: str = ""
    decision_date: str = ""
    procedural_posture: str = ""
    holding: str = ""
    source_url: str = ""
    source_type: str = ""
    document_number: str = ""
    pin_cite: str = ""
    quoted_passage: str = ""
    retrieved_at: str = ""
    semantic_text: str = ""

    kind: str | None = None
    element_type: ElementType | None = None
    claim_type: str | None = None
    polarity: str | None = None
    subject_alive: bool | None = None
    named: bool | None = None
    truth_claim_framing: bool | None = None


@dataclass(frozen=True, slots=True)
class PrecedentMatch:
    """A retrieved case, and the reason it was retrieved."""

    case_id: str
    name: str
    side: str
    outcome: str
    lesson: str
    score: int
    #: The dimensions that agreed. This is the audit trail, and it is what the
    #: report prints rather than the score.
    matched_on: tuple[str, ...]
    #: True only when the source and quoted passage passed corpus review.
    #: Rendered as an explicit badge and caveat, never dropped.
    verified: bool
    court: str = ""
    docket_number: str = ""
    citation: str = ""
    decision_date: str = ""
    procedural_posture: str = ""
    holding: str = ""
    source_url: str = ""
    source_type: str = ""
    document_number: str = ""
    pin_cite: str = ""
    quoted_passage: str = ""
    retrieved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "side": self.side,
            "outcome": self.outcome,
            "lesson": self.lesson,
            "score": self.score,
            "matched_on": list(self.matched_on),
            "verified": self.verified,
            "court": self.court,
            "docket_number": self.docket_number,
            "citation": self.citation,
            "decision_date": self.decision_date,
            "procedural_posture": self.procedural_posture,
            "holding": self.holding,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "document_number": self.document_number,
            "pin_cite": self.pin_cite,
            "quoted_passage": self.quoted_passage,
            "retrieved_at": self.retrieved_at,
            "caveat": (
                "Source passage checked against the linked court document; context "
                "for counsel, not legal advice."
                if self.verified
                else "Court metadata located, but the quoted passage has not been "
                "verified against retrieved court text. Do not cite as authority."
            ),
        }


@dataclass(slots=True)
class PrecedentIndex:
    """Reviewed court records, queryable by failure shape and sourced text."""

    shapes: list[PrecedentShape] = field(default_factory=list)
    matching: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_MATCHING))

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path | None = None) -> PrecedentIndex:
        """Read the corpus. A missing or malformed file yields an empty index.

        Retrieval is an enrichment, so its absence must degrade the report
        rather than fail the run. A run with no precedents is the product as it
        shipped last week.
        """
        source = path or CASES_PATH
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            log.warning("precedent corpus unreadable at %s: %s", source, exc)
            return cls(shapes=[], matching=dict(_DEFAULT_MATCHING))

        matching = {**_DEFAULT_MATCHING, **(raw.get("matching") or {})}
        shapes = [
            shape
            for case in (raw.get("cases") or [])
            if isinstance(case, dict) and (shape := _to_shape(case)) is not None
        ]
        log.info("precedent corpus loaded: %d cases from %s", len(shapes), source.name)
        return cls(shapes=shapes, matching=matching)

    # ── retrieval ────────────────────────────────────────────────────────────
    def for_element(
        self, element: ClearableElement, *, truth_claim_framing: bool = False
    ) -> list[PrecedentMatch]:
        """Precedents bearing on a clearance element."""
        negative_claims = [c for c in element.claims if str(c.polarity).lower() == "negative"]

        return self._match(
            {
                # A person carrying several unsupported negative claims is not
                # a claim question and not an ordinary element question. It is
                # the density shape, and the corpus holds it as its own kind.
                # Matching it here rather than per claim is deliberate: the
                # finding that matters is about the person, not any one line.
                "kind": (
                    "person_rollup"
                    if element.element_type in PERSON_ADJACENT and len(negative_claims) >= 2
                    else "element"
                ),
                "element_type": element.element_type,
                "subject_alive": element.subject_alive,
                # An element carries no polarity of its own. It inherits one
                # from the claims made about it, and the two element types that
                # are inherently disparaging supply one because that is what
                # they mean.
                "polarity": (
                    "negative"
                    if negative_claims
                    or element.element_type in (ElementType.DEFAMATORY_REF, ElementType.TRADE_LIBEL)
                    else None
                ),
                # The Baby Reindeer dimension, and only meaningful for a
                # subject who could be identified at all. Asking whether a
                # music cue is "named" retrieves person cases for a song.
                "named": (
                    element.element_type is not ElementType.REAL_PERSON_IDENTIFIABLE
                    if element.element_type in PERSON_ADJACENT
                    else None
                ),
                "truth_claim_framing": True if truth_claim_framing else None,
                "text": " ".join([element.canonical_form, *(c.claim_text for c in element.claims)]),
            }
        )

    def for_claim(
        self, claim: FactualClaim, *, truth_claim_framing: bool = False
    ) -> list[PrecedentMatch]:
        """Precedents bearing on one factual claim."""
        return self._match(
            {
                "kind": "claim",
                "claim_type": str(claim.claim_type),
                "polarity": str(claim.polarity),
                "subject_alive": claim.subject_alive,
                "named": True,
                "truth_claim_framing": True if truth_claim_framing else None,
                "text": f"{claim.subject_name} {claim.claim_text}",
            }
        )

    # ── the matcher ──────────────────────────────────────────────────────────
    def _match(self, query: dict[str, Any]) -> list[PrecedentMatch]:
        weights: dict[str, int] = self.matching.get("weights") or {}
        min_score = int(self.matching.get("min_score", 4))
        limit = int(self.matching.get("max_matches_per_finding", 3))

        scored: list[PrecedentMatch] = []
        for shape in self.shapes:
            score, matched_on = _score(shape, query, weights)
            if score < min_score or not matched_on:
                continue
            scored.append(
                PrecedentMatch(
                    case_id=shape.case_id,
                    name=shape.name,
                    side=shape.side,
                    outcome=shape.outcome,
                    lesson=shape.lesson,
                    score=score,
                    matched_on=matched_on,
                    verified=shape.verified,
                    court=shape.court,
                    docket_number=shape.docket_number,
                    citation=shape.citation,
                    decision_date=shape.decision_date,
                    procedural_posture=shape.procedural_posture,
                    holding=shape.holding,
                    source_url=shape.source_url,
                    source_type=shape.source_type,
                    document_number=shape.document_number,
                    pin_cite=shape.pin_cite,
                    quoted_passage=shape.quoted_passage,
                    retrieved_at=shape.retrieved_at,
                )
            )

        # Strongest first, then by case id so a tie is stable across runs and a
        # report does not reshuffle its own citations between drafts.
        scored.sort(key=lambda m: (-m.score, m.case_id))

        if self.matching.get("both_sides_always", True):
            return _keep_both_sides(scored, limit)
        return scored[:limit]


# =============================================================================
# internals
# =============================================================================
def _score(
    shape: PrecedentShape, query: dict[str, Any], weights: dict[str, int]
) -> tuple[int, tuple[str, ...]]:
    """Weighted agreement over the dimensions both sides actually state.

    A dimension absent from either side scores nothing and is not counted
    against the match. `None` genuinely means unknown here -- an element whose
    subject's mortality was never established is not thereby different from a
    case about a living person, it is simply silent on the point.
    """
    score = 0
    matched: list[str] = []

    for dimension, weight in weights.items():
        if dimension == "semantic_overlap":
            if _semantic_overlap(query.get("text"), shape.semantic_text):
                score += int(weight)
                matched.append("judgment language")
            continue
        theirs = getattr(shape, dimension, None)
        ours = query.get(dimension)
        if theirs is None or ours is None:
            continue
        # A negative-assertion dispute is not a precedent match for neutral or
        # positive copy merely because the person is alive and named.
        if dimension in {"kind", "polarity"} and not _equal(theirs, ours):
            return 0, ()
        if _equal(theirs, ours):
            score += int(weight)
            matched.append(dimension)

    return score, tuple(matched)


def _equal(a: Any, b: Any) -> bool:
    """Compare across the string and enum spellings the corpus mixes."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return str(a).strip().upper() == str(b).strip().upper()


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "him",
    "his",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "they",
    "this",
    "to",
    "was",
    "were",
    "with",
}


def _semantic_overlap(query_text: Any, case_text: str) -> bool:
    """A conservative lexical-semantic signal over sourced judgment text.

    This is intentionally not an embedding pretending to determine legal
    similarity. Two non-trivial terms must overlap, or one unusually specific
    term (nine or more characters). Shape remains the main retrieval signal.
    """
    if not query_text or not case_text:
        return False

    def terms(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) >= 4 and token not in _STOPWORDS
        }

    shared = terms(str(query_text)) & terms(case_text)
    return len(shared) >= 2 or any(len(token) >= 9 for token in shared)


def _keep_both_sides(scored: list[PrecedentMatch], limit: int) -> list[PrecedentMatch]:
    """Never return only losses when the corpus also holds a win.

    A reviewer shown three plaintiff side cases and no defence side one reads a
    finding as a disaster. The corpus was assembled specifically so that
    correctly clearing protected expressive use scores as heavily as catching a
    failure, and retrieval has to honour the same balance or it undoes it.

    The best of the other side displaces the weakest of the majority, and only
    when the other side has something above the threshold to offer.
    """
    if len(scored) <= 1:
        return scored[:limit]

    head = scored[:limit]
    if len({m.side for m in head}) > 1:
        return head

    majority = head[0].side
    other = next((m for m in scored[limit:] if m.side != majority), None)
    if other is None:
        return head
    return [*head[:-1], other]


def _to_shape(case: dict[str, Any]) -> PrecedentShape | None:
    """Derive the matchable shape from a case's own reconstruction block.

    Derived rather than declared alongside it. A second hand written
    representation of the same case would drift from the first, and the
    reconstruction is already stated in exactly the vocabulary the pipeline
    routes on.
    """
    case_id = str(case.get("id") or "").strip()
    if not case_id:
        return None

    reconstruction = case.get("shape") or case.get("reconstruction") or {}
    if not isinstance(reconstruction, dict):
        reconstruction = {}
    expected = case.get("expected") or {}
    if not isinstance(expected, dict):
        expected = {}

    element_type = _element_type(reconstruction.get("element_type"))

    # A person rollup is a bag of claims, and its shape is the shape of the
    # claims in it: the corpus entry exists because the *density* of negative
    # claims about one living person is itself the finding.
    kind = str(reconstruction.get("kind") or "") or None
    polarity = reconstruction.get("polarity")
    subject_alive = reconstruction.get("subject_alive")
    if kind == "person_rollup":
        claims = [c for c in (reconstruction.get("claims") or []) if isinstance(c, dict)]
        if any(str(c.get("polarity", "")).lower() == "negative" for c in claims):
            polarity = "negative"
        if subject_alive is None:
            subject_alive = True  # a rollup case is about a person who can sue

    source = case.get("source") or {}
    verification = case.get("verification") or {}
    issues = case.get("issues") or []
    quoted_passage = str(source.get("quoted_passage") or "").strip()
    source_url = str(source.get("url") or "").strip()
    verified = (
        str(verification.get("status") or "").strip().lower() == "verified"
        and bool(source_url)
        and bool(quoted_passage)
    )

    return PrecedentShape(
        case_id=case_id,
        name=str(case.get("name") or case_id),
        # `failure_mode: null` is how the corpus marks the cases the studios
        # won. It is load bearing and it is the only side marker present.
        side=str(
            case.get("side") or ("defence" if case.get("failure_mode") is None else "plaintiff")
        ),
        outcome=str(case.get("outcome") or case.get("failure_mode") or "").strip(),
        lesson=_lesson(case),
        verified=verified,
        court=str(case.get("court") or "").strip(),
        docket_number=str(case.get("docket_number") or "").strip(),
        citation=str(case.get("citation") or "").strip(),
        decision_date=str(case.get("decision_date") or "").strip(),
        procedural_posture=str(case.get("procedural_posture") or "").strip(),
        holding=str(case.get("holding") or "").strip(),
        source_url=source_url,
        source_type=str(source.get("type") or "").strip(),
        document_number=str(source.get("document_number") or "").strip(),
        pin_cite=str(source.get("pin_cite") or "").strip(),
        quoted_passage=quoted_passage,
        retrieved_at=str(source.get("retrieved_at") or "").strip(),
        semantic_text=" ".join(
            [
                str(case.get("holding") or ""),
                quoted_passage,
                *(str(issue) for issue in issues if issue),
            ]
        ),
        kind=kind,
        element_type=element_type,
        claim_type=reconstruction.get("claim_type") or _claim_type_of(expected),
        polarity=str(polarity) if polarity is not None else None,
        subject_alive=subject_alive if isinstance(subject_alive, bool) else None,
        named=reconstruction.get("named"),
        truth_claim_framing=reconstruction.get("project_truth_claim_framing"),
    )


def _element_type(raw: Any) -> ElementType | None:
    if raw is None:
        return None
    try:
        return ElementType(str(raw).strip())
    except ValueError:
        log.debug("precedent corpus names an unknown element type: %r", raw)
        return None


def _claim_type_of(expected: dict[str, Any]) -> str | None:
    value = expected.get("claim_type")
    return str(value) if value else None


def _lesson(case: dict[str, Any]) -> str:
    """The prose a reviewer actually reads.

    The corpus states the point of each case under a different key every time
    -- `the_sharp_lesson`, `why_amber_matters`, `the_calibration_point` -- and
    that is deliberate authorship rather than untidiness, so all of them are
    accepted instead of renaming the corpus to suit the code.
    """
    direct = case.get("lesson")
    if isinstance(direct, str) and direct.strip():
        return " ".join(direct.split())
    for key, value in case.items():
        if key.startswith(("why_", "the_")) and isinstance(value, str) and value.strip():
            return " ".join(value.split())
    note = case.get("subsystem_justified")
    return str(note).strip() if note else ""


@lru_cache(maxsize=1)
def load_precedents() -> PrecedentIndex:
    """The process wide corpus. Small, immutable, read once."""
    return PrecedentIndex.load()
