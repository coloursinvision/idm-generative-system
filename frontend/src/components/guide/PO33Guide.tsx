import { useState, useCallback } from "react";

/* ------------------------------------------------------------------ */
/* PO-33 K.O! constants from manual                                    */
/* ------------------------------------------------------------------ */

const STEPS = 16;
const SOUND_SLOTS = {
  melodic: { label: "MELODIC", range: [1, 8] as const },
  drum: { label: "DRUM", range: [9, 16] as const },
};

const PO33_FX: Record<number, string> = {
  1: "Loop 16",
  2: "Loop 12",
  3: "Loop short",
  4: "Loop shorter",
  5: "Unison",
  6: "Unison low",
  7: "Octave up",
  8: "Octave down",
  9: "Stutter 4",
  10: "Stutter 3",
  11: "Scratch",
  12: "Scratch fast",
  13: "6/8 Quantise",
  14: "Retrigger pattern",
  15: "Reverse",
  16: "No effect",
};

const DEFAULT_SOUNDS = [
  { slot: 1, name: "KICK", type: "drum" },
  { slot: 2, name: "SNARE", type: "drum" },
  { slot: 3, name: "HAT", type: "drum" },
  { slot: 4, name: "CLAP", type: "drum" },
  { slot: 5, name: "PERC 1", type: "drum" },
  { slot: 6, name: "PERC 2", type: "drum" },
  { slot: 7, name: "GLITCH 1", type: "drum" },
  { slot: 8, name: "GLITCH 2", type: "drum" },
];

interface PatternStep {
  active: boolean;
}

interface Track {
  name: string;
  slot: number;
  steps: PatternStep[];
}

/* ------------------------------------------------------------------ */
/* Instruction generator                                               */
/* ------------------------------------------------------------------ */

function generateInstructions(tracks: Track[]): string[] {
  const instructions: string[] = [];
  let stepNum = 1;

  instructions.push(`${stepNum++}. Press BPM to set tempo (HIP HOP=80, DISCO=120, TECHNO=140)`);

  for (const track of tracks) {
    const activeSteps = track.steps
      .map((s, i) => (s.active ? i + 1 : null))
      .filter((s): s is number => s !== null);

    if (activeSteps.length === 0) continue;

    instructions.push(
      `${stepNum++}. Hold SOUND + press ${track.slot} — select "${track.name}"`
    );
    instructions.push(
      `${stepNum++}. Press WRITE to enter rec mode`
    );
    instructions.push(
      `${stepNum++}. Press steps ${activeSteps.join(", ")} — program pattern`
    );
    instructions.push(
      `${stepNum++}. Press WRITE to exit rec mode`
    );
  }

  instructions.push(`${stepNum++}. Press PLAY to hear your pattern`);
  instructions.push(`${stepNum}. To chain patterns: hold PATTERN + press 1-16`);

  return instructions;
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function PO33Guide() {
  const [tracks, setTracks] = useState<Track[]>(() =>
    DEFAULT_SOUNDS.map((s) => ({
      name: s.name,
      slot: s.slot,
      steps: Array.from({ length: STEPS }, () => ({ active: false })),
    }))
  );

  const [selectedTrack, setSelectedTrack] = useState(0);
  const [showInstructions, setShowInstructions] = useState(false);

  const toggleStep = useCallback(
    (trackIdx: number, stepIdx: number) => {
      setTracks((prev) =>
        prev.map((track, ti) =>
          ti === trackIdx
            ? {
                ...track,
                steps: track.steps.map((step, si) =>
                  si === stepIdx ? { active: !step.active } : step
                ),
              }
            : track
        )
      );
    },
    []
  );

  const clearAll = () => {
    setTracks((prev) =>
      prev.map((track) => ({
        ...track,
        steps: track.steps.map(() => ({ active: false })),
      }))
    );
    setShowInstructions(false);
  };

  const instructions = generateInstructions(tracks);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          PO-33 K.O! GUIDE
        </h1>
        <p className="text-text-muted text-xs mt-1">
          16-STEP SEQUENCER — PROGRAM PATTERNS AND GET STEP-BY-STEP INSTRUCTIONS
          FOR YOUR PO-33.
        </p>
      </div>

      {/* Device info */}
      <div className="panel">
        <div className="flex gap-6 text-[10px] text-text-muted tracking-widest">
          <span>16 STEPS</span>
          <span>16 SOUNDS (8 MELODIC + 8 DRUM)</span>
          <span>16 PATTERNS</span>
          <span>40s SAMPLE MEMORY</span>
        </div>
      </div>

      {/* Track selector */}
      <div className="panel">
        <div className="panel-header">Sound slots</div>
        <div className="grid grid-cols-8 gap-0">
          {tracks.map((track, i) => (
            <button
              key={i}
              onClick={() => setSelectedTrack(i)}
              className={`py-2 text-[10px] uppercase tracking-[0.1em] border transition-colors duration-100 ${
                selectedTrack === i
                  ? "bg-accent-green/10 text-accent-green border-accent-green"
                  : track.steps.some((s) => s.active)
                    ? "bg-surface-2 text-text-secondary border-surface-3"
                    : "bg-surface-0 text-text-muted border-surface-3 hover:text-text-secondary"
              }`}
            >
              {track.name}
            </button>
          ))}
        </div>
      </div>

      {/* Step sequencer grid */}
      <div className="panel">
        <div className="panel-header">
          Step sequencer — {tracks[selectedTrack].name} (slot {tracks[selectedTrack].slot})
        </div>

        {/* Step numbers */}
        <div className="grid grid-cols-16 gap-0 mb-1">
          {Array.from({ length: STEPS }, (_, i) => (
            <div
              key={i}
              className="text-center text-[9px] text-text-muted"
            >
              {i + 1}
            </div>
          ))}
        </div>

        {/* Active track steps */}
        <div className="grid grid-cols-16 gap-0">
          {tracks[selectedTrack].steps.map((step, i) => (
            <button
              key={i}
              onClick={() => toggleStep(selectedTrack, i)}
              className={`aspect-square border transition-colors duration-75 ${
                step.active
                  ? "bg-accent-green border-accent-green"
                  : "bg-surface-0 border-surface-3 hover:bg-surface-2"
              }`}
            />
          ))}
        </div>

        {/* Beat markers */}
        <div className="grid grid-cols-16 gap-0 mt-0.5">
          {Array.from({ length: STEPS }, (_, i) => (
            <div
              key={i}
              className={`h-0.5 ${
                i % 4 === 0 ? "bg-text-muted" : "bg-transparent"
              }`}
            />
          ))}
        </div>

        {/* All tracks overview */}
        <div className="mt-4">
          <span className="label">All tracks</span>
          <div className="space-y-0.5 mt-1">
            {tracks.map((track, ti) => (
              <div key={ti} className="flex items-center gap-2">
                <span
                  className={`w-16 text-[9px] uppercase tracking-wider truncate ${
                    ti === selectedTrack
                      ? "text-accent-green"
                      : "text-text-muted"
                  }`}
                >
                  {track.name}
                </span>
                <div className="flex gap-0 flex-1">
                  {track.steps.map((step, si) => (
                    <button
                      key={si}
                      onClick={() => {
                        setSelectedTrack(ti);
                        toggleStep(ti, si);
                      }}
                      className={`flex-1 h-3 border-r border-surface-0 transition-colors duration-75 ${
                        step.active
                          ? ti === selectedTrack
                            ? "bg-accent-green"
                            : "bg-accent-green/50"
                          : "bg-surface-2"
                      }`}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        <button
          className="btn-primary"
          onClick={() => setShowInstructions(true)}
        >
          GENERATE INSTRUCTIONS
        </button>
        <button className="btn-secondary" onClick={clearAll}>
          CLEAR ALL
        </button>
      </div>

      {/* Instructions */}
      {showInstructions && (
        <div className="panel">
          <div className="panel-header">
            PO-33 Programming instructions
          </div>
          <div className="space-y-2">
            {instructions.map((inst, i) => (
              <div key={i} className="flex gap-3 text-xs">
                <span className="text-text-primary leading-relaxed">
                  {inst}
                </span>
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
          Hold FX + press 1-15 during playback. WRITE mode saves FX to pattern. FX + 16 = clear.
        </p>
      </div>
    </div>
  );
}
