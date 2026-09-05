"use client";

/**
 * Risk exposure and similar cases, for whichever line is selected.
 *
 * These were built into the pipeline and never reached the UI: the API
 * response for a run carried only a bare count of matched precedents and
 * nothing of the exposure model at all, so a producer looking at a red line
 * had no way to see either. `/v1/runs/{id}/exposure` and `/v1/runs/{id}/
 * precedents` exist so this component has something to fetch.
 *
 * Fetched once per run rather than once per selection -- both endpoints
 * return every finding, and re-fetching the whole run's exposure schedule
 * every time a different line is clicked would be forty requests to answer
 * one question the first request already contained.
 */

import { useEffect, useState } from "react";
import { ApiError, formatUsd, getExposure, getPrecedents } from "@/lib/api";
import type { ExposureAssessment, ExposureSchedule, PrecedentMatch, PrecedentsBySubject } from "@/lib/types";

interface Props {
  runId: string;
  /** claim_id or element_id of the line currently selected. */
  subjectId: string;
}

export function RiskAndPrecedent({ runId, subjectId }: Props) {
  const [schedule, setSchedule] = useState<ExposureSchedule | null>(null);
  const [exposureForbidden, setExposureForbidden] = useState(false);
  const [precedents, setPrecedents] = useState<PrecedentsBySubject | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setExposureForbidden(false);

    Promise.allSettled([getExposure(runId), getPrecedents(runId)]).then(([exp, prec]) => {
      if (cancelled) return;
      if (exp.status === "fulfilled") {
        setSchedule(exp.value);
      } else if (exp.reason instanceof ApiError && exp.reason.status === 403) {
        // The governance model working, not a failure. This role does not
        // see cost, and a modelled lawsuit exposure is a cost figure.
        setExposureForbidden(true);
      }
      if (prec.status === "fulfilled") setPrecedents(prec.value.precedents);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  const assessment: ExposureAssessment | undefined = schedule?.assessments.find(
    (a) => a.subject_id === subjectId,
  );
  const matches: PrecedentMatch[] = precedents?.[subjectId] ?? [];

  if (loading) {
    return <div className="risk-precedent loading">Loading risk and precedent…</div>;
  }

  if (!assessment && matches.length === 0 && exposureForbidden) {
    return null; // nothing this role can see and nothing to show either way
  }

  if (!assessment && matches.length === 0) {
    return null; // e.g. a routine, already clear finding: nothing to price or match
  }

  return (
    <div className="risk-precedent">
      {assessment && !exposureForbidden && <ExposureCard assessment={assessment} />}
      {matches.length > 0 && <PrecedentList matches={matches} />}
    </div>
  );
}

function bandTone(band: string): string {
  switch (band) {
    case "blocking":
      return "red";
    case "counsel_required":
      return "amber";
    case "negotiable":
      return "amber";
    default:
      return "grey";
  }
}

function ExposureCard({ assessment }: { assessment: ExposureAssessment }) {
  const { modelled_exposure: modelled, cost_to_cure: cure, statutory_anchors: anchors, venue } = assessment;

  return (
    <section className="risk-card">
      <p className="panel-subhead">Risk exposure</p>

      <div className={`band-chip band-${bandTone(assessment.band)}`}>
        {assessment.band.replace(/_/g, " ")}
      </div>
      <p className="band-means">{assessment.band_means}</p>

      {modelled && (
        <div className="modelled-exposure">
          <p className="modelled-range">
            {modelled.negligible
              ? "Negligible modelled exposure"
              : `${formatUsd(modelled.expected_usd.low)} – ${formatUsd(modelled.expected_usd.high)}`}
          </p>
          <p className="citation-meta">
            claim probability {(modelled.claim_probability * 100).toFixed(1)}%, uncalibrated
          </p>
          {modelled.drivers.length > 0 && (
            <ul className="driver-list">
              {modelled.drivers.map((d) => (
                <li key={d.id}>
                  ×{d.value} {d.id.replace(/_/g, " ")} — {d.because}
                </li>
              ))}
            </ul>
          )}
          <p className="disclaimer">{modelled.caveat}</p>
        </div>
      )}

      {cure && (
        <div className="cost-to-cure">
          <p className="panel-subhead">Cost to cure</p>
          <p>
            {formatUsd(cure.low_usd)} – {formatUsd(cure.high_usd)}{" "}
            <span className={`source-tag source-${cure.source}`}>
              {cure.source === "researched" ? "researched" : "policy table"}
            </span>
          </p>
          <p className="citation-meta">{cure.basis}</p>
          {cure.rate_research?.sources?.length ? (
            <p className="citation-meta">
              source:{" "}
              <a href={cure.rate_research.sources[0]} target="_blank" rel="noreferrer">
                {cure.rate_research.sources[0]}
              </a>
            </p>
          ) : null}
        </div>
      )}

      {anchors.length > 0 && (
        <div className="statutory-anchors">
          <p className="panel-subhead">Statutory anchors</p>
          {anchors.map((a) => (
            <div key={a.id} className="anchor-row">
              <p className="anchor-provision">{a.provision}</p>
              <p className="citation-meta">
                {a.floor_usd != null && `floor ${formatUsd(a.floor_usd)}`}
                {a.ceiling_usd != null && ` · ceiling ${formatUsd(a.ceiling_usd)}`}
                {a.willful_ceiling_usd != null && ` · willful ${formatUsd(a.willful_ceiling_usd)}`}
                {!a.verified && " · unverified, confirm before citing"}
              </p>
            </div>
          ))}
        </div>
      )}

      <p className="citation-meta">{venue.note}</p>
      <p className="disclaimer">{assessment.disclaimer}</p>
    </section>
  );
}

function PrecedentList({ matches }: { matches: PrecedentMatch[] }) {
  return (
    <section className="precedent-card">
      <p className="panel-subhead">Similar cases</p>
      {matches.map((m) => (
        <div key={m.case_id} className={`precedent-row side-${m.side}`}>
          <p className="precedent-name">
            {m.name} <span className={`side-tag side-${m.side}`}>{m.side}</span>
          </p>
          <p className="citation-meta">matched on {m.matched_on.join(", ")}</p>
          <p className="precedent-outcome">{m.outcome}</p>
          {!m.verified && <p className="disclaimer">{m.caveat}</p>}
        </div>
      ))}
    </section>
  );
}
