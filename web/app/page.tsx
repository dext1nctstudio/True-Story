"use client";

/**
 * The workspace.
 *
 * One screen: the screenplay on the left with every claim lit against the
 * record, the rail on the right carrying the evidence panel and the per person
 * dashboard, and the live counters and cost meter across the top.
 *
 * The demo path through this page is deliberate. Drop a draft in, watch the
 * truth claim banner fire, watch the overlay fill in live while the cost meter
 * ticks in cents, click the one red line, read the sources, apply the verified
 * rewrite. Every one of those beats is a real interaction with real state.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ClaimDashboard } from "@/components/ClaimDashboard";
import { CostMeter, VerdictCounters } from "@/components/CostMeter";
import { EvidencePanel } from "@/components/EvidencePanel";
import { CAPABILITIES, RoleSwitcher } from "@/components/RoleSwitcher";
import { VerdictOverlay } from "@/components/VerdictOverlay";
import { ApiError, getClaims, getOverlay, getRegister, getRun, streamRun } from "@/lib/api";
import type {
  Annotation,
  BudgetSnapshot,
  Claim,
  Overlay,
  PersonRollup,
  Remedy,
  Role,
  RunSummary,
  StreamEvent,
} from "@/lib/types";

const RUN_ID = process.env.NEXT_PUBLIC_DEMO_RUN_ID ?? "demo-run-0001";

export default function Workspace() {
  const [role, setRoleState] = useState<Role>("truestory.counsel");
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [persons, setPersons] = useState<PersonRollup[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [selected, setSelected] = useState<Annotation | null>(null);
  const [tab, setTab] = useState<"evidence" | "persons">("evidence");
  const [stage, setStage] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const capabilities = CAPABILITIES[role];

  // ── load ───────────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    try {
      const [overlayData, claimData, run] = await Promise.all([
        getOverlay(RUN_ID),
        getClaims(RUN_ID),
        getRun(RUN_ID),
      ]);
      setOverlay(overlayData);
      setClaims(claimData.claims);
      setSummary(run.summary);
      setError(null);

      // The register is counsel and producer only, so a 403 here is the
      // governance model working rather than a failure to report.
      try {
        const register = await getRegister(RUN_ID);
        setPersons(register.persons);
      } catch (exc) {
        if (!(exc instanceof ApiError && exc.isForbidden)) throw exc;
        setPersons([]);
      }
    } catch (exc) {
      setError(
        exc instanceof ApiError
          ? `API returned ${exc.status}. Is the backend running on port 8080?`
          : String(exc),
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, role]);

  // ── live stream ────────────────────────────────────────────────────────────
  useEffect(() => {
    const unsubscribe = streamRun(RUN_ID, (event: StreamEvent) => {
      if (event.budget) setBudget(event.budget);

      switch (event.event) {
        case "stage":
          setStage(String(event.stage ?? ""));
          break;
        case "adjudication_complete":
        case "run_complete":
          // Verdicts have landed, so re read the authoritative state rather
          // than reconstructing it from the event payload.
          void load();
          break;
        case "run_failed":
          setError(String(event.error ?? "run failed"));
          break;
      }
    });
    return unsubscribe;
  }, [load]);

  // ── derived ────────────────────────────────────────────────────────────────
  const selectedClaim = useMemo(
    () => claims.find((c) => c.claim_id === selected?.id) ?? null,
    [claims, selected],
  );

  const selectedRemedy: Remedy | null = null; // populated from the report payload

  const counts = useMemo(() => {
    if (summary) {
      return { ...summary.verdicts, counsel: summary.counsel_items };
    }
    return {
      green: claims.filter((c) => c.color === "green").length,
      amber: claims.filter((c) => c.color === "amber").length,
      red: claims.filter((c) => c.color === "red").length,
      grey: claims.filter((c) => c.color === "grey").length,
      counsel: claims.filter((c) => c.needs_counsel).length,
    };
  }, [claims, summary]);

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="shell">
      <header className="header">
        <span className="brand">True Story</span>

        {overlay && (
          <span className="script-title">
            {overlay.script.title} · {overlay.script.draft_version} ·{" "}
            {overlay.script.page_count} pages
          </span>
        )}

        {/* The escalation banner. This production tells its audience the story
            is true, which raises the risk tier of every person adjacent
            subject in the script. */}
        {overlay?.script.truth_claim_framing && (
          <span
            className="framing-banner"
            title={overlay.script.truth_claim_evidence ?? undefined}
          >
            TRUE STORY ASSERTED · all person adjacent elements escalated one tier
          </span>
        )}

        <span className="spacer" />

        {stage && <span className="counter-label">{stage}</span>}

        <VerdictCounters {...counts} />
        <CostMeter budget={budget} visible={capabilities.cost} />
        <RoleSwitcher role={role} onChange={setRoleState} />
      </header>

      <div className="workspace">
        <main>
          {error && <div className="warning" style={{ margin: 16 }}>{error}</div>}

          {overlay ? (
            <VerdictOverlay
              overlay={overlay}
              selectedId={selected?.id ?? null}
              onSelect={(annotation) => {
                setSelected(annotation);
                setTab("evidence");
              }}
            />
          ) : (
            !error && <div className="empty">Loading the draft.</div>
          )}
        </main>

        <aside className="rail">
          <div className="tabs">
            <button
              className={`tab ${tab === "evidence" ? "active" : ""}`}
              onClick={() => setTab("evidence")}
            >
              Evidence
            </button>
            <button
              className={`tab ${tab === "persons" ? "active" : ""}`}
              onClick={() => setTab("persons")}
            >
              People ({persons.length})
            </button>
          </div>

          {tab === "evidence" ? (
            <EvidencePanel
              runId={RUN_ID}
              annotation={selected}
              claim={selectedClaim}
              remedy={selectedRemedy}
              canSeeEvidence={capabilities.evidence}
              canUnmask={capabilities.unmask}
            />
          ) : (
            <ClaimDashboard persons={persons} />
          )}

          {overlay && (
            <div className="panel">
              <p className="panel-title">legend</p>
              <div className="legend">
                {Object.entries(overlay.legend).map(([color, text]) => (
                  <div className="legend-item" key={color}>
                    <span
                      className="legend-swatch"
                      style={{ background: `var(--verdict-${color}, transparent)` }}
                    />
                    <span title={text}>{color}</span>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 11, color: "var(--text-faint)", marginTop: 10 }}>
                {overlay.legend.amber}
              </p>
            </div>
          )}

          {summary && summary.coverage_warnings.length > 0 && (
            <div className="panel">
              <p className="panel-title">coverage</p>
              {summary.coverage_warnings.map((warning) => (
                <div className="warning" key={warning}>
                  {warning}
                </div>
              ))}
            </div>
          )}

          {/* Non negotiable, and it appears in the product as well as the
              report and the video. */}
          <p className="disclaimer">
            Decision support for a clearance attorney. Not legal advice. Every
            clearance report in this industry is reviewed by a qualified attorney
            before a policy is bound. This system automates the research and the
            document, not the judgement.
          </p>
        </aside>
      </div>
    </div>
  );
}
