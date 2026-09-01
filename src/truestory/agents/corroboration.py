"""Corroboration analysis. What the record actually supports, counted.

The Adjudicator asks a language model for a verdict and then applies the rubric
over the top. Between those two steps there is a question neither of them was
answering: *how well corroborated is this?* Citation count alone does not
answer it, because five URLs on one site are one source, a Wikipedia paragraph
and a federal docket are not interchangeable, and a research payload that
returns both supporting and contradicting facts has told you something
important that a single verdict token throws away.

This module reads the evidence set and reports:

  independence   distinct registrable domains behind the finding
  pedigree       how many recognised primary sources, how many low trust
  record signal  what the research payload itself concluded, read from the
                 schema fields rather than from prose
  agreement      whether the model's verdict matches that signal
  recency        how old the newest source is

Everything here is deterministic and testable. The adjudicator consumes the
report; it does not re derive any of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from truestory.models.evidence import Evidence

# Schema verdict vocabulary -> our own. `no_record` is deliberately not mapped
# to CONTRADICTED: unsupported is not false, and collapsing the two is the
# exact failure this product exists to prevent.
_SCHEMA_VERDICT: dict[str, str] = {
    "supported": "SUPPORTED",
    "contradicted": "CONTRADICTED",
    "no_record": "SILENT",
    "not_a_factual_claim": "OPINION",
}

#: Fields across the schema family that carry a list of facts with sources.
_SUPPORTING_KEYS = ("supporting_facts", "supporting_evidence", "corroborating_facts")
_CONTRADICTING_KEYS = ("contradicting_facts", "contradicting_evidence", "refuting_facts")


@dataclass(slots=True)
class Corroboration:
    """What is behind one subject's verdict. Reported to the UI verbatim."""

    citation_count: int = 0
    independent_domains: int = 0
    domains: list[str] = field(default_factory=list)
    primary_count: int = 0  # declared primary
    classified_primary_count: int = 0  # primary on a recognised host
    low_trust_count: int = 0
    #: Citations on hosts this system recognises and does not classify as user
    #: generated. An unrecognised host is not evidence that something is false;
    #: it is a page nobody can vouch for, and two of them are still nobody.
    recognised_count: int = 0
    strongest_trust: float = 0.0

    #: What the research payload concluded, read from its own fields.
    record_signal: str = "UNKNOWN"  # SUPPORTED | CONTRADICTED | SILENT | OPINION | MIXED
    supporting_facts: int = 0
    contradicting_facts: int = 0
    record_quality: str = ""  # strong | moderate | thin

    conflict: bool = False
    #: Stances assigned by the attribution gate, counted separately from the
    #: research payload's own fields. Two sources quoted against each other is
    #: a conflict whatever the payload concluded, and it was going unnoticed.
    supporting_sources: int = 0
    contradicting_sources: int = 0
    newest_source_days: int | None = None
    oldest_source_days: int | None = None

    notes: list[str] = field(default_factory=list)

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def single_source(self) -> bool:
        """Everything came from one site, however many URLs were returned."""
        return self.citation_count > 0 and self.independent_domains <= 1

    @property
    def low_trust_only(self) -> bool:
        return self.citation_count > 0 and self.low_trust_count == self.citation_count

    @property
    def score(self) -> float:
        """A 0..1 summary of how well the record backs this subject.

        Used to cap confidence, never to set it. The shape is deliberately
        blunt: independence and pedigree dominate, volume barely counts,
        because volume is the easiest thing for a research pipeline to
        manufacture and the least informative when it does.
        """
        if self.citation_count == 0:
            return 0.0
        domains = self.independent_domains
        # A recognised record of record counts as more than one voice, because
        # it is not a voice: it is the register the other sources are quoting.
        # Counting breadth alone scored an official scorecard at a third of a
        # mark, capped a correct verified claim at 0.73 against a 0.75 review
        # threshold, and sent three true, cited, primary sourced claims to a
        # lawyer for want of a blog repeating them. Deliberately not full
        # marks: one register is still one point of failure, so it earns the
        # weight of two ordinary sources and never that of three.
        if self.classified_primary_count >= 1 and not self.low_trust_only:
            domains = max(domains, 2)
        independence = min(domains, 3) / 3  # 3 domains is full marks
        pedigree = self.strongest_trust
        volume = min(self.citation_count, 4) / 8  # tops out at a half weight
        raw = 0.45 * independence + 0.45 * pedigree + 0.10 * volume
        if self.conflict:
            raw *= 0.7
        if self.low_trust_only:
            raw *= 0.4
        return round(min(1.0, raw), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_count": self.citation_count,
            "independent_domains": self.independent_domains,
            "domains": self.domains,
            "primary_count": self.primary_count,
            "classified_primary_count": self.classified_primary_count,
            "low_trust_count": self.low_trust_count,
            "recognised_count": self.recognised_count,
            "strongest_trust": round(self.strongest_trust, 3),
            "record_signal": self.record_signal,
            "supporting_facts": self.supporting_facts,
            "contradicting_facts": self.contradicting_facts,
            "record_quality": self.record_quality,
            "conflict": self.conflict,
            "supporting_sources": self.supporting_sources,
            "contradicting_sources": self.contradicting_sources,
            "single_source": self.single_source,
            "low_trust_only": self.low_trust_only,
            "newest_source_days": self.newest_source_days,
            "oldest_source_days": self.oldest_source_days,
            "score": self.score,
            "notes": self.notes,
        }


def analyse(evidence: list[Evidence]) -> Corroboration:
    """Read an evidence set and count what is actually there."""
    report = Corroboration()
    usable = [e for e in evidence if e.is_usable]
    if not usable:
        report.notes.append("No usable evidence records.")
        return report

    domains: set[str] = set()
    trusts: list[float] = []
    ages: list[int] = []

    for record in usable:
        report.citation_count += len(record.citations)
        report.primary_count += record.primary_source_count
        report.classified_primary_count += record.classified_primary_count
        report.low_trust_count += record.low_trust_count
        report.recognised_count += sum(
            1 for c in record.citations if c.verified_source and c.source_class != "user"
        )
        report.supporting_sources += sum(1 for c in record.citations if c.stance == "supports")
        report.contradicting_sources += sum(
            1 for c in record.citations if c.stance == "contradicts"
        )
        domains |= record.domains
        trusts.extend(c.trust for c in record.citations)
        for citation in record.citations:
            age = _age_days(citation.published_at or citation.accessed_at)
            if age is not None:
                ages.append(age)

        _read_record_signal(record.finding, report)

    report.domains = sorted(domains)
    report.independent_domains = len(domains)
    report.strongest_trust = max(trusts, default=0.0)
    report.newest_source_days = min(ages) if ages else None
    report.oldest_source_days = max(ages) if ages else None

    # A payload carrying facts on both sides is the single most valuable
    # signal in the set, and the one most easily lost when a verdict token is
    # read on its own.
    if report.supporting_facts and report.contradicting_facts:
        report.conflict = True
        report.record_signal = "MIXED"
        report.notes.append(
            f"The record cuts both ways: {report.supporting_facts} supporting and "
            f"{report.contradicting_facts} contradicting findings were returned."
        )

    # The same test over the stances the gate actually assigned. A payload can
    # report a clean verdict while the sources quoted underneath it disagree,
    # and the sources are the part that was checked.
    if report.supporting_sources and report.contradicting_sources:
        report.conflict = True
        report.notes.append(
            f"{report.supporting_sources} quoted source"
            f"{'' if report.supporting_sources == 1 else 's'} support this and "
            f"{report.contradicting_sources} contradict it. Both are shown."
        )

    if report.single_source:
        report.notes.append(
            f"Every citation resolves to one domain ({report.domains[0]}). Not corroborated."
        )
    if report.low_trust_only:
        report.notes.append(
            "Every source is user generated or unattributable. Not sufficient to "
            "settle a claim about a real person."
        )
    if report.classified_primary_count == 0 and report.primary_count:
        report.notes.append(
            "Sources described as primary sit on hosts this system does not "
            "recognise as a register, docket or official record."
        )

    return report


def _read_record_signal(finding: dict[str, Any], report: Corroboration) -> None:
    """Pull the research payload's own conclusion out of its schema fields."""
    if not isinstance(finding, dict):
        return

    for key in _SUPPORTING_KEYS:
        value = finding.get(key)
        if isinstance(value, list):
            report.supporting_facts += len(value)
    for key in _CONTRADICTING_KEYS:
        value = finding.get(key)
        if isinstance(value, list):
            report.contradicting_facts += len(value)

    quality = finding.get("record_quality")
    if isinstance(quality, str) and quality:
        report.record_quality = quality

    raw = finding.get("verdict")
    if isinstance(raw, str):
        mapped = _SCHEMA_VERDICT.get(raw.strip().lower())
        if mapped and report.record_signal in {"UNKNOWN", mapped}:
            report.record_signal = mapped
        elif mapped:
            report.record_signal = "MIXED"


def _age_days(stamp: datetime | None) -> int | None:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - stamp).days)


# =============================================================================
# agreement
# =============================================================================
# The research payload said one thing, the adjudicating model said another.
# That disagreement is information, and before this existed it was discarded.

#: Our verdict -> the record signals that are consistent with it.
_CONSISTENT: dict[str, set[str]] = {
    "VERIFIED": {"SUPPORTED"},
    "CONTRADICTED": {"CONTRADICTED"},
    "UNSUPPORTED": {"SILENT", "MIXED", "SUPPORTED", "CONTRADICTED"},
    "UNVERIFIABLE": {"SILENT", "MIXED"},
    "OPINION": {"OPINION", "SILENT", "UNKNOWN"},
}


def disagreement(verdict: str, report: Corroboration) -> str | None:
    """Describe a verdict that its own research does not support.

    Returns None when the two are consistent, or when the research payload
    carried no verdict of its own to compare against.
    """
    signal = report.record_signal
    if signal == "UNKNOWN":
        return None
    allowed = _CONSISTENT.get(verdict.upper())
    if allowed is None or signal in allowed:
        return None
    return (
        f"The adjudicator recorded {verdict} while the research payload reported "
        f"{signal.lower()}. The two are surfaced together and a human decides."
    )
