"""The attribution gate. What a source actually says about this claim.

A research API returns the sources it consulted. It does not return the sources
that bear on the question, and the difference between those two things is the
difference between a fact checker and a search box with a confident voice.

Measured, on this system, against the two test fixtures:

  * Asked whether an invented person was dismissed from an invented board,
    Google Search grounding returned ntsb.gov, kauai.gov, honolulu.gov and
    wikipedia.org. All real. All authoritative looking. None of them about the
    claim, which the prose answer said plainly while the citation list said the
    opposite.
  * Asked the same question, Parallel answered `no_record` — correctly — and
    attached a basis citation to a teenage swimmer's results page, because the
    basis explains fields like `record_quality`, not the verdict.

Attaching either set as evidence is the most damaging thing this product could
do: an underwriter reads four government domains under a sentence about a
person who does not exist.

So a citation is not evidence until something has said what it does for *this*
proposition and quoted the words that do it, and that quote has been found in
the retrieved text by string search rather than taken on trust.

    retrieve -> fetch the page -> quote it -> verify the quote is really there
             -> assign a stance -> only then is it evidence

The verification step is deliberately dumb. A model that has invented a quote
cannot make `in` return True.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from truestory.config import settings
from truestory.models.evidence import Citation
from truestory.providers import model_fallback
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.attribution")

# A single character floor was the wrong shape for this check, and it failed in
# the direction that costs coverage. Measured on the live MS Dhoni run: 23 of 44
# rejected quotes never reached the substring comparison at all, killed by a flat
# 24 character minimum. What died there was the best evidence in the run —
# "MS Dhoni not out 91 79." from the Cricbuzz scorecard (23 characters, one short),
# "IND 277-4 (48.2)", "India won by 6 wkts", "Winner : India" — while padded
# journalism and a page about the 2011 FIFA *Women's* World Cup sailed through on
# length alone. Registry and scorecard records state facts tersely; that is what
# makes them authoritative. A character floor therefore discarded the strongest
# source class and kept the weakest, which is precisely backwards.
#
# The floor now scales with how much folding the comparison did to get its match.
# Strictness is spent where fabrication actually hides: in the loose passes.

#: Floor for an exact hit, where nothing but capture artefacts were folded. A
#: verbatim run this long, found unchanged in the page, is not a coincidence —
#: and it is not the only defence, since the model must also have chosen the span
#: as bearing on the proposition and marked it about this subject.
MIN_EXACT_QUOTE_CHARS = 10

#: Floor for each part of an elided quotation. Below this a fragment is too
#: generic to pin an ordering on.
MIN_ELIDED_PART_CHARS = 8

#: Floor for the last resort comparison, counted in WORDS rather than characters.
#: Stripping punctuation shortens the string, so reusing a character floor here
#: penalised a quote twice for the same folding and made the loosest rescue path
#: the hardest to reach for the terse records that needed it. Word count is what
#: actually resists coincidence: "the" and "India" fail it, "India won by 6 wkts"
#: does not.
MIN_FALLBACK_WORDS = 4

#: How much of a page the gate is allowed to read per source. Raised from 6000
#: after the same run: a scorecard page spends its opening thousands of
#: characters on navigation, advertising and commentary, so the head slice
#: routinely excluded the results table holding the fact under test. The gate
#: then truthfully reported that the quote was not in the text it was given,
#: having been given the wrong part of the page. Where a body still exceeds this,
#: `_select_window` centres the slice on the passage rather than taking the head.
MAX_SOURCE_CHARS = 20000


# =============================================================================
# the forced declaration
# =============================================================================

RECORD_ATTRIBUTION_DECLARATION: dict[str, Any] = {
    "name": "record_attribution",
    "description": (
        "Say what each numbered source does for the proposition, quoting the "
        "words that do it. One entry per source, in the order given."
    ),
    "parameters": {
        "type": "object",
        "required": ["assessments"],
        "properties": {
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["index", "stance", "quote", "reason"],
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "The source number as given, starting at 1.",
                        },
                        "stance": {
                            "type": "string",
                            "enum": ["supports", "contradicts", "irrelevant"],
                            "description": (
                                "supports: the text states the proposition or entails it. "
                                "contradicts: the text states something that cannot be true "
                                "at the same time as the proposition. irrelevant: the text "
                                "does not address it, or is about a different subject that "
                                "happens to share a name. Silence is irrelevant, never "
                                "contradicts."
                            ),
                        },
                        "quote": {
                            "type": "string",
                            "description": (
                                "A verbatim span copied from that source's text, long enough "
                                "to stand on its own. Never paraphrase, never combine two "
                                "passages, never write a sentence the text does not contain. "
                                "Empty string when the stance is irrelevant."
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "One sentence. Why that quote does what you say it does.",
                        },
                        "about_subject": {
                            "type": "boolean",
                            "description": (
                                "Whether the text is about the named subject rather than "
                                "someone or something that shares the name."
                            ),
                        },
                    },
                },
            }
        },
    },
}

_SYSTEM = """\
You are a fact checker reading source material. You are not answering the
question from your own knowledge and you have no knowledge to add: your only
job is to report what each supplied text says about one proposition.

Rules, in order of importance.

1. Quote verbatim. Every quote you give must be copied character for character
   out of the source text you were shown. If you cannot find such a span, the
   stance is irrelevant and the quote is empty. A quote that is not in the text
   is the worst possible output and is checked by string search afterwards.

2. Silence is not contradiction. A source that does not mention the subject, or
   mentions the subject without addressing the proposition, is irrelevant. Only
   a source stating something incompatible with the proposition contradicts it.

3. Same name is not same subject. A results page for a schoolgirl swimmer named
   Rowan is not about Dr Maya Rowan of the Oceanic Safety Board. Set
   about_subject to false and the stance to irrelevant.

4. Partial support is not support. If the proposition says 97 and the text says
   91, that is a contradiction, not support. If the proposition says a date the
   text does not give, that is irrelevant.

5. Say irrelevant freely. Most sources returned by a search are irrelevant to
   any specific proposition, and reporting that honestly is the entire value of
   this step.
"""


# =============================================================================
# results
# =============================================================================


@dataclass(slots=True)
class AttributionReport:
    """What survived, what did not, and why. Shown to the user verbatim."""

    citations: list[Citation] = field(default_factory=list)
    assessed: int = 0
    kept: int = 0
    dropped_irrelevant: int = 0
    dropped_unquotable: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def supports(self) -> int:
        return sum(1 for c in self.citations if c.stance == "supports" and c.quote_verified)

    @property
    def contradicts(self) -> int:
        return sum(1 for c in self.citations if c.stance == "contradicts" and c.quote_verified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessed": self.assessed,
            "kept": self.kept,
            "supports": self.supports,
            "contradicts": self.contradicts,
            "dropped_irrelevant": self.dropped_irrelevant,
            "dropped_unquotable": self.dropped_unquotable,
            "notes": self.notes,
        }


# =============================================================================
# the gate
# =============================================================================


class AttributionGate:
    """Assess a set of candidate sources against one proposition."""

    name = "AttributionGate"

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        # Deliberately the fast model. This runs once per subject over a handful
        # of short texts, it is a reading comprehension task rather than a
        # judgement, and the deterministic quote check catches its mistakes.
        self.model = model or settings.model_attribution
        self._client = client

    async def assess(
        self,
        proposition: str,
        subject: str,
        citations: list[Citation],
        *,
        source_texts: dict[str, str] | None = None,
    ) -> AttributionReport:
        """Return the citations that bear on `proposition`, quoted and stanced.

        `source_texts` maps URL to the fullest text available for that source,
        normally a page captured by Extract. Where a URL is absent the
        citation's own excerpt is used, which is weaker but still verifiable.
        """
        report = AttributionReport()
        if not citations:
            return report

        texts = source_texts or {}
        candidates: list[tuple[Citation, str]] = []
        for citation in citations:
            body = (texts.get(citation.url) or citation.excerpt or "").strip()
            if body:
                # The model and the verifier must read exactly the same text,
                # so the window is chosen once, here, and carried through.
                candidates.append((citation, _select_window(body, proposition, subject)))
            else:
                # Nothing to read means nothing to verify. A URL with no text
                # behind it is a link, not a source, and it is dropped rather
                # than shown under a verdict.
                report.assessed += 1
                report.dropped_unquotable += 1

        if not candidates:
            report.notes.append(
                "No source returned any readable text, so nothing could be attributed."
            )
            return report

        report.assessed += len(candidates)
        calls = await self._call_model(proposition, subject, candidates)

        for index, (citation, body) in enumerate(candidates, start=1):
            call = calls.get(index)
            if call is None:
                report.dropped_unquotable += 1
                continue

            stance = str(call.get("stance", "irrelevant")).lower()
            quote = str(call.get("quote", "") or "").strip()
            reason = str(call.get("reason", "") or "")[:400]
            about_subject = call.get("about_subject")

            if about_subject is False:
                stance = "irrelevant"
                reason = reason or "The source is about a different subject that shares the name."

            if stance not in ("supports", "contradicts"):
                report.dropped_irrelevant += 1
                continue

            verified = verify_quote(quote, body)
            if not verified:
                # The model said the source says something and could not point
                # at where. That is the failure mode this whole module exists
                # for, so it is counted rather than quietly forgiven.
                log.info("unverifiable quote dropped for %s: %r", citation.url, quote[:80])
                report.dropped_unquotable += 1
                continue

            report.kept += 1
            report.citations.append(
                _with_attribution(citation, stance=stance, quote=quote, reason=reason)
            )

        if report.dropped_unquotable:
            report.notes.append(
                f"{report.dropped_unquotable} source"
                f"{'' if report.dropped_unquotable == 1 else 's'} could not be quoted "
                "against this claim and were not counted as evidence."
            )
        if report.dropped_irrelevant:
            report.notes.append(
                f"{report.dropped_irrelevant} source"
                f"{'' if report.dropped_irrelevant == 1 else 's'} were returned by the "
                "search but do not address this claim."
            )
        return report

    # ── model ────────────────────────────────────────────────────────────────
    async def _call_model(
        self, proposition: str, subject: str, candidates: list[tuple[Citation, str]]
    ) -> dict[int, dict[str, Any]]:
        if settings.offline:
            return _offline_assessment(proposition, candidates)

        from google.genai import types

        prompt = _prompt(proposition, subject, candidates)
        try:
            response = await model_fallback.generate(
                self._genai(),
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.0,
                    tools=[types.Tool(function_declarations=[RECORD_ATTRIBUTION_DECLARATION])],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY",
                            allowed_function_names=["record_attribution"],
                        )
                    ),
                ),
            )
            meter_response(self.model, response)
        except Exception as exc:
            log.warning("attribution call failed: %s", exc)
            # Failing closed is the only safe direction. An unassessed source is
            # not evidence, so a failed gate produces no evidence rather than
            # waving everything through.
            return {}

        for candidate in getattr(response, "candidates", []) or []:
            for part in getattr(candidate.content, "parts", []) or []:
                call = getattr(part, "function_call", None)
                if call and call.name == "record_attribution":
                    rows = dict(call.args).get("assessments") or []
                    return {int(r.get("index", 0)): dict(r) for r in rows if r.get("index")}
        return {}

    def _genai(self) -> Any:
        if self._client is None:
            self._client = model_fallback.genai_client()
        return self._client


# =============================================================================
# deterministic verification
# =============================================================================


#: Markdown that a page capture adds around the words. `[Gambhir](https://...)`
#: is the same quotation as `Gambhir`, and treating the link as part of the
#: wording rejected the correct passage: on a live run the ESPNcricinfo line
#: "India 277 for 4 (Gambhir 97, Dhoni 91*)" — the exact record for the claim
#: under test — was dropped as unverifiable because the captured markdown
#: carried a URL inside it.
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_WIKILINK = re.compile(r"\[\[([^\]]*)\]\]")
_MD_DECORATION = re.compile(r"[*_`>#|]+")


def _strip_markup(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_WIKILINK.sub(r"\1", text)
    return _MD_DECORATION.sub(" ", text)


def _normalise(text: str) -> str:
    """Fold everything that a copy out of a web page legitimately changes.

    Smart quotes, non breaking spaces, ligatures, markdown link syntax and
    collapsed whitespace are artefacts of the capture, not of the quotation.
    Case is folded too. What is deliberately *not* folded is word order or
    wording: those are the things a fabricated quote gets wrong.
    """
    folded = unicodedata.normalize("NFKD", _strip_markup(text))
    folded = folded.replace("\u2019", "'").replace("\u2018", "'")
    folded = folded.replace("\u201c", '"').replace("\u201d", '"')
    folded = folded.replace("\u2013", "-").replace("\u2014", "-")
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip().lower()


def _words_only(text: str) -> str:
    """The word sequence alone, every mark of punctuation removed.

    The last resort comparison. A quotation differing from its source only in
    punctuation, spacing or markup is the same quotation; one differing in its
    words is a different one, and this still catches that.
    """
    return " ".join(re.findall(r"[a-z0-9]+", _normalise(text)))


#: Words too common to locate a passage by. Deliberately short: the numbers and
#: proper nouns in a proposition are what pin it to a row in a table.
_WINDOW_STOPWORDS = frozenset(
    {
        "that", "this", "with", "from", "were", "what", "when", "where",
        "which", "while", "would", "could", "should", "have", "been", "being",
        "about", "into", "over", "under", "after", "before", "their", "there",
        "they", "them", "said", "says", "than", "then", "some", "such",
        "only", "also", "more", "most", "other", "these", "those",
    }
)  # fmt: skip


def _salient_terms(proposition: str, subject: str) -> set[str]:
    """The tokens worth locating a page window by.

    Numbers are kept whatever their length, because on the sources this gate
    reads terse ones carry the whole fact: 91, 277, 2011.
    """
    text = f"{subject} {proposition}".lower()
    words = {w for w in re.findall(r"[a-z]{4,}", text) if w not in _WINDOW_STOPWORDS}
    return words | set(re.findall(r"\d+", text))


#: Marks where a page was elided so the gate could read the relevant part. A
#: quotation spanning the join fails verification, which is the safe direction.
_WINDOW_JOIN = "\n\n[…]\n\n"


def _select_window(body: str, proposition: str, subject: str) -> str:
    """At most MAX_SOURCE_CHARS of `body`, chosen for relevance not position.

    Taking the head of a page is the wrong slice for exactly the sources worth
    reading. A scorecard, a docket or a registry entry puts navigation,
    advertising and commentary first and the load bearing row far down, so a
    head slice hands the gate a page that genuinely does not contain the fact
    and the gate correctly rejects a true quotation.

    The head is still kept, because a lede and an infobox live there, and the
    remainder of the budget goes to the densest match for the proposition.
    """
    if len(body) <= MAX_SOURCE_CHARS:
        return body

    terms = _salient_terms(proposition, subject)
    head_chars = MAX_SOURCE_CHARS // 4
    head = body[:head_chars]
    if not terms:
        return body[:MAX_SOURCE_CHARS]

    tail_budget = MAX_SOURCE_CHARS - head_chars - len(_WINDOW_JOIN)
    hay = body.lower()
    stride = max(1, tail_budget // 4)
    best_start, best_score = head_chars, -1
    for start in range(head_chars, len(body), stride):
        chunk = hay[start : start + tail_budget]
        score = sum(1 for term in terms if term in chunk)
        if score > best_score:
            best_start, best_score = start, score

    if best_score <= 0:
        return body[:MAX_SOURCE_CHARS]
    return head + _WINDOW_JOIN + body[best_start : best_start + tail_budget]


def verify_quote(quote: str, source_text: str) -> bool:
    """Whether `quote` really occurs in `source_text`.

    Three passes, each looser about formatting and none looser about wording,
    and each carrying its own floor because each has folded away a different
    amount of the evidence that the quotation is real:

      1. exact, after folding page artefacts   -> MIN_EXACT_QUOTE_CHARS
      2. an ellipsis elided quotation, in order -> MIN_ELIDED_PART_CHARS per part
      3. the bare word sequence, punctuation discarded -> MIN_FALLBACK_WORDS

    A model that invented the sentence fails all three, because every pass
    still requires the same words in the same order. What the graded floors
    change is only how short a *true* quotation is allowed to be, which is the
    axis on which a flat minimum was throwing away scorecards and registries.
    """
    if not quote or not source_text:
        return False

    needle = _normalise(quote)
    haystack = _normalise(source_text)
    if not needle or not haystack:
        return False

    # 1. Exact. Nothing folded but capture artefacts, so the shortest floor.
    if len(needle) >= MIN_EXACT_QUOTE_CHARS and needle in haystack:
        return True

    # 2. Elided. Ordering across parts is itself evidence, so each part may be
    #    shorter than a standalone quote would have to be.
    parts = [
        p.strip()
        for p in re.split(r"\.{3}|\u2026", needle)
        if len(p.strip()) >= MIN_ELIDED_PART_CHARS
    ]
    if len(parts) >= 2:
        cursor = 0
        for part in parts:
            found = haystack.find(part, cursor)
            if found == -1:
                break
            cursor = found + len(part)
        else:
            return True

    # 3. Words only. The heaviest folding, so the floor is a word count, which
    #    is the thing punctuation stripping cannot inflate away.
    words = _words_only(quote)
    if len(words.split()) < MIN_FALLBACK_WORDS:
        return False
    return words in _words_only(source_text)


def _with_attribution(citation: Citation, *, stance: str, quote: str, reason: str) -> Citation:
    """Citation is frozen, so attribution produces a new one."""
    return Citation(
        url=citation.url,
        title=citation.title,
        # The verified quote replaces whatever excerpt came back, because it is
        # the passage the verdict actually rests on and it is the passage the
        # evidence appendix should print.
        excerpt=quote[:1200] or citation.excerpt,
        accessed_at=citation.accessed_at,
        source_type=citation.source_type,
        publisher=citation.publisher,
        published_at=citation.published_at,
        reliability=citation.reliability,
        source_class=citation.source_class,
        trust=citation.trust,
        verified_source=citation.verified_source,
        stance=stance,
        quote=quote[:1200],
        quote_verified=True,
        stance_reason=reason,
    )


def _prompt(proposition: str, subject: str, candidates: list[tuple[Citation, str]]) -> str:
    blocks = []
    for index, (citation, body) in enumerate(candidates, start=1):
        blocks.append(
            f"SOURCE {index}\n"
            f"  url: {citation.url}\n"
            f"  publisher: {citation.publisher or citation.domain}\n"
            f"  text:\n{body}\n"
        )
    return (
        f"PROPOSITION: {proposition.strip()}\n"
        f"SUBJECT: {subject or 'not stated'}\n\n"
        "For each source below, say whether its text supports the proposition, "
        "contradicts it, or is irrelevant to it, and quote the words verbatim.\n\n"
        + "\n".join(blocks)
    )


# =============================================================================
# offline
# =============================================================================


def _offline_assessment(
    proposition: str, candidates: list[tuple[Citation, str]]
) -> dict[int, dict[str, Any]]:
    """Deterministic stand in, so mock mode exercises the same code path.

    Token overlap, and the quote is a real span lifted from the text, so the
    verification step below runs for real rather than being skipped offline.
    """
    words = set(re.findall(r"[a-z0-9']{4,}", proposition.lower()))
    out: dict[int, dict[str, Any]] = {}
    for index, (_, body) in enumerate(candidates, start=1):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 30]
        best, best_overlap = "", 0.0
        for sentence in sentences:
            tokens = set(re.findall(r"[a-z0-9']{4,}", sentence.lower()))
            overlap = len(words & tokens) / max(1, len(words))
            if overlap > best_overlap:
                best, best_overlap = sentence, overlap
        if best_overlap >= 0.2 and len(best) >= MIN_EXACT_QUOTE_CHARS:
            out[index] = {
                "index": index,
                "stance": "supports",
                "quote": best[:400],
                "reason": "Offline token overlap stand in. Not a reading of the source.",
                "about_subject": True,
            }
        else:
            out[index] = {"index": index, "stance": "irrelevant", "quote": "", "reason": ""}
    return out
