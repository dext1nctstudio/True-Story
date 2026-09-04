"""Precedent retrieval. The litigation set, read forwards.

`eval/litigation_set/cases.yaml` has been a scoring harness: run the pipeline
over a reconstruction and check whether it caught what the court eventually
did. That is the corpus answering a retrospective question.

The same corpus answers a more useful one at adjudication time. A finding does
not arrive in a vacuum; it has a shape, and a dozen of those shapes have
already been litigated in public. Telling a reviewer that the line in front of
them is the same shape as a matter that settled is worth more than another
paragraph of rationale, because it is the reasoning a clearance attorney
actually does.

SHAPE, NOT SUBJECT MATTER
    A chess prodigy and a prosecutor have nothing in common as topics. As
    failure shapes they are one object -- a negative assertion about a named,
    living person -- and that is what a court responds to. So matching runs
    over the dimensions the pipeline already routes on: element type, claim
    type, polarity, whether the subject is alive, whether they are named,
    whether the production asserts a true story.

    A match therefore reports *which dimensions matched*, not a similarity
    score. "Matched on element_type, polarity, subject_alive" is something a
    lawyer can disagree with. "0.87" is not.

NO MODEL, NO SPEND
    This stage makes no research call and no model call. Retrieval is a table
    lookup over a corpus of twelve, and the weights live in `cases.yaml` where
    an attorney can argue with them. Deciding by hand what a model would have
    guessed is the same choice `policy/rubric.yaml` already makes for the
    adjudicator's post checks.

THREE GUARDRAILS, ALL OF THEM LOAD BEARING
    A precedent never moves a status. It is attached to a finding as context
    for the human who decides, and nothing downstream reads it as a signal.
    The alternative -- letting a retrieved case nudge a verdict -- is reasoning
    from resemblance, which is exactly the error the attribution gate exists to
    prevent for sources.

    Defence side cases are retrieved on the same terms as plaintiff side ones.
    A corpus that surfaced only losses would make every finding look like a
    disaster, which is the paranoia engine `cases.yaml` opens by warning about.

    Every case in the corpus is marked `verify: required` and none has been
    confirmed against a primary source in this repository. That flag travels
    with the match and the renderer is expected to say so. An unconfirmed
    precedent presented as settled law is a worse failure than no precedent.
"""

from __future__ import annotations

import logging
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

#: The corpus. Ships with the repository and runs with no credentials.
CASES_PATH = EVAL_DIR / "litigation_set" / "cases.yaml"

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
    #: False for every case in the corpus today. Rendered as an explicit
    #: caveat, never dropped.
    verified: bool

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
            "caveat": (
                "Reconstructed from public reporting and not confirmed against a "
                "primary source. Context for counsel, not authority."
            ),
        }


@dataclass(slots=True)
class PrecedentIndex:
    """The litigation set, queryable by failure shape."""

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
                "truth_claim_framing": truth_claim_framing,
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
                "truth_claim_framing": truth_claim_framing,
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
        theirs = getattr(shape, dimension, None)
        ours = query.get(dimension)
        if theirs is None or ours is None:
            continue
        if _equal(theirs, ours):
            score += int(weight)
            matched.append(dimension)

    return score, tuple(matched)


def _equal(a: Any, b: Any) -> bool:
    """Compare across the string and enum spellings the corpus mixes."""
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    return str(a).strip().upper() == str(b).strip().upper()


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

    reconstruction = case.get("reconstruction") or {}
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

    return PrecedentShape(
        case_id=case_id,
        name=str(case.get("name") or case_id),
        # `failure_mode: null` is how the corpus marks the cases the studios
        # won. It is load bearing and it is the only side marker present.
        side="defence" if case.get("failure_mode") is None else "plaintiff",
        outcome=str(case.get("outcome") or case.get("failure_mode") or "").strip(),
        lesson=_lesson(case),
        # Every case carries `verify: required` today. Read rather than
        # assumed, so confirming one in the corpus is enough to change what the
        # report says about it.
        verified=str(case.get("verify", "required")).strip().lower() != "required",
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
    for key, value in case.items():
        if key.startswith(("why_", "the_")) and isinstance(value, str) and value.strip():
            return " ".join(value.split())
    note = case.get("subsystem_justified")
    return str(note).strip() if note else ""


@lru_cache(maxsize=1)
def load_precedents() -> PrecedentIndex:
    """The process wide corpus. Small, immutable, read once."""
    return PrecedentIndex.load()
