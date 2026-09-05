"use client";

/**
 * The counsel queue, shown when no single line is selected.
 *
 * The header counts "9 counsel" but until now nothing in the product listed
 * what those nine items actually were, and clearance elements, the names,
 * locations, songs and events that carry rights rather than facts, had no
 * view at all. This is that list: every item a human has to look at, with the
 * reason it was escalated, so the panel's resting state is the work queue
 * rather than an instruction to go clicking.
 *
 * Ranked, not just listed. Every item here carries an exposure band now, and
 * a flat list in extraction order buries the one blocking finding among
 * eight routine counsel items just as badly as no list did. When `runId` is
 * supplied the queue fetches the same schedule the Risk tab reads and sorts
 * by it -- worst first, same order the board already uses -- so opening
 * "Needs counsel" and opening "Risk" agree with each other rather than
 * presenting two different rankings of the same nine items.
 */

import { useEffect, useState } from "react";
import { getExposure } from "@/lib/api";
import type { Claim, ClearableElement, ExposureAssessment, ExposureBand } from "@/lib/types";

interface Props {
  claims: Claim[];
  elements: ClearableElement[];
  onSelectClaim?: (claimId: string) => void;
  /** Enables risk ranked ordering and the band chip on each row. Omit it and
   *  the queue still works, just unranked, exactly as it did before this. */
  runId?: string;
}

const BAND_RANK: Record<ExposureBand, number> = {
  blocking: 4,
  counsel_required: 3,
  negotiable: 2,
  routine: 1,
};

export function ReviewQueue({ claims, elements, onSelectClaim, runId }: Props) {
  const [bySubject, setBySubject] = useState<Map<string, ExposureAssessment> | null>(null);

  useEffect(() => {
    if (!runId) {
      setBySubject(null);
      return;
    }
    let cancelled = false;
    getExposure(runId)
      .then((schedule) => {
        if (cancelled) return;
        setBySubject(new Map(schedule.assessments.map((a) => [a.subject_id, a])));
      })
      .catch(() => {
        // A role without cost visibility, or a run this endpoint cannot
        // reach. The queue still works, just in extraction order.
        if (!cancelled) setBySubject(null);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const rank = (subjectId: string): number => {
    const a = bySubject?.get(subjectId);
    if (!a) return 0;
    // Band first, then the modelled figure within a band -- the same two
    // level order the Risk tab's own ranking already uses, so the two views
    // never disagree about which finding is worse.
    const fine = a.modelled_exposure && !a.modelled_exposure.negligible
      ? a.modelled_exposure.expected_usd.high
      : 0;
    return BAND_RANK[a.band] * 1e12 + fine;
  };

  const flaggedClaims = [...claims.filter((c) => c.needs_counsel)].sort(
    (a, b) => rank(b.claim_id) - rank(a.claim_id),
  );
  // An element that failed research is as much a counsel item as one the
  // rubric escalated: nobody has cleared it either way.
  const flaggedElements = [
    ...elements.filter(
      (e) => e.needs_counsel || e.status === "RESEARCH_FAILED" || e.status === "NEEDS_COUNSEL",
    ),
  ].sort((a, b) => rank(b.element_id) - rank(a.element_id));
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
      <p className="panel-title">
        Needs counsel <span className="queue-count">{total}</span>
      </p>

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
                  <BandChip assessment={bySubject?.get(claim.claim_id)} />
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
              <li
                key={element.element_id}
                className={`queue-item ${onSelectClaim ? "clickable" : ""}`}
                onClick={() => onSelectClaim?.(element.element_id)}
                role={onSelectClaim ? "button" : undefined}
                tabIndex={onSelectClaim ? 0 : undefined}
              >
                <div className="queue-item-head">
                  <span className="element-type">{formatType(element.element_type)}</span>
                  <span className={`element-status ${statusTone(element.status)}`}>
                    {formatStatus(element.status)}
                  </span>
                  <BandChip assessment={bySubject?.get(element.element_id)} />
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

function bandTone(band: string): string {
  if (band === "blocking") return "red";
  if (band === "counsel_required" || band === "negotiable") return "amber";
  return "grey";
}

/** Absent when exposure could not be fetched, so the row degrades to
 *  whatever it showed before rather than an empty chip claiming a band. */
function BandChip({ assessment }: { assessment: ExposureAssessment | undefined }) {
  if (!assessment) return null;
  return (
    <span className={`band-chip band-chip-inline band-${bandTone(assessment.band)}`}>
      {assessment.band.replace(/_/g, " ")}
    </span>
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
