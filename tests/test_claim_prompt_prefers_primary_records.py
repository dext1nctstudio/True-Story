"""The claim verification prompt used to accept whatever the model returned as
long as it cited *something*, and the model's cheapest good answer for a claim
whose falsity was famous through litigation was to cite reporting on the
litigation itself rather than the underlying record.

Live A/B tested against Nona Gaprindashvili's actual "never faced men" claim
(the real Gaprindashvili v. Netflix dispute this product's Litigation Set
models): the original prompt returned facts with placeholder source URLs
("example.com/source_not_provided..."), every fact marked secondary, and the
lawsuit itself listed as a contradicting fact. The instruction added here
produced two facts, both primary, both carrying a real URL and excerpt --
chessgames.com's own record of a specific 1977 game against a named male
opponent, and the World Chess Hall of Fame's own page -- with no mention of
Netflix or the lawsuit anywhere in the result.

This test cannot exercise the model; it pins the instruction that produced
that result so it cannot silently regress back to accepting reporting about a
dispute as if it were the record the dispute is about.
"""

from __future__ import annotations

from truestory.mcp.tools import _Q_CLAIM


def test_prompt_directs_reconstruction_of_the_primary_record() -> None:
    text = _Q_CLAIM.format(subject="X", claim="Y", jurisdictions="US")
    assert "reconstruct that fact directly from the primary record" in text


def test_prompt_rejects_dispute_coverage_as_a_substitute_for_the_record() -> None:
    text = _Q_CLAIM.format(subject="X", claim="Y", jurisdictions="US")
    assert "is not the primary record of the underlying fact" in text
    assert "not itself verification" in text


def test_prompt_requires_a_real_url_per_fact() -> None:
    text = _Q_CLAIM.format(subject="X", claim="Y", jurisdictions="US")
    assert "never a placeholder or an unlisted source" in text
