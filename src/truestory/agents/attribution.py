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
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.attribution")

#: A quote shorter than this proves nothing: "the" appears in every document.
MIN_QUOTE_CHARS = 24

#: How much of a page the gate is allowed to read per source. Long enough for
#: the passage to be present, short enough to keep forty of these concurrent.
MAX_SOURCE_CHARS = 6000


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
                candidates.append((citation, body[:MAX_SOURCE_CHARS]))
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
            response = await self._genai().aio.models.generate_content(
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
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
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


def verify_quote(quote: str, source_text: str) -> bool:
    """Whether `quote` really occurs in `source_text`.

    Three passes, each looser about formatting and none looser about wording:

      1. exact, after folding page artefacts
      2. an ellipsis elided quotation, checked as its parts in order
      3. the bare word sequence, punctuation and markup discarded

    A model that invented the sentence fails all three, because every pass
    still requires the same words in the same order.
    """
    if not quote or not source_text:
        return False

    needle = _normalise(quote)
    haystack = _normalise(source_text)
    if len(needle) < MIN_QUOTE_CHARS:
        return False

    if needle in haystack:
        return True

    parts = [p.strip() for p in re.split(r"\.{3}|\u2026", needle) if len(p.strip()) >= 12]
    if len(parts) >= 2:
        cursor = 0
        for part in parts:
            found = haystack.find(part, cursor)
            if found == -1:
                break
            cursor = found + len(part)
        else:
            return True

    words = _words_only(quote)
    return len(words) >= MIN_QUOTE_CHARS and words in _words_only(source_text)


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
        if best_overlap >= 0.2 and len(best) >= MIN_QUOTE_CHARS:
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
