"use client";

/**
 * The role switch.
 *
 * Four seconds of the demo, and instantly legible governance: switch to the
 * writer and the evidence panel simply is not there. That says more about the
 * IAM model than any architecture slide, because the audience sees a
 * capability disappear rather than being told one exists.
 *
 * In deployment the role is a verified claim on the identity token in front of
 * the service and is not selectable at all. This control exists so the demo
 * can show four views of one document without four logins.
 */

import { setRole } from "@/lib/api";
import type { Role } from "@/lib/types";

const ROLES: { value: Role; label: string; sees: string }[] = [
  {
    value: "truestory.counsel",
    label: "Counsel",
    sees: "Everything, including unmasked identities and full evidence.",
  },
  {
    value: "truestory.producer",
    label: "Producer",
    sees: "Verdict counts, risk posture, cost and alerts. Not the evidence.",
  },
  {
    value: "truestory.writer",
    label: "Writer",
    sees: "Their own draft's overlay and rewrites. No cross project access.",
  },
  {
    value: "truestory.underwriter",
    label: "Underwriter",
    sees: "The final package, read only and watermarked. External party.",
  },
];

export function RoleSwitcher({
  role,
  onChange,
}: {
  role: Role;
  onChange: (role: Role) => void;
}) {
  const current = ROLES.find((r) => r.value === role);

  return (
    <select
      className="role-select"
      value={role}
      title={current?.sees}
      onChange={(event) => {
        const next = event.target.value as Role;
        setRole(next);
        onChange(next);
      }}
    >
      {ROLES.map((entry) => (
        <option key={entry.value} value={entry.value}>
          {entry.label}
        </option>
      ))}
    </select>
  );
}

/** What each role may see. Mirrors VIEW_MATRIX in api/security.py exactly. */
export const CAPABILITIES: Record<Role, { evidence: boolean; cost: boolean; unmask: boolean }> = {
  "truestory.counsel": { evidence: true, cost: true, unmask: true },
  "truestory.producer": { evidence: false, cost: true, unmask: false },
  "truestory.writer": { evidence: false, cost: false, unmask: false },
  "truestory.underwriter": { evidence: true, cost: false, unmask: false },
};
