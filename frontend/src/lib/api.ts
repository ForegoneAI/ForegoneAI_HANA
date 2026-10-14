import { getSupabase } from "./supabase";

/** An H9N API failure, with a message that is safe and useful to show. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Where a deal stands in review (M2.4): approved deals are locked until reopened. */
export type ReviewStatus = "draft" | "reviewed" | "approved";

/** Where an extracted value came from (backend FieldEvidence). */
export interface FieldEvidence {
  field_name: string;
  value: string | null;
  source_document: string | null;
  page_number: number | null;
  snippet: string | null;
  verification: "value_matched" | "quote_only" | null;
}

/**
 * A value the extractor proposed but couldn't verify, held back for a
 * reviewer to accept or dismiss; its field stays empty meanwhile.
 */
export interface WithheldValue {
  field_name: string;
  proposed_value: string | number;
  reason: string;
  detail: string;
  evidence: FieldEvidence | null;
}

/**
 * A REPEDealProfile. The value fields (deal_name, asking_price, ...) are
 * listed in lib/dealFields.ts; the rest is what the extractor and reviewers
 * recorded about them.
 */
export interface DealProfile {
  deal_name: string | null;
  property_name: string | null;
  missing_information: string[];
  conflicting_information: string[];
  uncertain_information: string[];
  withheld_values: WithheldValue[];
  evidence: FieldEvidence[];
  corrected_fields: string[];
  review_feedback: string | null;
  review_status: ReviewStatus;
  [field: string]: unknown;
}

/**
 * A saved deal from GET /api/h9n/repe/deals/{id} (M2.4): the profile plus
 * where it stands in review. Any change must send `version` back, so a
 * change made against an out-of-date copy is refused instead of overwriting
 * someone else's.
 */
export interface DealRecord {
  deal_id: string;
  organization_id: string;
  status: ReviewStatus;
  version: number;
  source_filename: string;
  extraction_run_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  profile: DealProfile;
}

/** What a reviewer can do to a deal as a whole (M2.4). "reject" needs feedback. */
export type ReviewAction = "review" | "approve" | "reopen" | "reject";

/** One corrected field in a deal's history. */
export interface Correction {
  field_name: string;
  original_value: unknown;
  corrected_value: unknown;
  evidence: FieldEvidence | null;
  /** "reviewer_feedback": re-derived from the document after a rejection. */
  source: "reviewer" | "reviewer_feedback";
  feedback: string | null;
  corrected_by: string;
  deal_version: number;
  created_at: string;
}

/** One status change in a deal's history; "edit" is the automatic move back to draft. */
export interface StatusChange {
  action: ReviewAction | "edit";
  from_status: ReviewStatus;
  to_status: ReviewStatus;
  note: string | null;
  changed_by: string;
  deal_version: number;
  created_at: string;
}

export interface DealHistory {
  corrections: Correction[];
  status_changes: StatusChange[];
}

/** One row of GET /api/h9n/repe/deals. */
export interface DealSummary {
  deal_id: string;
  organization_id: string;
  deal_name: string | null;
  property_name: string | null;
  review_status: ReviewStatus;
  saved_at: string;
}

export interface Organization {
  id: string;
  name: string;
}

/** GET /api/h9n/me: who is signed in and which organizations they may act for. */
export interface CurrentUser {
  user_id: string;
  organizations: Organization[];
}

export interface ExtractResponse {
  deal_id: string;
  profile: DealProfile;
  extraction_run_id: string;
}

function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_H9N_API_URL;
  if (!base) {
    throw new ApiError(0, "The app is not configured. Set NEXT_PUBLIC_H9N_API_URL in frontend/.env.local.");
  }
  return `${base.replace(/\/$/, "")}${path}`;
}

async function accessToken(): Promise<string> {
  const { data } = await getSupabase().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Your session has ended. Please sign in again.");
  return token;
}

/**
 * Turns an API error response into one plain sentence. FastAPI returns
 * {"detail": "..."} for errors the backend raises on purpose, and
 * {"detail": [{msg: ...}]} for request validation errors.
 */
export function errorMessageFrom(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown };
    if (typeof first?.msg === "string") return first.msg;
  }
  if (status === 401) return "Your session has ended. Please sign in again.";
  if (status === 403) return "You don't have access to that.";
  if (status === 404) return "That deal could not be found.";
  if (status >= 500) return "The H9N service is having trouble right now. Please try again shortly.";
  return `The request failed (status ${status}).`;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/**
 * Uploads a PDF to POST /api/h9n/repe/extract.
 *
 * Uses XMLHttpRequest rather than fetch because fetch can't report upload
 * progress. onUploaded fires when the file has been fully sent, which is
 * when the API starts reading and extracting it. organizationId is only
 * needed for a member of several organizations (see getCurrentUser).
 */
export async function uploadDeal(
  file: File,
  options: {
    organizationId?: string;
    onProgress?: (fraction: number) => void;
    onUploaded?: () => void;
  } = {},
): Promise<ExtractResponse> {
  const url = apiUrl("/api/h9n/repe/extract");
  const token = await accessToken();
  const form = new FormData();
  form.append("file", file, file.name);
  if (options.organizationId) form.append("organization_id", options.organizationId);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", url);
    request.setRequestHeader("Authorization", `Bearer ${token}`);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) options.onProgress?.(event.loaded / event.total);
    };
    request.upload.onload = () => options.onUploaded?.();

    request.onload = () => {
      const body = parseJson(request.responseText);
      if (request.status >= 200 && request.status < 300 && body) {
        resolve(body as ExtractResponse);
      } else {
        reject(new ApiError(request.status, errorMessageFrom(request.status, body)));
      }
    };
    request.onerror = () =>
      reject(new ApiError(0, "Couldn't reach the H9N service. Check your connection and try again."));

    request.send(form);
  });
}

/** Calls the H9N API as the signed-in user, turning failures into ApiErrors. */
async function requestJson<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = await accessToken();
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method: init.method ?? "GET",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw new ApiError(0, "Couldn't reach the H9N service. Check your connection and try again.");
  }
  const body = parseJson(await response.text());
  if (!response.ok) throw new ApiError(response.status, errorMessageFrom(response.status, body));
  return body as T;
}

/** Lists the deals the user's organizations own, most recently saved first. */
export function listDeals(): Promise<DealSummary[]> {
  return requestJson<DealSummary[]>("/api/h9n/repe/deals");
}

function dealPath(dealId: string, rest = ""): string {
  return `/api/h9n/repe/deals/${encodeURIComponent(dealId)}${rest}`;
}

/** Fetches a saved deal from GET /api/h9n/repe/deals/{id}. */
export function getDeal(dealId: string): Promise<DealRecord> {
  return requestJson<DealRecord>(dealPath(dealId));
}

/** Fetches the signed-in user and their organizations from GET /api/h9n/me. */
export function getCurrentUser(): Promise<CurrentUser> {
  return requestJson<CurrentUser>("/api/h9n/me");
}

/**
 * Saves a reviewer's corrections (PATCH /deals/{id}). `version` is the one
 * the reviewer was looking at; if someone else saved since, this fails with
 * a 409 instead of overwriting their changes.
 */
export function correctDeal(dealId: string, version: number, changes: Record<string, unknown>): Promise<DealRecord> {
  return requestJson<DealRecord>(dealPath(dealId), { method: "PATCH", body: { version, changes } });
}

/** A review action on the whole deal (POST /deals/{id}/review). */
export function reviewDeal(
  dealId: string,
  action: ReviewAction,
  version: number,
  feedback?: string,
): Promise<DealRecord> {
  return requestJson<DealRecord>(dealPath(dealId, "/review"), {
    method: "POST",
    body: feedback === undefined ? { action, version } : { action, version, feedback },
  });
}

/** Every correction and status change on a deal, oldest first. */
export function getDealHistory(dealId: string): Promise<DealHistory> {
  return requestJson<DealHistory>(dealPath(dealId, "/history"));
}
