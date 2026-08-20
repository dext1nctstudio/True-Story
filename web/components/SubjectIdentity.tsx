"use client";

/**
 * Who the subject was resolved to, before anything was researched about them.
 *
 * The stage this reports on exists because of a measured failure. Asked to
 * check claims about a screenplay character called Dr Maya Rowan, the pipeline
 * dispatched research at the name and attached what came back: four government
 * domains from Google's grounding and a teenage swimmer's results page from
 * Parallel. All real sources. None of them about anybody.
 *
 * So the first question is now asked first, and its answer is shown, because a
 * reviewer needs to know which of three situations they are in before they
 * read a single citation:
 *
 *   resolved      a real subject, pinned to an identifier
 *   collision     several real people share the name and none is the referent
 *   unidentified  nobody. Nothing was researched and nothing is attached
 */

import type { Identity } from "@/lib/types";

const TONE: Record<Identity["status"], string> = {
  resolved: "green",
  collision: "amber",
  unidentified: "",
  unchecked: "",
};

const LABEL: Record<Identity["status"], string> = {
  resolved: "identified",
  collision: "name collision",
  unidentified: "no real subject",
  unchecked: "not checked",
};

export function SubjectIdentity({ identity }: { identity?: Identity }) {
  if (!identity || identity.status === "unchecked") return null;

  const canonical = identity.canonical;

  return (
    <div className={`identity identity-${identity.status}`}>
      <div className="identity-head">
        <span className="pedigree-title">Subject</span>
        <span className={`signal-chip ${TONE[identity.status]}`}>{LABEL[identity.status]}</span>
      </div>

      {canonical ? (
        <div className="identity-body">
          <a className="identity-name" href={canonical.url} target="_blank" rel="noreferrer">
            {canonical.label}
          </a>
          {canonical.description && (
            <span className="identity-desc">{canonical.description}</span>
          )}
          <div className="identity-meta">
            <span className="citation-domain">{canonical.qid}</span>
            {canonical.occupations.length > 0 && (
              <span>{canonical.occupations.join(", ")}</span>
            )}
            <span>{canonical.sitelinks} Wikipedia editions</span>
            {canonical.deceased !== null && (
              <span>{canonical.deceased ? "deceased" : "living"}</span>
            )}
          </div>
        </div>
      ) : (
        <p className="identity-reason">{identity.reason}</p>
      )}

      {/* The collision case names the people who do share it. That list is the
          finding: it is what an audience would find if they went looking. */}
      {identity.status === "collision" && (identity.candidates?.length ?? 0) > 0 && (
        <ul className="identity-candidates">
          {identity.candidates?.slice(0, 4).map((c) => (
            <li key={c.qid}>
              <a href={c.url} target="_blank" rel="noreferrer">
                {c.label}
              </a>
              {c.description && <span> — {c.description}</span>}
            </li>
          ))}
        </ul>
      )}

      {identity.web_checked && identity.web_summary && (
        <p className="identity-web">
          {identity.web_summary.replace(/^(EXISTS|NO_RECORD):\s*/i, "")}
          {(identity.web_domains?.length ?? 0) > 0 && (
            <span className="identity-web-domains">
              {" "}
              Searched: {identity.web_domains?.slice(0, 4).join(", ")}.
            </span>
          )}
        </p>
      )}
    </div>
  );
}
