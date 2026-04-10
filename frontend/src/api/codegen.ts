/**
 * api/codegen.ts
 *
 * HTTP helpers for POST /synthdef and POST /tidal.
 *
 * Import alongside existing helpers in api/client.ts,
 * or re-export from client.ts for a unified import surface:
 *
 *   // In api/client.ts:
 *   export { postSynthdef, postTidal } from "./codegen";
 *
 * Usage:
 *   import { postSynthdef, postTidal } from "../api/codegen";
 */

import type { CodegenRequest, CodegenResponse } from "../types/codegen";

const API_BASE = "/api";

/**
 * Shared codegen fetch — DRY wrapper for both endpoints.
 *
 * Handles:
 *   - JSON serialisation
 *   - FastAPI HTTPException detail extraction
 *   - Network error wrapping
 *
 * Throws Error with a human-readable message on any failure.
 */
async function codegen(
  endpoint: "/synthdef" | "/tidal",
  body: CodegenRequest,
): Promise<CodegenResponse> {
  let res: Response;

  try {
    res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    // Network-level failure (CORS, DNS, connection refused)
    throw new Error(
      err instanceof Error
        ? `Network error: ${err.message}`
        : "Network error: could not reach API",
    );
  }

  if (!res.ok) {
    // FastAPI returns { "detail": "..." } on HTTPException
    let message = `Code generation failed (${res.status})`;
    try {
      const payload = await res.json();
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        // Pydantic validation errors — join messages
        message = payload.detail
          .map((e: { msg?: string }) => e.msg ?? JSON.stringify(e))
          .join("; ");
      }
    } catch {
      // Response body is not JSON — use status text
      message = `Code generation failed: ${res.statusText}`;
    }
    throw new Error(message);
  }

  return res.json() as Promise<CodegenResponse>;
}

/**
 * Generate SuperCollider (sclang) code from engine configuration.
 *
 * Calls POST /synthdef — returns composable SynthDefs with bus routing,
 * group ordering, and optional Pbind/Pdef pattern code.
 */
export async function postSynthdef(
  body: CodegenRequest,
): Promise<CodegenResponse> {
  return codegen("/synthdef", body);
}

/**
 * Generate TidalCycles (Haskell DSL) code from engine configuration.
 *
 * Calls POST /tidal — returns ready-to-evaluate Tidal patterns
 * with effect chains.
 */
export async function postTidal(
  body: CodegenRequest,
): Promise<CodegenResponse> {
  return codegen("/tidal", body);
}
