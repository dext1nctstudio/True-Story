"""Roles, masking and audit.

The brief name checks the studio head enforcing IAM governance across multi
agent workflows, so this is shown rather than asserted. Four custom roles, each
mapping to a Firestore security rule and to a different shape of the same page:

    truestory.counsel      everything, including unmasked identities and full
                           evidence. The accountable human.
    truestory.producer     verdict counts, risk posture, cost, alerts. Manages
                           the production, does not read the evidence.
    truestory.writer       their own draft's overlay and rewrites. No cross
                           project access at all.
    truestory.underwriter  the final package, read only and watermarked. An
                           external party outside the trust boundary.

The role switch is four seconds of the demo and it is instantly legible: the
writer's view with the evidence panel simply absent says more about governance
than any architecture slide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from truestory.models.enums import Role
from truestory.storage import get_store

log = logging.getLogger("truestory.api.security")


@dataclass(frozen=True, slots=True)
class Principal:
    """The acting identity. Every audit record names one."""

    subject: str  # email or service account
    role: Role
    project_ids: tuple[str, ...] = ()

    @property
    def is_counsel(self) -> bool:
        return self.role is Role.COUNSEL

    def may_access_project(self, project_id: str) -> bool:
        # Counsel is scoped to the projects they are assigned, not to all of
        # them. There is no global override role in this system by design.
        return project_id in self.project_ids

    def may_unmask(self) -> bool:
        return self.role is Role.COUNSEL

    def may_see_evidence(self) -> bool:
        return self.role in (Role.COUNSEL, Role.UNDERWRITER)

    def may_see_cost(self) -> bool:
        return self.role in (Role.COUNSEL, Role.PRODUCER)

    def may_override(self) -> bool:
        return self.role is Role.COUNSEL

    def may_apply_remedy(self) -> bool:
        return self.role in (Role.COUNSEL, Role.WRITER)


#: What each role receives from the same underlying run document.
VIEW_MATRIX: dict[Role, dict[str, bool]] = {
    Role.COUNSEL: {
        "overlay": True,
        "evidence": True,
        "unmasked": True,
        "cost": True,
        "review_queue": True,
        "reports": True,
        "monitors": True,
        "override": True,
    },
    Role.PRODUCER: {
        "overlay": True,
        "evidence": False,
        "unmasked": False,
        "cost": True,
        "review_queue": True,
        "reports": True,
        "monitors": True,
        "override": False,
    },
    Role.WRITER: {
        "overlay": True,
        "evidence": False,
        "unmasked": False,
        "cost": False,
        "review_queue": False,
        "reports": False,
        "monitors": False,
        "override": False,
    },
    Role.UNDERWRITER: {
        "overlay": False,
        "evidence": True,
        "unmasked": False,
        "cost": False,
        "review_queue": False,
        "reports": True,
        "monitors": True,
        "override": False,
    },
}


def can(principal: Principal, capability: str) -> bool:
    return VIEW_MATRIX.get(principal.role, {}).get(capability, False)


# =============================================================================
# masking
# =============================================================================


def apply_view(payload: dict[str, Any], principal: Principal) -> dict[str, Any]:
    """Shape a response for the caller's role.

    Filtering happens on the way out rather than at the query, so there is one
    canonical run document and one place where a role decides what it sees.
    """
    view = VIEW_MATRIX.get(principal.role, {})
    shaped = dict(payload)

    if not view.get("evidence", False):
        shaped.pop("evidence", None)
        shaped.pop("evidence_appendix", None)
        for claim in shaped.get("claims", []) or []:
            claim.pop("evidence", None)
        for element in shaped.get("elements", []) or []:
            element.pop("evidence", None)

    if not view.get("cost", False):
        shaped.pop("cost_cents", None)
        shaped.pop("cost_usd", None)
        shaped.pop("budget", None)

    if not view.get("review_queue", False):
        shaped.pop("review_queue", None)
        shaped.pop("counsel_queue", None)

    if not view.get("monitors", False):
        shaped.pop("monitors", None)
        shaped.pop("monitor_manifest", None)

    if not view.get("unmasked", False):
        shaped = _enforce_masking(shaped)

    return shaped


def _enforce_masking(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip identifying detail from anything flagged masked.

    Principle P6. This system's output is assertions about real people, so a
    living private individual is summarised and never named until counsel says
    otherwise. The count and the source count still show, because "three
    matching individuals, four sources, withheld pending counsel review" is
    itself the useful signal.
    """
    for element in payload.get("elements", []) or []:
        if element.get("masked"):
            element["canonical_form"] = None
            element["aliases"] = []
            for evidence in element.get("evidence", []) or []:
                evidence["finding"] = {"withheld": True}
            # The identity block names the real people a name resolves to,
            # with links to their entries. That is precisely what masking
            # exists to withhold, so it goes with the rest of it: the counts
            # stay, because "three matching individuals" is the useful signal,
            # and the names do not.
            identity = element.get("identity")
            if identity:
                element["identity"] = {
                    "name": None,
                    "status": identity.get("status"),
                    "reason": identity.get("reason"),
                    "canonical": None,
                    "candidates": [],
                    "withheld": True,
                }

    for entry in (
        payload.get("elements_by_status", {}).values()
        if isinstance(payload.get("elements_by_status"), dict)
        else []
    ):
        for item in entry:
            if item.get("masked"):
                item["element"] = _masked_label(item)

    return payload


def _masked_label(item: dict[str, Any]) -> str:
    matches = item.get("match_count", item.get("citations", 0))
    return f"{matches} matching individuals · withheld pending counsel review"


# =============================================================================
# audited actions
# =============================================================================


def unmask(principal: Principal, project_id: str, element_id: str, reason: str) -> bool:
    """Reveal a masked identity. Gated on role, and always audited.

    Unmasking is the single most sensitive action in the product, because the
    thing being revealed is the identity of a private individual who has done
    nothing except resemble a character. It requires counsel, it requires a
    stated reason, and it leaves a permanent record naming who did it.
    """
    if not principal.may_unmask():
        log.warning(
            "unmask denied for %s (role %s) on %s", principal.subject, principal.role, element_id
        )
        return False

    get_store().audit(
        action="unmask_identity",
        principal=principal.subject,
        subject_id=element_id,
        detail={"project_id": project_id, "reason": reason, "role": str(principal.role)},
    )
    return True


def record_override(
    principal: Principal, subject_id: str, previous: str, new: str, reason: str
) -> bool:
    """A human overriding a machine verdict. Permitted, and permanently recorded."""
    if not principal.may_override():
        return False

    get_store().audit(
        action="override_verdict",
        principal=principal.subject,
        subject_id=subject_id,
        detail={"from": previous, "to": new, "reason": reason},
    )
    return True


def record_remedy_applied(principal: Principal, claim_id: str, remedy_id: str) -> None:
    get_store().audit(
        action="apply_remedy",
        principal=principal.subject,
        subject_id=claim_id,
        detail={"remedy_id": remedy_id, "role": str(principal.role)},
    )


# =============================================================================
# firestore security rules
# =============================================================================
# Shipped as a real artifact because per project isolation enforced only in
# application code is one deploy away from being bypassed. Terraform writes
# this file to the project.

FIRESTORE_RULES = """\
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function role() {
      return request.auth.token.get('truestory_role', '');
    }
    function assignedProjects() {
      return request.auth.token.get('truestory_projects', []);
    }
    function memberOf(projectId) {
      return request.auth != null && projectId in assignedProjects();
    }

    // Per project isolation. Nothing crosses a project boundary, whatever the
    // application tier believes.
    match /projects/{projectId} {
      allow read: if memberOf(projectId);
      allow write: if memberOf(projectId) && role() in ['truestory.counsel', 'truestory.producer'];

      match /runs/{runId} {
        allow read: if memberOf(projectId);
        allow write: if false;   // only the pipeline service account writes runs

        // Evidence is counsel and underwriter only. A writer sees verdicts,
        // never the research behind them.
        match /evidence/{evidenceId} {
          allow read: if memberOf(projectId)
                      && role() in ['truestory.counsel', 'truestory.underwriter'];
          allow write: if false;
        }

        match /{subcollection}/{docId} {
          allow read: if memberOf(projectId);
          allow write: if false;
        }
      }

      match /monitors/{monitorId} {
        allow read: if memberOf(projectId)
                    && role() in ['truestory.counsel', 'truestory.producer', 'truestory.underwriter'];
        allow write: if false;
      }
    }

    // The review queue is the human workflow. Counsel and producers see it.
    match /review_queue/{itemId} {
      allow read: if request.auth != null
                  && role() in ['truestory.counsel', 'truestory.producer'];
      allow update: if request.auth != null && role() == 'truestory.counsel';
      allow create, delete: if false;
    }

    // Audit records are append only from the server. Nobody edits them.
    match /audit/{recordId} {
      allow read: if request.auth != null && role() == 'truestory.counsel';
      allow write: if false;
    }
  }
}
"""


def dev_principal(role: Role = Role.COUNSEL, project_id: str = "demo") -> Principal:
    """Local development identity. Never constructed in a deployed environment."""
    return Principal(subject="dev@localhost", role=role, project_ids=(project_id,))
