"""Identity knows whether the subject is living; the claim has to know too.

The routing rule that defines this product -- `claim_negative_living`, whose
own note reads "Queen's Gambit, Baby Reindeer and Fairstein are all this rule"
-- matches on `{kind: claim, polarity: negative, subject_alive: true}` and
sends the match to the deepest processor at CRITICAL tier.

Found live on a Gaprindashvili run. Identity resolved her to Q231630 with
`deceased: False` and wrote `subject_alive = True` onto the *element*, but
nothing copied it onto the *claims* hanging off that element, and the router
reads `claim.subject_alive`. It was None, so the rule could not match and the
negative claim about a living person was researched by `parallel_task:base`
instead of `core`. Nothing failed loudly: the run completed, and the marquee
rule had simply never fired.

`subject_alive` was only ever populated later, by the adjudicator reading it
back off the research payload -- one stage too late to affect the routing that
chose the processor.
"""

from __future__ import annotations

from truestory.agents.pipeline import _inherit_subject_alive
from truestory.models.claims import FactualClaim
from truestory.models.elements import ClearableElement
from truestory.models.enums import ClaimType, ElementType, Polarity


def _element(alive: bool | None) -> ClearableElement:
    return ClearableElement(
        element_id="el_person",
        element_type=ElementType.REAL_PERSON_DEPICTED,
        canonical_form="Nona Gaprindashvili",
        subject_alive=alive,
    )


def _claim(alive: bool | None = None) -> FactualClaim:
    return FactualClaim(
        claim_id="cl_1",
        subject_element_id="el_person",
        subject_name="Nona Gaprindashvili",
        claim_text="Nona Gaprindashvili had never faced men in chess competitions.",
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
        subject_alive=alive,
    )


def test_a_claim_inherits_living_from_its_subject() -> None:
    """The bug: the element knew, the claim did not, and the router reads the claim."""
    element, claim = _element(True), _claim()

    _inherit_subject_alive([claim], [element])

    assert claim.subject_alive is True


def test_a_claim_inherits_deceased_too() -> None:
    """A dead subject cannot sue, and the rule must not fire for one."""
    element, claim = _element(False), _claim()

    _inherit_subject_alive([claim], [element])

    assert claim.subject_alive is False


def test_an_unresolved_subject_leaves_the_claim_unknown() -> None:
    """Unknown stays unknown. It must not be guessed into True."""
    element, claim = _element(None), _claim()

    _inherit_subject_alive([claim], [element])

    assert claim.subject_alive is None


def test_a_value_already_on_the_claim_is_not_overwritten() -> None:
    """A claim that already carries its own answer keeps it."""
    element, claim = _element(True), _claim(alive=False)

    _inherit_subject_alive([claim], [element])

    assert claim.subject_alive is False


def test_a_claim_with_no_matching_element_is_left_alone() -> None:
    orphan = FactualClaim(
        claim_id="cl_2",
        subject_element_id="el_missing",
        subject_name="Someone Else",
        claim_text="x",
        claim_type=ClaimType.CONDUCT,
        polarity=Polarity.NEGATIVE,
    )

    _inherit_subject_alive([orphan], [_element(True)])

    assert orphan.subject_alive is None


def test_the_routing_rule_now_fires_for_a_negative_claim_about_a_living_person() -> None:
    """The point of the fix, checked against the real routing table."""
    from truestory.policy import load_routing

    element, claim = _element(True), _claim()
    _inherit_subject_alive([claim], [element])

    decision = load_routing().match(
        {
            "kind": "claim",
            "polarity": str(claim.polarity),
            "subject_alive": claim.subject_alive,
        }
    )

    assert decision.rule_id == "claim_negative_living"


# ── the wiring ──────────────────────────────────────────────────────────────
# The helper above is only useful if the identity stage actually calls it, and
# calls it before routing reads the value. That is the part that was missing in
# the live run, so it is the part worth pinning.
def test_the_identity_stage_populates_claims_not_only_elements() -> None:
    import asyncio

    from truestory.agents.identity import IdentityStatus, IdentityVerdict
    from truestory.agents.pipeline import ProjectConfig, RunState, TrueStoryPipeline
    from truestory.providers.wikidata import EntityCandidate

    pipeline = TrueStoryPipeline(ProjectConfig(project_id="test"))

    async def _resolve(name: str, **_: object) -> IdentityVerdict:
        return IdentityVerdict(
            name=name,
            status=IdentityStatus.RESOLVED,
            canonical=EntityCandidate(
                qid="Q231630",
                label="Nona Gaprindashvili",
                instance_of=["Q5"],
                deceased=False,
                sitelinks=63,
            ),
        )

    pipeline.identity.resolve = _resolve  # type: ignore[method-assign]

    state = RunState(run_id="r", project_id="test")
    state.elements = [_element(None)]
    state.claims = [_claim()]

    asyncio.run(pipeline._stage_identity(state))

    assert state.elements[0].subject_alive is True
    assert state.claims[0].subject_alive is True, (
        "the element learned the subject is living but the claim did not, "
        "which is exactly what stopped claim_negative_living from matching"
    )
