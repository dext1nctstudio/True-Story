"use client";

/**
 * What a verdict is standing on.
 *
 * A citation count is close to meaningless on its own: five URLs on one site
 * are one source, and a Wikipedia paragraph and a federal docket are not
 * interchangeable however neatly they line up in a list. The backend counts
 * independent domains and classifies every host, and this is where that
 * arrives on screen — because the number a reviewer needs is not "6 sources",
 * it is "one register and two independent outlets, none of them a forum".
 *
 * Nothing here is computed in the browser. Every figure is read from the
 * `corroboration` block the Adjudicator wrote, so the report, the API and this
 * panel cannot drift.
 */

import type { Citation, Corroboration, SourceClass } from "@/lib/types";

const CLASS_LABEL: Record<SourceClass, string> = {
  official: "official record",
  registry: "registry",
  archive: "archive",
  news: "reporting",
  trade: "trade press",
  reference: "reference",
  user: "user generated",
  unknown: "unclassified",
};

/** Which classes read as a record rather than as a description of one. */
const RECORD_CLASSES = new Set<SourceClass>(["official", "registry", "archive"]);

export function SourcePedigree({ corroboration }: { corroboration?: Corroboration }) {
  if (!corroboration || corroboration.citation_count === 0) return null;

  const c = corroboration;
  const tone = c.score >= 0.75 ? "green" : c.score >= 0.45 ? "amber" : "red";

  return (
    <div className="pedigree">
      <div className="pedigree-head">
        <span className="pedigree-title">Corroboration</span>
        <span
          className={`pedigree-score ${tone}`}
          title="Independence and source pedigree, weighted. Caps the confidence a verdict may carry."
        >
          {Math.round(c.score * 100)}
          <span className="pedigree-score-unit">/100</span>
        </span>
      </div>

      <div className="pedigree-track">
        <div className={`pedigree-fill ${tone}`} style={{ width: `${c.score * 100}%` }} />
      </div>

      <div className="pedigree-facts">
        <Fact
          value={c.independent_domains}
          label={c.independent_domains === 1 ? "independent source" : "independent sources"}
          tone={c.independent_domains >= 2 ? "" : "amber"}
          title={c.domains.join(", ")}
        />
        <Fact
          value={c.classified_primary_count}
          label={c.classified_primary_count === 1 ? "record" : "records"}
          tone={c.classified_primary_count > 0 ? "" : "amber"}
          title="Dockets, registers, statutes and official archives, recognised by host."
        />
        <Fact
          value={c.citation_count}
          label="citations"
          title="Total sources attached, before independence is counted."
        />
        {c.low_trust_count > 0 && (
          <Fact
            value={c.low_trust_count}
            label="user generated"
            tone="red"
            title="Forums, social posts and content farms. These may corroborate; they may never decide."
          />
        )}
      </div>

      {/* The signal the research payload itself reported, which is a different
          thing from the verdict and is worth showing when they diverge. */}
      <div className="pedigree-signal">
        <span className={`signal-chip ${signalTone(c.record_signal)}`}>
          record: {c.record_signal.toLowerCase()}
        </span>
        {c.record_quality && <span className="signal-chip">{c.record_quality} record</span>}
        {c.conflict && <span className="signal-chip red">sources conflict</span>}
        {c.newest_source_days !== null && c.newest_source_days > 1095 && (
          <span className="signal-chip amber">
            newest source {Math.round(c.newest_source_days / 365)} years old
          </span>
        )}
      </div>

      {c.notes.length > 0 && (
        <ul className="pedigree-notes">
          {c.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function signalTone(signal: string): string {
  if (signal === "CONTRADICTED") return "red";
  if (signal === "SUPPORTED") return "green";
  if (signal === "MIXED") return "amber";
  return "";
}

function Fact({
  value,
  label,
  tone = "",
  title,
}: {
  value: number;
  label: string;
  tone?: string;
  title?: string;
}) {
  return (
    <span className={`pedigree-fact ${tone}`} title={title}>
      <span className="pedigree-fact-value">{value}</span>
      <span className="pedigree-fact-label">{label}</span>
    </span>
  );
}

/**
 * One source, with its pedigree on it.
 *
 * The badge is the classification from the host, not the researcher's opinion
 * of its own source. An unrecognised host says so rather than borrowing the
 * credibility of the ones that are recognised.
 */
export function SourceBadge({ citation }: { citation: Citation }) {
  const cls = (citation.source_class ?? "unknown") as SourceClass;
  const isRecord = RECORD_CLASSES.has(cls);
  const tone = isRecord ? "record" : cls === "user" ? "weak" : "";

  return (
    <span className={`source-badge ${tone}`} title={badgeTitle(citation)}>
      {CLASS_LABEL[cls] ?? cls}
      {citation.verified_source === false && <span className="source-badge-unverified">?</span>}
    </span>
  );
}

function badgeTitle(citation: Citation): string {
  const lines = [`Classified as ${CLASS_LABEL[(citation.source_class ?? "unknown") as SourceClass]}`];
  if (citation.domain) lines.push(`Domain: ${citation.domain}`);
  if (citation.verified_source === false) {
    lines.push(
      "This host is not in the source table, so its type is the researcher's own description and is treated as unconfirmed.",
    );
  }
  if (citation.published_at) {
    lines.push(`Published ${new Date(citation.published_at).toLocaleDateString()}`);
  }
  return lines.join("\n");
}
