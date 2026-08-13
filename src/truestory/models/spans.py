"""Raw spans, the output of IngestAgent.

A span is one occurrence of one potentially clearable thing, located precisely
enough that the overlay can light up the exact line and the report can cite the
exact page. Nothing is deduplicated at this stage. A name appearing forty times
produces forty spans, and LedgerAgent collapses them into one research subject
with forty occurrence pointers.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from truestory.models.enums import ElementType, Modality


@dataclass(frozen=True, slots=True)
class Occurrence:
    """Where in the script something appears.

    Page is expressed in eighths because that is how the industry measures a
    script. A report that says "page 14 2/8" reads as native to a line producer
    and a report that says "page 14.25" does not.
    """

    scene_no: int
    page: float
    line_no: int
    modality: Modality
    surface_form: str  # exactly as written, never normalised
    context: str = ""  # roughly plus or minus two hundred characters
    character_cue: str | None = None  # speaker, when the span sits in dialogue

    @property
    def page_eighths(self) -> str:
        whole = int(self.page)
        eighths = round((self.page - whole) * 8)
        return f"{whole}" if eighths == 0 else f"{whole} {eighths}/8"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["page_eighths"] = self.page_eighths
        return d


@dataclass(frozen=True, slots=True)
class RawSpan:
    """One untyped, undeduplicated hit from the ingest pass."""

    span_id: str
    scene_no: int
    page: float
    line_no: int
    element_type: ElementType
    surface_form: str
    context: str
    modality: Modality
    extraction_confidence: float
    character_cue: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_occurrence(self) -> Occurrence:
        return Occurrence(
            scene_no=self.scene_no,
            page=self.page,
            line_no=self.line_no,
            modality=self.modality,
            surface_form=self.surface_form,
            context=self.context,
            character_cue=self.character_cue,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["element_type"] = str(self.element_type)
        d["modality"] = str(self.modality)
        return d

    @staticmethod
    def make_id(scene_no: int, char_start: int, text: str) -> str:
        digest = hashlib.sha256(f"{scene_no}|{char_start}|{text}".encode()).hexdigest()
        return f"sp_{digest[:16]}"


@dataclass(frozen=True, slots=True)
class Scene:
    """One scene, the natural chunking boundary of a screenplay.

    INT. and EXT. headings are the most reliable structural signal in any
    document format the industry uses, which is why ingest chunks on them with
    a one scene overlap and processes the chunks in parallel.
    """

    scene_no: int
    heading: str
    start_page: float
    end_page: float
    text: str
    characters: list[str] = field(default_factory=list)

    @property
    def is_interior(self) -> bool:
        return self.heading.upper().startswith("INT")

    @property
    def length_eighths(self) -> int:
        return max(1, round((self.end_page - self.start_page) * 8))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScriptDocument:
    """A parsed draft.

    `script_hash` is what makes draft over draft caching free. Two uploads of
    the same bytes are the same run, and a revised draft shares element and
    claim identifiers with its parent for everything that did not change, so
    only the delta is researched.
    """

    script_id: str
    title: str
    draft_version: str
    script_hash: str
    page_count: float
    scenes: list[Scene]
    characters: list[str] = field(default_factory=list)

    # Project level detection from the ingest pass. One boolean that escalates
    # every person adjacent subject downstream.
    truth_claim_framing: bool = False
    truth_claim_evidence: str | None = None  # the title card or line that fired it

    source_format: str = "fountain"  # fountain | fdx | pdf | txt

    @property
    def scene_count(self) -> int:
        return len(self.scenes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id,
            "title": self.title,
            "draft_version": self.draft_version,
            "script_hash": self.script_hash,
            "page_count": self.page_count,
            "scene_count": self.scene_count,
            "characters": self.characters,
            "truth_claim_framing": self.truth_claim_framing,
            "truth_claim_evidence": self.truth_claim_evidence,
            "source_format": self.source_format,
            "scenes": [s.to_dict() for s in self.scenes],
        }

    @staticmethod
    def hash_bytes(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()[:32]
