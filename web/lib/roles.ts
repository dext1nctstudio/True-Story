/**
 * What each role's workspace actually is.
 *
 * The role control used to change almost nothing. All four roles landed on the
 * same docket, opened the same script, saw the same rail, and the only visible
 * differences were a hidden cost meter and an evidence panel that said "not
 * for your role". Four buttons producing one screen is worse than no buttons:
 * it advertises a governance model and then fails to demonstrate it.
 *
 * So a role here selects a workspace, not a filter. Each one has its own
 * landing surface, its own rail, its own actions and its own accent, because
 * these are four different jobs:
 *
 *   counsel      decides. Gets the evidence, the register, the queue, the
 *                overrides and the unmask, and is the only role that can.
 *   producer     runs the production. Gets exposure, money and workload, and
 *                is deliberately not given the research: a producer reading
 *                raw findings about a named living person is a discovery
 *                problem, not a feature.
 *   writer       fixes the lines. Gets their draft, the verdicts on it and
 *                the verified rewrites, and nothing about anybody else's.
 *   underwriter  binds the policy. Gets the finished package, watermarked and
 *                read only, and never the working state behind it.
 *
 * Every capability here mirrors VIEW_MATRIX in src/truestory/api/security.py.
 * The server enforces it; this file decides what to build, so a role never
 * renders a panel it would only be refused.
 */

import type { Role } from "./types";

export type HomeSurface = "docket" | "risk" | "desk" | "package";
export type RailTab = "evidence" | "people" | "queue" | "cost" | "monitors" | "report";

export interface RoleCapabilities {
  /** The annotated script itself. */
  overlay: boolean;
  /** Sources, excerpts and reasoning behind a verdict. */
  evidence: boolean;
  /** Research and model spend. */
  cost: boolean;
  /** Reveal a masked private individual. Audited, counsel only. */
  unmask: boolean;
  /** The per person claim register and its amber density meters. */
  register: boolean;
  /** The human review queue. */
  reviewQueue: boolean;
  /** E&O report, clearance log, evidence appendix. */
  reports: boolean;
  /** Living clearance watches. */
  monitors: boolean;
  /** Apply a verified rewrite to the draft. */
  remedies: boolean;
  /** Overrule a machine verdict. Audited. */
  override: boolean;
  /** Start a new run. */
  upload: boolean;
}

export interface RoleView {
  value: Role;
  label: string;
  /** The job, in four or five words. Shown under the role name. */
  role_line: string;
  /** What this role is given. */
  sees: string;
  /** What it is not given, said plainly rather than left as an empty panel. */
  withheld: string;
  home: HomeSurface;
  rail: RailTab[];
  caps: RoleCapabilities;
  /** Per role accent. The chrome itself changes, so the switch is legible. */
  accent: string;
}

export const ROLE_VIEWS: Record<Role, RoleView> = {
  "truestory.counsel": {
    value: "truestory.counsel",
    label: "Counsel",
    role_line: "Production counsel · the accountable human",
    sees: "Everything: the evidence behind every verdict, the person register, the review queue, and the audited overrides.",
    withheld: "Nothing is withheld from this role.",
    home: "docket",
    rail: ["evidence", "people", "queue", "cost", "monitors", "report"],
    accent: "#5d9ad4",
    caps: {
      overlay: true,
      evidence: true,
      cost: true,
      unmask: true,
      register: true,
      reviewQueue: true,
      reports: true,
      monitors: true,
      remedies: true,
      override: true,
      upload: true,
    },
  },

  "truestory.producer": {
    value: "truestory.producer",
    label: "Producer",
    role_line: "Production · exposure, spend and schedule",
    sees: "Exposure by person and by scene, what the run cost against a manual report, counsel workload, and every live watch.",
    withheld:
      "The research itself. A producer reading raw findings about a named living person creates a discovery problem rather than solving one.",
    home: "risk",
    rail: ["queue", "people", "cost", "monitors"],
    accent: "#c08a3e",
    caps: {
      overlay: true,
      evidence: false,
      cost: true,
      unmask: false,
      register: true,
      reviewQueue: true,
      reports: true,
      monitors: true,
      remedies: false,
      override: false,
      upload: true,
    },
  },

  "truestory.writer": {
    value: "truestory.writer",
    label: "Writer",
    role_line: "Writers room · this draft only",
    sees: "Your draft with every line marked, the verified rewrite for each one, and nothing from any other project.",
    withheld:
      "Cost, the evidence, the person register and the review queue. A rewrite does not need the docket behind it.",
    home: "desk",
    rail: ["evidence"],
    accent: "#6ba98a",
    caps: {
      overlay: true,
      evidence: false,
      cost: false,
      unmask: false,
      register: false,
      reviewQueue: false,
      reports: false,
      monitors: false,
      remedies: true,
      override: false,
      upload: true,
    },
  },

  "truestory.underwriter": {
    value: "truestory.underwriter",
    label: "Underwriter",
    role_line: "E&O carrier · outside the trust boundary",
    sees: "The finished package: the report, the clearance log and the evidence appendix, watermarked and read only.",
    withheld:
      "The working draft, the live cost, the review queue and every unresolved item. A carrier is given a filed document, not a workspace.",
    home: "package",
    rail: ["report", "evidence", "monitors"],
    accent: "#8f83c4",
    caps: {
      overlay: false,
      evidence: true,
      cost: false,
      unmask: false,
      register: false,
      reviewQueue: false,
      reports: true,
      monitors: true,
      remedies: false,
      override: false,
      upload: false,
    },
  },
};

export const ROLE_LIST: RoleView[] = [
  ROLE_VIEWS["truestory.counsel"],
  ROLE_VIEWS["truestory.producer"],
  ROLE_VIEWS["truestory.writer"],
  ROLE_VIEWS["truestory.underwriter"],
];

export function viewFor(role: Role): RoleView {
  return ROLE_VIEWS[role] ?? ROLE_VIEWS["truestory.counsel"];
}

/** Labels for the rail tabs, kept beside the role config they belong to. */
export const TAB_LABEL: Record<RailTab, string> = {
  evidence: "Evidence",
  people: "People",
  queue: "Queue",
  cost: "Cost",
  monitors: "Watches",
  report: "Package",
};
