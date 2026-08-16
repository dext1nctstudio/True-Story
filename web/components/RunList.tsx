"use client";

/**
 * The docket. Every run this project has produced, newest first, live while
 * any of them are still executing.
 *
 * Runs are process memory only, so this list, like everything else, resets on
 * the next API restart, it can only show what the current process has seen.
 */

import type { RunListItem } from "@/lib/types";

interface Props {
  runs: RunListItem[];
  onOpen: (runId: string) => void;
}

const TERMINAL = new Set(["COMPLETE", "FAILED"]);

export function RunList({ runs, onOpen }: Props) {
  if (runs.length === 0) {
    return (
      <div className="dashboard-empty">
        No runs yet in this session. Drop a draft above to open the first one.
      </div>
    );
  }

  return (
    <div className="run-list">
      {runs.map((run) => {
        const inFlight = !TERMINAL.has(run.status);
        const v = run.verdicts;
        return (
          <button key={run.run_id} className="run-row" onClick={() => onOpen(run.run_id)}>
            <div className="run-row-identity">
              <div className="run-row-main">
                <span className="run-row-title">{run.script_title ?? run.run_id}</span>
                <span className={`run-row-status ${inFlight ? "live" : run.status.toLowerCase()}`}>
                  {inFlight && <span className="pulse" />}
                  {run.status.toLowerCase().replace(/_/g, " ")}
                </span>
              </div>
              <div className="run-row-meta">
                <span>{new Date(run.started_at).toLocaleString()}</span>
                {run.error && <span className="warning-inline">{run.error}</span>}
              </div>
            </div>

            {v && (v.green > 0 || v.amber > 0 || v.red > 0) && (
              <div className="run-row-verdicts">
                {v.green > 0 && <span className="run-row-verdict-chip green">{v.green}</span>}
                {v.amber > 0 && <span className="run-row-verdict-chip amber">{v.amber}</span>}
                {v.red > 0 && <span className="run-row-verdict-chip red">{v.red}</span>}
              </div>
            )}

            {run.cost_usd != null && (
              <span className="run-row-cost">${run.cost_usd.toFixed(2)}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
