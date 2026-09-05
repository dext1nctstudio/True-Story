"""A defamatory passage about a real person produces two elements under one
name: the person (REAL_PERSON_DEPICTED) and the passage (DEFAMATORY_REF).

Found live, on a run about Linda Fairstein. The name map in `_attach_claims`
was built with a plain assignment, so whichever element came last won the
name outright, and every claim landed on the DEFAMATORY_REF. The person
element kept zero. The register lists person typed elements that have claims,
so she matched neither half of it and was absent from the People tab; and
because the claims did have an element, they were not reported as
unattributed either. Five unsupported negative claims about a living person,
missing from the document counsel works from.

DEFAMATORY_REF is not in CLAIM_BEARING at all, so it was never a legitimate
owner of a claim.
"""

from __future__ import annotations

from truestory.agents.ledger import LedgerAgent
from truestory.agents.report import ReportAgent
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClaimType, ElementType, Polarity, Verdict

NAME = "Linda Fairstein"


def _element(element_type: ElementType) -> ClearableElement:
    return ClearableElement(
        element_id=ClearableElement.make_id(element_type, NAME, ["US"]),
        element_type=element_type,
        canonical_form=NAME,
        jurisdictions=["US"],
    )


def _claim(text: str) -> FactualClaim:
    return FactualClaim(
        claim_id=FactualClaim.make_id("span_1", text),
        subject_element_id="span_1",
        subject_name=NAME,
        claim_text=text,
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
        verdict=Verdict.UNSUPPORTED,
    )


def _attach(order: list[ElementType]) -> list[ClearableElement]:
    elements = [_element(t) for t in order]
    claims = [
        _claim("Linda Fairstein concealed DNA evidence from the defence."),
        _claim("Linda Fairstein delayed DNA testing to gain a tactical advantage."),
    ]
    LedgerAgent(jurisdictions=["US"])._attach_claims(elements, claims, {})
    return elements


def test_claims_land_on_the_person_not_the_defamatory_ref() -> None:
    """The bug: DEFAMATORY_REF listed last used to take every claim."""
    elements = _attach([ElementType.REAL_PERSON_DEPICTED, ElementType.DEFAMATORY_REF])

    person = next(e for e in elements if e.element_type is ElementType.REAL_PERSON_DEPICTED)
    passage = next(e for e in elements if e.element_type is ElementType.DEFAMATORY_REF)

    assert len(person.claims) == 2
    assert passage.claims == []


def test_the_person_wins_regardless_of_element_order() -> None:
    """Ordering must not decide who owns a claim."""
    elements = _attach([ElementType.DEFAMATORY_REF, ElementType.REAL_PERSON_DEPICTED])

    person = next(e for e in elements if e.element_type is ElementType.REAL_PERSON_DEPICTED)
    passage = next(e for e in elements if e.element_type is ElementType.DEFAMATORY_REF)

    assert len(person.claims) == 2
    assert passage.claims == []


def test_a_named_person_with_claims_reaches_the_register() -> None:
    """The symptom counsel actually saw: an empty People tab."""
    elements = _attach([ElementType.REAL_PERSON_DEPICTED, ElementType.DEFAMATORY_REF])
    claims = [c for e in elements for c in e.claims]

    register = ReportAgent().claim_register(claims, elements)

    names = [p["person_name"] for p in register["persons"]]
    assert names == [NAME]
    assert register["persons"][0]["total_claims"] == 2
    assert register["unattributed_claims"] == []


def test_a_defamatory_ref_with_no_person_still_receives_its_claims() -> None:
    """The preference is only a tie break. With no claim bearing element under
    the name, the claim must still find its subject rather than be dropped."""
    elements = _attach([ElementType.DEFAMATORY_REF])

    assert len(elements[0].claims) == 2
