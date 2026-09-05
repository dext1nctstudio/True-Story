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
  const {
    researched_exposure: researched,
    modelled_exposure: modelled,
    cost_to_cure: cure,
    statutory_anchors: anchors,
    venue,
  } = assessment;

  return (
    <section className="risk-card">
      <p className="panel-subhead">Risk exposure</p>

      <div className={`band-chip band-${bandTone(assessment.band)}`}>
        {assessment.band.replace(/_/g, " ")}
      </div>
      <p className="band-means">{assessment.band_means}</p>

      {researched && <ResearchEvidence research={researched} />}

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

      {modelled && (
        <details className="planning-model">
          <summary>Planning model — relative ranking only</summary>
          <p className="planning-range">
            {modelled.negligible
              ? "Negligible in the planning model"
              : `${formatUsd(modelled.expected_usd.low)} – ${formatUsd(modelled.expected_usd.high)}`}
          </p>
          <p className="citation-meta">
            Uncalibrated prior · {(modelled.claim_probability * 100).toFixed(1)}% modelled claim frequency
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
        </details>
      )}

      <p className="citation-meta">{venue.note}</p>
      <p className="disclaimer">{assessment.disclaimer}</p>
    </section>
  );
}

function moneyRange(value: { low: number | null; high: number | null }): string {
  if (value.low != null && value.high != null) return `${formatUsd(value.low)} – ${formatUsd(value.high)}`;
  if (value.high != null) return `Up to ${formatUsd(value.high)}`;
  if (value.low != null) return `From ${formatUsd(value.low)}`;
  return "No amount reported";
}

function ResearchEvidence({ research }: { research: NonNullable<ExposureAssessment["researched_exposure"]> }) {
  const damages = research.damages_usd;
  const defence = research.defence_cost_usd;

  return (
    <div className={`research-evidence research-${research.status}`}>
      <div className="research-evidence-head">
        <p className="panel-subhead">What public sources show</p>
        <span className="source-tag source-researched">researched</span>
      </div>

      {research.status === "range_found" && damages ? (
        <>
          <p className="research-evidence-value">{moneyRange(damages)}</p>
          <p className="research-evidence-label">
            Reported {research.outcome?.replace(/_/g, " ") ?? "claimant-payment"} range
          </p>
        </>
      ) : research.status === "defence_cost_only" ? (
        <>
          <p className="research-evidence-status">No defensible claimant-payment range found</p>
          {defence && (
            <div className="research-secondary-amount">
              <span>Defence-cost evidence</span>
              <strong>{moneyRange(defence)}</strong>
            </div>
          )}
        </>
      ) : research.status === "no_public_range" ? (
        <p className="research-evidence-status">No public damages range found — this does not mean $0</p>
      ) : (
        <p className="research-evidence-status">The research response was not usable</p>
      )}

      <p className="citation-meta">
        {research.source_kind.replace(/_/g, " ")}{research.basis ? ` · ${research.basis}` : ""}
      </p>
      {research.outlier_warning && <p className="research-warning">{research.outlier_warning}</p>}
      {research.confidence_note && <p className="disclaimer">{research.confidence_note}</p>}
      {research.sources.length > 0 && (
        <ul className="research-source-list">
          {research.sources.slice(0, 3).map((source) => (
            <li key={source.url}>
              <a href={source.url} target="_blank" rel="noreferrer">
                {source.title || new URL(source.url).hostname} ↗
              </a>
              {source.excerpt && <p>{source.excerpt}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
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
            <span className={`precedent-verified ${m.verified ? "is-verified" : ""}`}>
              {m.verified ? "source checked" : "unverified"}
            </span>
          </p>
          <p className="citation-meta">
            {[m.court, m.citation, m.docket_number && `Docket ${m.docket_number}`, m.decision_date]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <p className="citation-meta">matched on {m.matched_on.join(", ")}</p>
          <p className="precedent-outcome">{m.outcome}</p>
          {m.holding && <p className="precedent-holding"><strong>Holding at this stage:</strong> {m.holding}</p>}
          {m.quoted_passage && (
            <blockquote className="precedent-quote">
              “{m.quoted_passage}” {m.pin_cite && <cite>{m.pin_cite}</cite>}
            </blockquote>
          )}
          {m.procedural_posture && <p className="disclaimer">{m.procedural_posture}</p>}
          <p className="precedent-links">
            {m.source_url && (
              <a href={m.source_url} target="_blank" rel="noreferrer">
                Open court document ↗
              </a>
            )}
          </p>
          <p className="disclaimer">{m.caveat}</p>
        </div>
      ))}
    </section>
  );
}
