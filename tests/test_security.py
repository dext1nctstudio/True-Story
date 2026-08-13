"""Governance, masking and webhook verification.

The privacy tests matter more than they look. This system's output is
assertions about real people, and built carelessly it becomes a defamation
engine pointed at exactly the people it exists to protect.
"""

from __future__ import annotations

import json
import time

import pytest

from truestory.api.security import VIEW_MATRIX, Principal, apply_view, can
from truestory.models.elements import ClearableElement
from truestory.models.enums import ElementType, PublicFigureStatus, Role
from truestory.webhooks.signature import SignatureError, compute, sign_outbound, verify


# =============================================================================
# roles
# =============================================================================


def test_only_counsel_may_unmask():
    """The most sensitive action in the product. The thing being revealed is
    the identity of a private individual who resembled a character."""
    for role in Role:
        principal = Principal("user@example.com", role, ("demo",))
        assert principal.may_unmask() is (role is Role.COUNSEL)


def test_writer_cannot_see_evidence():
    """Four seconds of the demo: the evidence panel is simply absent."""
    writer = Principal("writer@example.com", Role.WRITER, ("demo",))
    assert not can(writer, "evidence")
    assert not can(writer, "cost")
    assert not can(writer, "review_queue")
    assert can(writer, "overlay")


def test_underwriter_sees_evidence_but_not_cost():
    """An external party receives the package, not the production's spend."""
    underwriter = Principal("uw@carrier.com", Role.UNDERWRITER, ("demo",))
    assert can(underwriter, "evidence")
    assert can(underwriter, "reports")
    assert not can(underwriter, "cost")
    assert not can(underwriter, "unmasked")


def test_producer_sees_posture_not_evidence():
    producer = Principal("producer@example.com", Role.PRODUCER, ("demo",))
    assert can(producer, "cost")
    assert can(producer, "review_queue")
    assert not can(producer, "evidence")


def test_project_isolation_has_no_global_override():
    """There is no role that sees every project. Counsel is scoped too."""
    counsel = Principal("counsel@example.com", Role.COUNSEL, ("project-a",))
    assert counsel.may_access_project("project-a")
    assert not counsel.may_access_project("project-b")


def test_every_role_has_a_view_definition():
    for role in Role:
        assert role in VIEW_MATRIX, f"role {role} has no view definition"


# =============================================================================
# masking
# =============================================================================


def test_masked_element_never_exposes_its_name():
    element = ClearableElement(
        element_id="el_masked",
        element_type=ElementType.PERSON_NAME_FICTIONAL,
        canonical_form="Jane Smith",
        masked=True,
    )
    display = element.display_form()
    assert "Jane Smith" not in display
    assert "withheld pending counsel review" in display


def test_masked_element_still_reports_useful_counts():
    """"Three matching individuals, four sources, withheld" is itself the
    signal. Masking must not reduce to silence."""
    element = ClearableElement(
        element_id="el_masked",
        element_type=ElementType.PERSON_NAME_FICTIONAL,
        canonical_form="Jane Smith",
        masked=True,
    )
    assert "matching individuals" in element.display_form()


def test_serialisation_withholds_the_name_unless_unmasked():
    element = ClearableElement(
        element_id="el_masked",
        element_type=ElementType.PERSON_NAME_FICTIONAL,
        canonical_form="Jane Smith",
        aliases=["J. Smith"],
        masked=True,
    )

    masked = element.to_dict(unmasked=False)
    assert masked["canonical_form"] is None
    assert masked["aliases"] == []

    unmasked = element.to_dict(unmasked=True)
    assert unmasked["canonical_form"] == "Jane Smith"


def test_apply_view_strips_evidence_for_roles_that_may_not_see_it():
    payload = {
        "claims": [{"claim_id": "c1", "evidence": [{"evidence_id": "e1"}]}],
        "cost_usd": 2.31,
        "review_queue": [{"item": 1}],
    }
    writer = Principal("writer@example.com", Role.WRITER, ("demo",))
    shaped = apply_view(payload, writer)

    assert "evidence" not in shaped["claims"][0]
    assert "cost_usd" not in shaped
    assert "review_queue" not in shaped


def test_apply_view_leaves_counsel_untouched():
    payload = {
        "claims": [{"claim_id": "c1", "evidence": [{"evidence_id": "e1"}]}],
        "cost_usd": 2.31,
    }
    counsel = Principal("counsel@example.com", Role.COUNSEL, ("demo",))
    shaped = apply_view(payload, counsel)

    assert shaped["claims"][0]["evidence"]
    assert shaped["cost_usd"] == 2.31


def test_private_living_individuals_are_masked_by_adjudication():
    from truestory.agents.adjudicator import Adjudicator

    element = ClearableElement(
        element_id="el_x",
        element_type=ElementType.REAL_PERSON_DEPICTED,
        canonical_form="A Private Person",
        subject_alive=True,
        public_figure_status=PublicFigureStatus.PRIVATE,
    )
    Adjudicator()._apply_masking(element)
    assert element.masked


def test_public_figures_are_not_masked():
    from truestory.agents.adjudicator import Adjudicator

    element = ClearableElement(
        element_id="el_y",
        element_type=ElementType.REAL_PERSON_DEPICTED,
        canonical_form="A Public Figure",
        subject_alive=True,
        public_figure_status=PublicFigureStatus.PUBLIC,
    )
    Adjudicator()._apply_masking(element)
    assert not element.masked


# =============================================================================
# webhook signatures
# =============================================================================


def test_valid_signature_verifies():
    body = json.dumps({"type": "monitor.event"}).encode()
    headers = sign_outbound("shared-secret", body)

    assert verify(
        "shared-secret",
        headers["x-truestory-signature"],
        headers["x-truestory-timestamp"],
        body,
    )


def test_tampered_body_is_rejected():
    """The callbacks carry findings that become verdicts about real people."""
    body = json.dumps({"type": "monitor.event"}).encode()
    headers = sign_outbound("shared-secret", body)

    with pytest.raises(SignatureError, match="mismatch"):
        verify(
            "shared-secret",
            headers["x-truestory-signature"],
            headers["x-truestory-timestamp"],
            b'{"type": "tampered"}',
        )


def test_wrong_secret_is_rejected():
    body = b"{}"
    headers = sign_outbound("shared-secret", body)

    with pytest.raises(SignatureError):
        verify("other-secret", headers["x-truestory-signature"], headers["x-truestory-timestamp"], body)


def test_replayed_request_is_rejected():
    """A captured valid request must not work an hour later."""
    body = b"{}"
    stale = str(int(time.time()) - 4000)
    signature = f"sha256={compute('shared-secret', stale, body)}"

    with pytest.raises(SignatureError, match="replay window"):
        verify("shared-secret", signature, stale, body)


def test_missing_secret_refuses_rather_than_accepting():
    """An unauthenticated callback endpoint lets a stranger write findings into
    a legal deliverable. Refusing is the only safe default."""
    with pytest.raises(SignatureError, match="no webhook signing secret"):
        verify("", "sha256=abc", str(int(time.time())), b"{}")


def test_missing_headers_are_rejected():
    with pytest.raises(SignatureError, match="missing"):
        verify("shared-secret", "", "", b"{}")


def test_secret_redaction_never_leaks_the_value():
    from truestory.storage.secrets import redact

    secret = "sk-live-abcdef1234567890"
    redacted = redact(secret)
    assert "abcdef1234567890" not in redacted
    assert redacted.startswith("sk-l")
    assert redact("") == "(empty)"
