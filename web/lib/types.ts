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

export type SourceClass =
  | "official"
  | "registry"
  | "archive"
  | "news"
  | "trade"
  | "reference"
  | "user"
  | "unknown";

export interface Citation {
  url: string;
  title: string;
  excerpt: string;
  accessed_at: string;
  source_type: "primary" | "secondary" | "tertiary";
  publisher?: string | null;
  published_at?: string | null;
  /** Classified from the host, not asserted by the researcher. */
  source_class?: SourceClass;
  /** 0..1. Weights corroboration; never shown as a bare number. */
  trust?: number;
  /** False when the host is not one this system recognises. */
  verified_source?: boolean;
  /** Registrable domain. Two citations sharing one are not two sources. */
  domain?: string;

  /** What this source does for the claim, decided by the attribution gate.
   *  A search returns what it consulted, not what supports the proposition. */
  stance?: "supports" | "contradicts" | "irrelevant" | "unassessed";
  /** The verbatim span the stance rests on, found in the retrieved text. */
  quote?: string;
  /** Whether that span was located in the source by string search. */
  quote_verified?: boolean;
  stance_reason?: string;
}

/** What the attribution gate kept and dropped for one subject. */
export interface Attribution {
  assessed: number;
  kept: number;
  supports?: number;
  contradicts?: number;
  dropped_irrelevant: number;
  dropped_unquotable: number;
  notes: string[];
}

/** Who a named subject was resolved to, or why it could not be. */
export interface Identity {
  name: string;
  status: "resolved" | "collision" | "unidentified" | "unchecked";
  reason: string;
  canonical?: {
    qid: string;
    label: string;
    description: string;
    url: string;
    occupations: string[];
    sitelinks: number;
    deceased: boolean | null;
    official_site?: string | null;
  } | null;
  candidates?: { qid: string; label: string; description: string; url: string }[];
  web_checked?: boolean;
  web_summary?: string;
  web_domains?: string[];
  official_domain?: string | null;
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
  primary_source_count?: number;
  classified_primary_count?: number;
  independent_domains?: string[];
  source_strength?: number;
}

/** How well the record backs one subject. Counted, never asserted. */
// Every field is optional because the backend writes this block only when a
// subject was actually researched. A claim the swarm could not reach arrives
// as `{}`, and typing that as complete is what let an empty object reach
// `.join()` and crash the evidence panel.
export interface Corroboration {
  citation_count?: number;
  independent_domains: number;
  domains?: string[];
  primary_count: number;
  classified_primary_count: number;
  low_trust_count: number;
  recognised_count?: number;
  strongest_trust: number;
  record_signal: "SUPPORTED" | "CONTRADICTED" | "SILENT" | "OPINION" | "MIXED" | "UNKNOWN";
  supporting_facts: number;
  contradicting_facts: number;
  record_quality: string;
  conflict: boolean;
  single_source: boolean;
  low_trust_only: boolean;
  newest_source_days: number | null;
  oldest_source_days: number | null;
  score: number;
  notes?: string[];
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
  corroboration?: Corroboration;
  attribution?: Attribution;
  identity?: Identity;
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
  corroboration?: Corroboration;
  attribution?: Attribution;
  identity?: Identity;
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
  /** Research spend, priced per Parallel task run. Governed by the ceiling. */
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
  /** Model spend, priced per Gemini token. A separate bill, and on a short
   *  script it runs an order of magnitude above the research figure, so
   *  showing research alone badly understates what a run costs. */
  model_usd?: number;
  model_calls?: number;
  model_prompt_tokens?: number;
  model_output_tokens?: number;
  model_cached_tokens?: number;
  total_usd?: number;
  reserve_usd?: number;
  /** What the cache hits would have cost at list price. */
  cache_saved_usd?: number;
  by_tier?: Record<string, number>;
  by_provider?: Record<string, number>;
  by_model?: Record<string, number>;
  /** The pre flight estimate, so the meter can be read against an expectation. */
  projection?: CostProjection;
}

export interface CostProjection {
  subjects: number;
  projected_usd: number;
  ceiling_usd: number;
  within_budget: boolean;
  by_tier: Record<string, number>;
  by_processor: Record<string, { subjects: number; usd: number }>;
}

export interface RunCost {
  run_id: string;
  snapshot: BudgetSnapshot;
  economics: {
    total_usd: number;
    research_usd: number;
    model_usd: number;
    cache_saved_usd: number;
    per_subject_usd: number | null;
    per_claim_usd: number | null;
    per_page_usd: number | null;
    manual_baseline: {
      report_usd_low: number;
      report_usd_high: number;
      turnaround_days_low: number;
      turnaround_days_high: number;
      midpoint_usd: number;
      source?: string;
    };
    savings_vs_manual_usd: number;
    times_cheaper: number | null;
  };
  counts: {
    researched_subjects: number;
    claims: number;
    elements: number;
    pages: number;
  };
}

/** The pre flight calculator's answer. Same prices the meter runs on. */
export interface Estimate {
  input: { pages: number; truth_claim_framing: boolean; drafts: number; cache_hit_rate: number };
  subjects: {
    claims: number;
    elements: number;
    total: number;
    by_processor: Record<string, number>;
  };
  research_usd: number;
  model_usd: number;
  model_breakdown_usd: Record<string, number>;
  first_draft_usd: number;
  later_draft_usd: number;
  total_usd: number;
  manual_baseline_usd: number;
  savings_usd: number;
  times_cheaper: number | null;
  caveat: string;
}

export interface RunListItem {
  run_id: string;
  status: string;
  script_title: string | null;
  started_at: string;
  verdicts: { green: number; amber: number; red: number; grey: number } | null;
  cost_usd: number | null;
  error: string | null;
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

// ── exposure and precedent ──────────────────────────────────────────────────
// See src/truestory/agents/exposure.py and agents/precedent.py. Deliberately
// not a damages prediction: a band to sort a queue by, statutes quoted with
// their provision, a cost to fix that is a quote rather than a forecast, and
// a modelled range whose ranking is trustworthy and whose magnitude is an
// order of magnitude. Every field name here is the literal key the API sends.

export interface StatutoryAnchor {
  id: string;
  provision: string;
  jurisdiction: string;
  basis: string;
  floor_usd: number | null;
  ceiling_usd: number | null;
  willful_ceiling_usd: number | null;
  innocent_floor_usd: number | null;
  note: string;
  verified: boolean;
  caveat: string;
}

export interface CureRateResearch {
  rate_found: boolean;
  typical_usd?: number | null;
  rate_unit?: string | null;
  scope?: string | null;
  basis: string;
  confidence_note?: string;
  obtainable?: boolean | null;
  sources?: string[];
}

export interface CostToCure {
  remedy_class: string;
  stage: string;
  stage_multiplier: number;
  fee_usd: { low: number; high: number };
  change_usd: { low: number; high: number };
  low_usd: number;
  high_usd: number;
  basis: string;
  stage_basis: string;
  estimate: true;
  /** "policy_table" until a real market rate replaces it; "researched" once
   *  Parallel finds one with sources. Never render these as the same kind of
   *  figure -- the UI should always show which one it is looking at. */
  source: "policy_table" | "researched";
  researched: boolean;
  rate_research?: CureRateResearch;
}

export interface Venue {
  anti_slapp_available: boolean;
  note: string;
  jurisdictions: string[];
  with_anti_slapp?: string[];
  without_anti_slapp?: string[];
}

export interface ExposureDriver {
  id: string;
  value: number;
  because: string;
  detail?: string;
}

export interface ModelledExposure {
  expected_usd: { low: number; high: number };
  claim_probability: number;
  severity_given_claim_usd: { low: number; high: number };
  base_rate: number;
  base_rate_key: string;
  drivers: ExposureDriver[];
  outcome_weights: Record<string, number>;
  calibrated: boolean;
  negligible: boolean;
  caveat: string;
}

export interface ExposureResearchSource {
  url: string;
  title: string;
  excerpt: string;
  source_type: string;
}

/** Publicly reported monetary context. This never replaces modelled exposure:
 * one is sourced historical evidence, the other is an uncalibrated ranker. */
export interface ResearchedExposure {
  status: "range_found" | "defence_cost_only" | "no_public_range" | "unusable";
  range_found: boolean;
  outcome: "settled" | "adverse_judgment" | "dismissed_early" | "mixed" | null;
  damages_usd: { low: number; high: number; typical: number | null } | null;
  defence_cost_usd: { low: number | null; high: number | null } | null;
  source_kind: string;
  basis: string;
  confidence_note: string;
  outlier_warning: string;
  sources: ExposureResearchSource[];
  provider: string;
  schema_version: string;
  retrieved_at: string | null;
  confidence: number | null;
  researched: true;
}

export type ExposureBand = "routine" | "negotiable" | "counsel_required" | "blocking";

/** One finding's exposure picture, keyed by the same claim_id / element_id
 *  used everywhere else in the run. */
export interface ExposureAssessment {
  subject_id: string;
  band: ExposureBand;
  band_rank: number;
  band_means: string;
  rule_id: string;
  because: string;
  statutory_anchors: StatutoryAnchor[];
  cost_to_cure: CostToCure | null;
  venue: Venue;
  modelled_exposure: ModelledExposure | null;
  researched_exposure?: ResearchedExposure | null;
  disclaimer: string;
}

/** The run wide rollup: `/v1/runs/{id}/exposure`. */
export interface ExposureSchedule {
  stage: string;
  by_band: Partial<Record<ExposureBand, number>>;
  blocking: number;
  counsel_required: number;
  cost_to_cure_usd: {
    low: number;
    high: number;
    priced_findings: number;
    estimate: true;
    basis: string;
    researched_findings?: number;
  };
  modelled_exposure_usd: {
    low: number;
    high: number;
    findings: number;
    calibrated: boolean;
    basis?: string;
  };
  research_summary?: {
    shapes_available: number;
    shapes_researched: number;
    lookup_failures: number;
    findings_with_research: number;
    ranges_found: number;
    defence_cost_only: number;
    no_public_range: number;
    basis: string;
  };
  assessments: ExposureAssessment[];
}

/** One published dispute matched to a finding by failure shape, not topic. */
export interface PrecedentMatch {
  case_id: string;
  name: string;
  side: "plaintiff" | "defence";
  outcome: string;
  lesson: string;
  score: number;
  matched_on: string[];
  verified: boolean;
  caveat: string;
  court: string;
  docket_number: string;
  citation: string;
  decision_date: string;
  procedural_posture: string;
  holding: string;
  source_url: string;
  source_type: string;
  document_number: string;
  pin_cite: string;
  quoted_passage: string;
  retrieved_at: string;
}

/** `/v1/runs/{id}/precedents`: subject id (claim_id or element_id) to its
 *  matches, at most a handful per finding, both sides represented. */
export type PrecedentsBySubject = Record<string, PrecedentMatch[]>;
