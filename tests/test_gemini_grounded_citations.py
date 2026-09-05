"""Citation deduplication in the grounded fallback.

Found live: a React citation list keyed on URL crashed with duplicate keys,
traced to `_citations_from_grounding` checking its `seen` set against the
grounding chunk's redirect URL while storing a different value -- the
resolved domain -- as the citation's actual `.url`. Two chunks with distinct
vertexaisearch redirects that happen to resolve to the same real page, which
grounded search does constantly when several supported spans cite one source,
both passed the "unseen" check and both got appended with the identical
final url.
"""

from __future__ import annotations

from types import SimpleNamespace

from truestory.providers.gemini_grounded import _citations_from_grounding


def _chunk(uri: str, domain: str, title: str = "") -> SimpleNamespace:
    return SimpleNamespace(web=SimpleNamespace(uri=uri, domain=domain, title=title))


def _response(chunks: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                grounding_metadata=SimpleNamespace(
                    grounding_chunks=chunks,
                    grounding_supports=[],
                )
            )
        ]
    )


def test_two_redirects_to_the_same_domain_produce_one_citation() -> None:
    """The bug. Both redirects are unique; both resolve to en.wikipedia.org."""
    response = _response(
        [
            _chunk("https://vertexaisearch.cloud.google.com/redirect/aaa", "en.wikipedia.org"),
            _chunk("https://vertexaisearch.cloud.google.com/redirect/bbb", "en.wikipedia.org"),
        ]
    )
    citations = _citations_from_grounding(response)

    assert len(citations) == 1
    assert citations[0].url == "https://en.wikipedia.org"


def test_distinct_domains_both_survive() -> None:
    response = _response(
        [
            _chunk("https://vertexaisearch.cloud.google.com/redirect/aaa", "en.wikipedia.org"),
            _chunk(
                "https://vertexaisearch.cloud.google.com/redirect/bbb", "sportstar.thehindu.com"
            ),
        ]
    )
    citations = _citations_from_grounding(response)

    urls = {c.url for c in citations}
    assert urls == {"https://en.wikipedia.org", "https://sportstar.thehindu.com"}


def test_no_domain_falls_back_to_the_redirect_itself_and_still_dedupes() -> None:
    """A chunk with no `web.domain` keeps the raw redirect as its url, and two
    identical redirects with no domain must still collapse to one citation."""
    response = _response(
        [
            _chunk("https://vertexaisearch.cloud.google.com/redirect/ccc", ""),
            _chunk("https://vertexaisearch.cloud.google.com/redirect/ccc", ""),
        ]
    )
    citations = _citations_from_grounding(response)

    assert len(citations) == 1
    assert citations[0].url == "https://vertexaisearch.cloud.google.com/redirect/ccc"


def test_a_chunk_with_no_url_at_all_is_skipped() -> None:
    response = _response([_chunk("", "en.wikipedia.org")])
    assert _citations_from_grounding(response) == []


def test_no_grounding_chunks_returns_no_citations() -> None:
    assert _citations_from_grounding(_response([])) == []
