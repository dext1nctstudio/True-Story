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

import { useMemo } from "react";
import type { Annotation, Overlay, Scene } from "@/lib/types";

interface Props {
  overlay: Overlay;
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
}

export function VerdictOverlay({ overlay, selectedId, onSelect }: Props) {
  return (
    <div className="script-pane">
      <div className="script-page">
        {overlay.scenes.map((scene) => (
          <SceneBlock
            key={scene.scene_no}
            scene={scene}
            annotations={overlay.annotations}
            selectedId={selectedId}
            onSelect={onSelect}
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
}: {
  scene: Scene;
  annotations: Record<string, Annotation[]>;
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
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
            text={line}
            annotations={lineAnnotations}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        );
      })}
    </div>
  );
}

function ScriptLine({
  text,
  annotations,
  selectedId,
  onSelect,
}: {
  text: string;
  annotations: Annotation[];
  selectedId: string | null;
  onSelect: (annotation: Annotation) => void;
}) {
  const indent = classifyIndent(text);

  if (annotations.length === 0) {
    return <div className={`script-line ${indent}`}>{text || " "}</div>;
  }

  // When several annotations land on one line, the most severe one owns the
  // line's colour. A red claim and a cleared element on the same line is red.
  const dominant = annotations.reduce((worst, current) =>
    severity(current.color) > severity(worst.color) ? current : worst,
  );

  const isOpinion = dominant.color === "grey";
  const isSelected = annotations.some((a) => a.id === selectedId);

  return (
    <div
      className={[
        "script-line",
        indent,
        "annotated",
        dominant.color,
        isSelected ? "selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => !isOpinion && onSelect(dominant)}
      onKeyDown={(event) => {
        if (!isOpinion && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onSelect(dominant);
        }
      }}
      role={isOpinion ? undefined : "button"}
      tabIndex={isOpinion ? undefined : 0}
      title={annotationTitle(dominant)}
    >
      {dominant.masked ? <span className="mask-chip">{dominant.text}</span> : text || " "}

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
  const counsel = annotation.needs_counsel ? " · counsel review" : "";
  return `${verdict} · ${annotation.citation_count} sources · ${confidence}${counsel}`;
}
