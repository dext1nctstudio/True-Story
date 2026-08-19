"""Agent 2, ClaimExtractor. The heart of TRUE STORY. [LLM 2]

Every span tagged REAL_PERSON_DEPICTED, REAL_PERSON_IDENTIFIABLE or REAL_EVENT
is decomposed into atomic, independently verifiable factual claims. This is the
stage that turns "this scene involves a real person" into "this specific
sentence asserts that she was convicted twice, and the record shows she was
never charged".

Two rules carry the whole stage:

  Atomicity. A compound assertion is split until each part verifies on its own.
  That is how a complaint itemises alleged falsehoods and it is what lets the
  overlay light up one line rather than one scene.

  Opinion filtering. Defamation law protects opinion, so a characterisation is
  classified, coloured grey, and never researched. On a character driven script
  that is roughly a fifth of the extracted volume, which makes the single most
  legally motivated rule in the system also the largest budget control.

Expected volume on a thirty page adapted reality script: sixty to a hundred and
twenty claims, on top of a hundred to a hundred and fifty conventional
clearance elements.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from truestory.config import settings
from truestory.models.claims import FactualClaim
from truestory.models.enums import CLAIM_BEARING, ClaimType, Polarity
from truestory.models.spans import Occurrence, RawSpan, Scene
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.claims")

# Cheap negative valence markers used by the offline path. The model pass makes
# a far better judgement, and this exists so mock mode still exercises the
# escalation branch rather than producing an all neutral run.
_NEGATIVE_MARKERS = frozenset(
    {
        "convicted",
        "arrested",
        "charged",
        "guilty",
        "stole",
        "lied",
        "fraud",
        "assault",
        "abuse",
        "stalked",
        "beat",
        "killed",
        "murdered",
        "corrupt",
        "bribed",
        "cheated",
        "fired",
        "disgraced",
        "addicted",
        "imprisoned",
        "sentenced",
        "indicted",
        "racist",
        "coerced",
        "forged",
        "embezzled",
    }
)

_OPINION_MARKERS = frozenset(
    {
        "difficult",
        "brilliant",
        "cruel",
        "kind",
        "arrogant",
        "impossible",
        "genius",
        "monster",
        "saint",
        "charming",
        "cold",
        "warm",
        "greatest",
        "worst",
        "best",
        "insufferable",
        "gifted",
        "hopeless",
    }
)

_QUOTE_MARKERS = ('"', "'", "said", "told", "declared", "wrote")


class ClaimExtractor:
    """Decompose person and event spans into atomic factual claims."""

    name = "ClaimExtractor"

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or settings.model_claims
        self._client = client

    # ── entry point ──────────────────────────────────────────────────────────
    async def run(self, spans: list[RawSpan], scenes: list[Scene]) -> list[FactualClaim]:
        by_scene = {s.scene_no: s for s in scenes}
        claim_bearing = [s for s in spans if s.element_type in CLAIM_BEARING]

        claims: list[FactualClaim] = []
        for span in claim_bearing:
            scene = by_scene.get(span.scene_no)
            claims.extend(await self.extract(span, scene))

        deduped = self._dedupe(claims)
        log.info(
            "claim extraction: %s spans -> %s claims (%s after dedupe), %s opinions filtered",
            len(claim_bearing),
            len(claims),
            len(deduped),
            sum(1 for c in deduped if c.is_opinion),
        )
        return deduped

    # ── the model pass ───────────────────────────────────────────────────────
    async def extract(self, span: RawSpan, scene: Scene | None) -> list[FactualClaim]:
        if settings.offline:
            return self._extract_deterministic(span, scene)

        from google.genai import types

        from truestory.agents.prompts import CLAIM_EXTRACTOR_SYSTEM, CLAIM_EXTRACTOR_USER

        text = scene.text if scene else span.context
        try:
            response = await self._genai().aio.models.generate_content(
                model=self.model,
                contents=CLAIM_EXTRACTOR_USER.format(
                    subject=span.surface_form,
                    context=span.context,
                    scene_no=span.scene_no,
                    page=span.page,
                    text=text,
                ),
                config=types.GenerateContentConfig(
                    system_instruction=CLAIM_EXTRACTOR_SYSTEM,
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=_CLAIM_RESPONSE_SCHEMA,
                ),
            )
            meter_response(self.model, response)
        except Exception as exc:
            log.warning("claim extraction failed for span %s: %s", span.span_id, exc)
            return self._extract_deterministic(span, scene)

        return self._claims_from_response(span, scene, getattr(response, "text", "") or "")

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
        return self._client

    def _locate(self, span: RawSpan, scene: Scene | None, claim_text: str) -> Occurrence:
        """Find which line of the scene a claim's own sentence actually sits on.

        Every claim used to inherit `span.to_occurrence()` wholesale: the
        originating span's line, not the line the extracted sentence came
        from. A scene with several claim-bearing spans (several characters,
        say) then collapsed every claim from every one of them onto whichever
        few lines those spans themselves sat on, so the overlay stacked
        unrelated claims — a location claim, a person claim, an opinion — on
        one line and the highest severity one buried the rest from view.
        """
        base = span.to_occurrence()
        if scene is None:
            return base

        words = {w for w in _tokens(claim_text) if len(w) > 3}
        if not words:
            return base

        # Substring matching fails the moment the model rephrases a claim,
        # which it usually does — "walked on the Moon in July 1969" against a
        # script line reading "was the first person to walk on the Moon, in
        # July 1969". Scoring shared words instead tolerates the rewrite, and
        # requiring a real overlap stops a short line matching by accident.
        best_line, best_score = -1, 0.0
        for line_no, line in enumerate(scene.text.split("\n")):
            line_words = {w for w in _tokens(line) if len(w) > 3}
            if not line_words:
                continue
            overlap = len(words & line_words) / len(words)
            if overlap > best_score:
                best_line, best_score = line_no, overlap

        if best_line < 0 or best_score < 0.34:
            return base
        return Occurrence(
            scene_no=base.scene_no,
            page=base.page,
            line_no=best_line,
            modality=base.modality,
            surface_form=base.surface_form,
            context=base.context,
            character_cue=base.character_cue,
        )

    def _claims_from_response(
        self, span: RawSpan, scene: Scene | None, text: str
    ) -> list[FactualClaim]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            log.warning("unparseable claim output for span %s", span.span_id)
            return []

        subject_id = span.span_id
        out: list[FactualClaim] = []

        for item in payload.get("claims", []):
            claim_text = (item.get("claim_text") or "").strip()
            if not claim_text:
                continue

            try:
                claim_type = ClaimType(item.get("claim_type", "STATUS"))
            except ValueError:
                claim_type = ClaimType.STATUS
            try:
                polarity = Polarity(item.get("polarity", "neutral"))
            except ValueError:
                polarity = Polarity.NEUTRAL

            out.append(
                FactualClaim(
                    claim_id=FactualClaim.make_id(subject_id, claim_text),
                    subject_element_id=subject_id,
                    subject_name=item.get("subject") or span.surface_form,
                    claim_text=claim_text,
                    claim_type=claim_type,
                    polarity=polarity,
                    asserted_in=[self._locate(span, scene, claim_text)],
                )
            )
        return out

    # ── offline path ─────────────────────────────────────────────────────────
    def _extract_deterministic(
        self, span: RawSpan, scene: Scene | None = None
    ) -> list[FactualClaim]:
        """Sentence splitting plus keyword classification.

        Far weaker than the model pass and honest about it. Its purpose is to
        keep every downstream branch reachable with no credentials: negative
        claims about living subjects, opinion filtering, and the amber density
        rollup all fire on this output.
        """
        source = span.context or span.surface_form
        sentences = [s.strip() for s in _split_sentences(source) if len(s.strip()) > 12]

        # span.context is the surrounding scene text, not a window scoped to
        # this entity, so without filtering, every claim-bearing span in the
        # same scene reprocesses the identical sentences and each claim gets
        # stamped with whichever span happened to be running, misattributing
        # sentences to subjects that were never mentioned in them.
        name_tokens = [t for t in span.surface_form.lower().split() if len(t) > 2]
        if name_tokens:
            scoped = [s for s in sentences if any(t in s.lower() for t in name_tokens)]
            sentences = scoped or sentences[:1]

        claims: list[FactualClaim] = []
        for sentence in sentences[:6]:
            lowered = sentence.lower()
            words = set(lowered.replace(",", " ").replace(".", " ").split())

            if words & _OPINION_MARKERS:
                claim_type, polarity = ClaimType.CHARACTERIZATION, Polarity.NEUTRAL
            elif any(marker in lowered for marker in _QUOTE_MARKERS[:2]):
                claim_type, polarity = ClaimType.QUOTE, Polarity.NEUTRAL
            elif words & _NEGATIVE_MARKERS:
                claim_type, polarity = ClaimType.CONDUCT, Polarity.NEGATIVE
            else:
                claim_type, polarity = ClaimType.STATUS, Polarity.NEUTRAL

            claims.append(
                FactualClaim(
                    claim_id=FactualClaim.make_id(span.span_id, sentence),
                    subject_element_id=span.span_id,
                    subject_name=span.surface_form,
                    claim_text=sentence,
                    claim_type=claim_type,
                    polarity=polarity,
                    asserted_in=[self._locate(span, scene, sentence)],
                )
            )
        return claims

    # ── dedupe ───────────────────────────────────────────────────────────────
    @staticmethod
    def _dedupe(claims: list[FactualClaim]) -> list[FactualClaim]:
        """Collapse identical claims, keeping every occurrence pointer.

        The same assertion made three times across a script is one research
        subject and three places to light up in the overlay. Identity is the
        content hash, which is also why a revised draft reuses the answer.
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
        return list(merged.values())


def _tokens(text: str) -> set[str]:
    """Lowercase word set, punctuation stripped. Used for line matching."""
    import re

    return set(re.findall(r"[a-z0-9']+", text.lower()))


def _split_sentences(text: str) -> list[str]:
    import re

    return re.split(r"(?<=[.!?])\s+", text)


_CLAIM_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_text", "claim_type", "polarity"],
                "properties": {
                    "claim_text": {
                        "type": "string",
                        "description": "One atomic assertion, verifiable on its own.",
                    },
                    "claim_type": {"type": "string", "enum": [str(c) for c in ClaimType]},
                    "polarity": {"type": "string", "enum": [str(p) for p in Polarity]},
                    "subject": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
            },
        }
    },
}
