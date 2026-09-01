"""Agent 1, IngestAgent. Raw script to typed spans. [LLM 1]

Deliberately no document AI service. Gemini's native PDF and multimodal
understanding parses screenplay structure better than a general document
extractor, and dropping the service removed a dependency, a failure mode and a
line item at the same time.

Chunking is by scene. INT. and EXT. headings are the most reliable structural
boundary in any format the industry uses, so scenes chunk cleanly, overlap by
one scene to catch elements that straddle a cut, and process in parallel.

The project level pass is the important one. It sets a single boolean,
`truth_claim_framing`, that escalates the risk tier of every person adjacent
subject in the whole script.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from truestory.agents.stage_cache import StagePromptCache
from truestory.config import settings
from truestory.models.enums import ElementType, Modality
from truestory.models.spans import RawSpan, Scene, ScriptDocument
from truestory.providers.model_cost import meter_response

log = logging.getLogger("truestory.ingest")

# ── screenplay structure ─────────────────────────────────────────────────────
_SCENE_HEADING = re.compile(
    r"^\s*((?:INT|EXT|INT\.?/EXT|I/E)[\.\s][^\n]*)$", re.IGNORECASE | re.MULTILINE
)
_CHARACTER_CUE = re.compile(r"^\s{0,30}([A-Z][A-Z0-9 '\.\-]{1,38})(\s*\(.*\))?\s*$")
_TRANSITION = re.compile(r"^\s*(CUT TO|FADE (IN|OUT)|DISSOLVE TO|SMASH CUT)[:\.]?\s*$", re.I)
_TITLE_CARD = re.compile(r"^\s*(TITLE CARD|SUPER|CARD|TITLE)\s*:?\s*(.*)$", re.IGNORECASE)

#: Cue block decorations that are not part of the character's name.
_CUE_DECORATIONS = re.compile(r"\s*\((?:V\.?O\.?|O\.?S\.?|CONT'?D|CONTD|OFF)\)\s*", re.I)

#: Roughly one page per fifty five lines of standard screenplay formatting.
_LINES_PER_PAGE = 55

# The truth claim detector. A short, explicit list, because a false positive
# here escalates the tier of every person in the script and a false negative
# misses the single most consequential fact about the production.
_TRUTH_CLAIM_PATTERNS = [
    re.compile(r"\bthis\s+is\s+a\s+true\s+story\b", re.I),
    re.compile(r"\bbased\s+on\s+a\s+true\s+story\b", re.I),
    re.compile(r"\bbased\s+on\s+(actual|real)\s+events\b", re.I),
    re.compile(r"\bthe\s+following\s+is\s+a\s+true\s+(story|account)\b", re.I),
    re.compile(r"\ba\s+true\s+story\b", re.I),
]

# Explicitly not truth claims. Inspiration is a weaker assertion and courts
# have treated the difference as meaningful.
_NOT_TRUTH_CLAIM = [
    re.compile(r"\binspired\s+by\b", re.I),
    re.compile(r"\bsuggested\s+by\b", re.I),
]


class IngestAgent:
    """Parse a draft, then tag every clearable span in every scene."""

    name = "IngestAgent"

    def __init__(self, model: str | None = None, client: Any = None) -> None:
        self.model = model or settings.model_ingest
        self._client = client
        self._cache = StagePromptCache("ingest", "ingest_v2")

    # ── entry point ──────────────────────────────────────────────────────────
    async def run(
        self, source: Path | str, *, draft_version: str = "v1"
    ) -> tuple[ScriptDocument, list[RawSpan]]:
        raw, fmt = _read_source(source)
        document = self.parse(raw, fmt=fmt, draft_version=draft_version)

        # Scenes are independent of each other, so they are tagged together.
        # Sequentially, this was one Gemini 2.5 Pro call after another: a sixty
        # scene feature spent tens of minutes in a loop whose iterations shared
        # nothing, and the whole run looked hung with no way to tell.
        spans = await _gather_bounded(
            [
                self.tag_scene(scene, truth_claim_framing=document.truth_claim_framing)
                for scene in document.scenes
            ],
            limit=settings.ingest_max_concurrency,
            label="scene",
        )

        log.info(
            "ingest complete: %s scenes, %s spans, truth_claim_framing=%s",
            document.scene_count,
            len(spans),
            document.truth_claim_framing,
        )
        return document, spans

    # ── deterministic parsing ────────────────────────────────────────────────
    def parse(
        self, raw: str, *, fmt: str = "fountain", draft_version: str = "v1"
    ) -> ScriptDocument:
        """Structure the draft. No model involved, so this is fully testable."""
        text = _strip_fdx(raw) if fmt == "fdx" else raw
        scenes = self._split_scenes(text)
        framing, evidence = self.detect_truth_claim(text)

        characters = sorted(
            {c for scene in scenes for c in scene.characters},
            key=str.casefold,
        )

        return ScriptDocument(
            script_id=f"sc_{hashlib.sha256(text.encode()).hexdigest()[:16]}",
            title=_guess_title(text) or "Untitled Draft",
            draft_version=draft_version,
            script_hash=ScriptDocument.hash_bytes(text.encode()),
            page_count=round(len(text.splitlines()) / _LINES_PER_PAGE, 2),
            scenes=scenes,
            characters=characters,
            truth_claim_framing=framing,
            truth_claim_evidence=evidence,
            source_format=fmt,
        )

    def _split_scenes(self, text: str) -> list[Scene]:
        lines = text.splitlines()
        boundaries: list[tuple[int, str]] = [
            (i, line.strip()) for i, line in enumerate(lines) if _SCENE_HEADING.match(line)
        ]

        if not boundaries:
            # Not every draft has slug lines. Treat the whole document as one
            # scene rather than dropping it, and let the model do the work.
            return [
                Scene(
                    scene_no=1,
                    heading="FULL DOCUMENT",
                    start_page=1.0,
                    end_page=round(len(lines) / _LINES_PER_PAGE, 2) or 1.0,
                    text=text,
                    characters=_characters_in(lines),
                )
            ]

        scenes: list[Scene] = []
        for idx, (start_line, heading) in enumerate(boundaries):
            end_line = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
            body = lines[start_line:end_line]
            scenes.append(
                Scene(
                    scene_no=idx + 1,
                    heading=heading,
                    start_page=round(start_line / _LINES_PER_PAGE + 1, 2),
                    end_page=round(end_line / _LINES_PER_PAGE + 1, 2),
                    text="\n".join(body),
                    characters=_characters_in(body),
                )
            )
        return scenes

    # ── the project level boolean ────────────────────────────────────────────
    def detect_truth_claim(self, text: str) -> tuple[bool, str | None]:
        """Does this production assert to its audience that the story is true.

        One boolean, and it changes the risk tier of every person adjacent
        subject in the script, because courts have treated the framing itself
        as evidence bearing on reckless disregard for falsity.
        """
        head = text[:6000]  # title cards live at the front
        for pattern in _TRUTH_CLAIM_PATTERNS:
            match = pattern.search(head) or pattern.search(text)
            if not match:
                continue
            window = text[max(0, match.start() - 120) : match.end() + 120]
            if any(neg.search(window) for neg in _NOT_TRUTH_CLAIM):
                continue  # "inspired by a true story" is a weaker assertion
            return True, window.strip()
        return False, None

    # ── the model pass ───────────────────────────────────────────────────────
    async def tag_scene(self, scene: Scene, *, truth_claim_framing: bool = False) -> list[RawSpan]:
        """Tag one scene. Falls back to deterministic patterns in mock mode."""
        if settings.offline:
            return self._tag_deterministic(scene, truth_claim_framing=truth_claim_framing)

        from google.genai import types

        from truestory.agents.prompts import INGEST_SYSTEM, INGEST_USER

        prompt = INGEST_USER.format(
            scene_no=scene.scene_no,
            heading=scene.heading,
            start_page=scene.start_page,
            end_page=scene.end_page,
            scene_text=scene.text,
        )

        # An unchanged scene must break down to the same spans. Ingest names
        # every subject the rest of the pipeline researches, so drift here
        # renames claims, misses the research cache, and changes the report on
        # a script nobody edited.
        cached = self._cache.get(self.model, prompt)
        if cached:
            log.debug("scene %s breakdown replayed from cache", scene.scene_no)
            return self._spans_from_response(scene, cached)

        try:
            response = await self._genai().aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=INGEST_SYSTEM,
                    temperature=0.0,  # a breakdown is not a creative act
                    response_mime_type="application/json",
                    response_schema=_SPAN_RESPONSE_SCHEMA,
                    safety_settings=_analysis_safety(types),
                ),
            )
            meter_response(self.model, response)
        except Exception as exc:
            # Never skip a scene silently. A gap in the breakdown is a gap in
            # the report, so it is flagged for manual attention and the
            # deterministic pass still runs.
            log.warning("scene %s model pass failed, falling back: %s", scene.scene_no, exc)
            spans = self._tag_deterministic(scene, truth_claim_framing=truth_claim_framing)
            for s in spans:
                s.attributes["needs_manual_breakdown"] = True
            return spans

        raw = getattr(response, "text", "") or ""
        self._cache.put(self.model, prompt, raw)
        return self._spans_from_response(scene, raw)

    def _genai(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(
                vertexai=settings.use_vertex,
                project=settings.gcp_project or None,
                location=settings.gcp_location,
            )
        return self._client

    def _spans_from_response(self, scene: Scene, text: str) -> list[RawSpan]:
        import json

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            log.warning("scene %s returned unparseable output", scene.scene_no)
            return self._tag_deterministic(scene)

        spans: list[RawSpan] = []
        for i, item in enumerate(payload.get("spans", [])):
            try:
                element_type = ElementType(item["element_type"])
            except (KeyError, ValueError):
                continue
            surface = item.get("surface_form", "").strip()
            if not surface:
                continue
            if _is_predicate(surface, element_type):
                # Not a name, so nothing can be looked up under it. Dropped
                # here rather than argued about in the prompt, because the
                # consequence is silent: identity searches for a real entity
                # called "sank on its third voyage", finds none, and blocks
                # research on the claim attached to it.
                log.debug("dropped predicate span %r as %s", surface[:48], element_type)
                continue
            spans.append(
                RawSpan(
                    span_id=RawSpan.make_id(scene.scene_no, i, surface),
                    scene_no=scene.scene_no,
                    page=float(item.get("page", scene.start_page)),
                    line_no=int(item.get("line_no", 0)),
                    element_type=element_type,
                    surface_form=surface,
                    context=item.get("context", "")[:400],
                    modality=_modality(item.get("modality")),
                    extraction_confidence=float(item.get("confidence", 0.8)),
                    character_cue=item.get("character_cue"),
                    attributes=item.get("attributes", {}),
                )
            )
        return spans

    # ── offline path ─────────────────────────────────────────────────────────
    def _tag_deterministic(
        self, scene: Scene, *, truth_claim_framing: bool = False
    ) -> list[RawSpan]:
        """Pattern based tagging so mock mode exercises the whole pipeline.

        Recall is far below the model pass and precision is worse. This exists
        so that a clone with no credentials still produces a real ledger, a
        real overlay and a real report, not so that it produces a good one.
        Every span it emits carries a low extraction confidence to say so.
        """
        spans: list[RawSpan] = []
        lines = scene.text.splitlines()
        current_cue: str | None = None
        seen_names: set[str] = set()

        # In a production that asserts a true story, a named character is far
        # more likely to be a real person than an invention. Tagging them as
        # depicted rather than fictional is what routes them into claim
        # extraction, which is the whole point of the product.
        person_type = (
            ElementType.REAL_PERSON_DEPICTED
            if truth_claim_framing
            else ElementType.PERSON_NAME_FICTIONAL
        )

        patterns: list[tuple[re.Pattern[str], ElementType]] = [
            (re.compile(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b"), ElementType.PHONE_NUMBER),
            (re.compile(r"https?://\S+|@[A-Za-z0-9_]{3,}"), ElementType.URL_HANDLE),
            (
                re.compile(
                    r"\b\d{1,5}\s+[A-Z][a-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\b"
                ),
                ElementType.STREET_ADDRESS,
            ),
            (
                re.compile(
                    r"\b(?:poster|painting|mural|photograph|portrait|artwork)\s+of\s+([A-Z][\w' ]{2,40})",
                    re.I,
                ),
                ElementType.ARTWORK_VISUAL,
            ),
        ]

        # Music cues are matched against the whole scene rather than line by
        # line, because a quoted song title routinely wraps across a line break
        # in a formatted screenplay and a per line scan simply misses it.
        # American style puts the comma inside the closing quote, so the
        # separator has to be optional or every correctly typeset cue is missed.
        for match in re.finditer(
            r'"([^"]{4,90}?)[,.]?"\s*(?:by\s+|,\s*)?([A-Z][\w\s&.\'-]{2,40})',
            scene.text,
            re.DOTALL,
        ):
            title = " ".join(match.group(1).split()).strip(" ,.")
            seen_names.add(title)
            spans.append(
                _span(
                    scene,
                    0,
                    ElementType.MUSIC_CUE,
                    title,
                    " ".join(match.group(0).split()),
                    Modality.SCRIPT_ACTION,
                    None,
                    confidence=0.7,
                )
            )

        for line_no, line in enumerate(lines):
            if _TRANSITION.match(line) or _SCENE_HEADING.match(line):
                continue

            # A character cue is the single most reliable person signal in the
            # format, so it becomes a span rather than being consumed.
            cue = _CHARACTER_CUE.match(line)
            if cue:
                current_cue = _CUE_DECORATIONS.sub("", cue.group(1)).strip()
                if _all_noise(current_cue):
                    # "THE END" and "FADE OUT" match the cue shape exactly.
                    current_cue = None
                    continue
                if current_cue and current_cue not in seen_names:
                    seen_names.add(current_cue)
                    spans.append(
                        _span(
                            scene,
                            line_no,
                            person_type,
                            current_cue,
                            scene.text[:600],
                            Modality.SCRIPT_HEADING,
                            None,
                            confidence=0.75,
                        )
                    )
                continue

            card = _TITLE_CARD.match(line)
            if card and card.group(2).strip():
                spans.append(
                    _span(
                        scene,
                        line_no,
                        ElementType.REAL_EVENT,
                        card.group(2).strip(),
                        line,
                        Modality.TITLE_CARD,
                        None,
                        confidence=0.8,
                    )
                )

            for pattern, element_type in patterns:
                for match in pattern.finditer(line):
                    spans.append(
                        _span(
                            scene,
                            line_no,
                            element_type,
                            match.group(0),
                            line,
                            Modality.SCRIPT_DIALOGUE if current_cue else Modality.SCRIPT_ACTION,
                            current_cue,
                        )
                    )

            # Screenplay convention introduces a character in capitals inside
            # an action line. That is a named person, and in a true story
            # production it is very likely a real one.
            for match in re.finditer(r"\b([A-Z][A-Z]{2,}(?:\s+[A-Z][A-Z]{2,})*)\b", line):
                name = match.group(1).strip()
                # Reject when every token is formatting. Checking the phrase as
                # a whole lets "THE END" through, because neither half is the
                # phrase, and a slug line then becomes a depicted person.
                if len(name) < 4 or name in seen_names or _all_noise(name):
                    continue
                seen_names.add(name)
                spans.append(
                    _span(
                        scene,
                        line_no,
                        person_type,
                        name.title(),
                        # Claim extraction needs sentences to decompose, so a
                        # person span carries the surrounding scene rather than
                        # just its own line.
                        _window(scene.text, line, 600),
                        Modality.SCRIPT_ACTION,
                        None,
                        confidence=0.5,
                    )
                )

            # Title case proper noun pairs in action lines. Crude, low
            # confidence, and dropped by the ledger when nothing attaches.
            if not current_cue:
                for match in re.finditer(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b", line):
                    surface = match.group(0)
                    if surface in seen_names:
                        continue
                    seen_names.add(surface)
                    spans.append(
                        _span(
                            scene,
                            line_no,
                            ElementType.PERSON_NAME_FICTIONAL,
                            surface,
                            line,
                            Modality.SCRIPT_ACTION,
                            None,
                            confidence=0.3,
                        )
                    )

            if line.strip() == "":
                current_cue = None

        return spans


# =============================================================================
# helpers
# =============================================================================


def _span(
    scene: Scene,
    line_no: int,
    element_type: ElementType,
    surface: str,
    context: str,
    modality: Modality,
    cue: str | None,
    *,
    confidence: float = 0.6,
) -> RawSpan:
    return RawSpan(
        span_id=RawSpan.make_id(scene.scene_no, line_no, surface),
        scene_no=scene.scene_no,
        page=round(scene.start_page + line_no / _LINES_PER_PAGE, 2),
        line_no=line_no,
        element_type=element_type,
        surface_form=surface,
        context=_context_window(context),
        modality=modality,
        extraction_confidence=confidence,
        character_cue=cue,
    )


async def _gather_bounded(coros: list[Any], *, limit: int, label: str) -> list[RawSpan]:
    """Run independent taggings together, bounded, and never let one sink the run.

    A scene that fails to tag costs that scene's spans. A scene that takes the
    whole stage down costs the production its report, so failures are logged
    and skipped rather than raised.
    """
    semaphore = asyncio.Semaphore(max(1, limit))

    async def guarded(coro: Any) -> list[RawSpan]:
        async with semaphore:
            try:
                return await coro
            except Exception as exc:
                log.warning("%s tagging failed: %s", label, exc)
                return []

    batches = await asyncio.gather(*(guarded(c) for c in coros))
    return [span for batch in batches for span in batch]


#: How much surrounding scene text a span carries. Long enough for the offline
#: claim extractor to see whole sentences, short enough to keep a cache key
#: stable across a redraft that only touched the paragraph below.
_CONTEXT_CHARS = 400


def _context_window(context: str) -> str:
    """Trim the context to a word boundary rather than a character count.

    A hard slice at 400 characters cut mid word, and the offline extractor then
    treated the fragment as a sentence: the demo script produced a claim whose
    entire text was "They're sayi", which was researched, adjudicated and shown
    in the review queue exactly like a real assertion.
    """
    text = context.strip()
    if len(text) <= _CONTEXT_CHARS:
        return text
    cut = text[:_CONTEXT_CHARS]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > _CONTEXT_CHARS // 2 else cut).rstrip()


#: Capitalised tokens that are formatting, not names.
_CAPS_NOISE = frozenset(
    {
        "INT",
        "EXT",
        "CUT",
        "FADE",
        "DISSOLVE",
        "SMASH",
        "TITLE",
        "CARD",
        "SUPER",
        "CONTINUOUS",
        "LATER",
        "MOMENTS",
        "DAY",
        "NIGHT",
        "MORNING",
        "EVENING",
        "AFTERNOON",
        "DAWN",
        "DUSK",
        "THE",
        "AND",
        "BUT",
        "FOR",
        "WITH",
        "FROM",
        "INTO",
        "ONTO",
        "OVER",
        "THIS",
        "THAT",
        "TRUE",
        "STORY",
        "BASED",
        "ANGLE",
        "CLOSE",
        "WIDE",
        "POV",
        "INSERT",
        "MATCH",
        "BEAT",
        "FLASHBACK",
        "MONTAGE",
        "VOICE",
        "OFF",
        "SCREEN",
        "CONTD",
        "MORE",
        "END",
        "BLACK",
        "WHITE",
    }
)


def _all_noise(phrase: str) -> bool:
    """True when every token in the phrase is screenplay formatting."""
    tokens = [t.strip(".,:-'") for t in phrase.split()]
    return all(t.upper() in _CAPS_NOISE for t in tokens if t)


def _window(text: str, anchor: str, size: int) -> str:
    """Text around an anchor line, so claim extraction has sentences to work with."""
    idx = text.find(anchor.strip()) if anchor.strip() else -1
    if idx < 0:
        return text[:size]
    start = max(0, idx - size // 2)
    return text[start : start + size]


def _modality(raw: str | None) -> Modality:
    try:
        return Modality(raw) if raw else Modality.SCRIPT_ACTION
    except ValueError:
        return Modality.SCRIPT_ACTION


def _characters_in(lines: list[str]) -> list[str]:
    """Character cue blocks are free ground truth that prose does not have.

    An all capitals name on its own line above dialogue is the screenplay
    format telling us, unambiguously, that these tokens are the same character.
    The ledger's coreference stage leans on this heavily.
    """
    found: list[str] = []
    for i, line in enumerate(lines[:-1]):
        match = _CHARACTER_CUE.match(line)
        if not match or _SCENE_HEADING.match(line) or _TRANSITION.match(line):
            continue
        if lines[i + 1].strip():  # a cue is followed by dialogue
            name = match.group(1).strip()
            if name not in found and len(name) > 1:
                found.append(name)
    return found


def _guess_title(text: str) -> str | None:
    for line in text.splitlines()[:40]:
        stripped = line.strip()
        if stripped.lower().startswith("title:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _strip_fdx(raw: str) -> str:
    """Flatten Final Draft XML into plain screenplay text."""
    paragraphs = re.findall(r"<Paragraph[^>]*>(.*?)</Paragraph>", raw, re.DOTALL)
    out: list[str] = []
    for para in paragraphs:
        text = " ".join(re.findall(r"<Text[^>]*>(.*?)</Text>", para, re.DOTALL))
        out.append(re.sub(r"<[^>]+>", "", text).strip())
    return "\n".join(out) if out else re.sub(r"<[^>]+>", "", raw)


def _read_source(source: Path | str) -> tuple[str, str]:
    if isinstance(source, str) and not Path(source).exists():
        return source, "txt"

    path = Path(source)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages), "pdf"
        except Exception as exc:
            log.warning("pdf extraction failed, reading as text: %s", exc)

    text = path.read_text(encoding="utf-8", errors="replace")
    fmt = {".fdx": "fdx", ".fountain": "fountain", ".txt": "txt"}.get(suffix, "txt")
    return text, fmt


def _analysis_safety(types: Any) -> list[Any]:
    """Analysis is not generation.

    A clearance system must be able to read a scene containing violence, slurs
    or sexual content. Refusing to parse it produces a silent hole in the
    report, which is strictly worse than analysing it, so thresholds are
    relaxed for this read only task. When a scene still blocks, the span
    carries `needs_manual_breakdown` and the report says so.
    """
    return [
        types.SafetySetting(category=c, threshold="BLOCK_ONLY_HIGH")
        for c in (
            "HARM_CATEGORY_HARASSMENT",
            "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_DANGEROUS_CONTENT",
        )
    ]


_SPAN_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["spans"],
    "properties": {
        "spans": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["element_type", "surface_form"],
                "properties": {
                    "element_type": {"type": "string", "enum": [str(e) for e in ElementType]},
                    "surface_form": {"type": "string"},
                    "context": {"type": "string"},
                    "line_no": {"type": "integer"},
                    "page": {"type": "number"},
                    "modality": {"type": "string", "enum": [str(m) for m in Modality]},
                    "character_cue": {"type": "string"},
                    "confidence": {"type": "number"},
                    "attributes": {"type": "object"},
                },
            },
        }
    },
}


#: Verbs that begin a predicate rather than a name. A span opening with one of
#: these is describing what happened, not naming the thing it happened to.
_PREDICATE_OPENERS = frozenset(
    {
        "sank",
        "sunk",
        "died",
        "killed",
        "struck",
        "hit",
        "won",
        "lost",
        "scored",
        "founded",
        "dismissed",
        "arrested",
        "convicted",
        "sentenced",
        "married",
        "divorced",
        "resigned",
        "retired",
        "launched",
        "crashed",
        "survived",
        "testified",
        "was",
        "were",
        "had",
        "has",
        "became",
        "led",
        "captained",
        "played",
        "faced",
        "reached",
        "hailing",
        "born",
    }
)

#: Types whose spans must be nameable. A person or a place is always a name;
#: these are the ones the model reaches for when it wants to tag an assertion.
_MUST_BE_NAMEABLE = frozenset({"REAL_EVENT", "ORGANIZATION", "BUSINESS_NAME", "BRAND_PRODUCT"})


def _is_predicate(surface: str, element_type: ElementType) -> bool:
    """Whether this span is a description of an event rather than its name.

    Every span becomes a subject that is looked up in Wikidata and searched for
    on the open web, so it has to be the kind of thing that has a name. On a
    Titanic scene the model returned "the sinking", "sank on 15 April 1912" and
    "sank on its third voyage" as REAL_EVENT spans; identity then searched for a
    real entity of that name, found none, and blocked research on the claims
    filed under them. "The Titanic struck an iceberg" came back unsupported
    with no sources, never having been researched.

    Deliberately narrow. It only fires on types the model uses for assertions,
    and only on a leading verb or a bare article, so a genuine event name like
    "the Watergate break in" survives.
    """
    if str(element_type) not in _MUST_BE_NAMEABLE:
        return False

    words = surface.strip().strip("\"'").split()
    if not words:
        return True

    first = words[0].casefold().strip(".,;:")
    if first in _PREDICATE_OPENERS:
        return True

    # "the sinking", "a collapse": an article and one common noun names nothing.
    return first in {"the", "a", "an"} and len(words) == 2 and words[1].islower()
