"""Source pedigree and corroboration.

These tests guard the thing that decides whether a red line is allowed to
exist. Before the classifier, every citation defaulted to "secondary", so
`contradicted_requires_primary_source` silently downgraded every contradiction
in the product to unsupported and the headline output was unreachable in live
mode. If anything in this file starts failing, verdicts are resting on
something other than what the UI says they rest on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from truestory.agents import corroboration as corr
from truestory.models.evidence import Citation, Evidence
from truestory.providers.source_quality import assess, registrable_domain

# =============================================================================
# classification
# =============================================================================


@pytest.mark.parametrize(
    ("url", "expected_type", "expected_class"),
    [
        ("https://www.courtlistener.com/docket/1", "primary", "official"),
        ("https://tsdr.uspto.gov/#caseNumber=1", "primary", "registry"),
        ("https://www.legislation.gov.uk/ukpga/1988/48", "primary", "official"),
        ("https://oag.ca.gov/news/press", "primary", "official"),
        ("https://www.nytimes.com/2020/01/01/us/story.html", "secondary", "news"),
        ("https://variety.com/2024/film/news/story", "secondary", "trade"),
        ("https://en.wikipedia.org/wiki/Someone", "tertiary", "reference"),
        ("https://www.reddit.com/r/movies/comments/x", "tertiary", "user"),
        ("https://www.imdb.com/name/nm0000001/", "tertiary", "reference"),
    ],
)
def test_known_hosts_are_classified_from_the_url(url, expected_type, expected_class):
    verdict = assess(url, declared="secondary")
    assert verdict.source_type == expected_type
    assert verdict.source_class == expected_class
    assert verdict.verified is True


def test_a_known_host_overrules_what_the_researcher_declared():
    """Both directions. This is the whole point of the module."""
    promoted = assess("https://www.courtlistener.com/docket/9", declared="secondary")
    assert promoted.source_type == "primary"

    demoted = assess("https://en.wikipedia.org/wiki/X", declared="primary")
    assert demoted.source_type == "tertiary"


def test_an_unknown_host_keeps_the_declared_type_but_is_not_verified():
    verdict = assess("https://some-blog.example.xyz/post", declared="primary")
    assert verdict.source_type == "primary"
    assert verdict.verified is False
    assert verdict.trust < 0.6  # asserted, not established


def test_declared_primary_on_an_unknown_host_is_not_a_classified_primary():
    citation = Citation.classified("https://some-blog.example.xyz/post", declared_type="primary")
    assert citation.is_primary is True
    assert citation.is_classified_primary is False


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.bbc.co.uk/news/uk-1", "bbc.co.uk"),
        ("https://sub.section.nytimes.com/x", "nytimes.com"),
        ("https://example.com", "example.com"),
    ],
)
def test_registrable_domain_is_the_unit_of_independence(url, domain):
    assert registrable_domain(url) == domain


# =============================================================================
# corroboration
# =============================================================================


def _evidence(urls: list[str], finding: dict | None = None) -> Evidence:
    return Evidence(
        evidence_id="ev_1",
        subject_id="cl_1",
        question="q",
        finding=finding or {},
        citations=[Citation.classified(u, excerpt="passage") for u in urls],
        reasoning="",
        confidence=0.9,
        provider="parallel_task:core",
        schema_version="claim_verification_v1",
    )


def test_several_pages_on_one_site_are_one_source():
    report = corr.analyse(
        [
            _evidence(
                [
                    "https://www.nytimes.com/a",
                    "https://www.nytimes.com/b",
                    "https://www.nytimes.com/c",
                ]
            )
        ]
    )
    assert report.citation_count == 3
    assert report.independent_domains == 1
    assert report.single_source is True


def test_independent_domains_are_counted_separately():
    report = corr.analyse(
        [_evidence(["https://www.courtlistener.com/docket/1", "https://www.bbc.co.uk/news/1"])]
    )
    assert report.independent_domains == 2
    assert report.classified_primary_count == 1
    assert report.single_source is False


def test_forum_only_evidence_is_flagged_as_unable_to_decide():
    report = corr.analyse([_evidence(["https://www.reddit.com/r/x/1"])])
    assert report.low_trust_only is True
    assert report.score < 0.3


def test_a_payload_with_facts_on_both_sides_is_a_conflict():
    report = corr.analyse(
        [
            _evidence(
                ["https://www.courtlistener.com/docket/1"],
                finding={
                    "verdict": "supported",
                    "supporting_facts": [{"fact": "a"}],
                    "contradicting_facts": [{"fact": "b"}],
                    "record_quality": "moderate",
                },
            )
        ]
    )
    assert report.conflict is True
    assert report.record_signal == "MIXED"
    assert report.record_quality == "moderate"


def test_the_payloads_own_verdict_is_read_from_its_schema_fields():
    report = corr.analyse(
        [_evidence(["https://www.govinfo.gov/app/1"], finding={"verdict": "contradicted"})]
    )
    assert report.record_signal == "CONTRADICTED"


def test_pedigree_and_independence_dominate_the_score():
    weak = corr.analyse([_evidence(["https://www.reddit.com/r/x/1"])])
    strong = corr.analyse(
        [
            _evidence(
                [
                    "https://www.courtlistener.com/docket/1",
                    "https://www.bbc.co.uk/news/1",
                    "https://apnews.com/article/1",
                ]
            )
        ]
    )
    assert strong.score > 0.8
    assert weak.score < strong.score


def test_source_age_is_measured_from_publication_where_it_is_known():
    old = Citation.classified(
        "https://www.nytimes.com/1975/a",
        published_at=datetime.now(UTC) - timedelta(days=4000),
    )
    evidence = Evidence(
        evidence_id="ev_old",
        subject_id="cl_1",
        question="q",
        finding={},
        citations=[old],
        reasoning="",
        confidence=0.8,
        provider="parallel_task:base",
        schema_version="claim_verification_v1",
    )
    report = corr.analyse([evidence])
    assert report.oldest_source_days is not None
    assert report.oldest_source_days > 3900


# =============================================================================
# disagreement
# =============================================================================


def test_a_verified_verdict_over_a_contradicting_record_is_a_disagreement():
    report = corr.analyse(
        [_evidence(["https://www.govinfo.gov/app/1"], finding={"verdict": "contradicted"})]
    )
    assert corr.disagreement("VERIFIED", report) is not None


def test_agreement_is_silent():
    report = corr.analyse(
        [_evidence(["https://www.govinfo.gov/app/1"], finding={"verdict": "supported"})]
    )
    assert corr.disagreement("VERIFIED", report) is None


def test_no_payload_verdict_means_nothing_to_disagree_with():
    report = corr.analyse([_evidence(["https://www.govinfo.gov/app/1"])])
    assert corr.disagreement("CONTRADICTED", report) is None
