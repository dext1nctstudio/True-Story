"""Does this subject exist, and which one is it.

The stage the pipeline was missing. Research was dispatched at every named
subject in a screenplay, including the invented ones, and whatever came back
was attached as evidence. A fact checker does not work that way. Before asking
whether Dr Maya Rowan was dismissed from the Oceanic Safety Board, a person
establishes whether Dr Maya Rowan is anybody, because if she is not then the
question has no answer and any source offered for it is noise.

Three outcomes, and each one sends the subject somewhere different:

    RESOLVED     A real, identifiable subject, pinned to an identifier. Claims
                 about it are verified against the record.
    COLLISION    The name resolves to several real people, none of them
                 prominent. The character is invented; the *name* is the
                 finding, and it goes to the collision check rather than to
                 fact verification. This is the Baby Reindeer shape.
    UNIDENTIFIED No real subject bears this name. Claims about it are not
                 researched at all: they are recorded as having no verifiable
                 real-world referent, at zero spend, with no citations, because
                 a citation attached here is by construction about somebody
                 else.

Two independent authorities have to agree before a name is called an
invention. Wikidata answers first because it is free, immediate and incapable
of inventing an entry; it is also incomplete, so a miss is escalated to a
grounded web search rather than being taken as proof of absence.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

from truestory.agents.nameguard import is_nameable, label_matches_any
from truestory.config import settings
from truestory.providers import model_fallback
from truestory.providers.model_cost import meter_response
from truestory.providers.wikidata import EntityCandidate, WikidataClient

log = logging.getLogger("truestory.identity")

#: Wikipedia language editions above which a name is taken to denote its famous
#: holder. Below it, several real people share the name and none dominates,
#: which is the collision case rather than the identification case.
PROMINENCE_SITELINKS = 5


class IdentityStatus:
    RESOLVED = "resolved"
    COLLISION = "collision"
    UNIDENTIFIED = "unidentified"
    UNCHECKED = "unchecked"


@dataclass(slots=True)
class IdentityVerdict:
    """Who, if anyone, this name denotes."""

    name: str
    status: str = IdentityStatus.UNCHECKED
    canonical: EntityCandidate | None = None
    candidates: list[EntityCandidate] = field(default_factory=list)
    reason: str = ""
    #: What the grounded second opinion said, when one was needed.
    web_checked: bool = False
    web_summary: str = ""
    web_domains: list[str] = field(default_factory=list)

    @property
    def researchable(self) -> bool:
        """Whether a factual claim about this subject can be checked at all."""
        return self.status == IdentityStatus.RESOLVED

    @property
    def official_domain(self) -> str | None:
        """The subject's own site, which is a primary source about itself."""
        site = self.canonical.official_site if self.canonical else None
        if not site:
            return None
        from truestory.providers.source_quality import registrable_domain

        return registrable_domain(site) or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "canonical": self.canonical.to_dict() if self.canonical else None,
            "candidates": [c.to_dict() for c in self.candidates[:5]],
            "web_checked": self.web_checked,
            "web_summary": self.web_summary,
            "web_domains": self.web_domains,
            "official_domain": self.official_domain,
        }


class IdentityResolver:
    """Wikidata first, then the open web, then a decision."""

    name = "IdentityResolver"

    def __init__(
        self,
        wikidata: WikidataClient | None = None,
        model: str | None = None,
        client: Any = None,
    ) -> None:
        self.wikidata = wikidata or WikidataClient()
        self.model = model or settings.model_identity
        self._client = client
        self._cache: dict[str, IdentityVerdict] = {}
        self._lock = asyncio.Lock()

    async def resolve(
        self, name: str, *, hints: str = "", is_person: bool = True
    ) -> IdentityVerdict:
        """Identify `name`, using `hints` from the script to disambiguate."""
        clean = " ".join((name or "").split())
        if not clean:
            return IdentityVerdict(name=name, status=IdentityStatus.UNCHECKED, reason="no name")

        key = f"{clean.lower()}|{is_person}"
        async with self._lock:
            cached = self._cache.get(key)
        if cached:
            return cached

        verdict = await self._resolve(clean, hints, is_person)
        async with self._lock:
            self._cache[key] = verdict
        return verdict

    async def _resolve(self, name: str, hints: str, is_person: bool) -> IdentityVerdict:
        # Before the knowledge base is asked anything: is this the kind of
        # string that denotes a subject at all. A pronoun is not, and asking
        # Wikidata for "her" returns hertz, the SI unit, carried by 97
        # Wikipedia editions, which clears every prominence test this class
        # applies. See nameguard for the full incident.
        nameable, why = is_nameable(name)
        if not nameable:
            return IdentityVerdict(
                name=name,
                status=IdentityStatus.UNIDENTIFIED,
                reason=(
                    f"Not researched: {why}. A claim filed under this subject has no "
                    "real world referent, so any source offered for it is about somebody else."
                ),
            )

        if settings.offline:
            # Mock mode makes no outbound call of any kind, and that contract
            # covers the knowledge base too. An unchecked identity blocks
            # nothing downstream, so the offline pipeline behaves as it did
            # before this stage existed rather than resolving every name to a
            # confident nothing.
            return IdentityVerdict(
                name=name,
                status=IdentityStatus.UNCHECKED,
                reason="Identity resolution is skipped in mock mode: it would require a network call.",
            )

        candidates = await self.wikidata.search(name)
        verdict = IdentityVerdict(name=name, candidates=candidates)

        # Fictional characters have entries too. A script naming one is not
        # making a claim about a real person, and treating the entry as an
        # identification would be its own kind of wrong.
        real = [c for c in candidates if not c.is_fictional]
        if is_person:
            # No `or real` fallback. That fallback is what accepted hertz for
            # "her": when the human filter emptied the list it silently handed
            # back the unfiltered one. Asking for a person and being given an
            # SI unit is the wrong kind of thing, not a weaker answer, and
            # every downstream stage would go on treating it as a person.
            real = [c for c in real if c.is_human]

        # The answer has to resemble the question. A knowledge base search is a
        # fuzzy string match and its ranking is not an identification.
        real = [c for c in real if label_matches_any(name, c.label, c.aliases)]

        if real:
            best = _best_match(real, hints, name)
            resolved = (
                best.sitelinks >= PROMINENCE_SITELINKS
                or _hint_overlap(best, hints, name) > 0
                or _label_affinity(best, name) >= 2.0
            )
            if resolved:
                verdict.status = IdentityStatus.RESOLVED
                verdict.canonical = best
                verdict.reason = (
                    f"Resolved to {best.label} ({best.qid}), {best.description or 'no description'}"
                    f", carried by {best.sitelinks} Wikipedia editions."
                )
                return verdict

            verdict.status = IdentityStatus.COLLISION
            verdict.reason = (
                f"{len(real)} real people share this name and none is prominent enough to be "
                "the assumed referent."
            )
            return verdict

        # Before concluding absence, try the name as a catalogue would hold it.
        # A script writes "the 2011 ICC Cricket World Cup final"; Wikidata holds
        # "2011 Cricket World Cup Final". One missing qualifier had the whole
        # event declared an invention and eight true claims about it dropped.
        simplified = _simplify(name)
        if simplified and simplified != name:
            retry = await self.wikidata.search(simplified)
            retry_real = [c for c in retry if not c.is_fictional]
            if is_person:
                retry_real = [c for c in retry_real if c.is_human]
            retry_real = [
                c for c in retry_real if label_matches_any(simplified, c.label, c.aliases)
            ]
            if retry_real:
                best = _best_match(retry_real, hints, simplified)
                verdict.candidates = retry
                verdict.status = IdentityStatus.RESOLVED
                verdict.canonical = best
                verdict.reason = (
                    f"Resolved to {best.label} ({best.qid}) after normalising the name as a "
                    f"catalogue would hold it: {simplified!r}."
                )
                return verdict

        # Nothing in the knowledge base. That is a signal, not a verdict:
        # plenty of real private individuals have no entry, so the open web
        # gets a vote before a name is called an invention.
        summary, domains = await self._web_second_opinion(name, hints, is_person)

        if summary is None:
            # The second opinion never ran. Neither conclusion is available:
            # resolving would confirm an identity nothing checked, and calling
            # it an invention would drop a real subject over a transient
            # failure. UNCHECKED is the honest third answer, and it leaves the
            # deterministic post checks to cap anything consequential built on
            # it.
            verdict.status = IdentityStatus.UNCHECKED
            verdict.reason = (
                "Not in the knowledge base, and the grounded web check could not be run. "
                "Identity is unconfirmed rather than denied: research may proceed, but "
                "nothing consequential may rest on this subject being who the script says."
            )
            return verdict

        verdict.web_checked = True
        verdict.web_summary = summary
        verdict.web_domains = domains

        if _reads_as_existing(summary):
            verdict.status = IdentityStatus.RESOLVED
            verdict.reason = (
                "Not in the knowledge base, but a grounded web search found a real subject "
                "of this name. Research proceeds with the identification unpinned."
            )
            return verdict

        verdict.status = IdentityStatus.UNIDENTIFIED
        verdict.reason = (
            "No entry in Wikidata and no real subject of this name found on the open web. "
            "Claims about it are not researched: there is nothing for a source to be about."
        )
        return verdict

    # ── the grounded second opinion ──────────────────────────────────────────
    async def _web_second_opinion(
        self, name: str, hints: str, is_person: bool
    ) -> tuple[str | None, list[str]]:
        """Ask the open web whether this name denotes anybody at all.

        Grounded rather than free running, so the answer is drawn from search
        results instead of from the model's memory. Controlled generation is
        not available alongside the search tool, so the reply is prose and the
        caller reads it with a fixed rule rather than parsing JSON.
        """
        if settings.offline:
            return ("", [])

        from google.genai import types

        kind = _kind_word(name, is_person)
        prompt = (
            f"Search the web and answer one question.\n\n"
            f"Is there a real {kind} called {name!r}"
            + (f", associated with: {hints}" if hints else "")
            + "?\n\n"
            "Answer in this exact form and nothing else:\n"
            "  Begin the reply with EXISTS: if the search results show a real "
            f"{kind} of that name, followed by one sentence identifying them.\n"
            "  Begin the reply with NO_RECORD: if the search results show no such "
            f"{kind}, followed by one sentence saying what the name does return.\n\n"
            "Do not answer from memory. If the results do not show the subject, that is "
            "NO_RECORD even if the name sounds plausible."
        )

        try:
            response = await model_fallback.generate(
                self._genai(),
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            meter_response(self.model, response)
        except Exception as exc:
            # None, not "". They are different facts and were being conflated:
            # "" means the check ran and said nothing, which `_reads_as_existing`
            # deliberately reads as exists rather than concluding absence from
            # silence. None means the check never ran, and a subject must not
            # be declared real because the machine that would have checked it
            # was unreachable.
            log.warning("identity web check failed for %r: %s", name, exc)
            return (None, [])

        text = (getattr(response, "text", "") or "").strip()
        domains: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            meta = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(meta, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                domain = getattr(web, "domain", None) or getattr(web, "title", None)
                if domain and domain not in domains:
                    domains.append(domain)
        return (text[:1200], domains[:8])

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
        return self._client

    async def aclose(self) -> None:
        await self.wikidata.close()


# =============================================================================
# helpers
# =============================================================================


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", (text or "").lower()))


def _normalise_name(name: str) -> str:
    return " ".join((name or "").lower().split())


def _hint_overlap(candidate: EntityCandidate, hints: str, name: str) -> int:
    """How much the script's context agrees with the item's own description.

    The subject's own name is excluded from the comparison, and that exclusion
    is the whole correctness of this function. Without it, a search for "India"
    scored "Indian Railways" above the country, because the hint text contains
    the word India and so does that item's description — the name matched
    itself, and a railway company won a cricket question.
    """
    name_tokens = _tokens(name)
    wanted = _tokens(hints) - name_tokens
    if not wanted:
        return 0
    have = (_tokens(candidate.description) | _tokens(" ".join(candidate.occupations))) - name_tokens
    return len(wanted & have)


def _label_affinity(candidate: EntityCandidate, name: str) -> float:
    """How closely the item's own label matches what was asked for.

    Wikidata search matches aliases as well as labels, so a query for "India"
    legitimately returns "Indian Railways". The label is the strongest
    available signal that a candidate is the thing that was asked about, and it
    was not being used at all.
    """
    wanted = _normalise_name(name)
    label = _normalise_name(candidate.label)
    if not wanted or not label:
        return 0.0
    if label == wanted:
        return 2.0
    if wanted in label or label in wanted:
        return 1.0
    return 0.0


def _score(candidate: EntityCandidate, name: str, hints: str) -> float:
    """Rank candidates by label, prominence and context, in that order of pull.

    Prominence is logarithmic because the gap between two and twenty language
    editions means far more than the gap between two hundred and two hundred
    and twenty.
    """
    prominence = math.log10(1 + max(0, candidate.sitelinks))
    context = min(_hint_overlap(candidate, hints, name), 3) * 0.4
    # Prominence outweighs an exact label match on purpose. Wikidata holds
    # obscure items whose label is exactly the string being searched — a
    # lowercase "BccI" with no sitelinks outranked the Board of Control for
    # Cricket in India, whose label does not contain the acronym at all.
    return 1.2 * _label_affinity(candidate, name) + 2.0 * prominence + context


def _best_match(candidates: list[EntityCandidate], hints: str, name: str = "") -> EntityCandidate:
    return max(candidates, key=lambda c: _score(c, name, hints))


def _reads_as_existing(summary: str) -> bool:
    """Read the grounded reply by its required prefix, then by its content.

    The prefix is what was asked for. The fallback exists because a model that
    drifts off the format still says the same thing in words, and defaulting to
    "exists" on an unparseable answer is the safe direction: it costs a
    research call, where the other direction silently drops a real subject.
    """
    text = (summary or "").strip().upper()
    if not text:
        return True  # the check did not run; do not conclude absence from a failure
    if text.startswith("NO_RECORD"):
        return False
    if text.startswith("EXISTS"):
        return True
    negative = ("NO EVIDENCE", "NO RECORD", "DOES NOT APPEAR", "NO SUCH", "NOT FIND", "FICTIONAL")
    return not any(marker in text[:400] for marker in negative)


#: Qualifiers a script writes and a catalogue does not. Dropping them is how
#: "the 2011 ICC Cricket World Cup final" finds "2011 Cricket World Cup Final".
_NOISE_WORDS = (
    "icc",
    "fifa",
    "uefa",
    "the",
    "official",
    "annual",
)


def _simplify(name: str) -> str:
    """The same name as a catalogue would hold it."""
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    kept = [w for w in words if w.lower().strip(".,") not in _NOISE_WORDS]
    simplified = " ".join(kept).strip()
    return simplified if len(simplified) >= 3 else ""


def _kind_word(name: str, is_person: bool) -> str:
    """What to call the subject when asking the web whether it exists.

    Asking whether there is a real "organisation, business or vessel" called
    the 2011 Cricket World Cup final gets a confused answer and, on a live run,
    a NO_RECORD for an event that plainly happened.
    """
    if is_person:
        return "person"
    lowered = name.lower()
    if any(marker in lowered for marker in ("final", "cup", "championship", "games", "olympic")):
        return "sporting event or tournament"
    if any(marker in lowered for marker in ("19", "20")) and len(name) > 8:
        return "event"
    return "organisation, business, place or work"
