"use client";

/**
 * Living clearance: what is still being watched after the report is filed.
 *
 * A clearance report is a photograph. Rights are a film. Music terms of the
 * WKRP era expired quietly years after the report was filed and the show went
 * out with sound alikes for three decades; a depicted person dies and the
 * post mortem publicity term starts running under the law of their domicile;
 * a new record surfaces against a claim that verified cleanly this morning.
 *
 * So the watches are a product surface rather than a background job nobody can
 * see. Each one names its subject, its cadence, and the reason it exists.
 */

import { useEffect, useState } from "react";
import { getMonitors } from "@/lib/api";

interface Monitor {
  monitor_id?: string;
  subject_id?: string;
  query?: string;
  cadence?: string;
  reason?: string;
  active?: boolean;
  last_checked_at?: string | null;
  expiry_hint?: string | null;
}

export function MonitorPanel({ projectId, opened }: { projectId: string; opened: number }) {
  const [monitors, setMonitors] = useState<Monitor[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMonitors(projectId)
      .then((data) => setMonitors((data.monitors ?? []) as Monitor[]))
      .catch(() => setError("Watches are not available to this role."));
  }, [projectId]);

  return (
    <div className="panel">
      <p className="panel-title">Living clearance</p>

      <p className="cost-note">
        {opened} watch{opened === 1 ? "" : "es"} were opened by this run. A clearance
        report is a photograph; rights are a film.
      </p>

      {error && <div className="empty">{error}</div>}

      {monitors !== null && monitors.length === 0 && !error && (
        <div className="empty">
          No watch has reported an event yet. Cadence runs from daily on an expiring
          licence to quarterly on a settled public figure.
        </div>
      )}

      {monitors?.map((monitor, index) => (
        <div className="watch" key={monitor.monitor_id ?? index}>
          <div className="watch-head">
            <span className={`watch-state ${monitor.active === false ? "off" : ""}`}>
              {monitor.active === false ? "closed" : "watching"}
            </span>
            <span className="watch-cadence">{monitor.cadence ?? "monthly"}</span>
          </div>
          <p className="watch-query">{monitor.query ?? monitor.subject_id}</p>
          {monitor.reason && <p className="watch-reason">{monitor.reason}</p>}
          {monitor.expiry_hint && (
            <p className="watch-expiry">
              Term ends {new Date(monitor.expiry_hint).toLocaleDateString()}, cadence
              tightens as it approaches.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
