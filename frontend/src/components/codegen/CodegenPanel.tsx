/**
 * components/codegen/CodegenPanel.tsx
 *
 * Code generation panel — main app tab (docked mode).
 *
 * Layout (v4 — live-ready):
 *   ┌─────────────────────────────────────┐
 *   │  SC │ TIDAL            ⧉  GENERATE  │  ← top bar
 *   ├─────────────────────────────────────┤
 *   │  ▸ CONFIG  ─── GLITCH / STUDIO / …  │  ← collapsed drawer
 *   ├─────────────────────────────────────┤
 *   │  SCLANG .SCD — 48 LINES   COPY SAVE │  ← code toolbar
 *   │  1 │ // IDM Generative System …      │
 *   │  2 │ // glitch_click | studio | 120  │  ← code output
 *   │  … │ …                               │     (85% of panel)
 *   ├─────────────────────────────────────┤
 *   │  ▸ WARNINGS              3           │  ← collapsed strips
 *   │  ▸ UNMAPPED              8           │
 *   │  ▸ SETUP                             │
 *   └─────────────────────────────────────┘
 *
 * Popout mode:
 *   When popout window is open, this panel shows a status message
 *   with a link to close the popout and return to docked mode.
 *   State is synchronised via BroadcastChannel("idm-codegen").
 *
 * 3-click live flow: SC|TIDAL → GENERATE → COPY
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
const POPOUT_URL = "/codegen-popout";
const POPOUT_FEATURES =
  "width=780,height=720,menubar=no,toolbar=no,status=no,scrollbars=yes";

/* ------------------------------------------------------------------ */
/* Collapsible info strip                                              */
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
/* CodegenPanel                                                        */
/* ------------------------------------------------------------------ */

export function CodegenPanel() {
  /* --- State: config --- */
  const [target, setTarget] = useState<CodegenTarget>("supercollider");
  const [mode, setMode] = useState<CodegenMode>("studio");
  const [generator, setGenerator] = useState<string>("glitch_click");
  const [bpm, setBpm] = useState(120);
  const [activeEffects, setActiveEffects] = useState<Set<EffectKey>>(
    () => new Set(["filter", "reverb", "compressor"]),
  );

  /* --- State: UI --- */
  const [configOpen, setConfigOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CodegenResponse | null>(null);

  /* --- Popout --- */
  const [popoutOpen, setPopoutOpen] = useState(false);
  const popoutRef = useRef<Window | null>(null);

  const { lastMessage, postMessage, isConnected } =
    useBroadcastChannel<CodegenBroadcastMessage>(CHANNEL_NAME);

  // React to popout messages
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "popout_ready") {
      setPopoutOpen(true);
      // Send current state to popout
      postMessage({
        type: "state_update",
        generator,
        effects: Object.fromEntries(
          [...activeEffects].map((k) => [k, {}]),
        ),
        bpm,
        mode,
      });
    } else if (lastMessage.type === "popout_closed") {
      setPopoutOpen(false);
      popoutRef.current = null;
    }
  }, [lastMessage, postMessage, generator, activeEffects, bpm, mode]);

  // Broadcast state changes to popout
  useEffect(() => {
    if (!isConnected) return;
    postMessage({
      type: "state_update",
      generator,
      effects: Object.fromEntries(
        [...activeEffects].map((k) => [k, {}]),
      ),
      bpm,
      mode,
    });
  }, [generator, activeEffects, bpm, mode, isConnected, postMessage]);

  // Detect popout close via polling (beforeunload is unreliable cross-origin)
  useEffect(() => {
    if (!popoutRef.current) return;
    const interval = setInterval(() => {
      if (popoutRef.current?.closed) {
        setPopoutOpen(false);
        popoutRef.current = null;
        clearInterval(interval);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [popoutOpen]);

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

  const handlePopout = useCallback(() => {
    if (popoutRef.current && !popoutRef.current.closed) {
      popoutRef.current.focus();
      return;
    }
    const win = window.open(POPOUT_URL, "idm-codegen-popout", POPOUT_FEATURES);
    if (win) {
      popoutRef.current = win;
      setPopoutOpen(true);
    }
  }, []);

  const handleClosePopout = useCallback(() => {
    if (popoutRef.current && !popoutRef.current.closed) {
      popoutRef.current.close();
    }
    setPopoutOpen(false);
    popoutRef.current = null;
  }, []);

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

  /* --- Popout active: show status --- */
  if (popoutOpen) {
    return (
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="font-display text-lg font-bold tracking-tight">
            CODE GENERATION
          </h1>
          <p className="text-text-muted text-xs mt-1">
            CODEGEN IS OPEN IN A SEPARATE WINDOW.
          </p>
        </div>
        <div className="panel">
          <p className="text-text-secondary text-sm">
            The code generation panel is running in a detached window.
            Configuration changes from this tab are synchronised automatically.
          </p>
          <button
            className="btn-secondary mt-4"
            onClick={handleClosePopout}
            type="button"
          >
            CLOSE POPOUT &amp; RETURN HERE
          </button>
        </div>
      </div>
    );
  }

  /* --- Main render --- */
  return (
    <div className="max-w-3xl mx-auto space-y-0">
      {/* ── Top bar ── */}
      <div className="flex items-stretch border border-surface-3">
        {/* SC / TIDAL tabs */}
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

        {/* Spacer */}
        <div className="flex-1 bg-surface-0" />

        {/* Popout button */}
        <button
          onClick={handlePopout}
          className="px-3 text-text-muted hover:text-text-secondary bg-surface-0 border-l border-surface-3 transition-colors duration-100 text-sm"
          type="button"
          title="Open in separate window"
        >
          ⧉
        </button>

        {/* Generate button */}
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="px-7 py-2.5 text-[13px] font-display font-bold tracking-[0.15em] uppercase bg-accent-green text-surface-base transition-opacity duration-100 hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
          type="button"
        >
          {loading ? "…" : "GENERATE"}
        </button>
      </div>

      {/* ── Config drawer toggle ── */}
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

      {/* ── Config drawer body ── */}
      {configOpen && (
        <div className="border border-surface-3 border-t-0 px-3 py-2.5 space-y-3">
          {/* Generator + Mode + BPM */}
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

          {/* Effects chain */}
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

          {/* Warnings */}
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

          {/* Unmapped params */}
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

          {/* Setup notes */}
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

          {/* Footer */}
          <div className="flex justify-end gap-4 text-[9px] tracking-[0.1em] text-text-muted pt-1.5">
            <span>{result.target === "supercollider" ? "SUPERCOLLIDER" : "TIDALCYCLES"}</span>
            <span>{result.mode.toUpperCase()}</span>
          </div>
        </>
      )}
    </div>
  );
}
