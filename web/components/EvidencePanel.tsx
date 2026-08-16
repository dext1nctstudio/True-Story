"use client";

/**
 * The evidence panel. What opens when a red line is clicked.
 *
 * The decomposed claim, the verdict in the rubric's own fixed wording, the
 * confidence, the citations with excerpts and retrieval timestamps, and the
 * proposed rewrite that has itself been verified against the record.
 *
 * The wording is deliberately not restated here. UNSUPPORTED is not FALSE, and
 * the sentence saying so comes from policy/rubric.yaml so that the UI, the PDF
 * and the API can never drift apart on the one distinction that matters most.
 */

import { useState } from "react";
import { applyRemedy, unmaskElement } from "@/lib/api";
import type { Annotation, Claim, ClearableElement, Evidence, Remedy } from "@/lib/types";

interface Props {
  runId: string;
  annotation: Annotation | null;
  claim: Claim | null;
  /** The selected subject when the annotation is a clearance element rather
   *  than a claim. Without it an element opened with "no evidence records
   *  attached" even when its research had returned sources. */
  element?: ClearableElement | null;
  remedy: Remedy | null;
  canSeeEvidence: boolean;
  canUnmask: boolean;
  onApplied?: (remedyId: string) => void;
}

export function EvidencePanel({
  runId,
  annotation,
  claim,
  element,
  remedy,
  canSeeEvidence,
  canUnmask,
  onApplied,
}: Props) {
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [revealed, setRevealed] = useState(false);

  if (!annotation) {
    return (
      <div className="empty">
        Select any highlighted line to see the claim as decomposed, the verdict,
        and the sources behind it.
      </div>
    );
  }

  // The governance model made visible. A writer sees verdicts and rewrites,
  // never the research behind them, and this panel says so rather than
  // silently rendering an empty box.
  if (!canSeeEvidence) {
    return (
      <div className="panel">
        <p className="panel-title">Verdict</p>
        <VerdictHeader annotation={annotation} />
        <div className="claim-text">{annotation.text}</div>
        <p className="verdict-language">{annotation.language}</p>
        <div className="empty">
          Evidence is visible to production counsel and to the underwriter. Your
          role sees the verdict and the proposed rewrite.
        </div>
        {remedy && <RemedyBlock remedy={remedy} applying={applying} applied={applied} onApply={apply} />}
      </div>
    );
  }

  // A selected line is either a decomposed claim or a clearance element, and
  // each carries its own evidence records.
  const evidence = claim?.evidence ?? element?.evidence ?? [];

  async function apply() {
    if (!remedy || !claim) return;
    setApplying(true);
    try {
      await applyRemedy(runId, claim.claim_id, remedy.remedy_id);
      setApplied(true);
      onApplied?.(remedy.remedy_id);
    } finally {
      setApplying(false);
    }
  }

  async function reveal() {
    if (!annotation) return;
    await unmaskElement(runId, annotation.id, "counsel review of a collision match");
    setRevealed(true);
  }

  return (
    <div className="panel">
      <p className="panel-title">
        {annotation.kind === "claim" ? "Factual claim" : "Clearance element"}
      </p>

      <VerdictHeader annotation={annotation} />

      {annotation.subject && (
        <p className="citation-meta">Subject: {annotation.subject}</p>
      )}

      <div className="claim-text">{claim?.claim_text ?? annotation.text}</div>

      {/* The fixed rubric wording. This is the sentence that keeps
          "unsupported" from being read as "false". */}
      {annotation.language && <p className="verdict-language">{annotation.language}</p>}

      {claim?.rationale && <p className="evidence-rationale">{claim.rationale}</p>}

      {annotation.needs_counsel && (
        <div className="queue-item-head">
          <span className="counsel-flag">counsel review</span>
          <span className="queue-item-subject">{claim?.counsel_reason}</span>
        </div>
      )}

      {annotation.masked && !revealed && (
        <div className="warning">
          <p>
            Identifying details are withheld by default. This concerns a living
            private individual.
          </p>
          {canUnmask && (
            <button className="apply reveal-action" onClick={reveal}>
              Reveal, audited
            </button>
          )}
        </div>
      )}

      {remedy && (
        <RemedyBlock remedy={remedy} applying={applying} applied={applied} onApply={apply} />
      )}

      <p className="panel-title panel-title-section">
        Sources ({evidence.reduce((n, e) => n + e.citations.length, 0)})
      </p>

      {evidence.length === 0 && (
        <div className="empty">No evidence records attached to this subject.</div>
      )}

      {evidence.map((record) => (
        <EvidenceBlock key={record.evidence_id} evidence={record} />
      ))}
    </div>
  );
}

function VerdictHeader({ annotation }: { annotation: Annotation }) {
  return (
    <div className="verdict-header">
      <span className={`verdict-pill ${annotation.color}`}>
        {annotation.verdict ?? annotation.status ?? "pending"}
      </span>
      <span className="confidence">
        {Math.round(annotation.confidence * 100)}% confidence
      </span>
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence: Evidence }) {
  return (
    <div className="evidence-record">
      {/* Provider, degradation and confidence, separated by rules rather than
          by punctuation, so each field stays its own readable unit. */}
      <div className="meta-strip">
        <span>{evidence.provider}</span>
        {evidence.is_fallback && <span>fallback, confidence capped</span>}
        {evidence.cached && <span>cached</span>}
        <span>{Math.round(evidence.effective_confidence * 100)}% confidence</span>
      </div>

      {evidence.citations.map((citation) => (
        <div className="citation" key={citation.url}>
          <a
            className="citation-title"
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {citation.title}
          </a>
          <div className="citation-meta">
            <span className={`source-tag ${citation.source_type}`}>
              {citation.source_type}
            </span>
            {/* Retrieval time is not decoration. At claim time, a source read
                on a known date is worth far more than a live URL. */}
            <span>read {new Date(citation.accessed_at).toLocaleDateString()}</span>
          </div>
          {citation.excerpt && <p className="citation-excerpt">{citation.excerpt}</p>}
        </div>
      ))}
    </div>
  );
}

function RemedyBlock({
  remedy,
  applying,
  applied,
  onApply,
}: {
  remedy: Remedy;
  applying: boolean;
  applied: boolean;
  onApply: () => void;
}) {
  return (
    <div className="remedy">
      <span className="remedy-label">
        {remedy.verified ? "Verified rewrite" : "Proposed, not yet verified"}
      </span>
      <div className="remedy-proposal">{remedy.proposal}</div>
      <p className="remedy-rationale">{remedy.rationale}</p>

      {remedy.alternatives.length > 0 && (
        <p className="remedy-alternatives">
          Alternatives: {remedy.alternatives.join(", ")}
        </p>
      )}

      {/* Only a remedy that came back verified through the same research path
          can be applied. A proposal that never verified is not a fix. */}
      <button className="apply" disabled={!remedy.verified || applying || applied} onClick={onApply}>
        {applied ? "Applied" : applying ? "Applying" : "Apply redline"}
      </button>
    </div>
  );
}
