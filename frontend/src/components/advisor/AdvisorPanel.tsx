import { useState } from "react";
import { postAsk } from "../../api/client";
import { SourceTags } from "../shared/SourceTags";
import type { AskResponse } from "../../types";

export function AdvisorPanel() {
  const [question, setQuestion] = useState("");
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const data = await postAsk({ question: question.trim(), limit });
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
          SOUND DESIGN ADVISOR
        </h1>
        <p className="text-text-muted text-xs mt-1">
          ASK ANYTHING ABOUT DSP, HARDWARE, SYNTHESIS, REGIONAL AESTHETICS,
          OR EFFECTS CHAIN CONFIGURATION.
        </p>
      </div>

      {/* Input */}
      <div className="panel">
        <label className="label">Question</label>
        <textarea
          className="textarea-field"
          rows={3}
          placeholder="How do I recreate the Autechre granular texture from Tri Repetae?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
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
            disabled={!question.trim() || loading}
          >
            {loading ? "SEARCHING…" : "ASK"}
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
        <div className="panel space-y-4">
          <div className="panel-header">Answer</div>

          <div className="text-text-primary text-sm leading-relaxed whitespace-pre-wrap">
            {result.answer}
          </div>

          <SourceTags sources={result.sources} />

          {/* Token usage */}
          <div className="divider" />
          <div className="flex justify-end gap-4 text-[10px] text-text-muted tracking-wider">
            <span>
              {result.usage.prompt_tokens}p + {result.usage.completion_tokens}c
              = {result.usage.total_tokens} tokens
            </span>
            <span>{result.model}</span>
          </div>
        </div>
      )}
    </div>
  );
}
