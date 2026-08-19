"use client";

/**
 * The writers room view: the lines to fix, and nothing else.
 *
 * A writer does not need the docket, the spend, or the research. They need to
 * know which of their lines the record will not carry, in page order, with a
 * rewrite that has itself been checked. So this is a worklist rather than a
 * dashboard, and it is the only surface in the product that leads with the
 * proposed sentence instead of with the verdict.
 *
 * Only a rewrite that came back verified through the same research path can be
 * applied. A proposal that never verified is a suggestion, and it is labelled
 * as one rather than being quietly applyable.
 */

import { useMemo, useState } from "react";
import { applyRemedy, pageRef } from "@/lib/api";
import type { Claim, Remedy } from "@/lib/types";

interface Props {
  runId: string;
  claims: Claim[];
  remedies: Remedy[];
  onOpenLine: (claimId: string) => void;
  canApply: boolean;
}

export function WriterDesk({ runId, claims, remedies, onOpenLine, canApply }: Props) {
  const [applied, setApplied] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);

  const work = useMemo(() => {
    const byId = new Map(remedies.map((r) => [r.remedy_id, r]));
    return claims
      .filter((c) => c.color === "red" || c.color === "amber")
      .map((claim) => ({ claim, remedy: claim.remedy_id ? byId.get(claim.remedy_id) : undefined }))
      .sort((a, b) => {
        // Contradicted first, then by page. A writer works the script in order
        // once the emergencies are out of the way.
        if (a.claim.color !== b.claim.color) return a.claim.color === "red" ? -1 : 1;
        return (a.claim.occurrences[0]?.page ?? 0) - (b.claim.occurrences[0]?.page ?? 0);
      });
  }, [claims, remedies]);

  const withFix = work.filter((w) => w.remedy?.verified).length;

  async function apply(claimId: string, remedyId: string) {
    setBusy(claimId);
    try {
      await applyRemedy(runId, claimId, remedyId);
      setApplied((prev) => new Set(prev).add(claimId));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="desk">
      <header className="board-head">
        <h1 className="board-title">Lines to look at</h1>
        <p className="board-sub">
          {work.length} line{work.length === 1 ? "" : "s"} the public record does not carry
          as written{withFix > 0 && `, ${withFix} with a rewrite already checked against it`}.
        </p>
      </header>

      {work.length === 0 && (
        <div className="empty">
          Nothing in this draft is contradicted or unsupported. Every claim about a real
          person checks out against the record.
        </div>
      )}

      <div className="desk-list">
        {work.map(({ claim, remedy }) => {
          const isApplied = applied.has(claim.claim_id);
          return (
            <article className={`desk-card ${claim.color}`} key={claim.claim_id}>
              <div className="desk-card-head">
                <span className={`verdict-pill ${claim.color}`}>
                  {claim.verdict?.toLowerCase() ?? "pending"}
                </span>
                <button className="desk-locate" onClick={() => onOpenLine(claim.claim_id)}>
                  page {pageRef(claim.occurrences[0])}
                  {claim.occurrences[0]?.character_cue
                    ? ` · ${claim.occurrences[0].character_cue}`
                    : ""}
                </button>
              </div>

              <p className="desk-original">{claim.claim_text}</p>

              {/* The rubric's own wording. "Unsupported" is not "false", and
                  the sentence that keeps those apart is not paraphrased here. */}
              {claim.rationale && <p className="desk-why">{claim.rationale}</p>}

              {remedy ? (
                <div className="desk-fix">
                  <span className="remedy-label">
                    {remedy.verified ? "Verified rewrite" : "Suggested, not yet verified"}
                  </span>
                  <p className="desk-proposal">{remedy.proposal}</p>
                  {remedy.rationale && <p className="desk-why">{remedy.rationale}</p>}
                  {remedy.alternatives.length > 0 && (
                    <p className="remedy-alternatives">
                      Alternatives: {remedy.alternatives.join(" · ")}
                    </p>
                  )}
                  {remedy.preserves_beat && (
                    <p className="desk-beat">Keeps the beat the scene is built on.</p>
                  )}
                  <button
                    className="apply"
                    disabled={!canApply || !remedy.verified || isApplied || busy === claim.claim_id}
                    onClick={() => apply(claim.claim_id, remedy.remedy_id)}
                  >
                    {isApplied
                      ? "Applied"
                      : busy === claim.claim_id
                        ? "Applying"
                        : "Apply redline"}
                  </button>
                </div>
              ) : (
                <p className="desk-nofix">
                  No rewrite proposed. This one needs a decision rather than a sentence.
                </p>
              )}
            </article>
          );
        })}
      </div>

      <p className="disclaimer">
        You are seeing your own draft and the rewrites for it. The research behind each
        verdict, the other projects on this docket and the production&rsquo;s spend are
        not part of this workspace.
      </p>
    </div>
  );
}
