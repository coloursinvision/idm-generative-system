import { useEffect, useState, useCallback } from "react";
import { useSequencer } from "../../hooks/useSequencer";

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

const TIMING_MODES = ["1/8", "1/16", "1/32"] as const;
type TimingMode = (typeof TIMING_MODES)[number];

const STEPS_PER_TIMING: Record<TimingMode, number> = {
  "1/8": 8,
  "1/16": 16,
  "1/32": 32,
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
  const [activeGroup, setActiveGroup] = useState<Group>("A");
  const [timing, setTiming] = useState<TimingMode>("1/16");

  const numSteps = STEPS_PER_TIMING[timing];

  const {
    tracks,
    bpm,
    setBpm,
    isPlaying,
    currentStep,
    loadingAll,
    initTracks,
    toggleStep,
    loadAllSamples,
    play,
    stop,
    clearPattern,
  } = useSequencer({ numSteps, defaultBpm: 130 });

  // Re-init tracks when group changes
  const switchGroup = useCallback(
    (group: Group) => {
      if (isPlaying) stop();
      setActiveGroup(group);
    },
    [isPlaying, stop]
  );

  useEffect(() => {
    initTracks(GROUP_TRACKS[activeGroup]);
  }, [activeGroup, initTracks]);

  const hasBuffers = tracks.some((t) => t.buffer !== null);
  const hasPattern = tracks.some((t) => t.steps.some(Boolean));

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          EP-133 K.O.II GUIDE
        </h1>
        <p className="text-text-muted text-xs mt-1">
          12 PADS × 4 GROUPS — LOAD SAMPLES, PROGRAM PATTERNS, PLAY BACK IN
          BROWSER.
        </p>
      </div>

      {/* Device info */}
      <div className="panel">
        <div className="flex gap-6 text-[10px] text-text-muted tracking-widest">
          <span>GROUP {activeGroup}: {GROUP_ROLES[activeGroup].label}</span>
          <span>TIMING: {timing}</span>
          <span>STEPS: {numSteps}</span>
          <span>BPM: {bpm}</span>
        </div>
      </div>

      {/* Group selector + Timing */}
      <div className="flex gap-4">
        {/* Groups */}
        <div className="panel flex-1">
          <div className="panel-header">Groups</div>
          <div className="grid grid-cols-4 gap-0">
            {GROUPS.map((g) => (
              <button
                key={g}
                onClick={() => switchGroup(g)}
                className={`py-3 text-center border transition-colors duration-100 ${
                  activeGroup === g
                    ? "bg-accent-green/10 text-accent-green border-accent-green"
                    : "bg-surface-0 text-text-muted border-surface-3 hover:text-text-secondary"
                }`}
              >
                <div className="text-lg font-bold font-display">{g}</div>
                <div className="text-[9px] tracking-widest mt-0.5">
                  {GROUP_ROLES[g].label}
                </div>
              </button>
            ))}
          </div>
          <div className="text-[9px] text-text-muted mt-2 tracking-wider">
            SLOTS: {GROUP_ROLES[activeGroup].slots}
          </div>
        </div>

        {/* Timing */}
        <div className="panel w-48">
          <div className="panel-header">Timing</div>
          <div className="grid grid-cols-3 gap-0">
            {TIMING_MODES.map((t) => (
              <button
                key={t}
                onClick={() => setTiming(t)}
                className={`py-2 text-[10px] border transition-colors duration-100 ${
                  timing === t
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

      {/* Transport */}
      <div className="panel">
        <div className="panel-header">Transport</div>
        <div className="flex items-end gap-4">
          <button
            className="btn-primary"
            onClick={loadAllSamples}
            disabled={loadingAll}
          >
            {loadingAll
              ? "LOADING…"
              : hasBuffers
                ? "RELOAD SAMPLES"
                : "LOAD SAMPLES"}
          </button>

          <button
            className={`${isPlaying ? "btn-secondary border-accent-red text-accent-red" : "btn-primary"}`}
            onClick={isPlaying ? stop : play}
            disabled={!hasBuffers || !hasPattern}
          >
            {isPlaying ? "STOP" : "PLAY"}
          </button>

          <div>
            <label className="label">BPM: {bpm}</label>
            <input
              type="range"
              min={60}
              max={200}
              value={bpm}
              onChange={(e) => setBpm(Number(e.target.value))}
              className="w-32 accent-accent-green"
            />
          </div>

          <div className="text-[10px] text-text-muted tracking-wider ml-auto">
            {tracks.filter((t) => t.buffer).length}/{tracks.length} SAMPLES
            LOADED
          </div>
        </div>
      </div>

      {/* Step sequencer — all tracks in group */}
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
          {tracks.map((track, ti) => (
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
                {track.steps.slice(0, numSteps).map((active, si) => (
                  <button
                    key={si}
                    onClick={() => toggleStep(ti, si)}
                    className={`flex-1 h-5 border-r border-surface-0 transition-colors duration-75 ${
                      active
                        ? currentStep === si && isPlaying
                          ? "bg-white"
                          : "bg-accent-green"
                        : currentStep === si && isPlaying
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
        <button className="btn-secondary" onClick={clearPattern}>
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
