"use client";

/**
 * The docket. What counsel sees before any script is open.
 *
 * Four stat cards read the whole book at a glance: how many matters are open,
 * what the book has cost, how the record has broken across every claim ever
 * adjudicated in this process, and how many runs are in motion right now.
 * Everything here is derived from the same run list the dashboard already
 * polls — no separate aggregate endpoint, so there is nothing here that can
 * drift from what the run rows below it show.
 */

import { useMemo } from "react";
import { RunList } from "@/components/RunList";
import { UploadZone } from "@/components/UploadZone";
import type { RunListItem } from "@/lib/types";

interface Props {
  runs: RunListItem[];
  onOpen: (runId: string) => void;
  onFile: (file: File) => void;
  uploading: boolean;
  uploadError: string | null;
}

const TERMINAL = new Set(["COMPLETE", "FAILED"]);

export function Dashboard({ runs, onOpen, onFile, uploading, uploadError }: Props) {
  const stats = useMemo(() => {
    const totals = { green: 0, amber: 0, red: 0, grey: 0 };
    let cost = 0;
    let live = 0;
    for (const run of runs) {
      if (!TERMINAL.has(run.status)) live += 1;
      if (run.verdicts) {
        totals.green += run.verdicts.green;
        totals.amber += run.verdicts.amber;
        totals.red += run.verdicts.red;
        totals.grey += run.verdicts.grey;
      }
      if (run.cost_usd) cost += run.cost_usd;
    }
    const claimTotal = totals.green + totals.amber + totals.red + totals.grey;
    return { totals, cost, live, claimTotal, runCount: runs.length };
  }, [runs]);

  const pct = (n: number) => (stats.claimTotal ? (n / stats.claimTotal) * 100 : 0);

  return (
    <div className="dashboard">
      <div className="dashboard-hero">
        <div className="dashboard-welcome">
          <h1 className="dashboard-title">The docket</h1>
          <p className="dashboard-subtitle">
            Every claim about a real person, checked against the record before a line
            reaches a set. Drop a draft below to open a new matter.
          </p>
        </div>
        <div className="upload-card">
          <UploadZone onFile={onFile} uploading={uploading} error={uploadError} />
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <span className="stat-card-label">Runs this session</span>
          <span className="stat-card-value">{stats.runCount}</span>
          <span className="stat-card-sub">
            {stats.live > 0 ? (
              <span className="stat-card-live">
                <span className="pulse" />
                {stats.live} in progress
              </span>
            ) : (
              "none in progress"
            )}
          </span>
        </div>

        <div className="stat-card">
          <span className="stat-card-label">Total spend</span>
          <span className="stat-card-value">${stats.cost.toFixed(2)}</span>
          <span className="stat-card-sub">across every run below</span>
        </div>

        <div className="stat-card" style={{ gridColumn: "span 2" }}>
          <span className="stat-card-label">Verdict record</span>
          <span className="stat-card-value">{stats.claimTotal}</span>
          {stats.claimTotal > 0 && (
            <>
              <div className="verdict-bar">
                <div className="verdict-bar-seg green" style={{ width: `${pct(stats.totals.green)}%` }} />
                <div className="verdict-bar-seg amber" style={{ width: `${pct(stats.totals.amber)}%` }} />
                <div className="verdict-bar-seg red" style={{ width: `${pct(stats.totals.red)}%` }} />
                <div className="verdict-bar-seg grey" style={{ width: `${pct(stats.totals.grey)}%` }} />
              </div>
              <div className="verdict-bar-legend">
                <span className="verdict-bar-legend-item">
                  <span className="verdict-bar-dot green" /> {stats.totals.green} verified
                </span>
                <span className="verdict-bar-legend-item">
                  <span className="verdict-bar-dot amber" /> {stats.totals.amber} unsupported
                </span>
                <span className="verdict-bar-legend-item">
                  <span className="verdict-bar-dot red" /> {stats.totals.red} contradicted
                </span>
                <span className="verdict-bar-legend-item">
                  <span className="verdict-bar-dot grey" /> {stats.totals.grey} opinion
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="dashboard-section-head">
        <h2 className="dashboard-section-title">Runs</h2>
        <span className="dashboard-section-count">{runs.length}</span>
      </div>
      <RunList runs={runs} onOpen={onOpen} />
    </div>
  );
}
