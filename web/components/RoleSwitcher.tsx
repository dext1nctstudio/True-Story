"use client";

/**
 * The role switch.
 *
 * A dropdown of four words was the wrong control for this, because the thing
 * being chosen is a workspace and the dropdown showed no sign of that. This is
 * a segmented control that carries the role's accent, and choosing one states
 * in a sentence what the role is given and what it is not, so the governance
 * model is read rather than inferred from an absence.
 *
 * In deployment the role is a verified claim on the identity token in front of
 * the service and is not selectable at all. This control exists so one
 * document can be seen through four eyes without four logins.
 */

import { useEffect, useRef, useState } from "react";
import { setRole } from "@/lib/api";
import { ROLE_LIST, viewFor } from "@/lib/roles";
import type { Role } from "@/lib/types";

export function RoleSwitcher({
  role,
  onChange,
}: {
  role: Role;
  onChange: (role: Role) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const current = viewFor(role);

  // Click outside and Escape both close it. A popover that only closes by
  // re-clicking the trigger is the kind of thing that reads as unfinished.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function pick(next: Role) {
    setRole(next);
    onChange(next);
    setOpen(false);
  }

  return (
    <div className="role-switch" ref={wrapRef}>
      <button suppressHydrationWarning
        className="role-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        title="Switch role. Each role is a different workspace."
      >
        <span className="role-dot" style={{ background: current.accent }} />
        <span className="role-trigger-label">{current.label}</span>
        <span className="role-caret" aria-hidden>
          ▾
        </span>
      </button>

      {open && (
        <div className="role-menu" role="listbox">
          <p className="role-menu-head">
            One document, four workspaces. The server enforces this, not the page.
          </p>
          {ROLE_LIST.map((entry) => (
            <button suppressHydrationWarning
              key={entry.value}
              role="option"
              aria-selected={entry.value === role}
              className={`role-option ${entry.value === role ? "active" : ""}`}
              onClick={() => pick(entry.value)}
            >
              <span className="role-option-head">
                <span className="role-dot" style={{ background: entry.accent }} />
                <span className="role-option-label">{entry.label}</span>
                {entry.value === role && <span className="role-current">current</span>}
              </span>
              <span className="role-option-line">{entry.role_line}</span>
              <span className="role-option-sees">{entry.sees}</span>
              {entry.caps.evidence && entry.caps.cost && entry.caps.unmask ? null : (
                <span className="role-option-withheld">Withheld · {entry.withheld}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
