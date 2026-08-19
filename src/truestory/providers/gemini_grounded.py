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
from typing import Any

from truestory.config import settings
from truestory.models.evidence import Citation, Evidence
from truestory.providers.base import ResearchProvider, ResearchRequest


class GeminiGroundedProvider(ResearchProvider):
    name = "gemini_grounded"
    supports_citations = True  # only when grounding metadata comes back
    supports_async = False
    unit_cost_cents = 0.2  # inference only, no research API charge

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or settings.model_adjudicator
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
        from google.genai import types

        prompt = (
            "You are a clearance researcher. Answer the question strictly from "
            "sources you can find and cite. If the record does not settle the "
            "question, say so explicitly rather than inferring. Never state a "
            "fact about a real person that you cannot point to a source for.\n\n"
            f"Question: {request.question}\n\n"
            f"Jurisdictions in scope: {', '.join(request.jurisdictions) or 'US'}\n\n"
            "Return JSON conforming to this schema:\n"
            f"{json.dumps(request.output_schema)}"
        )

        with self._timed() as timing:
            try:
                response = await self._genai().aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.0,  # research is not a creative task
                        response_mime_type="application/json",
                        safety_settings=_permissive_analysis_safety(types),
                    ),
                )
            except Exception as exc:
                return Evidence.failed(request.subject_id, request.question, self.name, str(exc))

        finding = _parse_json(getattr(response, "text", "") or "")
        citations = _citations_from_grounding(response)

        return Evidence(
            evidence_id=Evidence.make_id(request.subject_id, request.question, self.name),
            subject_id=request.subject_id,
            question=request.question,
            finding=finding,
            citations=citations,
            reasoning="Grounded completion produced as a fallback while the primary research provider was unavailable.",
            confidence=0.55 if citations else 0.0,
            provider=self.name,
            schema_version=request.schema_name,
            is_fallback=True,  # caps effective confidence and warns the report
            cost_cents=self.unit_cost_cents,
            latency_ms=timing["latency_ms"],
            error=None if citations else "grounding returned no citable sources",
        )

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


def _parse_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return {"raw": text[:2000], "parse_error": True}


def _citations_from_grounding(response: Any) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for candidate in getattr(response, "candidates", []) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        for chunk in getattr(metadata, "grounding_chunks", []) or []:
            web = getattr(chunk, "web", None)
            url = getattr(web, "uri", None)
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(
                Citation.classified(
                    url=url,
                    title=getattr(web, "title", None) or url,
                    declared_type="secondary",
                )
            )
    return citations
