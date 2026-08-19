"use client";

/**
 * Where the run has got to.
 *
 * A spinner and the word "researching" tells someone nothing about whether a
 * four minute wait is normal. Eight named stages, with the ones already done
 * marked and the current one moving, turns the same wait into a process
 * somebody can read — and when a run fails, it shows the stage it failed at
 * rather than leaving a dead spinner behind.
 */

const STAGES: { key: string; label: string; note: string }[] = [
  { key: "ingest", label: "Ingest", note: "Parsing the screenplay and detecting the framing." },
  { key: "claims", label: "Claims", note: "Decomposing dialogue into atomic factual assertions." },
  { key: "ledger", label: "Ledger", note: "Collapsing mentions into subjects worth researching." },
  { key: "routing", label: "Routing", note: "Assigning a tier, a depth and a schema to each one." },
  { key: "research", label: "Research", note: "The swarm, against the live public record." },
  { key: "adjudication", label: "Adjudication", note: "Evidence into verdicts, then the rubric." },
  { key: "remedy", label: "Remedies", note: "Rewrites, re verified against the same record." },
  { key: "report", label: "Report", note: "The E&O package and the clearance log." },
];

const ALIASES: Record<string, string> = {
  INGESTING: "ingest",
  EXTRACTING: "claims",
  BUILDING_LEDGER: "ledger",
  ROUTING: "routing",
  RESEARCHING: "research",
  ADJUDICATING: "adjudication",
  REMEDIATING: "remedy",
  REPORTING: "report",
  COMPLETE: "done",
  FAILED: "failed",
};

export function RunTimeline({
  stage,
  status,
}: {
  /** The last stage event seen on the stream. */
  stage: string;
  /** The polled run status, which covers a page opened mid run. */
  status: string;
}) {
  const failed = status === "FAILED";
  const done = status === "COMPLETE";
  const currentKey = normalise(stage) || normalise(status);
  const currentIndex = done
    ? STAGES.length
    : STAGES.findIndex((s) => s.key === currentKey);

  return (
    <ol className="timeline" aria-label="Run progress">
      {STAGES.map((entry, index) => {
        const state = done
          ? "done"
          : index < currentIndex
            ? "done"
            : index === currentIndex
              ? failed
                ? "failed"
                : "active"
              : "waiting";
        return (
          <li className={`timeline-step ${state}`} key={entry.key} title={entry.note}>
            <span className="timeline-mark" />
            <span className="timeline-label">{entry.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function normalise(raw: string): string {
  if (!raw) return "";
  const upper = raw.toUpperCase();
  if (ALIASES[upper]) return ALIASES[upper];
  const lower = raw.toLowerCase().replace(/\s+/g, "_");
  return STAGES.some((s) => s.key === lower) ? lower : "";
}
