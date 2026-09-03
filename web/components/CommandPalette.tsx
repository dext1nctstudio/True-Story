"use client";

/**
 * ⌘K.
 *
 * A feature length script produces two hundred subjects, and finding the one
 * you are thinking about by scrolling a script pane is the difference between
 * a demo and a tool someone uses for six hours. This searches every claim,
 * every clearance element and every named person in the run, and carries the
 * filters and exports as commands so the keyboard reaches everything the mouse
 * does.
 *
 * Matching is a plain subsequence score rather than a fuzzy search library:
 * the corpus is a few hundred short strings, it runs in under a millisecond,
 * and it does not add a dependency to a page that currently has three.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pageRef } from "@/lib/api";
import type { Claim, ClearableElement, PersonRollup } from "@/lib/types";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  claims: Claim[];
  elements: ClearableElement[];
  persons: PersonRollup[];
  commands: Command[];
  onSelectClaim: (claimId: string) => void;
  onSelectElement: (elementId: string) => void;
}

export function CommandPalette({
  open,
  onClose,
  claims,
  elements,
  persons,
  commands,
  onSelectClaim,
  onSelectElement,
}: Props) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // The frame delay matters: focusing before the element is painted loses
      // the first keystroke, which is exactly the one someone typed on purpose.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const entries = useMemo<Command[]>(() => {
    const rows: Command[] = [...commands];

    for (const claim of claims) {
      rows.push({
        id: `claim:${claim.claim_id}`,
        label: claim.claim_text,
        hint: `${claim.subject_name} · p ${pageRef(claim.occurrences[0])} · ${
          claim.verdict?.toLowerCase() ?? "pending"
        }`,
        group: "Claims",
        run: () => onSelectClaim(claim.claim_id),
      });
    }

    for (const element of elements) {
      rows.push({
        id: `element:${element.element_id}`,
        label: element.display_form || element.canonical_form || element.element_id,
        hint: `${element.element_type.replace(/_/g, " ").toLowerCase()} · ${element.status
          .replace(/_/g, " ")
          .toLowerCase()}`,
        group: "Elements",
        run: () => onSelectElement(element.element_id),
      });
    }

    for (const person of persons) {
      rows.push({
        id: `person:${person.element_id}`,
        label: person.person_name,
        hint: `${person.total_claims} claims · ${person.amber_count} unsupported`,
        group: "People",
        run: () => onSelectElement(person.element_id),
      });
    }

    return rows;
  }, [claims, commands, elements, onSelectClaim, onSelectElement, persons]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries.slice(0, 40);
    return entries
      .map((entry) => ({ entry, score: score(`${entry.label} ${entry.hint ?? ""}`, q) }))
      .filter((row) => row.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 40)
      .map((row) => row.entry);
  }, [entries, query]);

  const choose = useCallback(
    (entry: Command | undefined) => {
      if (!entry) return;
      entry.run();
      onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((c) => Math.min(c + 1, results.length - 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        choose(results[cursor]);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [choose, cursor, onClose, open, results]);

  if (!open) return null;

  let lastGroup = "";

  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-label="Command palette"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input suppressHydrationWarning
          ref={inputRef}
          className="palette-input"
          value={query}
          placeholder="Search claims, elements, people, or type a command"
          onChange={(event) => {
            setQuery(event.target.value);
            setCursor(0);
          }}
        />

        <div className="palette-results">
          {results.length === 0 && <div className="palette-empty">Nothing matches that.</div>}
          {results.map((entry, index) => {
            const showGroup = entry.group !== lastGroup;
            lastGroup = entry.group;
            return (
              <div key={entry.id}>
                {showGroup && <div className="palette-group">{entry.group}</div>}
                <button suppressHydrationWarning
                  className={`palette-row ${index === cursor ? "active" : ""}`}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => choose(entry)}
                >
                  <span className="palette-row-label">{entry.label}</span>
                  {entry.hint && <span className="palette-row-hint">{entry.hint}</span>}
                </button>
              </div>
            );
          })}
        </div>

        <div className="palette-foot">
          <kbd>↑</kbd>
          <kbd>↓</kbd>
          <span>navigate</span>
          <kbd>↵</kbd>
          <span>open</span>
          <kbd>esc</kbd>
          <span>close</span>
        </div>
      </div>
    </div>
  );
}

/** Subsequence match, with a bonus for hits at a word boundary. */
function score(haystack: string, needle: string): number {
  const text = haystack.toLowerCase();
  if (text.includes(needle)) return 100 + (text.startsWith(needle) ? 50 : 0);

  let index = 0;
  let points = 0;
  for (const char of needle) {
    const found = text.indexOf(char, index);
    if (found === -1) return 0;
    points += found === 0 || text[found - 1] === " " ? 3 : 1;
    index = found + 1;
  }
  return points;
}
