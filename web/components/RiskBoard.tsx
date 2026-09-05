"use client";

/**
 * A dedicated tab for risk exposure alone, across the whole run.
 *
 * `RiskAndPrecedent` in the evidence panel answers "what is the risk on this
 * one line" and requires clicking every flagged line to find out. This
 * answers the question a reviewer actually opens the run with: which findings
 * are worst, ranked, in one place, before reading any of them individually.
 *
 * The list is already ordered by the API -- band first, then modelled
 * exposure within a band -- so this renders it as given rather than
 * re-deriving an order the backend has already decided and tested.
 *
 * Routine findings are collapsed to a count rather than listed. A "clear with
 * conditions" background prop needs no attention here, and a board that lists
 * every clear finding beside every blocking one buries the one that matters.
 */

import { useEffect, useMemo, useState } from "react";
import { ApiError, formatUsd, getExposure } from "@/lib/api";
import type { Claim, ClearableElement, ExposureAssessment, ExposureSchedule } from "@/lib/types";

interface Props {
  runId: string;
  claims: Claim[];
  elements: ClearableElement[];
  onOpenLine: (subjectId: string) => void;
}

export function RiskBoard({ runId, claims, elements, onOpenLine }: Props) {
  const [schedule, setSchedule] = useState<ExposureSchedule | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setForbidden(false);
    getExposure(runId)
      .then((s) => !cancelled && setSchedule(s))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) setForbidden(true);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // subject_id -> what a reviewer recognises, so the board never shows a bare
  // hash. Claims and elements share the id space this looks up against.
  const labels = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of claims) map.set(c.claim_id, c.claim_text);
    for (const e of elements) map.set(e.element_id, e.display_form || e.canonical_form || e.element_type);
    return map;
  }, [claims, elements]);

  if (forbidden) {
    return (
      <div className="empty">
        Exposure is visible to production counsel and to the producer. Your role
        sees the verdict and the proposed rewrite, not a modelled cost of it.
      </div>
    );
  }

  if (loading) {
    return <div className="empty">Loading risk exposure.</div>;
  }

  if (!schedule || schedule.assessments.length === 0) {
    return <div className="empty">No findings to price yet.</div>;
  }

  const flagged = schedule.assessments.filter((a) => a.band !== "routine");
  const routineCount = schedule.assessments.length - flagged.length;

  return (
    <div className="board">
      <header className="board-head">
        <h1 className="board-title">Risk exposure</h1>
        <p className="board-sub">
          {schedule.assessments.length} findings, ranked. Modelled, not predicted -- see the
          caveat on each figure before it is repeated as a number.
        </p>
      </header>

      <div className="board-grid">
        <div className={`board-tile ${schedule.blocking > 0 ? "red" : ""}`}>
          <span className="board-tile-value">{schedule.blocking}</span>
          <span className="board-tile-label">blocking</span>
          <span className="board-tile-note">Do not shoot as written. Remedy first, then re clear.</span>
        </div>
        <div className={`board-tile ${schedule.counsel_required > 0 ? "amber" : ""}`}>
          <span className="board-tile-value">{schedule.counsel_required}</span>
          <span className="board-tile-label">counsel required</span>
          <span className="board-tile-note">A qualified attorney decides these before they are shot.</span>
        </div>
        <div className="board-tile">
          <span className="board-tile-value wide">
            {formatUsd(schedule.modelled_exposure_usd.low)}–{formatUsd(schedule.modelled_exposure_usd.high)}
          </span>
          <span className="board-tile-label">modelled exposure</span>
          <span className="board-tile-note">
            Sum of expected values across {schedule.modelled_exposure_usd.findings} findings. Not a
            worst case, and uncalibrated: rank by it, do not budget a reserve against it.
          </span>
        </div>
        <div className="board-tile">
          <span className="board-tile-value wide">
            {formatUsd(schedule.cost_to_cure_usd.low)}–{formatUsd(schedule.cost_to_cure_usd.high)}
          </span>
          <span className="board-tile-label">cost to cure</span>
          <span className="board-tile-note">
            {schedule.cost_to_cure_usd.priced_findings} findings priced at the {schedule.stage.replace(/_/g, " ")}{" "}
            stage.{" "}
            {schedule.cost_to_cure_usd.researched_findings
              ? `${schedule.cost_to_cure_usd.researched_findings} from a real market rate.`
              : "All from the policy table; none researched yet."}
          </span>
        </div>
      </div>

      <div className="risk-list">
        {flagged.map((a) => (
          <RiskRow key={a.subject_id} assessment={a} label={labels.get(a.subject_id)} onOpen={onOpenLine} />
        ))}
        {routineCount > 0 && (
          <p className="citation-meta risk-routine-note">
            {routineCount} routine finding{routineCount === 1 ? "" : "s"} not shown. Clear, or clear
            with conditions that are art department notes rather than a legal problem.
          </p>
        )}
      </div>
    </div>
  );
}

function bandTone(band: string): string {
  if (band === "blocking") return "red";
  if (band === "counsel_required" || band === "negotiable") return "amber";
  return "grey";
}

function RiskRow({
  assessment,
  label,
  onOpen,
}: {
  assessment: ExposureAssessment;
  label?: string;
  onOpen: (subjectId: string) => void;
}) {
  const modelled = assessment.modelled_exposure;
  const text = (label ?? assessment.subject_id).trim();
  const short = text.length > 90 ? `${text.slice(0, 90)}…` : text;

  return (
    <button
      className={`risk-row risk-row-${bandTone(assessment.band)}`}
      onClick={() => onOpen(assessment.subject_id)}
    >
      <div className="risk-row-main">
        <span className={`band-chip band-${bandTone(assessment.band)}`}>
          {assessment.band.replace(/_/g, " ")}
        </span>
        <span className="risk-row-text">{short}</span>
      </div>
      <div className="risk-row-figure">
        {modelled && !modelled.negligible
          ? `${formatUsd(modelled.expected_usd.low)}–${formatUsd(modelled.expected_usd.high)}`
          : assessment.cost_to_cure
            ? `cure ${formatUsd(assessment.cost_to_cure.low_usd)}–${formatUsd(assessment.cost_to_cure.high_usd)}`
            : "—"}
      </div>
    </button>
  );
}
