/* ------------------------------------------------------------------ */
/* V2.3 + V2.4 tuning API client                                      */
/*                                                                    */
/* Mirrors the existing pattern in frontend/src/api/client.ts:        */
/*   - thin fetch wrapper over /api/* (Vite proxy in dev,             */
/*     FastAPI StaticFiles mount + nginx /api/* strip in prod)        */
/*   - JSON error body surfaced as Error.message                      */
/* ------------------------------------------------------------------ */

import type {
  TuningRequest,
  TuningResponse,
  TuningExtractRequest,
  TuningExtractResponse,
} from "../types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error: ${res.status}`);
  }
  return res.json();
}

/* ---- /tuning (V2.3) ---- */

export async function postTuning(
  body: TuningRequest,
): Promise<TuningResponse> {
  return request("/tuning", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/* ---- /tuning/extract (V2.4) ---- */

export async function postTuningExtract(
  body: TuningExtractRequest,
): Promise<TuningExtractResponse> {
  return request("/tuning/extract", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
