"use client";

/**
 * The verdict overlay. The single most important surface in the product.
 *
 * A screenplay rendered in proper Courier at industry margins, with every line
 * that makes a factual claim about a real person lit against the record.
 * Green is a quiet underline, amber is visible, red is unmissable, and opinion
 * is left completely untouched because defamation law protects it.
 *
 * Restraint is the design language. A page drowning in highlights reads as
 * noise, so red has to stay rare to stay legible. Clicking any annotated line
 * opens the evidence panel with the decomposed claim, the verdict, the
 * citations and the proposed rewrite.
 */

import { useEffect, useMemo, useRef } from "react";
import type { Annotation, Overlay, Scene } from "@/lib/types";

interface Props {
  overlay: Overlay;
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
  /** Set by clicking a header counter. Non matching lines fade rather than
   *  disappear, since the script's shape and page count stay useful context
   *  while scanning for, say, every contradiction. */
  filterColor?: string | null;
}

export function VerdictOverlay({ overlay, selectedId, onSelect, filterColor = null }: Props) {
  const paneRef = useRef<HTMLDivElement>(null);

  // Scroll the first match into view when a filter is applied. A feature
  // length script can hold a single opinion line among a hundred and seventy
  // others, so filtering without this fades the whole visible page and leaves
  // the one match far below the fold: indistinguishable from nothing matching.
  useEffect(() => {
    if (!filterColor || !paneRef.current) return;
    const first = paneRef.current.querySelector<HTMLElement>(
      ".annotated:not(.faded)",
    );
    first?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [filterColor]);

  return (
    <div className="script-pane" ref={paneRef}>
      <div className="script-page">
        {overlay.scenes.map((scene) => (
          <SceneBlock
            key={scene.scene_no}
            scene={scene}
            annotations={overlay.annotations}
            selectedId={selectedId}
            onSelect={onSelect}
            filterColor={filterColor}
          />
        ))}
      </div>
    </div>
  );
}

function SceneBlock({
  scene,
  annotations,
  selectedId,
  onSelect,
  filterColor,
}: {
  scene: Scene;
  annotations: Record<string, Annotation[]>;
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
  filterColor: string | null;
}) {
  const lines = useMemo(() => scene.text.split("\n"), [scene.text]);

  return (
    <div data-scene={scene.scene_no}>
      {lines.map((line, index) => {
        const key = `${scene.scene_no}:${index}`;
        const lineAnnotations = annotations[key] ?? [];

        if (isSceneHeading(line)) {
          return (
            <div key={key} className="scene-heading">
              {line.trim()}
            </div>
          );
        }

        return (
          <ScriptLine
            key={key}
            lineKey={key}
            text={line}
            annotations={lineAnnotations}
            selectedId={selectedId}
            onSelect={onSelect}
            filterColor={filterColor}
          />
        );
      })}
    </div>
  );
}

function ScriptLine({
  lineKey,
  text,
  annotations,
  selectedId,
  onSelect,
  filterColor,
}: {
  lineKey: string;
  text: string;
  annotations: Annotation[];
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
  filterColor: string | null;
}) {
  const indent = classifyIndent(text);

  if (annotations.length === 0) {
    return <div className={`script-line ${indent}`}>{text || " "}</div>;
  }

  // When several annotations land on one line, the most severe one owns the
  // line's colour. A red claim and a cleared element on the same line is red.
  const worst = annotations.reduce((acc, current) =>
    severity(current.color) > severity(acc.color) ? current : acc,
  );

  // The header counters count claim verdicts, so the filters they drive must
  // only ever match claims. Elements share the same colour space for an
  // entirely different question, green on an element means the rights are
  // cleared, not that anything is true, and matching those made the line
  // "The Eiffel Tower is in London" light up as verified because the Eiffel
  // Tower is cleared to depict. In a defamation tool that is the worst
  // possible way to be wrong.
  //
  // Severity ranking still means a line carrying six verified claims and one
  // amber element renders amber, so the match is found across all claims on
  // the line rather than just the dominant annotation.
  const match = filterColor
    ? annotations.find((a) => a.kind === "claim" && a.color === filterColor)
    : undefined;
  const dominant = match ?? worst;
  const isSelected = annotations.some((a) => a.id === selectedId);
  const isFiltered = filterColor !== null && !match;

  return (
    <div
      data-verdict-line={lineKey}
      data-color={dominant.color}
      className={[
        "script-line",
        indent,
        "annotated",
        dominant.color,
        isSelected ? "selected" : "",
        isFiltered ? "faded" : "",
        // Opinion is deliberately almost unmarked, so filtering to it left the
        // one match visually indistinguishable from the faded rest and read as
        // nothing having happened. A match under an active filter is marked
        // explicitly rather than relying on its verdict colour.
        match ? "matched" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      /* Opinion lines used to be inert, on the reasoning that an opinion is
         never researched so there is nothing to show. But the panel does have
         something to say, the decomposed claim and why it was classified as
         characterisation rather than fact, and a line that visibly carries a
         verdict but refuses to open reads as broken. */
      onClick={() => onSelect(dominant)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect(dominant);
        }
      }}
      role="button"
      tabIndex={0}
      title={annotationTitle(dominant)}
    >
      {dominant.masked ? <span className="mask-chip">{dominant.text}</span> : text || " "}

      {/* The badge only appears on contradictions. It is the count of sources
          that say otherwise, which is the number that matters on screen. */}
      {dominant.color === "red" && dominant.citation_count > 0 && (
        <span className="citation-badge">{dominant.citation_count}</span>
      )}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function severity(color: string): number {
  return { red: 4, amber: 3, pending: 2, green: 1, grey: 0 }[color] ?? 0;
}

function isSceneHeading(line: string): boolean {
  return /^\s*(INT|EXT|INT\.?\/EXT|I\/E)[.\s]/i.test(line);
}

/** Screenplay geometry. Cue blocks, dialogue and parentheticals each have a
 *  fixed indent, and getting them wrong is immediately visible to anyone from
 *  the industry. */
function classifyIndent(line: string): string {
  const trimmed = line.trim();
  if (!trimmed) return "";
  if (/^\(.*\)$/.test(trimmed)) return "paren";
  if (/^[A-Z][A-Z0-9 '.\-]{1,38}(\s*\(.*\))?$/.test(trimmed) && trimmed.length < 40) return "cue";
  return "";
}

function annotationTitle(annotation: Annotation): string {
  const verdict = annotation.verdict ?? annotation.status ?? "pending";
  const confidence = `${Math.round(annotation.confidence * 100)}% confidence`;
  const counsel = annotation.needs_counsel ? ", counsel review" : "";
  return `${verdict}, ${annotation.citation_count} sources, ${confidence}${counsel}`;
}
