import { useState } from "react";
import { postTuningExtract } from "../../api/client";
import type { TuningRequest } from "../../types";

interface Props {
  onExtracted: (extracted: TuningRequest) => void;
}

export function TuningExtract({ onExtracted }: Props) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastModel, setLastModel] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!text.trim() || loading) return;
    setLoading(true);
    setError("");
    try {
      const data = await postTuningExtract({ text: text.trim() });
      setLastModel(data.model_version);
      onExtracted(data.extracted);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Extraction failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel space-y-4">
      <div className="panel-header">Describe the context</div>
      <p className="text-text-muted text-xs">
        FREE TEXT — REGION, BPM, KEY, FEEL. GPT-4o EXTRACTS A TUNING REQUEST
        FOR YOU TO REVIEW BEFORE COMPUTING.
      </p>
      <textarea
        className="textarea-field"
        rows={3}
        placeholder="120 BPM Detroit techno in A minor, moderate swing"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.metaKey) handleSubmit();
        }}
        maxLength={2000}
      />
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-muted tracking-wider">
          {text.length} / 2000
        </span>
        <button
          className="btn-primary"
          onClick={handleSubmit}
          disabled={!text.trim() || loading}
        >
          {loading ? "EXTRACTING…" : "EXTRACT"}
        </button>
      </div>
      {error && (
        <div className="text-accent-red text-xs">{error}</div>
      )}
      {lastModel && !error && (
        <div className="text-[10px] text-text-muted tracking-wider">
          extracted via {lastModel}
        </div>
      )}
    </div>
  );
}
