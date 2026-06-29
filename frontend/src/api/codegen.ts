import type { CodegenRequest, CodegenResponse } from "../types/codegen";

const API_BASE = "/api";

/**
 * Shared codegen fetch - DRY wrapper for both endpoints.
 * Handles FastAPI HTTPException detail extraction and Pydantic validation errors.
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
    throw new Error(
      err instanceof Error
        ? `Network error: ${err.message}`
        : "Network error: could not reach API",
    );
  }

  if (!res.ok) {
    let message = `Code generation failed (${res.status})`;
    try {
      const payload = await res.json();
      // FastAPI returns { "detail": "..." } on HTTPException
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        // Pydantic validation errors - join error messages
        message = payload.detail
          .map((e: { msg?: string }) => e.msg ?? JSON.stringify(e))
          .join("; ");
      }
    } catch {
      message = `Code generation failed: ${res.statusText}`;
    }
    throw new Error(message);
  }

  return res.json() as Promise<CodegenResponse>;
}

/**
 * Generate SuperCollider (sclang) code from engine configuration.
 * Returns composable SynthDefs with bus routing and group ordering.
 */
export async function postSynthdef(
  body: CodegenRequest,
): Promise<CodegenResponse> {
  return codegen("/synthdef", body);
}

/**
 * Generate TidalCycles (Haskell DSL) code from engine configuration.
 * Returns ready-to-evaluate Tidal patterns with effect chains.
 */
export async function postTidal(
  body: CodegenRequest,
): Promise<CodegenResponse> {
  return codegen("/tidal", body);
}
