import { useState } from "react";
import { postCompose } from "../../api/client";
import { SourceTags } from "../shared/SourceTags";
import type { ComposeResponse } from "../../types";

export function ComposerPanel() {
  const [description, setDescription] = useState("");
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ComposeResponse | null>(null);
  const [parsed, setParsed] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!description.trim() || loading) return;
    setLoading(true);
    setError("");
    setResult(null);
    setParsed(null);

    try {
      const data = await postCompose({ description: description.trim(), limit });
      setResult(data);

      if (typeof data.config === "object" && data.config !== null) {
        setParsed(data.config);
      } else {
        try {
          setParsed(JSON.parse(data.config));
        } catch {
          setParsed(null);
        }
      }
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
          AUTO-COMPOSER
        </h1>
        <p className="text-text-muted text-xs mt-1">
          DESCRIBE AN AESTHETIC — GET A COMPLETE EFFECTS CHAIN CONFIGURATION.
          OUTPUT IS JSON READY FOR /GENERATE OR /PROCESS.
        </p>
      </div>

      {/* Input */}
      <div className="panel">
        <label className="label">Aesthetic description</label>
        <textarea
          className="textarea-field"
          rows={3}
          placeholder="dark Detroit techno stab with heavy 909 swing and dub delay"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.metaKey) handleSubmit();
          }}
        />

        <div className="flex items-end justify-between mt-4">
          <div>
            <label className="label">Context chunks: {limit}</label>
            <input
              type="range"
              min={1}
              max={10}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="w-40 accent-accent-green"
            />
          </div>

          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={!description.trim() || loading}
          >
            {loading ? "COMPOSING…" : "COMPOSE"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="panel border-accent-red/50">
          <span className="text-accent-red text-xs">{error}</span>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-4">
          {/* JSON Config */}
          <div className="panel">
            <div className="panel-header">Generated configuration</div>

            {parsed ? (
              <pre className="text-xs text-accent-green leading-relaxed overflow-x-auto">
                {JSON.stringify(parsed, null, 2)}
              </pre>
            ) : (
              <>
                <p className="text-[10px] text-text-muted mb-2">
                  RAW RESPONSE (NOT VALID JSON)
                </p>
                <pre className="text-xs text-text-secondary leading-relaxed overflow-x-auto">
                {typeof result.config === "string"
                  ? result.config
                  : JSON.stringify(result.config, null, 2)}
                </pre>
              </>
            )}
          </div>

          {/* Reasoning */}
          {result.reasoning && (
            <div className="panel">
              <div className="panel-header">Reasoning</div>
              <p className="text-sm text-text-secondary leading-relaxed">
                {result.reasoning}
              </p>
            </div>
          )}

          {/* Sources */}
          <div className="panel">
            <SourceTags sources={result.sources} />

            <div className="divider" />
            <div className="flex justify-end gap-4 text-[10px] text-text-muted tracking-wider">
              <span>
                {result.usage.prompt_tokens}p + {result.usage.completion_tokens}c
                = {result.usage.total_tokens} tokens
              </span>
              <span>{result.model}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
