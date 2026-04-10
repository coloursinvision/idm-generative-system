/**
 * components/codegen/CodegenPopout.tsx
 *
 * Standalone codegen panel for the detached popout window.
 * Opened via window.open() from CodegenPanel.
 *
 * State synchronisation:
 *   - Receives config updates from main app via BroadcastChannel.
 *   - If opened directly (no main app), falls back to local config
 *     with CONFIG drawer open by default.
 *   - Sends "popout_ready" on mount and "popout_closed" on unmount.
 *   - Sends heartbeat every 2s so main app knows popout is alive.
 *
 * Layout is identical to CodegenPanel's docked mode but stripped
 * of the popout button (you're already in the popout).
 *
 * Route: /codegen-popout (add to your router)
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { postSynthdef, postTidal } from "../../api/codegen";
import { CodeBlock } from "./CodeBlock";
import { useBroadcastChannel } from "./useBroadcastChannel";
import type {
  CodegenRequest,
  CodegenResponse,
  CodegenTarget,
  CodegenMode,
  CodegenBroadcastMessage,
} from "../../types/codegen";

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const GENERATORS = ["glitch_click", "noise_burst", "fm_blip"] as const;

const EFFECT_BLOCKS = [
  "noise_floor", "bitcrusher", "filter", "saturation", "reverb",
  "delay", "spatial", "glitch", "compressor", "vinyl",
] as const;

type EffectKey = (typeof EFFECT_BLOCKS)[number];

const CHANNEL_NAME = "idm-codegen";

/* ------------------------------------------------------------------ */
/* Collapsible info strip (local copy — avoids cross-file dep)         */
/* ------------------------------------------------------------------ */

function InfoStrip({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-3 py-1.5 border border-surface-3 border-t-0 cursor-pointer transition-colors hover:bg-surface-0"
        type="button"
      >
        <span className="text-[9px] tracking-[0.12em] uppercase text-text-muted">
          {open ? "▾" : "▸"} {title}
        </span>
        {badge !== undefined && badge > 0 && (
          <span className="px-1 py-px text-[9px] bg-accent-amber/10 text-accent-amber border border-accent-amber/25">
            {badge}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 py-2 border border-surface-3 border-t-0">
          {children}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/* CodegenPopout                                                       */
/* ------------------------------------------------------------------ */

export function CodegenPopout() {
  /* --- State: config --- */
  const [target, setTarget] = useState<CodegenTarget>("supercollider");
  const [mode, setMode] = useState<CodegenMode>("studio");
  const [generator, setGenerator] = useState<string>("glitch_click");
  const [bpm, setBpm] = useState(120);
  const [activeEffects, setActiveEffects] = useState<Set<EffectKey>>(
    () => new Set(["filter", "reverb", "compressor"]),
  );

  /* --- State: UI --- */
  const [configOpen, setConfigOpen] = useState(true); // open by default in popout
  const [hasRemote, setHasRemote] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CodegenResponse | null>(null);

  /* --- BroadcastChannel --- */
  const { lastMessage, postMessage } =
    useBroadcastChannel<CodegenBroadcastMessage>(CHANNEL_NAME, true);

  // Send ready signal on mount, closed signal on unmount
  const sentReady = useRef(false);
  useEffect(() => {
    if (!sentReady.current) {
      postMessage({ type: "popout_ready" });
      sentReady.current = true;
    }
    const handleUnload = () => {
      postMessage({ type: "popout_closed" });
    };
    window.addEventListener("beforeunload", handleUnload);
    return () => {
      handleUnload();
      window.removeEventListener("beforeunload", handleUnload);
    };
  }, [postMessage]);

  // Receive state updates from main app
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "state_update") return;
    setHasRemote(true);
    setConfigOpen(false); // collapse config when receiving remote state
    setGenerator(lastMessage.generator);
    setMode(lastMessage.mode);
    setBpm(lastMessage.bpm);
    setActiveEffects(
      new Set(Object.keys(lastMessage.effects) as EffectKey[]),
    );
  }, [lastMessage]);

  /* --- Handlers --- */

  const toggleEffect = useCallback((key: EffectKey) => {
    setActiveEffects((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleGenerate = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    setResult(null);

    const effects: Record<string, Record<string, unknown>> = {};
    for (const key of activeEffects) {
      effects[key] = {};
    }

    const body: CodegenRequest = {
      generator,
      effects,
      mode,
      include_pattern: true,
      bpm,
      bus_offset: 16,
    };

    try {
      const fn = target === "supercollider" ? postSynthdef : postTidal;
      const data = await fn(body);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Code generation failed");
    } finally {
      setLoading(false);
    }
  }, [loading, target, mode, generator, bpm, activeEffects]);

  /* --- Derived --- */
  const warningCount = result?.warnings.length ?? 0;
  const unmappedCount = result
    ? Object.values(result.unmapped_params).reduce((s, a) => s + a.length, 0)
    : 0;
  const configSummary = [
    generator.replace(/_click|_burst|_blip/g, "").toUpperCase(),
    mode.toUpperCase(),
    `${bpm} BPM`,
    `${activeEffects.size} FX`,
  ].join(" / ");

  /* --- Render --- */
  return (
    <div className="min-h-screen bg-surface-base">
      <div className="max-w-3xl mx-auto p-4 space-y-0">
        {/* Sync indicator */}
        {hasRemote && (
          <div className="flex items-center gap-2 mb-3">
            <span className="w-1.5 h-1.5 rounded-full bg-accent-green animate-pulse" />
            <span className="text-[9px] tracking-[0.12em] uppercase text-text-muted">
              SYNCED WITH MAIN APP
            </span>
          </div>
        )}

        {/* ── Top bar ── */}
        <div className="flex items-stretch border border-surface-3">
          {(["supercollider", "tidalcycles"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTarget(t)}
              className={`relative px-6 py-2.5 text-[13px] font-display font-medium tracking-[0.12em] uppercase border-r border-surface-3 transition-colors duration-100 ${
                target === t
                  ? "text-text-primary bg-surface-1"
                  : "text-text-muted bg-surface-0 hover:text-text-secondary"
              }`}
              type="button"
            >
              {t === "supercollider" ? "SC" : "TIDAL"}
              {target === t && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent-green" />
              )}
            </button>
          ))}
          <div className="flex-1 bg-surface-0" />
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="px-7 py-2.5 text-[13px] font-display font-bold tracking-[0.15em] uppercase bg-accent-green text-surface-base transition-opacity duration-100 hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
            type="button"
          >
            {loading ? "…" : "GENERATE"}
          </button>
        </div>

        {/* ── Config drawer ── */}
        <button
          onClick={() => setConfigOpen(!configOpen)}
          className="w-full flex items-center gap-2 px-3 py-1.5 bg-surface-0 border border-surface-3 border-t-0 cursor-pointer transition-colors hover:bg-surface-1"
          type="button"
        >
          <span
            className={`text-[8px] text-text-muted transition-transform duration-150 ${
              configOpen ? "rotate-90" : ""
            }`}
          >
            ▸
          </span>
          <span className="text-[9px] tracking-[0.15em] uppercase text-text-muted">
            CONFIG
          </span>
          <span className="flex-1 border-t border-surface-3" />
          <span className="text-[9px] tracking-[0.08em] uppercase text-text-secondary">
            {configSummary}
          </span>
        </button>

        {configOpen && (
          <div className="border border-surface-3 border-t-0 px-3 py-2.5 space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <span className="block text-[9px] tracking-[0.12em] uppercase text-text-muted mb-1">
                  Generator
                </span>
                <div className="flex">
                  {GENERATORS.map((g) => (
                    <button
                      key={g}
                      onClick={() => setGenerator(g)}
                      className={`px-2.5 py-1 text-[10px] tracking-[0.08em] uppercase border border-surface-3 transition-colors duration-100 ${
                        generator === g
                          ? "text-accent-green border-accent-green bg-accent-green/5"
                          : "text-text-muted bg-surface-0 hover:text-text-secondary"
                      }`}
                      type="button"
                    >
                      {g.replace(/_click|_burst|_blip/g, "")}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <span className="block text-[9px] tracking-[0.12em] uppercase text-text-muted mb-1">
                  Mode
                </span>
                <div className="flex">
                  {(["studio", "live"] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      className={`px-2.5 py-1 text-[10px] tracking-[0.08em] uppercase border border-surface-3 transition-colors duration-100 ${
                        mode === m
                          ? "text-accent-green border-accent-green bg-accent-green/5"
                          : "text-text-muted bg-surface-0 hover:text-text-secondary"
                      }`}
                      type="button"
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <span className="block text-[9px] tracking-[0.12em] uppercase text-text-muted mb-1">
                  BPM
                </span>
                <input
                  type="number"
                  min={20}
                  max={300}
                  step={1}
                  value={bpm}
                  onChange={(e) => setBpm(Number(e.target.value) || 120)}
                  className="w-14 bg-surface-0 border border-surface-3 text-text-primary text-xs px-1.5 py-1 font-mono text-center focus:border-accent-green focus:outline-none transition-colors"
                />
              </div>
            </div>
            <div>
              <span className="block text-[9px] tracking-[0.12em] uppercase text-text-muted mb-1">
                Effects chain
              </span>
              <div className="flex flex-wrap gap-1">
                {EFFECT_BLOCKS.map((key) => {
                  const active = activeEffects.has(key);
                  return (
                    <button
                      key={key}
                      onClick={() => toggleEffect(key)}
                      className={`px-2 py-0.5 text-[9px] tracking-[0.06em] uppercase border transition-colors duration-100 ${
                        active
                          ? "text-accent-green border-surface-3"
                          : "text-text-muted border-transparent hover:text-text-secondary"
                      }`}
                      type="button"
                    >
                      {key.replace(/_/g, " ")}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* ── Error ── */}
        {error && (
          <div className="px-3 py-2 border border-accent-red/50 border-t-0">
            <span className="text-accent-red text-xs">{error}</span>
          </div>
        )}

        {/* ── Code output ── */}
        {result && (
          <>
            <div className="border-t-0">
              <CodeBlock
                code={result.code}
                target={result.target}
                filename={`${generator}_${result.mode}.${
                  result.target === "supercollider" ? "scd" : "tidal"
                }`}
              />
            </div>
            {warningCount > 0 && (
              <InfoStrip title="WARNINGS" badge={warningCount} defaultOpen>
                <div className="space-y-0.5">
                  {result.warnings.map((w, i) => (
                    <p key={i} className="text-[11px] text-accent-amber leading-relaxed font-mono">
                      {w}
                    </p>
                  ))}
                </div>
              </InfoStrip>
            )}
            {unmappedCount > 0 && (
              <InfoStrip title="UNMAPPED" badge={unmappedCount}>
                {Object.entries(result.unmapped_params).map(([block, params]) => (
                  <div key={block} className="mb-1.5 last:mb-0">
                    <span className="text-[9px] tracking-[0.12em] uppercase text-text-muted">
                      {block}
                    </span>
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {params.map((p) => (
                        <span
                          key={p}
                          className="px-1.5 py-px text-[9px] text-text-secondary border border-surface-3 font-mono"
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </InfoStrip>
            )}
            {result.setup_notes.length > 0 && (
              <InfoStrip title="SETUP">
                <div className="space-y-0.5">
                  {result.setup_notes.map((note, i) => (
                    <p key={i} className="text-[11px] text-text-secondary leading-relaxed">
                      {i + 1}. {note}
                    </p>
                  ))}
                </div>
              </InfoStrip>
            )}
            <div className="flex justify-end gap-4 text-[9px] tracking-[0.1em] text-text-muted pt-1.5">
              <span>{result.target === "supercollider" ? "SUPERCOLLIDER" : "TIDALCYCLES"}</span>
              <span>{result.mode.toUpperCase()}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
