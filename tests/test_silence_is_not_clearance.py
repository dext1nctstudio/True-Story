"""Silence is not clearance.

The claim path has always distinguished "searched and found nothing" from
"false", because collapsing the two is the defamation this system exists to
prevent. The element path did not, and it failed in the opposite and equally
expensive direction: when research returned no citable source, every element
type was marked CLEAR at confidence 0.0 on one boilerplate sentence.

Measured on a live run of a two page script:

    MUSIC_CUE      "IMAGINE"                              CLEAR  0.0
    DEFAMATORY_REF "Tara Bedi embezzled forty thousand
                    pounds from the department"           CLEAR  0.0
    DEFAMATORY_REF "he faked it ... shot in a studio"     CLEAR  0.0

The first tells a production it may use one of the most expensive sync
licences in the world for nothing. The second and third clear an unproven
criminal allegation and an unproven fraud allegation on the grounds that
nobody has published a rebuttal, which is what an unproven allegation looks
like by definition.
"""

from __future__ import annotations

import pytest

from truestory.agents.adjudicator import Adjudicator
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClearanceStatus, ElementType


def _element(element_type: ElementType, name: str) -> ClearableElement:
    return ClearableElement(
        element_id=f"el_{name.lower().replace(' ', '_')[:12]}",
        element_type=element_type,
        canonical_form=name,
    )


#: The categories where a right or an injured party exists whether or not this
#: run's research surfaced one.
RIGHTS_BEARING = [
    (ElementType.MUSIC_CUE, "IMAGINE"),
    (ElementType.ARTWORK_VISUAL, "GUERNICA"),
    (ElementType.FILM_CLIP, "THE GODFATHER"),
    (ElementType.BRAND_PRODUCT, "Coca-Cola"),
    (ElementType.TRADEMARK_LOGO, "NIKE swoosh"),
    (ElementType.DEFAMATORY_REF, "Tara Bedi embezzled forty thousand pounds"),
    (ElementType.TRADE_LIBEL, "their brakes fail in the wet"),
    (ElementType.REAL_PERSON_DEPICTED, "Neil Armstrong"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("element_type", "name"), RIGHTS_BEARING)
async def test_no_record_never_clears_a_rights_bearing_element(
    element_type: ElementType, name: str
) -> None:
    element = _element(element_type, name)

    await Adjudicator().adjudicate_element(element, [])

    assert element.status is not ClearanceStatus.CLEAR, (
        f"{element_type} was cleared on an empty record. Silence about a right "
        f"is a failed lookup, not a clearance."
    )
    assert element.status is ClearanceStatus.NEEDS_COUNSEL
    assert element.needs_counsel is True


@pytest.mark.asyncio
async def test_a_generic_location_still_clears_on_silence() -> None:
    """The case the CLEAR-on-silence branch was written for, still working.

    A generic set location has no record because there is nothing to have one.
    Sending that to counsel would bury the queue in nothing, which is why the
    fix is scoped by category rather than applied to every element.
    """
    element = _element(ElementType.REAL_LOCATION, "a corridor")

    await Adjudicator().adjudicate_element(element, [])

    assert element.status is ClearanceStatus.CLEAR
    assert element.needs_counsel is False
