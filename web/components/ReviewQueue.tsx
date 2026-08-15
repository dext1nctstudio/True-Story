"use client";

/**
 * The counsel queue, shown when no single line is selected.
 *
 * The header counts "9 counsel" but until now nothing in the product listed
 * what those nine items actually were, and clearance elements — the names,
 * locations, songs and events that carry rights rather than facts — had no
 * view at all. This is that list: every item a human has to look at, with the
 * reason it was escalated, so the panel's resting state is the work queue
 * rather than an instruction to go clicking.
 */

import type { Claim, ClearableElement } from "@/lib/types";

interface Props {
  claims: Claim[];
  elements: ClearableElement[];
  onSelectClaim?: (claimId: string) => void;
}

export function ReviewQueue({ claims, elements, onSelectClaim }: Props) {
  const flaggedClaims = claims.filter((c) => c.needs_counsel);
  // An element that failed research is as much a counsel item as one the
  // rubric escalated: nobody has cleared it either way.
  const flaggedElements = elements.filter(
    (e) => e.needs_counsel || e.status === "RESEARCH_FAILED" || e.status === "NEEDS_COUNSEL",
  );
  const total = flaggedClaims.length + flaggedElements.length;

  if (total === 0) {
    return (
      <div className="empty">
        Nothing is waiting on counsel. Select any highlighted line to read the
        claim, the verdict and the sources behind it.
      </div>
    );
  }

  return (
    <div className="panel">
      <p className="panel-title">needs counsel · {total}</p>

      {flaggedClaims.length > 0 && (
        <div className="queue-group">
          <p className="queue-group-title">Claims</p>
          <ul className="queue-list">
            {flaggedClaims.map((claim, index) => (
              <li
                key={`${claim.claim_id}:${index}`}
                className={`queue-item ${claim.color ?? "grey"} ${onSelectClaim ? "clickable" : ""}`}
                onClick={() => onSelectClaim?.(claim.claim_id)}
                role={onSelectClaim ? "button" : undefined}
                tabIndex={onSelectClaim ? 0 : undefined}
              >
                <div className="queue-item-head">
                  <span className={`verdict-pill ${claim.color ?? "grey"}`}>{claim.verdict}</span>
                  {claim.subject_name && (
                    <span className="queue-item-subject">{claim.subject_name}</span>
                  )}
                </div>
                <p className="queue-item-text">{claim.claim_text}</p>
                {claim.counsel_reason && (
                  <p className="queue-item-why">{claim.counsel_reason}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {flaggedElements.length > 0 && (
        <div className="queue-group">
          <p className="queue-group-title">Clearance elements</p>
          <ul className="queue-list">
            {flaggedElements.map((element) => (
              <li key={element.element_id} className="queue-item">
                <div className="queue-item-head">
                  <span className="element-type">{formatType(element.element_type)}</span>
                  <span className={`element-status ${statusTone(element.status)}`}>
                    {formatStatus(element.status)}
                  </span>
                </div>
                <p className="queue-item-text">
                  {element.display_form || element.canonical_form || element.element_id}
                </p>
                {element.counsel_reason && (
                  <p className="queue-item-why">{element.counsel_reason}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function formatType(type: string | undefined): string {
  return (type ?? "element").toLowerCase().replace(/_/g, " ");
}

function formatStatus(status: string | undefined): string {
  return (status ?? "").toLowerCase().replace(/_/g, " ");
}

function statusTone(status: string | undefined): string {
  if (status === "CLEARED") return "green";
  if (status === "NOT_CLEAR") return "red";
  return "amber";
}
