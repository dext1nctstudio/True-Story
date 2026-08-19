"use client";

/**
 * The cost surface, in full.
 *
 * The header meter answers "what is this costing right now". This answers the
 * three questions that come immediately after it, and that a single number
 * cannot: where the money went, whether the run is tracking its own estimate,
 * and what the same work costs when a human does it.
 *
 * Two bills, never blended. Parallel is priced per task run and is what the
 * per script ceiling governs; Gemini is priced per token and is not governed by
 * it at all. A single "cost" figure that adds them together cannot be checked
 * against either invoice, so both are always shown with their own totals.
 *
 * Every rate on this panel comes from /v1/pricing. Nothing here restates a
 * price of its own.
 */

import { useCallback, useEffect, useState } from "react";
import { estimateRun, formatUsd, getCost } from "@/lib/api";
import type { Estimate, RunCost } from "@/lib/types";

export function CostPanel({ runId, live = false }: { runId: string; live?: boolean }) {
  const [cost, setCost] = useState<RunCost | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCost(await getCost(runId));
      setError(null);
    } catch {
      // Cost detail is process memory. A run restored after a restart has a
      // total on its summary and no breakdown, and saying so is better than
      // an empty panel.
      setError("Cost detail is not retained for this run after a restart.");
    }
  }, [runId]);

  // Re read only while the run is still spending. A finished run's ledger does
  // not change, and polling it forever kept a timer, a fetch and a re render
  // running for as long as the tab stayed open.
  useEffect(() => {
    void load();
    if (!live) return;
    const timer = setInterval(() => void load(), 6000);
    return () => clearInterval(timer);
  }, [live, load]);

  if (error) return <div className="empty">{error}</div>;
  if (!cost) return <div className="empty">Reading the ledger.</div>;

  const { snapshot: s, economics: e, counts } = cost;
  const projection = s.projection;
  const research = s.spent_usd;
  const model = s.model_usd ?? 0;
  const total = s.total_usd ?? research + model;

  return (
    <div className="cost-panel">
      <div className="cost-headline">
        <span className="cost-headline-value">{formatUsd(total)}</span>
        <span className="cost-headline-label">
          this run, across {counts.researched_subjects} researched subjects
        </span>
      </div>

      {/* The comparison the product exists to make. Stated against the low end
          of the published manual range, never the flattering high end. */}
      {e.times_cheaper !== null && total > 0 && (
        <div className="cost-versus">
          <span className="cost-versus-lead">{e.times_cheaper}×</span>
          <span className="cost-versus-text">
            cheaper than the {formatUsd(e.manual_baseline.report_usd_low)}–
            {formatUsd(e.manual_baseline.report_usd_high)} a first full feature clearance
            report is quoted at, delivered in {e.manual_baseline.turnaround_days_low}–
            {e.manual_baseline.turnaround_days_high} business days.
          </span>
        </div>
      )}

      <Section title="Two bills">
        <Line
          label="Research"
          sub={`${s.calls} lookups, ${Math.round((s.cache_hit_rate ?? 0) * 100)}% served from cache`}
          value={formatUsd(research)}
        />
        <div className="cost-bar">
          <div
            className={`cost-fill ${s.utilisation >= 1 ? "over" : s.utilisation >= 0.8 ? "warn" : ""}`}
            style={{ width: `${Math.min(1, s.utilisation) * 100}%` }}
          />
        </div>
        <p className="cost-note">
          Governed by a {formatUsd(s.ceiling_usd)} ceiling, of which{" "}
          {formatUsd(s.reserve_usd ?? 0)} is reserved for critical subjects and cannot be
          drawn down by anything else.
        </p>

        <Line
          label="Model"
          sub={`${s.model_calls ?? 0} calls, ${fmtTokens(s.model_prompt_tokens)} in, ${fmtTokens(
            s.model_output_tokens,
          )} out`}
          value={formatUsd(model)}
        />
        <p className="cost-note">
          Priced per token and deliberately outside the research ceiling: charging
          model tokens against it would silently reduce the research a script can buy.
        </p>
      </Section>

      {projection && projection.subjects > 0 && (
        <Section title="Estimate against actual">
          <Line
            label="Projected before dispatch"
            sub={`${projection.subjects} subjects routed`}
            value={formatUsd(projection.projected_usd)}
          />
          <Line
            label="Research actually spent"
            sub={
              research <= projection.projected_usd
                ? "inside the estimate"
                : "over the estimate"
            }
            value={formatUsd(research)}
          />
          <div className="cost-split">
            {Object.entries(projection.by_processor).map(([name, row]) => (
              <div className="cost-split-row" key={name}>
                <span className="cost-split-name">{name}</span>
                <span className="cost-split-sub">{row.subjects} subjects</span>
                <span className="cost-split-value">{formatUsd(row.usd)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {(s.cache_saved_usd ?? 0) > 0 && (
        <Section title="Cache">
          <Line
            label="Saved on this run"
            sub={`${s.cache_hits} of ${s.calls} lookups served from a previous draft`}
            value={formatUsd(s.cache_saved_usd ?? 0)}
          />
          <p className="cost-note">
            Claim and element identifiers are content hashes, so a redraft only
            researches what actually changed. This is the number that makes per
            episode series pricing work.
          </p>
        </Section>
      )}

      <Section title="Unit economics">
        <Line label="Per researched subject" value={fmtSmall(e.per_subject_usd)} />
        <Line label="Per claim" value={fmtSmall(e.per_claim_usd)} />
        <Line label="Per script page" value={fmtSmall(e.per_page_usd)} />
      </Section>

      {s.warnings.length > 0 && (
        <Section title="Coverage">
          {s.warnings.map((w) => (
            <div className="warning" key={w}>
              {w}
            </div>
          ))}
        </Section>
      )}

      <Calculator />
    </div>
  );
}

/**
 * The pre flight calculator.
 *
 * Answers the first question anyone with a script asks, before they upload it.
 * It calls the same endpoint the router's projection uses, against the same
 * published prices, so the number here and the number on the meter afterwards
 * are the same arithmetic rather than a marketing figure and a real one.
 */
export function Calculator({ standalone = false }: { standalone?: boolean }) {
  const [pages, setPages] = useState(105);
  const [drafts, setDrafts] = useState(4);
  const [framing, setFraming] = useState(true);
  const [reuse, setReuse] = useState(0.9);
  const [result, setResult] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    const timer = setTimeout(() => {
      void estimateRun({
        pages,
        truth_claim_framing: framing,
        drafts,
        cache_hit_rate: reuse,
      })
        .then((data) => {
          if (!cancelled) setResult(data);
        })
        .catch(() => undefined)
        .finally(() => {
          if (!cancelled) setBusy(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pages, drafts, framing, reuse]);

  return (
    <div className={`calculator ${standalone ? "standalone" : ""}`}>
      <p className="panel-title">What would a script cost</p>

      <div className="calc-row">
        <label className="calc-label" htmlFor="calc-pages">
          Pages
          <span className="calc-value">{pages}</span>
        </label>
        <input
          id="calc-pages"
          type="range"
          min={20}
          max={200}
          step={5}
          value={pages}
          onChange={(event) => setPages(Number(event.target.value))}
        />
      </div>

      <div className="calc-row">
        <label className="calc-label" htmlFor="calc-drafts">
          Drafts over the life of the title
          <span className="calc-value">{drafts}</span>
        </label>
        <input
          id="calc-drafts"
          type="range"
          min={1}
          max={12}
          value={drafts}
          onChange={(event) => setDrafts(Number(event.target.value))}
        />
      </div>

      <div className="calc-row">
        <label className="calc-label" htmlFor="calc-reuse">
          Unchanged between drafts
          <span className="calc-value">{Math.round(reuse * 100)}%</span>
        </label>
        <input
          id="calc-reuse"
          type="range"
          min={0}
          max={95}
          step={5}
          value={reuse * 100}
          onChange={(event) => setReuse(Number(event.target.value) / 100)}
        />
      </div>

      <label className="calc-check">
        <input
          type="checkbox"
          checked={framing}
          onChange={(event) => setFraming(event.target.checked)}
        />
        <span>
          Presented as a true story
          <span className="calc-hint">
            escalates every person adjacent subject one tier, which is most of the
            difference in the number
          </span>
        </span>
      </label>

      {result && (
        <div className={`calc-result ${busy ? "busy" : ""}`}>
          <div className="calc-result-main">
            <span className="calc-result-value">{formatUsd(result.total_usd)}</span>
            <span className="calc-result-label">
              all {result.input.drafts} draft{result.input.drafts === 1 ? "" : "s"}
            </span>
          </div>
          <div className="calc-result-grid">
            <Line label="First draft" value={formatUsd(result.first_draft_usd)} />
            <Line label="Each redraft" value={formatUsd(result.later_draft_usd)} />
            <Line
              label="Subjects researched"
              value={String(result.subjects.total)}
              sub={`${result.subjects.claims} claims, ${result.subjects.elements} elements`}
            />
            <Line
              label="Manual equivalent"
              value={formatUsd(result.manual_baseline_usd)}
              sub={result.times_cheaper ? `${result.times_cheaper}× more` : undefined}
            />
          </div>
          <p className="cost-note">{result.caveat}</p>
        </div>
      )}
    </div>
  );
}

// ── small pieces ─────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="cost-section">
      <p className="panel-title">{title}</p>
      {children}
    </div>
  );
}

function Line({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="cost-line">
      <span className="cost-line-label">
        {label}
        {sub && <span className="cost-line-sub">{sub}</span>}
      </span>
      <span className="cost-line-value">{value}</span>
    </div>
  );
}

function fmtSmall(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0.00";
  return value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

function fmtTokens(value: number | undefined): string {
  if (!value) return "0";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`;
  return String(value);
}
