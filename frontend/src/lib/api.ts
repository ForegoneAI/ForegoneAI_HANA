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

/** The fields the app currently shows from a REPEDealProfile. */
export interface DealProfile {
  deal_name: string | null;
  property_name: string | null;
  property_type: string | null;
  address: string | null;
  asking_price: number | null;
  noi: number | null;
  cap_rate: number | null;
  missing_information: string[];
  conflicting_information: string[];
  uncertain_information: string[];
  withheld_values: { field_name: string }[];
  review_status: "pending" | "approved" | "rejected";
  [field: string]: unknown;
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
 * when the API starts reading and extracting it.
 */
export async function uploadDeal(
  file: File,
  handlers: { onProgress?: (fraction: number) => void; onUploaded?: () => void } = {},
): Promise<ExtractResponse> {
  const url = apiUrl("/api/h9n/repe/extract");
  const token = await accessToken();
  const form = new FormData();
  form.append("file", file, file.name);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", url);
    request.setRequestHeader("Authorization", `Bearer ${token}`);

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) handlers.onProgress?.(event.loaded / event.total);
    };
    request.upload.onload = () => handlers.onUploaded?.();

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

/** Fetches a saved deal from GET /api/h9n/repe/deals/{id}. */
export async function getDeal(dealId: string): Promise<DealProfile> {
  const token = await accessToken();
  let response: Response;
  try {
    response = await fetch(apiUrl(`/api/h9n/repe/deals/${encodeURIComponent(dealId)}`), {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError(0, "Couldn't reach the H9N service. Check your connection and try again.");
  }
  const body = parseJson(await response.text());
  if (!response.ok) throw new ApiError(response.status, errorMessageFrom(response.status, body));
  return body as DealProfile;
}
