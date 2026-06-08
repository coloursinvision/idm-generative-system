import { useState, useCallback } from "react";
import {
  useEP133Sequencer,
  TIMING_MODES,
  STEPS_PER_TIMING,
} from "../../hooks/useEP133Sequencer";
import type { TimingMode } from "../../hooks/useEP133Sequencer";

/* ------------------------------------------------------------------ */
/* EP-133 K.O.II constants from manual                                 */
/* ------------------------------------------------------------------ */

const GROUPS = ["A", "B", "C", "D"] as const;
type Group = (typeof GROUPS)[number];

const GROUP_ROLES: Record<Group, { label: string; slots: string }> = {
  A: { label: "DRUMS", slots: "1-99 Kicks / 100-199 Snares / 200-299 Hats / 300-399 Perc" },
  B: { label: "BASS", slots: "400-499" },
  C: { label: "MELODIC", slots: "500-599" },
  D: { label: "SAMPLES", slots: "User samples" },
};

const GROUP_TRACKS: Record<Group, { name: string; generator: string }[]> = {
  A: [
    { name: "KICK 1", generator: "noise_burst" },
    { name: "KICK 2", generator: "noise_burst" },
    { name: "SNARE 1", generator: "noise_burst" },
    { name: "SNARE 2", generator: "noise_burst" },
    { name: "HAT CL", generator: "glitch_click" },
    { name: "HAT OP", generator: "glitch_click" },
    { name: "CLAP", generator: "noise_burst" },
    { name: "RIM", generator: "glitch_click" },
    { name: "TOM HI", generator: "fm_blip" },
    { name: "TOM LO", generator: "fm_blip" },
    { name: "PERC 1", generator: "glitch_click" },
    { name: "PERC 2", generator: "glitch_click" },
  ],
  B: [
    { name: "BASS 1", generator: "fm_blip" },
    { name: "BASS 2", generator: "fm_blip" },
    { name: "BASS 3", generator: "fm_blip" },
    { name: "SUB 1", generator: "fm_blip" },
  ],
  C: [
    { name: "PAD 1", generator: "fm_blip" },
    { name: "LEAD 1", generator: "fm_blip" },
    { name: "STAB 1", generator: "fm_blip" },
    { name: "BELL 1", generator: "fm_blip" },
  ],
  D: [
    { name: "SMP 1", generator: "noise_burst" },
    { name: "SMP 2", generator: "glitch_click" },
    { name: "SMP 3", generator: "fm_blip" },
    { name: "SMP 4", generator: "noise_burst" },
  ],
};

const EP133_FX = [
  "DELAY", "REVERB", "DISTORTION", "CHORUS", "FILTER", "COMPRESSOR",
];

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function EP133Guide() {
  /*
   * activeGroup selects the EDITING SURFACE only. Playback is global and
   * unaffected by this value (CR-F12 AC3) — the sequencer plays all four
   * groups from one master transport regardless of which is on screen.
   */
  const [activeGroup, setActiveGroup] = useState<Group>("A");

  const seq = useEP133Sequencer({
    groups: GROUPS,
    groupTracks: GROUP_TRACKS,
    defaultBpm: 130,
  });

  const active = seq.groups[activeGroup];
  const numSteps = STEPS_PER_TIMING[active.timing];
  const currentStep = seq.currentStepByGroup[activeGroup];

  const anySolo = GROUPS.some((g) => seq.groups[g].solo);
  const audible = (g: Group) => (anySolo ? seq.groups[g].solo : !seq.groups[g].muted);

  const anyBuffers = GROUPS.some((g) =>
    seq.groups[g].tracks.some((t) => t.buffer !== null)
  );
  const anyPattern = GROUPS.some((g) =>
    seq.groups[g].tracks.some((t) => t.steps.some(Boolean))
  );

  const activeLoaded = active.tracks.filter((t) => t.buffer).length;

  /*
   * Click handlers wrap the async hook methods so that:
   *  - WebKit audio unlock fires on the first user gesture (idempotent)
   *  - Rejected Promises are surfaced to the console rather than left
   *    unhandled (CR-F13 acceptance criterion 8).
   */
  const handleLoadGroup = useCallback(() => {
    seq.unlockAudioContext().catch((err) =>
      console.error("[EP133Guide] unlockAudioContext failed:", err)
    );
    seq.loadGroupSamples(activeGroup).catch((err) =>
      console.error("[EP133Guide] loadGroupSamples failed:", err)
    );
  }, [seq, activeGroup]);

  const handlePlay = useCallback(() => {
    seq.unlockAudioContext().catch((err) =>
      console.error("[EP133Guide] unlockAudioContext failed:", err)
    );
    seq.play().catch((err) => console.error("[EP133Guide] play failed:", err));
  }, [seq]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          EP-133 K.O.II GUIDE
        </h1>
        <p className="text-text-muted text-xs mt-1">
          12 PADS × 4 GROUPS — ALL GROUPS PLAY SIMULTANEOUSLY FROM ONE MASTER
          TRANSPORT.
        </p>
      </div>

      {/* Device info */}
      <div className="panel">
        <div className="flex gap-6 text-[10px] text-text-muted tracking-widest">
          <span>EDITING {activeGroup}: {GROUP_ROLES[activeGroup].label}</span>
          <span>TIMING: {active.timing}</span>
          <span>STEPS: {numSteps}</span>
          <span>BPM: {seq.bpm}</span>
          <span className={seq.isPlaying ? "text-accent-green" : ""}>
            {seq.isPlaying ? "PLAYING" : "STOPPED"}
          </span>
        </div>
      </div>

      {/* Group selector (editing view + per-group mixer) + Timing */}
      <div className="flex gap-4">
        {/* Groups */}
        <div className="panel flex-1">
          <div className="panel-header">Groups — edit surface · mute / solo</div>
          <div className="grid grid-cols-4 gap-2">
            {GROUPS.map((g) => {
              const gs = seq.groups[g];
              const isActive = activeGroup === g;
              return (
                <div
                  key={g}
                  className={`border ${
                    isActive ? "border-accent-green" : "border-surface-3"
                  }`}
                >
                  <button
                    onClick={() => setActiveGroup(g)}
                    className={`w-full py-2 text-center transition-colors duration-100 ${
                      isActive
                        ? "bg-accent-green/10 text-accent-green"
                        : "bg-surface-0 text-text-muted hover:text-text-secondary"
                    }`}
                  >
                    <div className="flex items-center justify-center gap-1">
                      <div className="text-lg font-bold font-display">{g}</div>
                      {seq.isPlaying && audible(g) && (
                        <span className="w-1.5 h-1.5 bg-accent-green rounded-full animate-pulse" />
                      )}
                    </div>
                    <div className="text-[9px] tracking-widest mt-0.5">
                      {GROUP_ROLES[g].label}
                    </div>
                  </button>

                  {/* Per-group mixer: mute / solo */}
                  <div className="grid grid-cols-2 gap-0 border-t border-surface-3">
                    <button
                      onClick={() => seq.toggleMute(g)}
                      className={`py-1 text-[9px] tracking-widest border-r border-surface-3 transition-colors duration-100 ${
                        gs.muted
                          ? "bg-accent-red/15 text-accent-red"
                          : "text-text-muted hover:text-text-secondary"
                      }`}
                    >
                      MUTE
                    </button>
                    <button
                      onClick={() => seq.toggleSolo(g)}
                      className={`py-1 text-[9px] tracking-widest transition-colors duration-100 ${
                        gs.solo
                          ? "bg-accent-amber/15 text-accent-amber"
                          : "text-text-muted hover:text-text-secondary"
                      }`}
                    >
                      SOLO
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="text-[9px] text-text-muted mt-2 tracking-wider">
            SLOTS: {GROUP_ROLES[activeGroup].slots}
          </div>
        </div>

        {/* Timing (per active group) */}
        <div className="panel w-48">
          <div className="panel-header">Timing — group {activeGroup}</div>
          <div className="grid grid-cols-3 gap-0">
            {TIMING_MODES.map((t) => (
              <button
                key={t}
                onClick={() => seq.setTiming(activeGroup, t as TimingMode)}
                className={`py-2 text-[10px] border transition-colors duration-100 ${
                  active.timing === t
                    ? "bg-accent-amber/10 text-accent-amber border-accent-amber"
                    : "bg-surface-0 text-text-muted border-surface-3 hover:text-text-secondary"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Transport (global) */}
      <div className="panel">
        <div className="panel-header">Transport — master (all groups)</div>
        <div className="flex items-end gap-4">
          <button
            className="btn-primary"
            onClick={handleLoadGroup}
            disabled={active.loading}
          >
            {active.loading
              ? "LOADING…"
              : activeLoaded > 0
                ? `RELOAD ${activeGroup}`
                : `LOAD ${activeGroup}`}
          </button>

          <button
            className={`${seq.isPlaying ? "btn-secondary border-accent-red text-accent-red" : "btn-primary"}`}
            onClick={seq.isPlaying ? seq.stop : handlePlay}
            disabled={!anyBuffers || !anyPattern}
          >
            {seq.isPlaying ? "STOP" : "PLAY"}
          </button>

          <div>
            <label className="label">BPM: {seq.bpm}</label>
            <input
              type="range"
              min={60}
              max={200}
              value={seq.bpm}
              onChange={(e) => seq.setBpm(Number(e.target.value))}
              className="w-32 accent-accent-green"
            />
          </div>

          <div className="text-[10px] text-text-muted tracking-wider ml-auto">
            {activeLoaded}/{active.tracks.length} SAMPLES LOADED (GROUP {activeGroup})
          </div>
        </div>
      </div>

      {/* Step sequencer — active group's editing surface */}
      <div className="panel">
        <div className="panel-header">
          Step sequencer — Group {activeGroup} ({GROUP_ROLES[activeGroup].label})
        </div>

        {/* Step numbers + playhead */}
        <div className="flex items-center gap-2 mb-1">
          <div className="w-16" />
          <div className="flex gap-0 flex-1">
            {Array.from({ length: numSteps }, (_, i) => (
              <div
                key={i}
                className={`flex-1 text-center text-[8px] ${
                  currentStep === i
                    ? "text-accent-green font-bold"
                    : "text-text-muted"
                }`}
              >
                {i + 1}
              </div>
            ))}
          </div>
        </div>

        {/* Track rows */}
        <div className="space-y-0.5">
          {active.tracks.map((track, ti) => (
            <div key={ti} className="flex items-center gap-2">
              <div className="w-16 flex items-center gap-1">
                <span
                  className={`text-[8px] uppercase tracking-wider truncate ${
                    track.buffer
                      ? "text-text-secondary"
                      : track.loading
                        ? "text-accent-amber animate-pulse"
                        : "text-text-muted"
                  }`}
                >
                  {track.name}
                </span>
                {track.buffer && (
                  <span className="w-1 h-1 bg-accent-green flex-shrink-0" />
                )}
              </div>

              <div className="flex gap-0 flex-1">
                {track.steps.slice(0, numSteps).map((stepActive, si) => (
                  <button
                    key={si}
                    onClick={() => seq.toggleStep(activeGroup, ti, si)}
                    className={`flex-1 h-5 border-r border-surface-0 transition-colors duration-75 ${
                      stepActive
                        ? currentStep === si && seq.isPlaying
                          ? "bg-white"
                          : "bg-accent-green"
                        : currentStep === si && seq.isPlaying
                          ? "bg-surface-3"
                          : "bg-surface-2 hover:bg-surface-3"
                    }`}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Beat markers */}
        <div className="flex items-center gap-2 mt-0.5">
          <div className="w-16" />
          <div className="flex gap-0 flex-1">
            {Array.from({ length: numSteps }, (_, i) => (
              <div
                key={i}
                className={`flex-1 h-0.5 ${
                  i % (numSteps / 4) === 0 ? "bg-text-muted" : "bg-transparent"
                }`}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button className="btn-secondary" onClick={() => seq.clearGroup(activeGroup)}>
          CLEAR GROUP {activeGroup}
        </button>
      </div>

      {/* FX Reference */}
      <div className="panel">
        <div className="panel-header">EP-133 Effects</div>
        <div className="grid grid-cols-6 gap-0">
          {EP133_FX.map((fx) => (
            <div
              key={fx}
              className="px-2 py-2 border border-surface-3 text-center text-[10px] text-text-secondary uppercase tracking-wider"
            >
              {fx}
            </div>
          ))}
        </div>
      </div>

      {/* Workflow reference */}
      <div className="panel">
        <div className="panel-header">EP-133 Workflow reference</div>
        <div className="space-y-1.5 text-[10px] text-text-secondary">
          <div><span className="text-accent-green">RECORD + PAD</span> — record pad to current step</div>
          <div><span className="text-accent-green">-/+</span> — navigate steps forward/backward</div>
          <div><span className="text-accent-green">KEYS</span> — chromatic keyboard mode</div>
          <div><span className="text-accent-green">TIMING + Knob X</span> — set note interval</div>
          <div><span className="text-accent-green">TIMING + Knob Y</span> — set swing</div>
          <div><span className="text-accent-green">SHIFT + MAIN</span> — commit scene</div>
          <div><span className="text-accent-green">ERASE + PAD</span> — erase pad notes</div>
        </div>
      </div>
    </div>
  );
}
