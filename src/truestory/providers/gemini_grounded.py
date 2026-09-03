"""Gemini with Google Search grounding. The honest fallback.

This provider exists so that a Parallel outage, a rate limit that outlasts the
retry budget, or an exhausted quota degrades the run rather than ending it.

Everything it returns is stamped `is_fallback=True`, which caps effective
confidence at 0.6 in the Evidence envelope and puts a coverage warning on the
front page of the report. Principle P5, degrade honestly. A grounded completion
is a useful answer and it is not the same thing as a multi hop research run
with a citation per field, so it never gets to present as one.

It is also structurally barred from CRITICAL work by `supports_citations`
remaining conditional: grounding metadata is attached when the model returns
it, and when it does not, the envelope comes back unusable and the subject
routes to counsel rather than quietly taking a thin answer.
"""

from __future__ import annotations

import json
import re
from typing import Any

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers import model_fallback
from truestory.providers.base import ResearchProvider, ResearchRequest
from truestory.providers.vertex_schema import to_vertex_schema


class GeminiGroundedProvider(ResearchProvider):
    name = "gemini_grounded"
    supports_citations = True  # only when grounding metadata comes back
    supports_async = False
    unit_cost_cents = 0.2  # inference only, no research API charge

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or settings.model_grounded
        self._client = client

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
        return self._client

    async def investigate(self, request: ResearchRequest) -> Evidence:
        """Two steps, in a fixed order, and the order is the guardrail.

            RETRIEVE   search the web, in plain language, no schema
            STRUCTURE  shape only what was retrieved, no search tool

        **Why it is two calls and not one.** Asking for the search tool and a
        JSON object in the same request does not error, it quietly stops
        searching. Measured on this project: the same question asked plainly
        returns two to six grounding chunks, and asked with "return JSON
        conforming to this schema" appended returns **zero** while still
        answering confidently. The verdicts it produced that way were often
        right — it correctly called Owens' four world records contradicted, and
        Dhoni's 97 contradicted — and every one of them was drawn from the
        model's memory with nothing behind it.

        That is the exact failure this system exists to prevent, arriving
        through the fallback path: an assertion about a real person with no
        source under it. The envelope was then discarded for having no
        citations, so the cost was silent — a true claim reported UNSUPPORTED,
        having looked like it was researched.

        Splitting the call fixes both halves. Retrieval cannot invent a
        citation because the citations come from grounding metadata rather than
        from the model's prose. Structuring cannot invent a fact because it is
        given the retrieved text and told it is the only permitted input, and
        it runs with controlled generation, which is available precisely
        because the search tool is absent from that second call.
        """
        with self._timed() as timing:
            try:
                retrieved, citations = await self._retrieve(request)
            except Exception as exc:
                return Evidence.failed(request.subject_id, request.question, self.name, str(exc))

            try:
                finding = await self._structure(request, retrieved)
            except Exception as exc:
                return Evidence.failed(request.subject_id, request.question, self.name, str(exc))

        # A search that ran and found nothing is a finding. A search that could
        # not run is a failure. They were the same thing here, and the smoke
        # suite caught it: "Margaret Holloway was convicted of falsifying her
        # flight logs" and "Brundage was a small man in a large chair" both
        # returned zero sources, which is the *correct* outcome for an invented
        # person and for an opinion, and both were reported as research
        # failures. That is the B13 confusion inverted — an answer discarded as
        # an error rather than an error presented as an answer — and it hides
        # the two results a clearance reviewer most wants to see.
        #
        # So the finding stands, with one deterministic restriction below.
        if not citations:
            finding = _restrict_to_negative(finding)

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=finding,
            citations=citations,
            reasoning=(
                "Grounded web retrieval, then structured from the retrieved text alone. "
                "Produced as a fallback while the primary research provider was "
                "unavailable or did not return in time."
            ),
            confidence=0.55 if citations else 0.0,
            provider=self.name,
            schema_version=request.schema_name,
            is_fallback=True,  # caps effective confidence and warns the report
            cost_cents=self.unit_cost_cents,
            latency_ms=timing["latency_ms"],
            error=None,
        )

    async def _retrieve(self, request: ResearchRequest) -> tuple[str, list[Citation]]:
        """Step one. Search, in plain language, and keep what the search found.

        No schema and no JSON anywhere in this prompt. The moment either
        appears the model stops calling the search tool.
        """
        from google.genai import types

        prompt = (
            "You are a clearance researcher. Search the web and report only what "
            "the sources say.\n\n"
            f"Question: {request.question}\n\n"
            f"Jurisdictions in scope: {', '.join(request.jurisdictions) or 'US'}\n\n"
            "State what the record shows, and state plainly where it is silent. "
            "Quote the specific wording that settles the question. Never assert a "
            "fact about a real person that you cannot point at a source for. If the "
            "sources do not settle it, say that they do not."
        )

        response = await model_fallback.generate(
            self._genai(),
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,  # research is not a creative task
                safety_settings=_permissive_analysis_safety(types),
            ),
        )
        return (getattr(response, "text", "") or ""), _citations_from_grounding(response)

    async def _structure(self, request: ResearchRequest, retrieved: str) -> dict[str, Any]:
        """Step two. Shape the retrieved text, and nothing else, into the schema.

        No search tool here, which is what makes controlled generation
        available: Vertex refuses `response_schema` alongside the Search tool
        with "controlled generation is not supported with Search tool". Asking
        for the schema in a separate call gets the guarantee back instead of
        parsing a fenced block and hoping.
        """
        from google.genai import types

        prompt = (
            "Convert the research below into the required structure.\n\n"
            "The research text is your ONLY permitted source. Do not add facts "
            "from your own knowledge, do not resolve a question the text leaves "
            "open, and where the text does not settle something, record that it "
            "is unsettled rather than filling it in.\n\n"
            f"Question that was researched:\n{request.question}\n\n"
            f"Research text:\n{retrieved}"
        )

        response = await model_fallback.generate(
            self._genai(),
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=to_vertex_schema(request.output_schema),
                safety_settings=_permissive_analysis_safety(types),
            ),
        )
        return _parse_json(getattr(response, "text", "") or "")

    async def health(self) -> bool:
        return bool(settings.gcp_project)


def _permissive_analysis_safety(types: Any) -> list[Any]:
    """Analysis is not generation.

    A clearance system reads scripts containing violence, slurs and sexual
    content, and refusing to parse a scene is a silent hole in the report
    rather than a safe outcome. Thresholds are relaxed for analysis only, and
    when a scene still blocks, the pipeline flags it for manual breakdown
    instead of skipping it quietly.
    """
    categories = [
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    ]
    return [types.SafetySetting(category=c, threshold="BLOCK_ONLY_HIGH") for c in categories]


#: A ```json fence, which is how a grounded model returns an object when it
#: cannot be told to emit one.
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _parse_json(text: str) -> dict[str, Any]:
    """Recover the JSON object from a grounded answer.

    Grounding rules out controlled generation, so the model returns prose
    shaped like JSON rather than JSON: usually a ```json fence, sometimes a
    sentence of preamble before the object. Insisting on a clean parse threw
    away findings that were entirely well formed a fence away.
    """
    candidate = text.strip()
    if not candidate:
        return {"raw": "", "parse_error": True}

    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        pass

    # Last resort: the outermost braces. A model that wrapped the object in a
    # sentence still gave us the object.
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(candidate[start : end + 1])
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            pass

    return {"raw": text[:2000], "parse_error": True}


def _citations_from_grounding(response: Any) -> list[Citation]:
    """Turn grounding metadata into citations that carry their real pedigree.

    Two things about this metadata are easy to get wrong and were both wrong
    here.

    The `uri` is not the source. It is a redirect on
    vertexaisearch.cloud.google.com that expires, so classifying it produced
    "unknown host" for every grounded citation in the product — including for
    bcci.tv and theguardian.com, which the classifier knows perfectly well.
    The real host is in `web.domain`, and that is what gets classified.

    `grounding_supports` maps spans of the answer to the chunks that support
    them. That mapping is the only part of a grounded response with any
    attribution in it, so the supported sentence is carried onto the citation
    as its excerpt, which gives the attribution gate something real to check a
    quote against instead of an empty string.
    """
    supports_by_chunk = _supports_by_chunk(response)
    citations: list[Citation] = []
    seen: set[str] = set()

    for candidate in getattr(response, "candidates", []) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        for index, chunk in enumerate(getattr(metadata, "grounding_chunks", []) or []):
            web = getattr(chunk, "web", None)
            url = getattr(web, "uri", None)
            if not url or url in seen:
                continue
            seen.add(url)

            domain = getattr(web, "domain", None) or getattr(web, "title", None) or ""
            citations.append(
                Citation.classified(
                    # Classified on the domain the redirect points at, not on
                    # the redirect. The URL stays the redirect because that is
                    # what resolves; the pedigree comes from the real host.
                    url=f"https://{domain}" if domain else url,
                    title=getattr(web, "title", None) or domain or url,
                    excerpt=" ".join(supports_by_chunk.get(index, []))[:1200],
                    declared_type="secondary",
                    publisher=domain or None,
                )
            )
    return citations


def _supports_by_chunk(response: Any) -> dict[int, list[str]]:
    """Which sentences of the answer each grounding chunk was cited for."""
    out: dict[int, list[str]] = {}
    for candidate in getattr(response, "candidates", []) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        for support in getattr(metadata, "grounding_supports", None) or []:
            text = getattr(getattr(support, "segment", None), "text", "") or ""
            if not text:
                continue
            for index in getattr(support, "grounding_chunk_indices", None) or []:
                out.setdefault(int(index), []).append(text.strip())
    return out


#: The only verdicts a source-less answer is permitted to carry.
_NEGATIVE_VERDICTS = frozenset({"no_record", "not_a_factual_claim"})


def _restrict_to_negative(finding: dict[str, Any]) -> dict[str, Any]:
    """Hold a source-less finding to what a source-less finding can support.

    Retrieval searched and came back with nothing. That legitimately settles two
    things — the record is silent, or the sentence was never a factual claim —
    and it cannot settle anything else. `supported` or `contradicted` with no
    citation under it is precisely the assertion about a real person that this
    system exists to prevent, and the model will produce one if asked, because
    the retrieved text says "no sources found" and it reads that as evidence of
    absence.

    Deterministic and in code rather than in the prompt, per the design
    principle that everything consequential happens after the model.
    """
    verdict = (finding or {}).get("verdict")
    if verdict in _NEGATIVE_VERDICTS:
        return finding

    corrected = dict(finding or {})
    corrected["verdict"] = "no_record"
    corrected["record_quality"] = "no sources retrieved"
    note = (
        f"Downgraded from {verdict!r}: retrieval returned no citable source, and a "
        "verdict of that kind requires one."
    )
    corrected["downgrade_reason"] = note
    # Any facts the model listed came from its own memory rather than from a
    # retrieved page, so they are not evidence and do not travel.
    corrected["supporting_facts"] = []
    corrected["contradicting_facts"] = []
    return corrected
