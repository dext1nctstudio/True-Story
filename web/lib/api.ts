/**
 * API client.
 *
 * Everything goes through the same origin proxy declared in next.config.mjs,
 * so the browser never handles a cross origin credential and the server sent
 * event stream passes through without special casing.
 *
 * The role header is how the demo switches between counsel, producer, writer
 * and underwriter views. In deployment the role comes from a verified claim on
 * the identity token in front of the service, never from a client header.
 */

import type {
  Claim,
  ClearableElement,
  Estimate,
  Evidence,
  ExposureSchedule,
  Overlay,
  PersonRollup,
  PrecedentsBySubject,
  Remedy,
  Role,
  RunCost,
  RunListItem,
  RunSummary,
  StreamEvent,
} from "./types";

const BASE = "/api";

let activeRole: Role = "truestory.counsel";

export function setRole(role: Role): void {
  activeRole = role;
}

export function getRole(): Role {
  return activeRole;
}

function headers(): HeadersInit {
  return {
    "content-type": "application/json",
    "x-truestory-role": activeRole,
    "x-truestory-subject": "demo@truestory.dev",
    "x-truestory-projects": "demo",
  };
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { headers: headers(), cache: "no-store" });
  if (!response.ok) {
    // A 403 here is the governance model working, not a failure. The writer
    // view genuinely does not receive the evidence panel.
    throw new ApiError(response.status, await response.text());
  }
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

// ── reads ────────────────────────────────────────────────────────────────────

export const getOverlay = (runId: string) => get<Overlay>(`/v1/runs/${runId}/overlay`);

export const getClaims = (runId: string, verdict?: string) =>
  get<{ claims: Claim[]; total: number }>(
    `/v1/runs/${runId}/claims${verdict ? `?verdict=${verdict}` : ""}`,
  );

export const getRemedies = (runId: string) =>
  get<{ remedies: Remedy[]; total: number }>(`/v1/runs/${runId}/remedies`);

export const getElements = (runId: string) =>
  get<{ elements: ClearableElement[]; total: number }>(`/v1/runs/${runId}/elements`);

export const getRegister = (runId: string) =>
  get<{ persons: PersonRollup[]; note: string }>(`/v1/runs/${runId}/register`);

export const getExposure = (runId: string) =>
  get<ExposureSchedule>(`/v1/runs/${runId}/exposure`);

export const getPrecedents = (runId: string) =>
  get<{ precedents: PrecedentsBySubject }>(`/v1/runs/${runId}/precedents`);

export const listRuns = (projectId: string) =>
  get<{ runs: RunListItem[] }>(`/v1/projects/${projectId}/runs`);

export const getRun = (runId: string) =>
  get<{
    run_id: string;
    status: string;
    summary: RunSummary | null;
    /** Rebuilt from durable storage rather than held in the API process. */
    restored?: boolean;
  }>(`/v1/runs/${runId}`);

export const getReport = (runId: string) =>
  get<Record<string, unknown>>(`/v1/runs/${runId}/report`);

/** The full cost breakdown. Counsel and producer only, enforced server side. */
export const getCost = (runId: string) => get<RunCost>(`/v1/runs/${runId}/cost`);

/** Published unit prices. Nothing in the UI restates a rate of its own. */
export const getPricing = () => get<Record<string, unknown>>(`/v1/pricing`);

/** Pre flight calculator. Same prices, same subject density, as a real run. */
export async function estimateRun(input: {
  pages: number;
  truth_claim_framing: boolean;
  drafts: number;
  cache_hit_rate: number;
}): Promise<Estimate> {
  const response = await fetch(`${BASE}/v1/estimate`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

/**
 * Ask the record a question about one line. A live search round trip, priced
 * in tenths of a cent, whose answer is a lead rather than a finding: it never
 * enters adjudication and never changes a verdict.
 */
export async function interrogate(
  runId: string,
  body: { question: string; subject_id?: string; subject?: string },
): Promise<Evidence> {
  const response = await fetch(`${BASE}/v1/runs/${runId}/interrogate`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

/** Absolute URLs for the two exports an underwriter actually asks for. */
export const reportPdfUrl = (runId: string) => `${BASE}/v1/runs/${runId}/report.pdf`;
export const clearanceLogUrl = (runId: string) => `${BASE}/v1/runs/${runId}/clearance_log.csv`;

export const getMonitors = (projectId: string) =>
  get<{ monitors: unknown[] }>(`/v1/projects/${projectId}/monitors`);

export const getReviewQueue = () =>
  get<{ items: unknown[] }>(`/v1/review_queue`);

/** The drag and drop path. Multipart, so content-type is left to the browser
 * to set with its own boundary rather than reusing the JSON headers() helper. */
export async function uploadRun(
  projectId: string,
  file: File,
  draftVersion = "v1",
): Promise<{ run_id: string; filename: string; bytes: number; stream: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${BASE}/v1/projects/${projectId}/runs/upload?draft_version=${draftVersion}`,
    {
      method: "POST",
      headers: {
        "x-truestory-role": activeRole,
        "x-truestory-subject": "demo@truestory.dev",
        "x-truestory-projects": projectId,
      },
      body: form,
    },
  );
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

// ── writes ───────────────────────────────────────────────────────────────────

/** Write the redline. Only a remedy that verified against the record is applyable. */
export async function applyRemedy(
  runId: string,
  claimId: string,
  remedyId: string,
): Promise<{ applied: boolean }> {
  const response = await fetch(
    `${BASE}/v1/claims/${claimId}/apply_remedy?run_id=${runId}&remedy_id=${remedyId}`,
    { method: "POST", headers: headers() },
  );
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

/** Reveal a masked identity. Counsel only, reason required, always audited. */
export async function unmaskElement(
  runId: string,
  elementId: string,
  reason: string,
): Promise<{ unmasked: boolean }> {
  const response = await fetch(
    `${BASE}/v1/elements/${elementId}/unmask?run_id=${runId}`,
    { method: "POST", headers: headers(), body: JSON.stringify({ reason }) },
  );
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

export async function startRun(
  projectId: string,
  scriptText: string,
  draftVersion = "v1",
): Promise<{ run_id: string; stream: string }> {
  const response = await fetch(`${BASE}/v1/projects/${projectId}/runs`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ script_text: scriptText, draft_version: draftVersion }),
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

// ── the live stream ──────────────────────────────────────────────────────────

/**
 * Subscribe to a run.
 *
 * This is what makes the page fill in live rather than showing a spinner and
 * then a wall of results. Verdicts arrive as the swarm completes them and the
 * cost meter ticks alongside in cents.
 *
 * Returns an unsubscribe function.
 */
export function streamRun(
  runId: string,
  onEvent: (event: StreamEvent) => void,
  onError?: (error: Event) => void,
): () => void {
  const source = new EventSource(`${BASE}/v1/runs/${runId}/stream`);

  const forward = (type: string) => (message: MessageEvent<string>) => {
    try {
      onEvent({ event: type, ...(JSON.parse(message.data) as Record<string, unknown>) });
    } catch {
      // A malformed frame is dropped rather than breaking the stream. The run
      // itself is authoritative and is re read on completion.
    }
  };

  for (const type of [
    "stage",
    "ingest_complete",
    "claims_extracted",
    "ledger_built",
    "plan_ready",
    "swarm_dispatched",
    "claim_researched",
    "element_researched",
    "swarm_complete",
    "adjudication_complete",
    "remedies_ready",
    "run_complete",
    "run_failed",
    "message",
  ]) {
    source.addEventListener(type, forward(type) as EventListener);
  }

  source.addEventListener("end", () => source.close());
  source.onerror = (error) => {
    onError?.(error);
    source.close();
  };

  return () => source.close();
}

export function formatUsd(value: number): string {
  return value < 0.01 && value > 0 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}


/**
 * How a page is written in this industry: whole pages and eighths.
 *
 * The raw value is a float, because a span's page is derived from its line
 * offset, and printing that float put "page 2.49" on screen in three places.
 * Nobody in a production office has ever said page two point four nine.
 */
export function pageRef(occurrence?: { page?: number; page_eighths?: string } | null): string {
  if (!occurrence) return "—";
  if (occurrence.page_eighths) return occurrence.page_eighths;
  return occurrence.page ? String(Math.round(occurrence.page)) : "—";
}
