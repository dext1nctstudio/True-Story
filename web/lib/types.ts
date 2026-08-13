/**
 * Shared types.
 *
 * These mirror the Python dataclasses in src/truestory/models exactly. The
 * verdict vocabulary in particular is not restated or reinterpreted here: the
 * distinction between UNSUPPORTED and CONTRADICTED is load bearing, and the
 * UI reads its wording from the rubric rather than inventing its own.
 */

export type Verdict =
  | "VERIFIED"
  | "UNSUPPORTED"
  | "CONTRADICTED"
  | "UNVERIFIABLE"
  | "OPINION";

export type ClearanceStatus =
  | "CLEAR"
  | "CLEAR_WITH_CONDITIONS"
  | "NOT_CLEAR"
  | "NEEDS_LICENSE"
  | "NEEDS_COUNSEL"
  | "PENDING"
  | "RESEARCH_FAILED";

export type VerdictColor = "green" | "amber" | "red" | "grey" | "pending";

export type RiskTier = "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type Role =
  | "truestory.counsel"
  | "truestory.producer"
  | "truestory.writer"
  | "truestory.underwriter";

export interface Citation {
  url: string;
  title: string;
  excerpt: string;
  accessed_at: string;
  source_type: "primary" | "secondary" | "tertiary";
  publisher?: string | null;
}

export interface Evidence {
  evidence_id: string;
  subject_id: string;
  question: string;
  finding: Record<string, unknown>;
  citations: Citation[];
  reasoning: string;
  confidence: number;
  effective_confidence: number;
  provider: string;
  is_fallback: boolean;
  cost_cents: number;
  latency_ms: number;
  cached: boolean;
  retrieved_at: string;
  error?: string | null;
}

export interface Occurrence {
  scene_no: number;
  page: number;
  page_eighths: string;
  line_no: number;
  modality: string;
  surface_form: string;
  context: string;
  character_cue?: string | null;
}

export interface Claim {
  claim_id: string;
  subject_element_id: string;
  subject_name: string;
  claim_text: string;
  claim_type: string;
  polarity: "positive" | "neutral" | "negative";
  risk_tier: RiskTier;
  verdict: Verdict | null;
  color: VerdictColor;
  confidence: number;
  rationale: string;
  needs_counsel: boolean;
  counsel_reason: string;
  remedy_id?: string | null;
  citation_count: number;
  occurrences: Occurrence[];
  evidence?: Evidence[];
}

export interface ClearableElement {
  element_id: string;
  element_type: string;
  /** Null when masked and the caller is not counsel. */
  canonical_form: string | null;
  display_form: string;
  masked: boolean;
  risk_tier: RiskTier;
  status: ClearanceStatus;
  confidence: number;
  rationale: string;
  conditions: string[];
  needs_counsel: boolean;
  counsel_reason: string;
  occurrence_count: number;
  first_page: number;
  citation_count: number;
  escalated_by: string[];
  occurrences: Occurrence[];
  evidence?: Evidence[];
}

export interface Remedy {
  remedy_id: string;
  subject_id: string;
  kind: string;
  proposal: string;
  original: string;
  rationale: string;
  verified: boolean;
  iteration: number;
  preserves_beat: boolean;
  alternatives: string[];
}

/** One annotated span in the overlay. */
export interface Annotation {
  kind: "claim" | "element";
  id: string;
  text: string;
  surface_form: string;
  color: VerdictColor;
  confidence: number;
  citation_count: number;
  needs_counsel: boolean;
  verdict?: Verdict | null;
  status?: ClearanceStatus;
  subject?: string;
  element_type?: string;
  polarity?: string;
  masked?: boolean;
  remedy_id?: string | null;
  language?: string;
}

export interface Scene {
  scene_no: number;
  heading: string;
  start_page: number;
  text: string;
}

export interface Overlay {
  script: {
    title: string;
    draft_version: string;
    page_count: number;
    truth_claim_framing: boolean;
    truth_claim_evidence?: string | null;
  };
  scenes: Scene[];
  /** Keyed "sceneNo:lineNo". */
  annotations: Record<string, Annotation[]>;
  legend: Record<string, string>;
}

export interface PersonRollup {
  element_id: string;
  person_name: string;
  alive: boolean | null;
  public_figure_status: string;
  total_claims: number;
  verified: number;
  unsupported: number;
  contradicted: number;
  unverifiable: number;
  opinion: number;
  amber_count: number;
  amber_density: number;
  counsel_items: number;
  exceeds_amber_threshold?: boolean;
  amber_threshold?: number;
  claims?: Claim[];
}

export interface BudgetSnapshot {
  spent_cents: number;
  spent_usd: number;
  ceiling_usd: number;
  remaining_usd: number;
  utilisation: number;
  calls: number;
  cache_hits: number;
  cache_hit_rate: number;
  degradations: number;
  warnings: string[];
}

export interface RunSummary {
  run_id: string;
  script_title: string;
  draft_version: string;
  truth_claim_framing: boolean;
  total_claims: number;
  total_elements: number;
  research_subjects: number;
  verdicts: { green: number; amber: number; red: number; grey: number };
  counsel_items: number;
  monitors_created: number;
  remedies_verified: number;
  cost_usd: number;
  duration_seconds: number;
  cache_hit_rate: number;
  fallback_rate: number;
  coverage_warnings: string[];
}

/** One server sent event from the run stream. */
export interface StreamEvent {
  event: string;
  [key: string]: unknown;
  budget?: BudgetSnapshot;
}

/** Colour tokens. Restraint is the design language: green is a quiet
 *  underline, grey is untouched, and red has to stay rare to stay legible. */
export const COLORS: Record<VerdictColor, { line: string; chip: string; label: string }> = {
  green: { line: "var(--verdict-green)", chip: "var(--verdict-green-bg)", label: "Verified" },
  amber: { line: "var(--verdict-amber)", chip: "var(--verdict-amber-bg)", label: "Unsupported" },
  red: { line: "var(--verdict-red)", chip: "var(--verdict-red-bg)", label: "Contradicted" },
  grey: { line: "transparent", chip: "transparent", label: "Opinion" },
  pending: { line: "var(--verdict-pending)", chip: "transparent", label: "Pending" },
};
