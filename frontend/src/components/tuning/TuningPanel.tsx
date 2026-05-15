import { useState } from "react";
import { postTuning } from "../../api/client";
import type { TuningRequest, TuningResponse } from "../../types";
import { TuningExtract } from "./TuningExtract";
import { TuningForm } from "./TuningForm";
import { TuningResult } from "./TuningResult";

const DEFAULT_REQUEST: TuningRequest = {
  bpm: 130,
  pitch_midi: 69,
  swing_pct: 0,
  region: "UK_IDM",
  sub_region: null,
};

export function TuningPanel() {
  const [request, setRequest] = useState<TuningRequest>(DEFAULT_REQUEST);
  const [result, setResult] = useState<TuningResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleExtracted = (extracted: TuningRequest) => {
    setRequest(extracted);
    setResult(null);
    setError("");
  };

  const handleSubmit = async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await postTuning(request);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          TUNING
        </h1>
        <p className="text-text-muted text-xs mt-1">
          ML-DERIVED TUNING FREQUENCY AND RESONANT POINTS FOR A
          GENERATIVE CONTEXT. DESCRIBE IT, REVIEW, COMPUTE.
        </p>
      </div>

      {/* LLM extraction (optional shortcut) */}
      <TuningExtract onExtracted={handleExtracted} />

      {/* Form */}
      <TuningForm
        value={request}
        onChange={setRequest}
        onSubmit={handleSubmit}
        loading={loading}
        error={error}
      />

      {/* Result */}
      {result && <TuningResult result={result} />}
    </div>
  );
}
