/* ------------------------------------------------------------------ */
/* V2.3 + V2.4 tuning types — TS mirror of FastAPI Pydantic models    */
/*                                                                    */
/* Source contracts:                                                  */
/*   api/main.py — TuningRequest, ResonantPoint, TuningResponse,      */
/*                 TuningExtractRequest, TuningExtractResponse        */
/*   engine/ml/regional_profiles.py — RegionCode, SubRegion           */
/*                                                                    */
/* Keep these aliases in lockstep with the Python type aliases per    */
/* [[DECISIONS]] D-S7-02 (single source of truth: spoke filenames →   */
/* Python RegionCode/SubRegion → these TS literals → frontend UI).    */
/* ------------------------------------------------------------------ */

export const REGION_CODES = [
  "DETROIT_FIRST_WAVE",
  "DETROIT_UR",
  "DREXCIYA",
  "UK_IDM",
  "UK_BRAINDANCE",
  "JAPAN_IDM",
] as const;

export type RegionCode = (typeof REGION_CODES)[number];

export const SUB_REGIONS = ["TOKYO", "OSAKA"] as const;
export type SubRegion = (typeof SUB_REGIONS)[number];

/* ---- V2.3 — /tuning ---- */

export interface TuningRequest {
  bpm: number;
  pitch_midi: number;
  swing_pct: number;
  region: RegionCode;
  sub_region: SubRegion | null;
}

export interface ResonantPoint {
  hz: number;
  label: string;
  confidence: number;
}

export interface TuningResponse {
  tuning_hz: number;
  resonant_points: ResonantPoint[];
  model_version: string;
  dataset_dvc_hash: string;
  inference_latency_ms: number;
}

/* ---- V2.4 — /tuning/extract ---- */

export interface TuningExtractRequest {
  text: string;
}

export interface TuningExtractResponse {
  extracted: TuningRequest;
  model_version: string;
}
