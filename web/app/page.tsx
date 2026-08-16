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

import Image from "next/image";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ClaimDashboard } from "@/components/ClaimDashboard";
import { CostMeter, VerdictCounters } from "@/components/CostMeter";
import { EvidencePanel } from "@/components/EvidencePanel";
import { CAPABILITIES, RoleSwitcher } from "@/components/RoleSwitcher";
import { Dashboard } from "@/components/Dashboard";
import { ReviewQueue } from "@/components/ReviewQueue";
import { VerdictOverlay } from "@/components/VerdictOverlay";
import {
  ApiError,
  getClaims,
  getOverlay,
  getElements,
  getRegister,
  getRemedies,
  getRun,
  listRuns,
  streamRun,
  uploadRun,
} from "@/lib/api";
import type {
  Annotation,
  BudgetSnapshot,
  Claim,
  ClearableElement,
  Overlay,
  PersonRollup,
  Remedy,
  Role,
  RunListItem,
  RunSummary,
  StreamEvent,
} from "@/lib/types";

const PROJECT_ID = "demo";

/**
 * Run ids are minted per upload and the store is in memory, so there is no
 * id to bake in at build time. No `?run=` means no run is open yet, and the
 * home dashboard is what renders instead of the single track workspace view.
 */
function resolveRunId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("run");
}

export default function Workspace() {
  const [role, setRoleState] = useState<Role>("truestory.counsel");
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [remedies, setRemedies] = useState<Remedy[]>([]);
  const [elements, setElements] = useState<ClearableElement[]>([]);
  const [persons, setPersons] = useState<PersonRollup[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [selected, setSelected] = useState<Annotation | null>(null);
  // Set by clicking a header counter. Dims every script line whose verdict
  // does not match, rather than hiding them, so scanning "every red line"
  // does not lose the surrounding scene structure.
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null);
  const [tab, setTab] = useState<"evidence" | "persons">("evidence");
  const [stage, setStage] = useState<string>("");
  const [runStatus, setRunStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const capabilities = CAPABILITIES[role];
  // Always null on the first render, on both server and client: the server
  // has no window to read ?run= from, and hydration requires the client's
  // first pass to match that exact output. Reading the URL synchronously
  // here (window is defined on the client but not during SSR) produced two
  // different first renders and a hydration mismatch. The real value is
  // resolved a moment later in the effect below, client only.
  const [runId, setRunIdState] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // The run 404s until ingest lands (registration is stage 1, not upload),
  // so runStatus alone can't distinguish "just started" from "no run at all"
  // for that first stretch. This flag covers the gap; load() clears it the
  // moment a real status comes back.
  const [justStarted, setJustStarted] = useState(false);

  const openRun = useCallback((id: string | null) => {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("run", id);
    else url.searchParams.delete("run");
    window.history.pushState(null, "", url);
    setRunIdState(id);
    setVerdictFilter(null);
  }, []);

  // Resolves the real ?run= value once mounted, then keeps it in sync with
  // the back button. pushState does not fire popstate on its own.
  useEffect(() => {
    const onPop = () => setRunIdState(resolveRunId());
    onPop();
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const startRun = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      try {
        const { run_id } = await uploadRun(PROJECT_ID, file);
        // Reset everything from the previous run rather than let stale claims
        // or an old selection bleed into the freshly opened one.
        setOverlay(null);
        setClaims([]);
        setRemedies([]);
        setPersons([]);
        setSummary(null);
        setRunStatus("");
        setSelected(null);
        setError(null);
        setJustStarted(true);
        openRun(run_id);
      } catch (exc) {
        setUploadError(exc instanceof ApiError ? exc.message : String(exc));
      } finally {
        setUploading(false);
      }
    },
    [openRun],
  );

  // ── dashboard ──────────────────────────────────────────────────────────────
  const loadRuns = useCallback(async () => {
    try {
      const { runs: rows } = await listRuns(PROJECT_ID);
      setRuns(rows);
    } catch {
      // The dashboard degrading to "no runs yet" is preferable to it
      // throwing while the workspace view is what the role actually needs.
    }
  }, []);

  useEffect(() => {
    if (runId) return;
    void loadRuns();
    const timer = setInterval(() => void loadRuns(), 5000);
    return () => clearInterval(timer);
  }, [runId, loadRuns]);

  // ── load ───────────────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    if (!runId) return;
    try {
      const [overlayData, claimData, run, remedyData, elementData] = await Promise.all([
        getOverlay(runId),
        getClaims(runId),
        getRun(runId),
        // Remedies and elements only exist from later stages. A miss there is
        // expected for most of the run's life, not a real error, so both are
        // swallowed rather than joined into the same catch as the required
        // reads.
        getRemedies(runId).catch(() => ({ remedies: [] as Remedy[] })),
        getElements(runId).catch(() => ({ elements: [] as ClearableElement[] })),
      ]);
      // A run that has not reached the report stage can answer with {}, which
      // is truthy and would render an overlay with no script behind it.
      setOverlay(overlayData?.script ? overlayData : null);
      setClaims(claimData.claims);
      setRemedies(remedyData.remedies);
      setElements(elementData.elements ?? []);
      setSummary(run.summary);
      setRunStatus(run.status);
      setJustStarted(false);
      setError(null);

      // The register is counsel and producer only, so a 403 here is the
      // governance model working rather than a failure to report.
      try {
        const register = await getRegister(runId);
        setPersons(register.persons ?? []);
      } catch (exc) {
        if (!(exc instanceof ApiError && exc.isForbidden)) throw exc;
        setPersons([]);
      }
    } catch (exc) {
      // A 404 before ingest lands is the ordinary startup window, not a
      // failure: the run is registered the moment the script is parsed, so
      // this clears itself within a few seconds. Showing an error banner and
      // a `?run=` workaround there reads like something broke when nothing
      // has. Only a genuine non-404 is surfaced as an error.
      if (exc instanceof ApiError && exc.status === 404) {
        setJustStarted(true);
        setError(null);
      } else {
        setError(
          exc instanceof ApiError
            ? `API returned ${exc.status} for run ${runId}. Is the backend running on port 8080?`
            : String(exc),
        );
      }
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load, role]);

  // Keep re reading while the run is unavailable or still moving, so a run in
  // flight fills the overlay in as verdicts land instead of appearing at the
  // end all at once. Stops as soon as the run reaches a terminal state.
  useEffect(() => {
    if (!runId) return;
    const settled = runStatus === "COMPLETE" || runStatus === "FAILED";
    if (settled) return;
    const timer = setInterval(() => void load(), 5000);
    return () => clearInterval(timer);
  }, [runId, runStatus, load]);

  // ── live stream ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!runId) return;
    const unsubscribe = streamRun(runId, (event: StreamEvent) => {
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
  }, [load, runId]);

  // ── derived ────────────────────────────────────────────────────────────────
  const selectedClaim = useMemo(
    () => claims.find((c) => c.claim_id === selected?.id) ?? null,
    [claims, selected],
  );

  // An annotation is either a claim or a clearance element; the evidence panel
  // needs whichever one it is to show that subject's research.
  const selectedElement = useMemo(
    () => elements.find((e) => e.element_id === selected?.id) ?? null,
    [elements, selected],
  );

  const selectedRemedy = useMemo(
    () => remedies.find((r) => r.remedy_id === selectedClaim?.remedy_id) ?? null,
    [remedies, selectedClaim],
  );

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
      // Claims exist from stage 2 but stay uncoloured until adjudication at
      // stage 6. Without this the header reads all zeros for most of the run
      // and a live run looks identical to a dead one.
      pending: claims.filter((c) => c.color === "pending").length,
    };
  }, [claims, summary]);

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="shell">
      <header className="header">
        <div className="header-group">
          <button
            className="brand"
            onClick={() => openRun(null)}
            title="Back to the docket"
          >
            {/* The mark already sets both the name and the descriptor, so the
                text versions would duplicate it. alt carries them for anyone
                the image does not reach. */}
            <Image
              src="/logo-light.png"
              alt="True Story, a fact and rights engine"
              width={1580}
              height={553}
              priority
              className="brand-logo"
            />
          </button>

          {overlay && (
            <span className="script-title">
              {overlay.script.title}, {overlay.script.draft_version},{" "}
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
              True story asserted, every person adjacent element escalated one tier
            </span>
          )}
        </div>

        <span className="spacer" />

        <div className="header-actions">
          {/* Stage events only arrive for transitions seen while connected, so a
              page opened mid run has none. The polled status covers that gap. */}
          {runId && (stage || (runStatus && runStatus !== "COMPLETE")) && (
            <span className="stage-indicator">
              <span className="pulse" />
              {(stage || runStatus).toLowerCase().replace(/_/g, " ")}
            </span>
          )}

          {runId && (
            <div className="header-readouts">
              <VerdictCounters
                {...counts}
                activeFilter={verdictFilter}
                onFilter={setVerdictFilter}
              />
              <CostMeter budget={budget} visible={capabilities.cost} />
            </div>
          )}

          <div className="header-controls">
            <label className="btn btn-primary">
              New draft
              <input
                type="file"
                accept=".fountain,.fdx,.pdf,.txt"
                hidden
                disabled={uploading}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void startRun(file);
                  event.target.value = "";
                }}
              />
            </label>
            <RoleSwitcher role={role} onChange={setRoleState} />
          </div>
        </div>
      </header>

      {!runId ? (
        <div className="workspace-single">
          <Dashboard
            runs={runs}
            onOpen={openRun}
            onFile={startRun}
            uploading={uploading}
            uploadError={uploadError}
          />
        </div>
      ) : (
      <div className="workspace">
        <main>
          {error && <div className="warning error-banner">{error}</div>}

          {overlay ? (
            <VerdictOverlay
              overlay={overlay}
              selectedId={selected?.id ?? null}
              filterColor={verdictFilter}
              onSelect={(annotation) => {
                setSelected(annotation);
                setTab("evidence");
              }}
            />
          ) : justStarted ? (
            <div className="starting">
              <div className="starting-spinner" />
              <p className="starting-title">Parsing the screenplay</p>
              <p className="starting-sub">
                The script appears here as soon as ingest finishes, then lines light
                up as verdicts land.
              </p>
            </div>
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
            selected ? (
              <EvidencePanel
                runId={runId}
                annotation={selected}
                claim={selectedClaim}
                element={selectedElement}
                remedy={selectedRemedy}
                canSeeEvidence={capabilities.evidence}
                canUnmask={capabilities.unmask}
              />
            ) : (
              // Nothing selected. The resting state is the work queue rather
              // than an instruction to go clicking.
              <ReviewQueue
                claims={claims}
                elements={elements}
                onSelectClaim={(claimId) => {
                  const found = Object.values(overlay?.annotations ?? {})
                    .flat()
                    .find((a) => a.id === claimId);
                  if (found) setSelected(found);
                }}
              />
            )
          ) : (
            <ClaimDashboard persons={persons} />
          )}

          {overlay && (
            <div className="panel">
              <p className="panel-title">Legend</p>
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
              <p className="legend-note">{overlay.legend.amber}</p>
            </div>
          )}

          {summary && (summary.coverage_warnings?.length ?? 0) > 0 && (
            <div className="panel">
              <p className="panel-title">Coverage</p>
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
      )}
    </div>
  );
}
