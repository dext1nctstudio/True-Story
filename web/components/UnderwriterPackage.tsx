"use client";

/**
 * The underwriter's workspace: the filed package, and nothing behind it.
 *
 * A carrier is outside the trust boundary. What they are given is the document
 * an E&O submission is made on — the report, the clearance log, the evidence
 * appendix — watermarked, read only, and complete enough to bind against. What
 * they are not given is the working draft, the live spend, or any item still
 * open, because those are the production's business and disclosing them serves
 * nobody.
 *
 * The overlay is genuinely absent for this role rather than hidden with CSS:
 * `overlay: false` in VIEW_MATRIX means the server will not serve it either.
 */

import { useEffect, useState } from "react";
import { clearanceLogUrl, getReport, reportPdfUrl } from "@/lib/api";
import type { ClearableElement, RunSummary } from "@/lib/types";

interface Props {
  runId: string;
  summary: RunSummary | null;
  elements: ClearableElement[];
}

export function UnderwriterPackage({ runId, summary, elements }: Props) {
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getReport(runId)
      .then(setReport)
      .catch(() => setError("The report is not available for this run."));
  }, [runId]);

  const byStatus = elements.reduce<Record<string, number>>((acc, element) => {
    acc[element.status] = (acc[element.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="board package">
      <header className="board-head">
        <span className="package-stamp">Underwriter copy · watermarked</span>
        <h1 className="board-title">{summary?.script_title ?? "Clearance package"}</h1>
        <p className="board-sub">
          {summary?.draft_version ? `${summary.draft_version} · ` : ""}
          Errors and omissions submission package, generated{" "}
          {summary ? `from ${summary.research_subjects} researched subjects` : ""}.
        </p>
      </header>

      <div className="board-grid">
        <Stat value={summary?.verdicts.green ?? 0} label="verified" tone="green" />
        <Stat value={summary?.verdicts.amber ?? 0} label="unsupported" tone="amber" />
        <Stat value={summary?.verdicts.red ?? 0} label="contradicted" tone="red" />
        <Stat value={summary?.counsel_items ?? 0} label="with counsel" />
      </div>

      <section className="board-section">
        <h2 className="board-section-title">Documents</h2>
        <div className="package-links">
          <a className="btn btn-primary" href={reportPdfUrl(runId)} target="_blank" rel="noreferrer">
            Clearance report, PDF
          </a>
          <a className="btn" href={clearanceLogUrl(runId)} target="_blank" rel="noreferrer">
            Clearance log, CSV
          </a>
        </div>
        <p className="cost-note">
          Every URL in the appendix carries the date it was read. The web moves, and a
          source read on a known date is what a submission is actually made on.
        </p>
      </section>

      <section className="board-section">
        <h2 className="board-section-title">Clearance status</h2>
        <div className="package-status">
          {Object.entries(byStatus)
            .sort((a, b) => b[1] - a[1])
            .map(([status, count]) => (
              <div className="package-status-row" key={status}>
                <span className={`element-status ${statusTone(status)}`}>
                  {status.replace(/_/g, " ").toLowerCase()}
                </span>
                <span className="package-status-count">{count}</span>
              </div>
            ))}
        </div>
      </section>

      {summary && summary.coverage_warnings.length > 0 && (
        <section className="board-section">
          <h2 className="board-section-title">Stated limitations</h2>
          <p className="board-section-sub">
            Declared on the front page of the report rather than left for a reader to
            discover. A package that hides its own gaps is worth less, not more.
          </p>
          {summary.coverage_warnings.map((warning) => (
            <div className="warning" key={warning}>
              {warning}
            </div>
          ))}
        </section>
      )}

      {error && <div className="warning">{error}</div>}
      {report && <FrontMatter report={report} />}

      <p className="disclaimer">
        Read only, and watermarked to this recipient. The working draft, the production&rsquo;s
        spend and any item still open with counsel are outside this package by design.
      </p>
    </div>
  );
}

/**
 * The report's own front matter, set as a document.
 *
 * This was a JSON dump, which is a developer looking at their own API rather
 * than a carrier reading a submission. The fields are the same; they are laid
 * out the way the PDF lays them out, and the raw payload stays one click away
 * for anyone who does want to check the shape of it.
 */
function FrontMatter({ report }: { report: Record<string, unknown> }) {
  const [raw, setRaw] = useState(false);
  const title = (report.title_page ?? {}) as Record<string, unknown>;
  const coverage = (report.coverage_statement ?? {}) as Record<string, unknown>;

  return (
    <section className="board-section">
      <div className="package-head-row">
        <h2 className="board-section-title">Report front matter</h2>
        <button className="btn btn-quiet" onClick={() => setRaw((v) => !v)}>
          {raw ? "Show as a document" : "Show the raw payload"}
        </button>
      </div>

      {raw ? (
        <pre className="package-json">{JSON.stringify(report, null, 2).slice(0, 6000)}</pre>
      ) : (
        <>
          <dl className="package-fields">
            <Field label="Production" value={title.production_title} />
            <Field label="Draft" value={title.draft} />
            <Field label="Pages" value={roundPages(title.page_count)} />
            <Field label="Prepared" value={formatDate(title.prepared_at)} />
            <Field label="Script hash" value={title.script_hash} mono />
            <Field
              label="Truth claim"
              value={title.truth_claim_framing ? "asserted to the audience" : "not asserted"}
            />
            <Field label="Coverage" value={coverage.coverage_quality} />
            <Field label="Cache hit rate" value={formatRate(coverage.cache_hit_rate)} />
            <Field label="Fallback rate" value={formatRate(coverage.fallback_rate)} />
            <Field label="Open with counsel" value={coverage.counsel_items} />
          </dl>

          {typeof title.framing_note === "string" && (
            <p className="package-note">{title.framing_note}</p>
          )}
          {typeof title.disclaimer === "string" && (
            <p className="package-note">{title.disclaimer}</p>
          )}
        </>
      )}
    </section>
  );
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: unknown;
  mono?: boolean;
}) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="package-field">
      <dt>{label}</dt>
      <dd className={mono ? "mono" : undefined}>{String(value)}</dd>
    </div>
  );
}

/** A page count is a count. The stored value is a float derived from line
 *  offsets, and printing it put "3.36 pages" on a filed document. */
function roundPages(value: unknown): number | null {
  return typeof value === "number" ? Math.max(1, Math.round(value)) : null;
}

function formatDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatRate(value: unknown): string | null {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : null;
}

function statusTone(status: string): string {
  if (status === "CLEAR") return "green";
  if (status === "NOT_CLEAR" || status === "RESEARCH_FAILED") return "red";
  return "amber";
}

function Stat({ value, label, tone = "" }: { value: number; label: string; tone?: string }) {
  return (
    <div className={`board-tile ${tone}`}>
      <span className="board-tile-value">{value}</span>
      <span className="board-tile-label">{label}</span>
    </div>
  );
}
