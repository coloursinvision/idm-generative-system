import { useEffect } from "react";
import { useSequencer } from "../../hooks/useSequencer";

/* ------------------------------------------------------------------ */
/* PO-33 K.O! constants from manual                                    */
/* ------------------------------------------------------------------ */

const STEPS = 16;

const PO33_FX: Record<number, string> = {
  1: "Loop 16", 2: "Loop 12", 3: "Loop short", 4: "Loop shorter",
  5: "Unison", 6: "Unison low", 7: "Octave up", 8: "Octave down",
  9: "Stutter 4", 10: "Stutter 3", 11: "Scratch", 12: "Scratch fast",
  13: "6/8 Quantise", 14: "Retrigger pattern", 15: "Reverse", 16: "No effect",
};

const TRACK_DEFS = [
  { name: "KICK", generator: "noise_burst" },
  { name: "SNARE", generator: "noise_burst" },
  { name: "HAT", generator: "glitch_click" },
  { name: "CLAP", generator: "noise_burst" },
  { name: "PERC 1", generator: "glitch_click" },
  { name: "PERC 2", generator: "glitch_click" },
  { name: "GLITCH 1", generator: "fm_blip" },
  { name: "GLITCH 2", generator: "fm_blip" },
];

/* ------------------------------------------------------------------ */
/* Instruction generator                                               */
/* ------------------------------------------------------------------ */

function generateInstructions(
  tracks: { name: string; steps: boolean[] }[]
): string[] {
  const instructions: string[] = [];
  let stepNum = 1;

  instructions.push(
    `${stepNum++}. Press BPM to set tempo (HIP HOP=80, DISCO=120, TECHNO=140)`
  );

  for (let ti = 0; ti < tracks.length; ti++) {
    const track = tracks[ti];
    const activeSteps = track.steps
      .map((s, i) => (s ? i + 1 : null))
      .filter((s): s is number => s !== null);

    if (activeSteps.length === 0) continue;

    instructions.push(
      `${stepNum++}. Hold SOUND + press ${ti + 1} — select "${track.name}"`
    );
    instructions.push(`${stepNum++}. Press WRITE to enter rec mode`);
    instructions.push(
      `${stepNum++}. Press steps ${activeSteps.join(", ")} — program pattern`
    );
    instructions.push(`${stepNum++}. Press WRITE to exit rec mode`);
  }

  instructions.push(`${stepNum++}. Press PLAY to hear your pattern`);
  instructions.push(
    `${stepNum}. To chain patterns: hold PATTERN + press 1-16`
  );

  return instructions;
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function PO33Guide() {
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
  } = useSequencer({ numSteps: STEPS, defaultBpm: 120 });

  useEffect(() => {
    initTracks(TRACK_DEFS);
  }, [initTracks]);

  const hasBuffers = tracks.some((t) => t.buffer !== null);
  const hasPattern = tracks.some((t) => t.steps.some(Boolean));

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          PO-33 K.O! GUIDE
        </h1>
        <p className="text-text-muted text-xs mt-1">
          16-STEP SEQUENCER — LOAD SAMPLES, PROGRAM PATTERNS, PLAY BACK IN
          BROWSER.
        </p>
      </div>

      {/* Device info */}
      <div className="panel">
        <div className="flex gap-6 text-[10px] text-text-muted tracking-widest">
          <span>16 STEPS</span>
          <span>8 SOUNDS</span>
          <span>16 PATTERNS</span>
          <span>BPM: {bpm}</span>
        </div>
      </div>

      {/* Transport + BPM */}
      <div className="panel">
        <div className="panel-header">Transport</div>
        <div className="flex items-end gap-4">
          <button
            className="btn-primary"
            onClick={loadAllSamples}
            disabled={loadingAll}
          >
            {loadingAll ? "LOADING…" : hasBuffers ? "RELOAD SAMPLES" : "LOAD SAMPLES"}
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

      {/* Step sequencer — all tracks */}
      <div className="panel">
        <div className="panel-header">Step sequencer</div>

        {/* Step numbers + playhead */}
        <div className="flex items-center gap-2 mb-1">
          <div className="w-16" />
          <div className="flex gap-0 flex-1">
            {Array.from({ length: STEPS }, (_, i) => (
              <div
                key={i}
                className={`flex-1 text-center text-[9px] ${
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
                  className={`text-[9px] uppercase tracking-wider truncate ${
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
                {track.steps.map((active, si) => (
                  <button
                    key={si}
                    onClick={() => toggleStep(ti, si)}
                    className={`flex-1 h-6 border-r border-surface-0 transition-colors duration-75 ${
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
            {Array.from({ length: STEPS }, (_, i) => (
              <div
                key={i}
                className={`flex-1 h-0.5 ${
                  i % 4 === 0 ? "bg-text-muted" : "bg-transparent"
                }`}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button className="btn-secondary" onClick={clearPattern}>
          CLEAR ALL
        </button>
      </div>

      {/* Instructions — auto-show when pattern exists */}
      {hasPattern && (
        <div className="panel">
          <div className="panel-header">PO-33 Programming instructions</div>
          <div className="space-y-2">
            {generateInstructions(tracks).map((inst, i) => (
              <div
                key={i}
                className="text-xs text-text-primary leading-relaxed"
              >
                {inst}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* FX Reference */}
      <div className="panel">
        <div className="panel-header">PO-33 Effects reference</div>
        <div className="grid grid-cols-4 gap-0">
          {Object.entries(PO33_FX).map(([num, name]) => (
            <div
              key={num}
              className="flex items-baseline gap-2 px-2 py-1.5 border border-surface-3 text-[10px]"
            >
              <span className="text-accent-green font-bold">{num}</span>
              <span className="text-text-secondary uppercase tracking-wider">
                {name}
              </span>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-text-muted mt-2">
          Hold FX + press 1-15 during playback. WRITE mode saves FX to pattern.
          FX + 16 = clear.
        </p>
      </div>
    </div>
  );
}
