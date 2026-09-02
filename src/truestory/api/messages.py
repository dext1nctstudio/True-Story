"""Operator facing copy for infrastructure faults.

The audience for a coverage warning is a production's counsel, not an engineer.
Before this module the interface showed them this, verbatim, on a clearance
report:

    RESEARCH PROVIDER OUT OF SERVICE: parallel_task stopped answering during
    this run and every subject it had not yet reached went unchecked. Reported:
    parallel_task: HTTP 402: {"type":"error","error":{"ref_id":"b03c0f0bcc57
    74c8b662393d9200e8bb","message":"Insufficient credit in account, please
    check your plan ...

A JSON blob and a support reference in a legal deliverable. The reader cannot
tell whether the report is safe to file, and nothing in it says what to do.

Every fault here resolves to three things, because those are the three
questions the reader actually has:

    what happened   one sentence, no identifiers, no vendor names they do not
                    already use
    what it means   specifically for THIS report, including whether it can be
                    filed
    what to do      one concrete action, phrased for whoever is holding the
                    screen

The technical detail is kept, on `detail`, and demoted in the interface rather
than discarded. An engineer still has to be able to find the ref_id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Ordered. The first pattern that matches a fault string wins, so the specific
#: cases precede the general ones.
_FAULTS: list[tuple[str, str]] = [
    (r"\b402\b|insufficient credit|payment required", "no_credit"),
    (r"\b401\b|unauthori[sz]ed|invalid api key|invalid key", "bad_key"),
    (r"\b403\b|forbidden|permission denied", "no_permission"),
    (r"\b429\b|rate limit|resource[ _]exhausted|quota", "rate_limited"),
    (r"still active|timed out|timeout|deadline", "too_slow"),
    (r"credential|default credentials were not found|unauthenticated", "no_credentials"),
    (r"\b5\d\d\b|internal server error|bad gateway|service unavailable", "provider_down"),
]


@dataclass(frozen=True, slots=True)
class OperatorMessage:
    """One fault, said three ways, plus the raw text for whoever needs it."""

    kind: str
    headline: str
    meaning: str
    action: str
    #: Whether a report produced under this condition may be filed at all. The
    #: distinction that matters most and the one a raw error string cannot make.
    blocks_filing: bool
    detail: str = ""
    subjects_affected: int = 0
    subjects_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "headline": self.headline,
            "meaning": self.meaning,
            "action": self.action,
            "blocks_filing": self.blocks_filing,
            "detail": self.detail,
            "subjects_affected": self.subjects_affected,
            "subjects_total": self.subjects_total,
        }

    def as_sentence(self) -> str:
        """The flat form, for surfaces that take a plain string.

        Deliberately carries no identifiers. Somewhere in the product this will
        be pasted into a document, and the ref_id is the part that makes a
        report look like a stack trace.
        """
        scope = ""
        if self.subjects_total:
            scope = f" {self.subjects_affected} of {self.subjects_total} subjects were affected."
        return f"{self.headline} {self.meaning}{scope} {self.action}".strip()


def classify(fault: str) -> str:
    """Which family of fault this text describes."""
    lowered = (fault or "").casefold()
    for pattern, kind in _FAULTS:
        if re.search(pattern, lowered):
            return kind
    return "unknown"


def describe(
    fault: str,
    *,
    provider: str = "the research provider",
    subjects_affected: int = 0,
    subjects_total: int = 0,
) -> OperatorMessage:
    """Turn a raw provider fault into something a reader can act on.

    `fault` is whatever the provider said, JSON and all. It goes to `detail`
    and never into the prose.
    """
    kind = classify(fault)
    built = _COPY.get(kind, _COPY["unknown"])(provider)

    return OperatorMessage(
        kind=kind,
        headline=built[0],
        meaning=built[1],
        action=built[2],
        blocks_filing=built[3],
        detail=_trim(fault),
        subjects_affected=subjects_affected,
        subjects_total=subjects_total,
    )


def _trim(fault: str) -> str:
    """Keep the technical text useful without letting it become the message."""
    text = " ".join((fault or "").split())
    return text[:400]


# Each entry returns (headline, meaning, action, blocks_filing).
#
# The wording is deliberately plain. "Insufficient credit in account" is a
# billing status; "the research account has run out of credit" is a sentence a
# producer can act on without knowing what an account is.
_COPY: dict[str, Any] = {
    "no_credit": lambda p: (
        "Research stopped: the account has run out of credit.",
        "Subjects the run had not yet reached were never checked, so this report "
        "does not show that their record is clear. It shows that nobody looked.",
        "Top up the research account, then run the draft again.",
        True,
    ),
    "bad_key": lambda p: (
        "Research stopped: the access key was rejected.",
        "Nothing was checked after that point. The findings already collected "
        "stand; everything after them is absent rather than clear.",
        "Replace the research API key and run the draft again.",
        True,
    ),
    "no_permission": lambda p: (
        "Research stopped: this account is not permitted to run that lookup.",
        "The affected subjects were never checked. Their absence from the "
        "findings is not evidence that they are clear.",
        "Check the research account's plan and permissions, then run again.",
        True,
    ),
    "rate_limited": lambda p: (
        "Research was throttled and some lookups did not complete.",
        "The report is thinner than it should be. Completed findings are sound; "
        "the affected subjects are unchecked rather than clear.",
        "Wait a few minutes and run the draft again to fill the gaps.",
        True,
    ),
    "too_slow": lambda p: (
        "Some lookups were still running when the run reached its time limit.",
        "Those subjects fell back to a secondary check or were left unchecked. "
        "Anything marked as a fallback finding carries lower confidence by design.",
        "Re-run the draft to complete them, or raise the per lookup time limit.",
        False,
    ),
    "no_credentials": lambda p: (
        "Research could not start: the system has no working credentials.",
        "No subject in this run was checked against the public record at all.",
        "Configure the research and cloud credentials, then run the draft again.",
        True,
    ),
    "provider_down": lambda p: (
        "Research stopped: the research service is not responding.",
        "Subjects after that point were never checked. This is an outage, not a "
        "finding about anybody in the script.",
        "Try again shortly. If it persists, the research service is down.",
        True,
    ),
    "unknown": lambda p: (
        "Research stopped before the run finished.",
        "Some subjects were never checked, so their absence from the findings is "
        "not evidence that they are clear. The technical detail is recorded below.",
        "Run the draft again. If it fails the same way, send the detail below to "
        "whoever maintains the deployment.",
        True,
    ),
}


@dataclass
class CoverageReport:
    """Every operator message a run produced, and whether it may be filed."""

    messages: list[OperatorMessage] = field(default_factory=list)

    def add(self, message: OperatorMessage) -> None:
        self.messages.append(message)

    @property
    def blocks_filing(self) -> bool:
        return any(m.blocks_filing for m in self.messages)

    def sentences(self) -> list[str]:
        return [m.as_sentence() for m in self.messages]

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": [m.to_dict() for m in self.messages],
            "blocks_filing": self.blocks_filing,
        }
