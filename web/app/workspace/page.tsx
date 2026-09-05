"use client";

/**
 * The workspace.
 *
 * One run, seen four ways. The role does not filter this page, it selects
 * which page gets built: counsel opens the script with the evidence beside it,
 * the producer opens exposure and spend, the writer opens the lines to fix,
 * and the underwriter opens the filed package with no working draft behind it
 * at all. `lib/roles.ts` holds that decision, and the server enforces the same
 * matrix, so a role never renders a panel it would be refused.
 *
 * The demo path is unchanged and still deliberate: drop a draft in, watch the
 * truth claim banner fire, watch the overlay fill in live while the meter
 * ticks in cents, click the one red line, read the sources, apply the verified
 * rewrite.
 */

import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ClaimDashboard } from "@/components/ClaimDashboard";
import { Calculator, CostPanel } from "@/components/CostPanel";
import { CommandPalette, type Command } from "@/components/CommandPalette";
import { CostMeter, VerdictCounters } from "@/components/CostMeter";
import { RiskBoard } from "@/components/RiskBoard";
import { Dashboard } from "@/components/Dashboard";
import { EvidencePanel } from "@/components/EvidencePanel";
import { MonitorPanel } from "@/components/MonitorPanel";
import { ProducerBoard } from "@/components/ProducerBoard";
import { ReviewQueue } from "@/components/ReviewQueue";
import { RoleSwitcher } from "@/components/RoleSwitcher";
import { RunTimeline } from "@/components/RunTimeline";
import { UnderwriterPackage } from "@/components/UnderwriterPackage";
import { VerdictOverlay } from "@/components/VerdictOverlay";
import { WriterDesk } from "@/components/WriterDesk";
import {
  ApiError,
  clearanceLogUrl,
  getClaims,
  getElements,
  getOverlay,
  getRegister,
  getRemedies,
  getRun,
  listRuns,
  reportPdfUrl,
  setRole,
  streamRun,
  uploadRun,
} from "@/lib/api";
import { ROLE_VIEWS, TAB_LABEL, type RailTab, viewFor } from "@/lib/roles";
import { presentRunError } from "@/lib/run-error";
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

/** No `?run=` means no run is open; the durable docket renders instead. */
function resolveRunId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("run");
}

/** "1 page", not "1 pages". A three page fixture rounds to one. */
function pageLabel(pageCount: number): string {
  const pages = Math.max(1, Math.round(pageCount));
  return `${pages} page${pages === 1 ? "" : "s"}`;
}

/**
 * The modifier key this machine actually uses.
 *
 * The palette binds both metaKey and ctrlKey, and the button has always
 * advertised ⌘K regardless. On Windows, where most people will open this,
 * the hint named a key that is not on the keyboard, which is a small reason
 * to conclude a control does not work.
 *
 * Resolved after mount rather than during render: `navigator` does not exist
 * on the server, and reading it in the render path is the SSR/client
 * divergence that produces a hydration mismatch.
 */
function useModifierKey(): string {
  const [key, setKey] = useState("Ctrl");
  useEffect(() => {
    const platform =
      (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ??
      navigator.platform ??
      "";
    if (/mac|iphone|ipad|ipod/i.test(platform)) setKey("⌘");
  }, []);
  return key;
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
  const [tab, setTab] = useState<RailTab>("evidence");
  // Producer and writer open on their own surface and can flip to the script.
  // Counsel opens on the script. The underwriter has no script at all.
  const [surface, setSurface] = useState<"native" | "script">("native");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [runStatus, setRunStatus] = useState<string>("");
  // Rebuilt from durable storage rather than held in this process.
  const [restored, setRestored] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const view = viewFor(role);
  const caps = view.caps;
  const modKey = useModifierKey();

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
    setRestored(false);
  }, []);

  // Resolves the real ?run= and ?role= values once mounted, then keeps them in
  // sync with the back button. pushState does not fire popstate on its own.
  //
  // The role lives in the URL so a workspace is a link. "Here is what the
  // underwriter sees" is a sentence somebody says several times a day in this
  // workflow, and it should be a URL rather than a set of instructions.
  useEffect(() => {
    const onPop = () => {
      setRunIdState(resolveRunId());
      const wanted = new URLSearchParams(window.location.search).get("role");
      if (wanted && wanted in ROLE_VIEWS) {
        setRole(wanted as Role);
        setRoleState(wanted as Role);
      }
    };
    onPop();
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const changeRole = useCallback((next: Role) => {
    setRoleState(next);
    const url = new URL(window.location.href);
    // Counsel is the default, so it stays out of the URL and a plain link
    // keeps working as it did.
    if (next === "truestory.counsel") url.searchParams.delete("role");
    else url.searchParams.set("role", next);
    window.history.replaceState(null, "", url);
  }, []);

  // A role change can land on a tab that role does not have. Snap to the
  // first tab it does, rather than rendering an empty rail.
  useEffect(() => {
    setTab((current) => (view.rail.includes(current) ? current : (view.rail[0] ?? "evidence")));
  }, [view]);

  // Each role opens on its own surface. Kept in its own effect, keyed on the
  // role alone: folded in with the tab reset above, every tab click also threw
  // the user back to the role's landing surface.
  useEffect(() => {
    setSurface(view.home === "docket" ? "script" : "native");
  }, [view]);

  // ⌘K / ctrl-K anywhere, and the shortcuts a six hour session needs.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing =
        event.target instanceof HTMLElement &&
        ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "/") {
        event.preventDefault();
        setPaletteOpen(true);
      } else if (event.key === "Escape") {
        setSelected(null);
        setVerdictFilter(null);
      } else if (["1", "2", "3", "4"].includes(event.key)) {
        const colours = ["green", "amber", "red", "grey"];
        const next = colours[Number(event.key) - 1];
        setVerdictFilter((current) => (current === next ? null : next));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
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
      // The run record is the authoritative one and the only required read.
      // Everything else is stage dependent. Restored runs read their detailed
      // artifacts from durable storage through the same endpoints.
      const run = await getRun(runId);
      setSummary(run.summary);
      setRunStatus(run.status);
      setRestored(Boolean(run.restored));
      setJustStarted(false);
      setError(run.status === "FAILED" ? presentRunError(run.error) : null);

      const [overlayData, claimData, remedyData, elementData] = await Promise.all([
        caps.overlay ? getOverlay(runId).catch(() => null) : Promise.resolve(null),
        getClaims(runId).catch(() => ({ claims: [] as Claim[] })),
        getRemedies(runId).catch(() => ({ remedies: [] as Remedy[] })),
        getElements(runId).catch(() => ({ elements: [] as ClearableElement[] })),
      ]);
      // A run that has not reached the report stage can answer with {}, which
      // is truthy and would render an overlay with no script behind it.
      setOverlay(overlayData?.script ? overlayData : null);
      setClaims(claimData.claims);
      setRemedies(remedyData.remedies);
      setElements(elementData.elements ?? []);

      // The register is counsel and producer only, and the server enforces
      // that, so a 403 here is the governance model working rather than a
      // failure to report.
      if (caps.register) {
        try {
          const register = await getRegister(runId);
          setPersons(register.persons ?? []);
        } catch (exc) {
          if (!(exc instanceof ApiError && exc.isForbidden)) throw exc;
          setPersons([]);
        }
      } else {
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
  }, [caps.overlay, caps.register, runId]);

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
          setError(presentRunError(String(event.error ?? "Run failed.")));
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

  /** Open a subject by id from anywhere: the palette, the board, the desk. */
  const openSubject = useCallback(
    (subjectId: string) => {
      const annotation = Object.values(overlay?.annotations ?? {})
        .flat()
        .find((a) => a.id === subjectId);
      if (annotation) {
        setSelected(annotation);
        setTab("evidence");
        if (caps.overlay) setSurface("script");
      }
    },
    [caps.overlay, overlay],
  );

  const commands = useMemo<Command[]>(() => {
    const rows: Command[] = [];
    if (caps.overlay) {
      for (const [colour, label] of [
        ["red", "contradicted"],
        ["amber", "unsupported"],
        ["green", "verified"],
      ] as const) {
        rows.push({
          id: `filter:${colour}`,
          label: `Show only ${label} lines`,
          hint: "filter the script",
          group: "View",
          run: () => {
            setSurface("script");
            setVerdictFilter((current) => (current === colour ? null : colour));
          },
        });
      }
      rows.push({
        id: "filter:clear",
        label: "Clear the filter",
        group: "View",
        run: () => setVerdictFilter(null),
      });
    }
    if (view.home !== "docket") {
      rows.push({
        id: "surface:native",
        label: `Go to ${view.label.toLowerCase()} view`,
        group: "View",
        run: () => setSurface("native"),
      });
    }
    rows.push({
      id: "nav:docket",
      label: "Back to the docket",
      group: "View",
      run: () => openRun(null),
    });
    if (caps.reports && runId) {
      rows.push({
        id: "export:pdf",
        label: "Open the clearance report, PDF",
        group: "Export",
        run: () => window.open(reportPdfUrl(runId), "_blank"),
      });
      rows.push({
        id: "export:csv",
        label: "Download the clearance log, CSV",
        group: "Export",
        run: () => window.open(clearanceLogUrl(runId), "_blank"),
      });
    }
    return rows;
  }, [caps.overlay, caps.reports, openRun, runId, view]);

  const showScript = caps.overlay && (view.home === "docket" || surface === "script");

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="shell" data-role={view.value} style={{ ["--role" as string]: view.accent }}>
      <header className="header">
        <div className="header-group">
          <Link href="/" className="home-back" title="Back to True Story home" aria-label="Back to home">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </Link>
          <button suppressHydrationWarning className="brand" onClick={() => openRun(null)} title="Back to the docket">
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

          {/* The title carries the weight; the draft and length are metadata and
              are set as metadata. This was previously one comma spliced line of
              three equal facts — "THE FINISHER — EVIDENCE TEST, v1, 1 pages" —
              which read as generated text and got "1 pages" wrong on any script
              short enough to round to one. */}
          {overlay && (
            <span className="script-title">
              <span className="script-name">{overlay.script.title}</span>
              <span className="script-meta">
                {overlay.script.draft_version} · {pageLabel(overlay.script.page_count)}
              </span>
            </span>
          )}

          {/* The escalation signal. This production tells its audience the story
              is true, which raises the risk tier of every person adjacent
              subject in the script, so it has to be visible.
              It does not have to be a sentence. It sat next to the title as a
              second block of prose in its own colour and font, and two loud
              blocks side by side is what made the masthead look automated. The
              rule it stands for lives in the tooltip and in the report. */}
          {overlay?.script.truth_claim_framing && (
            <span
              className="framing-banner"
              title={
                overlay.script.truth_claim_evidence
                  ? `Truth claim asserted: "${overlay.script.truth_claim_evidence}". Every person adjacent element is escalated one risk tier.`
                  : "Truth claim asserted. Every person adjacent element is escalated one risk tier."
              }
            >
              True story
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
              {caps.overlay && (
                <VerdictCounters
                  {...counts}
                  activeFilter={verdictFilter}
                  onFilter={(colour) => {
                    setSurface("script");
                    setVerdictFilter(colour);
                  }}
                />
              )}
              <CostMeter budget={budget} visible={caps.cost} />
            </div>
          )}

          <div className="header-controls">
            <button suppressHydrationWarning
              className="btn btn-quiet"
              onClick={() => setPaletteOpen(true)}
              title="Search claims, elements and people"
            >
              Search
              <kbd className="btn-kbd">{modKey}K</kbd>
            </button>

            {caps.upload && (
              <label className="btn btn-primary">
                New draft
                <input suppressHydrationWarning
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
            )}
            <RoleSwitcher role={role} onChange={changeRole} />
          </div>
        </div>
      </header>

      {/* Governance, said rather than implied. Four roles that look identical
          teach nobody anything; a line naming what this one does not get is
          the whole point of the control. */}
      <div className="role-strip">
        <span className="role-strip-role" style={{ color: view.accent }}>
          {view.role_line}
        </span>
        <span className="role-strip-sees">{view.sees}</span>
        {!caps.evidence && <span className="role-strip-withheld">{view.withheld}</span>}
      </div>

      {!runId ? (
        <div className="workspace-single">
          <Dashboard
            runs={runs}
            onOpen={openRun}
            onFile={startRun}
            uploading={uploading}
            uploadError={uploadError}
            title={
              view.home === "package"
                ? "Filed packages"
                : view.home === "desk"
                  ? "Your drafts"
                  : "The docket"
            }
            canUpload={caps.upload}
          />
          {caps.cost && <Calculator standalone />}
        </div>
      ) : (
        <div className={showScript ? "workspace" : "workspace-single"}>
          <main>
            {error && <div className="warning error-banner">{error}</div>}

            {/* The surface switch. Only rendered for the roles that have two,
                which is why it is not a permanent piece of chrome. */}
            {caps.overlay && view.home !== "docket" && (
              <div className="surface-switch">
                <button suppressHydrationWarning
                  className={`surface-tab ${surface === "native" ? "active" : ""}`}
                  onClick={() => setSurface("native")}
                >
                  {view.home === "risk" ? "Risk" : "Lines to fix"}
                </button>
                <button suppressHydrationWarning
                  className={`surface-tab ${surface === "script" ? "active" : ""}`}
                  onClick={() => setSurface("script")}
                >
                  Script
                </button>
              </div>
            )}

            {view.home === "package" ? (
              <UnderwriterPackage runId={runId} summary={summary} elements={elements} />
            ) : surface === "native" && view.home === "risk" ? (
              <ProducerBoard
                runId={runId}
                live={runStatus !== "COMPLETE" && runStatus !== "FAILED"}
                summary={summary}
                claims={claims}
                elements={elements}
                persons={persons}
                onOpenLine={openSubject}
              />
            ) : surface === "native" && view.home === "desk" ? (
              <WriterDesk
                runId={runId}
                claims={claims}
                remedies={remedies}
                onOpenLine={openSubject}
                canApply={caps.remedies}
              />
            ) : overlay ? (
              <VerdictOverlay
                overlay={overlay}
                selectedId={selected?.id ?? null}
                filterColor={verdictFilter}
                onSelect={(annotation) => {
                  setSelected(annotation);
                  setTab("evidence");
                }}
              />
            ) : restored ? (
              <div className="starting">
                <p className="starting-title">Archived run</p>
                <p className="starting-sub">
                  This run was restored from durable storage. Its summary is available,
                  but it predates detailed artifact persistence.
                </p>
              </div>
            ) : justStarted ||
              (runStatus && runStatus !== "COMPLETE" && runStatus !== "FAILED") ? (
              // No overlay yet and the run is still moving. Covers both the
              // window before the run registers and the ingest stage after it,
              // which on a feature length script is minutes of model calls.
              <div className="starting">
                <RunTimeline stage={stage} status={runStatus} />
                <p className="starting-title">
                  {stage ? stageTitle(stage) : "Parsing the screenplay"}
                </p>
                <p className="starting-sub">
                  The script appears here as soon as ingest finishes, then lines light
                  up as verdicts land.
                </p>
              </div>
            ) : (
              !error && <div className="empty">Loading the draft.</div>
            )}
          </main>

          {showScript && (
            <aside className="rail">
              <div className="tabs">
                {view.rail.map((entry) => (
                  <button suppressHydrationWarning
                    key={entry}
                    className={`tab ${tab === entry ? "active" : ""}`}
                    onClick={() => setTab(entry)}
                  >
                    {TAB_LABEL[entry]}
                    {entry === "people" && persons.length > 0 && ` (${persons.length})`}
                  </button>
                ))}
              </div>

              {tab === "evidence" &&
                (selected ? (
                  <EvidencePanel
                    runId={runId}
                    annotation={selected}
                    claim={selectedClaim}
                    element={selectedElement}
                    remedy={selectedRemedy}
                    canSeeEvidence={caps.evidence}
                    canUnmask={caps.unmask}
                  />
                ) : (
                  // Nothing selected. The resting state is the work queue rather
                  // than an instruction to go clicking.
                  <ReviewQueue
                    claims={claims}
                    elements={elements}
                    onSelectClaim={openSubject}
                    runId={runId}
                  />
                ))}

              {tab === "people" && <ClaimDashboard persons={persons} />}

              {tab === "queue" && (
                <ReviewQueue
                  claims={claims}
                  elements={elements}
                  onSelectClaim={openSubject}
                  runId={runId}
                />
              )}

              {tab === "cost" && (
                <CostPanel
                  runId={runId}
                  live={runStatus !== "COMPLETE" && runStatus !== "FAILED"}
                />
              )}

              {tab === "risk" && (
                <RiskBoard
                  runId={runId}
                  claims={claims}
                  elements={elements}
                  onOpenLine={openSubject}
                />
              )}

              {tab === "monitors" && (
                <MonitorPanel projectId={PROJECT_ID} opened={summary?.monitors_created ?? 0} />
              )}

              {tab === "report" && (
                <UnderwriterPackage runId={runId} summary={summary} elements={elements} />
              )}

              {overlay && tab === "evidence" && (
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
          )}
        </div>
      )}

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        claims={claims}
        elements={elements}
        persons={persons}
        commands={commands}
        onSelectClaim={openSubject}
        onSelectElement={openSubject}
      />
    </div>
  );
}

function stageTitle(stage: string): string {
  const titles: Record<string, string> = {
    ingest: "Parsing the screenplay",
    claims: "Decomposing the dialogue into claims",
    ledger: "Collapsing mentions into subjects",
    routing: "Routing every subject by risk",
    research: "Researching against the live record",
    adjudication: "Turning evidence into verdicts",
    remedy: "Drafting verified rewrites",
    report: "Assembling the clearance package",
  };
  return titles[stage.toLowerCase()] ?? "Working";
}
