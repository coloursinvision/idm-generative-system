/**
 * types/codegen.ts
 *
 * TypeScript interfaces for the code generation endpoints.
 * Mirrors CodegenRequest / CodegenResponse Pydantic models in api/main.py.
 *
 * These types are the contract between frontend and backend — any change
 * to the Pydantic models MUST be reflected here. The CI type-check step
 * catches drift if the frontend consumes a field that no longer exists.
 */

/* ------------------------------------------------------------------ */
/* Enums                                                               */
/* ------------------------------------------------------------------ */

/**
 * Target language for code generation.
 *
 * - supercollider → sclang (.scd)
 * - tidalcycles   → Haskell / TidalCycles (.tidal)
 */
export type CodegenTarget = "supercollider" | "tidalcycles";

/**
 * Generation mode.
 *
 * - studio → self-contained script with s.waitForBoot, full comments, Pbind.
 * - live   → minimal boilerplate, assumes server running, Pdef/Ndef hot-swap.
 */
export type CodegenMode = "studio" | "live";

/* ------------------------------------------------------------------ */
/* Pattern configuration                                               */
/* ------------------------------------------------------------------ */

/**
 * Pattern configuration — tagged union on `type`.
 *
 * - euclidean:     Bjorklund algorithm — `pulses` per voice, `steps` total.
 * - probabilistic: Per-step trigger probability.
 * - density:       Fractional density → probabilistic grid.
 */
export interface PatternConfigEuclidean {
  type: "euclidean";
  pulses: Record<string, number>;
  steps: number;
}

export interface PatternConfigProbabilistic {
  type: "probabilistic";
  density: number;
  steps: number;
}

export interface PatternConfigDensity {
  type: "density";
  density: number;
  steps: number;
}

export type PatternConfig =
  | PatternConfigEuclidean
  | PatternConfigProbabilistic
  | PatternConfigDensity;

/* ------------------------------------------------------------------ */
/* Request                                                             */
/* ------------------------------------------------------------------ */

/** POST body for /synthdef and /tidal. */
export interface CodegenRequest {
  generator: string;
  generator_params?: Record<string, unknown>;
  effects?: Record<string, Record<string, unknown>>;
  pattern?: PatternConfig | null;
  mode?: CodegenMode;
  include_pattern?: boolean;
  bpm?: number;
  /** Starting private bus number — SuperCollider only. */
  bus_offset?: number;
}

/* ------------------------------------------------------------------ */
/* Response                                                            */
/* ------------------------------------------------------------------ */

/** Response from /synthdef and /tidal. */
export interface CodegenResponse {
  /** Generated source code string. */
  code: string;
  /** Target language: 'supercollider' or 'tidalcycles'. */
  target: CodegenTarget;
  /** Generation mode used: 'studio' or 'live'. */
  mode: CodegenMode;
  /** Mapping approximation warnings. */
  warnings: string[];
  /** Parameters with no target equivalent — keys are effect block names. */
  unmapped_params: Record<string, string[]>;
  /** Target-specific metadata (SynthDef names, bus allocation, etc.). */
  metadata: Record<string, unknown>;
  /** User-facing setup instructions for the generated code. */
  setup_notes: string[];
}

/* ------------------------------------------------------------------ */
/* BroadcastChannel message types                                      */
/* ------------------------------------------------------------------ */

/**
 * Messages exchanged between main app and popout window
 * via BroadcastChannel("idm-codegen").
 */
export type CodegenBroadcastMessage =
  | {
      type: "state_update";
      generator: string;
      effects: Record<string, Record<string, unknown>>;
      bpm: number;
      mode: CodegenMode;
    }
  | { type: "popout_ready" }
  | { type: "popout_closed" }
  | { type: "heartbeat" };
