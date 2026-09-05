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
import { AskTheRecord } from "@/components/AskTheRecord";
import {
  AttributionSummary,
  SourceBadge,
  SourcePedigree,
  SourceStance,
} from "@/components/SourcePedigree";
import { RiskAndPrecedent } from "@/components/RiskAndPrecedent";
import { SubjectIdentity } from "@/components/SubjectIdentity";
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
        <RiskAndPrecedent runId={runId} subjectId={annotation.id} />
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

      {/* Who the subject is, established before anything was researched about
          them. A verdict on a claim about nobody is not a verdict, and this is
          where a reviewer finds out which of those they are reading. */}
      <SubjectIdentity identity={claim?.identity ?? element?.identity} />

      {annotation.subject && !claim?.identity && !element?.identity && (
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

      <RiskAndPrecedent runId={runId} subjectId={annotation.id} />

      {/* What the verdict is standing on, counted rather than asserted. A
          citation total on its own hides the two things that decide whether a
          finding is worth anything: how many independent domains are behind
          it, and whether any of them is a record. */}
      <SourcePedigree corroboration={claim?.corroboration ?? element?.corroboration} />

      {/* What the search returned versus what survived reading. The honest
          description of most searches is "six results, one of which is about
          this", and saying so is the difference between a fact checker and a
          search box with a confident voice. */}
      <AttributionSummary attribution={claim?.attribution ?? element?.attribution} />

      <p className="panel-title panel-title-section">
        Sources ({evidence.reduce((n, e) => n + e.citations.length, 0)})
      </p>

      {evidence.length === 0 && (
        <div className="empty">
          {claim?.identity?.status === "unidentified" || claim?.identity?.status === "collision"
            ? "Nothing was researched and nothing is attached. Any source returned for this name would be about somebody else."
            : "No source could be quoted against this claim, so none is attached."}
        </div>
      )}

      {evidence.map((record) => (
        <EvidenceBlock key={record.evidence_id} evidence={record} />
      ))}

      {/* The follow up question, asked against the live record rather than
          against what this run happened to collect. */}
      <AskTheRecord
        runId={runId}
        subjectId={annotation.id}
        subject={claim?.subject_name ?? annotation.subject}
        suggestion={askSuggestion(claim?.claim_text ?? annotation.text, annotation.subject)}
      />
    </div>
  );
}

/** A first question worth asking about this subject, so the box is not blank. */
function askSuggestion(text: string, subject?: string): string {
  const trimmed = text.trim().replace(/\s+/g, " ");
  const short = trimmed.length > 90 ? `${trimmed.slice(0, 90)}…` : trimmed;
  return subject
    ? `What is the source for: ${short} (${subject})`
    : `What is the source for: ${short}`;
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
        {(evidence.independent_domains?.length ?? 0) > 1 && (
          <span>{evidence.independent_domains?.length} independent domains</span>
        )}
        <span>{Math.round(evidence.effective_confidence * 100)}% confidence</span>
      </div>

      {evidence.citations.map((citation, index) => (
        <div className="citation" key={`${citation.url}-${index}`}>
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
            <SourceBadge citation={citation} />
            {citation.domain && <span className="citation-domain">{citation.domain}</span>}
            {/* Retrieval time is not decoration. At claim time, a source read
                on a known date is worth far more than a live URL. */}
            <span>read {new Date(citation.accessed_at).toLocaleDateString()}</span>
            {citation.published_at && (
              <span>published {new Date(citation.published_at).toLocaleDateString()}</span>
            )}
          </div>
          {/* The stance and the verbatim span it rests on. The span was found
              in the retrieved page by string search, so a quote nothing could
              locate never reached this list. */}
          <SourceStance citation={citation} />

          {!citation.quote && citation.excerpt && (
            <p className="citation-excerpt">{citation.excerpt}</p>
          )}
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
