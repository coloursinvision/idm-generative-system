/* ------------------------------------------------------------------ */
/* API client — thin fetch wrapper over FastAPI backend                */
/* Vite proxy rewrites /api/* → http://localhost:8000/*                */
/* ------------------------------------------------------------------ */

import type {
  HealthResponse,
  EffectBlock,
  AskRequest,
  AskResponse,
  ComposeRequest,
  ComposeResponse,
  GenerateRequest,
} from "../types";

const BASE = "/api";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
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

/* ---- Endpoints ---- */

export async function getHealth(): Promise<HealthResponse> {
  return request("/health");
}

export async function getEffects(): Promise<EffectBlock[]> {
  return request("/effects");
}

export async function postAsk(body: AskRequest): Promise<AskResponse> {
  return request("/ask", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postCompose(
  body: ComposeRequest
): Promise<ComposeResponse> {
  return request("/compose", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function postGenerate(
  body: GenerateRequest
): Promise<Blob> {
  const res = await fetch(`${BASE}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }

  return res.blob();
}
