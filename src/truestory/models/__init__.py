"""Domain contracts.

Frozen where possible, content addressed where it matters, and free of any
dependency on Google Cloud, Parallel, or a web framework. Every other layer of
the system imports these and none of them imports any other layer, which is why
the whole pipeline can run offline against fixtures.
"""

from truestory.models.claims import ClaimRollup, FactualClaim
from truestory.models.elements import ClearableElement, Remedy, RunSummary
from truestory.models.enums import (
    CLAIM_BEARING,
    DETERMINISTIC_ONLY,
    PERSON_ADJACENT,
    VERDICT_COLOR,
    ClaimType,
    ClearanceStatus,
    ElementType,
    Modality,
    Polarity,
    Processor,
    PublicFigureStatus,
    RiskTier,
    Role,
    RunStatus,
    Verdict,
)
from truestory.models.evidence import Citation, Evidence, MonitorHandle
from truestory.models.spans import Occurrence, RawSpan, Scene, ScriptDocument

# Grouped by module rather than sorted alphabetically. This list is the
# package's public surface and the grouping is what makes it readable, so the
# sort rule is declined here deliberately.
__all__ = [  # noqa: RUF022
    # enums
    "ClaimType",
    "ClearanceStatus",
    "ElementType",
    "Modality",
    "Polarity",
    "Processor",
    "PublicFigureStatus",
    "RiskTier",
    "Role",
    "RunStatus",
    "Verdict",
    "PERSON_ADJACENT",
    "CLAIM_BEARING",
    "DETERMINISTIC_ONLY",
    "VERDICT_COLOR",
    # evidence
    "Citation",
    "Evidence",
    "MonitorHandle",
    # spans
    "Occurrence",
    "RawSpan",
    "Scene",
    "ScriptDocument",
    # claims
    "FactualClaim",
    "ClaimRollup",
    # elements
    "ClearableElement",
    "Remedy",
    "RunSummary",
]
