"use client";

/**
 * "Why is this line red?"
 *
 * The most common thing a reviewer does with a verdict is ask a follow up, and
 * until this existed the only available answer was whatever the run happened
 * to have collected. This asks the live record instead: one search round trip,
 * a tenth of a cent, sources back with excerpts.
 *
 * What it returns is a lead, and the panel says so in those words. It never
 * enters adjudication, never changes the verdict on screen, and the provider
 * caps its confidence for the same reason: excerpts from a single round trip
 * are not a multi hop verification and must never present as one.
 */

import { useState } from "react";
import { SourceBadge } from "@/components/SourcePedigree";
import { ApiError, interrogate } from "@/lib/api";
import type { Evidence } from "@/lib/types";

interface Props {
  runId: string;
  subjectId: string;
  subject?: string;
  /** Seeded from the claim, so the common case is one click. */
  suggestion: string;
}

export function AskTheRecord({ runId, subjectId, subject, suggestion }: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (trimmed.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await interrogate(runId, { question: trimmed, subject_id: subjectId, subject }));
    } catch (exc) {
      setError(exc instanceof ApiError ? `Search failed: ${exc.message}` : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ask">
      <p className="panel-title panel-title-section">Ask the record</p>

      <div className="ask-row">
        <input
          className="ask-input"
          value={question}
          placeholder={suggestion}
          disabled={busy}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void ask(question || suggestion);
          }}
        />
        <button className="btn" disabled={busy} onClick={() => void ask(question || suggestion)}>
          {busy ? "Searching" : "Search"}
        </button>
      </div>

      <p className="cost-note">
        A live search round trip against the public record, about a tenth of a cent.
        What comes back is a lead for a human to read, not a verdict: it does not
        change the finding above it.
      </p>

      {error && <div className="warning">{error}</div>}

      {answer && (
        <div className="ask-answer">
          <div className="meta-strip">
            <span>{answer.provider}</span>
            <span>{answer.citations.length} passages</span>
            <span>{Math.round(answer.effective_confidence * 100)}% confidence, capped</span>
          </div>

          {answer.citations.length === 0 && (
            <div className="empty">Nothing came back for that question.</div>
          )}

          {answer.citations.map((citation, index) => (
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
                <SourceBadge citation={citation} />
                {citation.domain && <span className="citation-domain">{citation.domain}</span>}
              </div>
              {citation.excerpt && <p className="citation-excerpt">{citation.excerpt}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
