import { useEffect, useState } from "react";
import { getEffects } from "../../api/client";
import type { EffectBlock } from "../../types";

export function EffectsExplorer() {
  const [blocks, setBlocks] = useState<EffectBlock[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getEffects()
      .then(setBlocks)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="text-text-muted text-xs tracking-widest animate-pulse">
        LOADING EFFECTS CHAIN…
      </div>
    );
  }

  if (error) {
    return (
      <div className="panel border-accent-red/50">
        <span className="text-accent-red text-xs">{error}</span>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          EFFECTS CHAIN
        </h1>
        <p className="text-text-muted text-xs mt-1">
          10 HARDWARE-SOURCED DSP BLOCKS IN CANONICAL SIGNAL CHAIN ORDER.
        </p>
      </div>

      {/* Signal chain diagram */}
      <div className="panel overflow-x-auto">
        <div className="flex items-center gap-0 text-[9px] tracking-[0.1em] whitespace-nowrap">
          <span className="text-text-muted px-2">INPUT</span>
          {blocks.map((block, i) => (
            <div key={block.key} className="flex items-center">
              <span className="text-text-muted">→</span>
              <button
                onClick={() => setExpanded(expanded === i ? null : i)}
                className={`px-2 py-1 border transition-colors duration-100 ${
                  expanded === i
                    ? "border-accent-green text-accent-green bg-accent-green/5"
                    : "border-surface-3 text-text-secondary hover:text-text-primary hover:border-text-muted"
                }`}
              >
                {block.class_name}
              </button>
            </div>
          ))}
          <span className="text-text-muted">→</span>
          <span className="text-text-muted px-2">OUTPUT</span>
        </div>
      </div>

      {/* Block details */}
      {blocks.map((block, i) => (
        <div
          key={block.key}
          className={`panel transition-all duration-100 ${
            expanded === i
              ? "border-accent-green/40"
              : "cursor-pointer hover:border-text-muted"
          }`}
          onClick={() => setExpanded(expanded === i ? null : i)}
        >
          {/* Block header */}
          <div className="flex items-baseline justify-between">
            <div className="flex items-baseline gap-3">
              <span className="text-text-muted text-[10px] font-bold">
                [{block.position}]
              </span>
              <span className="font-display text-sm font-bold">
                {block.class_name}
              </span>
              <span className="text-text-muted text-[10px] tracking-widest">
                {block.key}
              </span>
            </div>
            <span className="text-text-muted text-[10px]">
              {expanded === i ? "▼" : "▶"}
            </span>
          </div>

          {/* Expanded detail */}
          {expanded === i && (
            <div className="mt-4 space-y-3">
              {/* Docstring */}
              {block.docstring && (
                <p className="text-text-secondary text-xs leading-relaxed italic">
                  {block.docstring}
                </p>
              )}

              {/* Parameters */}
              <div>
                <span className="label">Parameters</span>
                <div className="grid grid-cols-1 gap-1 mt-1">
                  {Object.entries(block.params).map(([name, info]) => (
                    <div
                      key={name}
                      className="flex items-baseline gap-2 text-xs"
                    >
                      <span className="text-accent-green font-medium">
                        {name}
                      </span>
                      <span className="text-text-muted">:</span>
                      <span className="text-text-secondary">{info.type}</span>
                      <span className="text-text-muted">=</span>
                      <span className="text-text-primary">
                        {JSON.stringify(info.default)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
