"use client";

/**
 * The producer's workspace: exposure, money, and who is waiting on whom.
 *
 * Deliberately not the counsel view with the evidence removed. A producer is
 * not a lawyer with fewer permissions, they are answering different questions:
 * how much of this script is a problem, which people are the problem, what has
 * it cost, and how much of counsel's week does it represent. So the surface is
 * built from those questions rather than filtered down from someone else's.
 *
 * The research itself is absent by design and the panel says so, because an
 * empty space where evidence used to be reads as a bug rather than as a rule.
 */

import { useMemo } from "react";
import { CostPanel } from "@/components/CostPanel";
import { formatUsd, pageRef } from "@/lib/api";
import type { Claim, ClearableElement, PersonRollup, RunSummary } from "@/lib/types";

interface Props {
  runId: string;
  /** Whether the run is still moving. Drives whether cost keeps re reading. */
  live?: boolean;
  summary: RunSummary | null;
  claims: Claim[];
  elements: ClearableElement[];
  persons: PersonRollup[];
  onOpenLine: (claimId: string) => void;
}

export function ProducerBoard({
  summary,
  runId,
  live = false,
  claims,
  elements,
  persons,
  onOpenLine,
}: Props) {
  const exposure = useMemo(() => {
    const red = claims.filter((c) => c.color === "red");
    const amber = claims.filter((c) => c.color === "amber");
    const counsel = claims.filter((c) => c.needs_counsel).length
      + elements.filter((e) => e.needs_counsel).length;
    const licences = elements.filter(
      (e) => e.status === "NEEDS_LICENSE" || e.status === "CLEAR_WITH_CONDITIONS",
    );
    const blocked = elements.filter((e) => e.status === "NOT_CLEAR");
    return { red, amber, counsel, licences, blocked };
  }, [claims, elements]);

  // Where the risk sits in the running order. A producer schedules by page, so
  // exposure is worth showing the same way.
  const heat = useMemo(() => {
    // Bucketed by whole page. A span's page is a float derived from its line
    // offset, so keying on it directly produced a column per line and a row of
    // axis labels reading 1.29, 1.35, 1.46.
    const byPage = new Map<number, { red: number; amber: number }>();
    for (const claim of claims) {
      const raw = claim.occurrences[0]?.page;
      if (!raw) continue;
      const page = Math.max(1, Math.floor(raw));
      const row = byPage.get(page) ?? { red: 0, amber: 0 };
      if (claim.color === "red") row.red += 1;
      else if (claim.color === "amber") row.amber += 1;
      byPage.set(page, row);
    }
    const rows = [...byPage.entries()].sort((a, b) => a[0] - b[0]);
    const peak = Math.max(1, ...rows.map(([, r]) => r.red + r.amber));
    return { rows, peak };
  }, [claims]);

  const flagged = persons.filter((p) => p.exceeds_amber_threshold);

  return (
    <div className="board">
      <header className="board-head">
        <h1 className="board-title">Production risk</h1>
        <p className="board-sub">
          {summary?.script_title ?? "This draft"} · what is exposed, what it cost, and who
          is waiting on counsel.
        </p>
      </header>

      <div className="board-grid">
        <Tile
          value={exposure.red.length}
          label="contradicted lines"
          tone={exposure.red.length > 0 ? "red" : ""}
          note="The record says otherwise. These are the lines that get filed on."
        />
        <Tile
          value={exposure.amber.length}
          label="unsupported lines"
          tone={exposure.amber.length > 0 ? "amber" : ""}
          note="Not provably false, and therefore not defensible either. This is the category that settles."
        />
        <Tile
          value={exposure.counsel}
          label="items awaiting counsel"
          note="Every one is a decision the system declined to make on its own."
        />
        <Tile
          value={exposure.licences.length}
          label="licences to clear"
          note="Music, artwork and marks that are usable only on terms."
        />
      </div>

      {flagged.length > 0 && (
        <section className="board-section">
          <h2 className="board-section-title">People carrying density</h2>
          <p className="board-section-sub">
            Not one false line, but a pattern of unsupported conduct about one named
            living person. That pattern is what the When They See Us claim was built on,
            so the person is escalated rather than the line.
          </p>
          <div className="board-people">
            {flagged.map((person) => (
              <div className="board-person" key={person.element_id}>
                <div className="board-person-head">
                  <span className="board-person-name">{person.person_name}</span>
                  <span className="board-person-density">
                    {Math.round(person.amber_density * 100)}% unsupported
                  </span>
                </div>
                <div className="density-track">
                  <div
                    className="density-fill over"
                    style={{ width: `${Math.min(1, person.amber_density) * 100}%` }}
                  />
                  <div
                    className="density-threshold"
                    style={{ left: `${(person.amber_threshold ?? 0.3) * 100}%` }}
                  />
                </div>
                <span className="board-person-meta">
                  {person.amber_count} of {person.total_claims} claims · {person.counsel_items}{" "}
                  with counsel
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {exposure.red.length > 0 && (
        <section className="board-section">
          <h2 className="board-section-title">Contradicted lines</h2>
          <div className="queue-list">
            {exposure.red.map((claim) => (
              <button
                key={claim.claim_id}
                className="queue-item red clickable"
                onClick={() => onOpenLine(claim.claim_id)}
              >
                <div className="queue-item-head">
                  <span className="queue-item-subject">{claim.subject_name}</span>
                  <span className="queue-count">
                    p {pageRef(claim.occurrences[0])}
                  </span>
                </div>
                <div className="queue-item-text">{claim.claim_text}</div>
                {claim.remedy_id && (
                  <div className="queue-item-why">A verified rewrite is proposed.</div>
                )}
              </button>
            ))}
          </div>
        </section>
      )}

      {heat.rows.length > 0 && (
        <section className="board-section">
          <h2 className="board-section-title">Exposure by page</h2>
          <p className="board-section-sub">
            Where the problems sit in the running order, so a shooting schedule can be
            read against them. Height is claims on that page, scaled to the worst one.
          </p>
          <div className="heat">
            {heat.rows.map(([page, row]) => (
              <div
                className="heat-col"
                key={page}
                title={`Page ${page}: ${row.red} contradicted, ${row.amber} unsupported`}
              >
                <div className="heat-stack">
                  {row.red > 0 && (
                    <div
                      className="heat-seg red"
                      style={{ height: `${(row.red / heat.peak) * 76 + 6}px` }}
                    />
                  )}
                  {row.amber > 0 && (
                    <div
                      className="heat-seg amber"
                      style={{ height: `${(row.amber / heat.peak) * 76 + 6}px` }}
                    />
                  )}
                </div>
                <span className="heat-label">{page}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="board-section">
        <h2 className="board-section-title">Spend</h2>
        <CostPanel runId={runId} live={live} />
      </section>

      {summary && summary.coverage_warnings.length > 0 && (
        <section className="board-section">
          <h2 className="board-section-title">Coverage</h2>
          {summary.coverage_warnings.map((warning) => (
            <div className="warning" key={warning}>
              {warning}
            </div>
          ))}
        </section>
      )}

      <p className="disclaimer">
        The research behind these verdicts is not shown in this workspace. Sources sit
        with production counsel, whose role is the one accountable for the call.
        {summary && ` Run cost ${formatUsd(summary.cost_usd)}.`}
      </p>
    </div>
  );
}

function Tile({
  value,
  label,
  note,
  tone = "",
}: {
  value: number;
  label: string;
  note: string;
  tone?: string;
}) {
  return (
    <div className={`board-tile ${tone}`} title={note}>
      <span className="board-tile-value">{value}</span>
      <span className="board-tile-label">{label}</span>
      <span className="board-tile-note">{note}</span>
    </div>
  );
}
