"use client";

/**
 * The home dashboard.
 *
 * Every run this project has produced, newest first, live while any of them
 * are still executing. Runs are process memory only, so this list, like
 * everything else, resets on the next API restart — it can only show what
 * the current process has seen.
 */

import type { RunListItem } from "@/lib/types";

interface Props {
  runs: RunListItem[];
  onOpen: (runId: string) => void;
}

const TERMINAL = new Set(["COMPLETE", "FAILED"]);

export function RunList({ runs, onOpen }: Props) {
  if (runs.length === 0) {
    return <div className="empty">No runs yet. Upload a draft to start one.</div>;
  }

  return (
    <div className="run-list">
      {runs.map((run) => {
        const inFlight = !TERMINAL.has(run.status);
        return (
          <button key={run.run_id} className="run-row" onClick={() => onOpen(run.run_id)}>
            <div className="run-row-main">
              <span className="run-row-title">{run.script_title ?? run.run_id}</span>
              <span className={`run-row-status ${inFlight ? "live" : run.status.toLowerCase()}`}>
                {inFlight && <span className="pulse" />}
                {run.status.toLowerCase().replace(/_/g, " ")}
              </span>
            </div>
            <div className="run-row-meta">
              <span>{new Date(run.started_at).toLocaleString()}</span>
              {run.verdicts && (
                <span>
                  {run.verdicts.green} verified · {run.verdicts.amber} unsupported ·{" "}
                  {run.verdicts.red} contradicted
                </span>
              )}
              {run.cost_usd != null && <span>${run.cost_usd.toFixed(2)}</span>}
              {run.error && <span className="warning-inline">{run.error}</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}
