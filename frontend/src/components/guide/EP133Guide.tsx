import { useState, useCallback } from "react";

/* ------------------------------------------------------------------ */
/* EP-133 K.O.II constants from manual                                 */
/* ------------------------------------------------------------------ */

const GROUPS = ["A", "B", "C", "D"] as const;
type Group = (typeof GROUPS)[number];

const GROUP_ROLES: Record<Group, { label: string; slots: string }> = {
  A: { label: "DRUMS", slots: "1-99 Kicks / 100-199 Snares / 200-299 Hats / 300-399 Perc" },
  B: { label: "BASS", slots: "400-499" },
  C: { label: "MELODIC", slots: "500-599" },
  D: { label: "SAMPLES / LOOPS", slots: "User samples" },
};

const TIMING_MODES = ["1/8", "1/8T", "1/16", "1/16T", "1/32"] as const;
type TimingMode = (typeof TIMING_MODES)[number];

const STEPS_PER_BAR: Record<TimingMode, number> = {
  "1/8": 8,
  "1/8T": 12,
  "1/16": 16,
  "1/16T": 24,
  "1/32": 32,
};

const PADS = 12;

const DEFAULT_PADS: Record<Group, string[]> = {
  A: ["KICK 1", "KICK 2", "SNARE 1", "SNARE 2", "HAT CL", "HAT OP",
      "CLAP", "RIM", "TOM HI", "TOM LO", "PERC 1", "PERC 2"],
  B: ["BASS 1", "BASS 2", "BASS 3", "BASS 4", "SUB 1", "SUB 2",
      "BASS 5", "BASS 6", "BASS 7", "BASS 8", "BASS 9", "BASS 10"],
  C: ["PAD 1", "PAD 2", "LEAD 1", "LEAD 2", "STAB 1", "STAB 2",
      "BELL 1", "BELL 2", "KEY 1", "KEY 2", "TEXTURE 1", "TEXTURE 2"],
  D: ["SMP 1", "SMP 2", "SMP 3", "SMP 4", "SMP 5", "SMP 6",
      "SMP 7", "SMP 8", "SMP 9", "SMP 10", "SMP 11", "SMP 12"],
};

const EP133_FX = [
  "DELAY", "REVERB", "DISTORTION", "CHORUS", "FILTER", "COMPRESSOR",
];

interface PatternStep {
  active: boolean;
}

interface PadTrack {
  name: string;
  padNum: number;
  steps: PatternStep[];
}

/* ------------------------------------------------------------------ */
/* Instruction generator                                               */
/* ------------------------------------------------------------------ */

function generateInstructions(
  group: Group,
  tracks: PadTrack[],
  timing: TimingMode
): string[] {
  const inst: string[] = [];
  let n = 1;

  inst.push(`${n++}. Press MAIN to enter main mode`);
  inst.push(`${n++}. Press Group ${group} to select ${GROUP_ROLES[group].label}`);
  inst.push(`${n++}. Press TIMING, turn Knob X to set note interval to ${timing}`);

  for (const track of tracks) {
    const activeSteps = track.steps
      .map((s, i) => (s.active ? i + 1 : null))
      .filter((s): s is number => s !== null);

    if (activeSteps.length === 0) continue;

    inst.push(`${n++}. Select Pad ${track.padNum} — "${track.name}"`);

    for (const step of activeSteps) {
      const bar = Math.floor((step - 1) / STEPS_PER_BAR[timing]) + 1;
      const beat = Math.floor(((step - 1) % STEPS_PER_BAR[timing]) / (STEPS_PER_BAR[timing] / 4)) + 1;
      const subStep = ((step - 1) % (STEPS_PER_BAR[timing] / 4)) + 1;
      inst.push(
        `${n++}. Navigate to step ${bar}.${beat}.${subStep} — hold RECORD + press Pad ${track.padNum}`
      );
    }
  }

  inst.push(`${n++}. Press PLAY to hear your pattern`);
  inst.push(`${n++}. Press SHIFT + MAIN to commit as a scene`);
  inst.push(`${n}. To extend: hold RECORD + press + to add bars`);

  return inst;
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function EP133Guide() {
  const [activeGroup, setActiveGroup] = useState<Group>("A");
  const [timing, setTiming] = useState<TimingMode>("1/16");
  const [selectedPad, setSelectedPad] = useState(0);
  const [showInstructions, setShowInstructions] = useState(false);

  const stepsCount = STEPS_PER_BAR[timing];

  const [groupTracks, setGroupTracks] = useState<Record<Group, PadTrack[]>>(
    () => {
      const tracks: Record<string, PadTrack[]> = {};
      for (const g of GROUPS) {
        tracks[g] = DEFAULT_PADS[g].map((name, i) => ({
          name,
          padNum: i + 1,
          steps: Array.from({ length: 32 }, () => ({ active: false })),
        }));
      }
      return tracks as Record<Group, PadTrack[]>;
    }
  );

  const tracks = groupTracks[activeGroup];

  const toggleStep = useCallback(
    (padIdx: number, stepIdx: number) => {
      setGroupTracks((prev) => ({
        ...prev,
        [activeGroup]: prev[activeGroup].map((track, pi) =>
          pi === padIdx
            ? {
                ...track,
                steps: track.steps.map((step, si) =>
                  si === stepIdx ? { active: !step.active } : step
                ),
              }
            : track
        ),
      }));
    },
    [activeGroup]
  );

  const clearGroup = () => {
    setGroupTracks((prev) => ({
      ...prev,
      [activeGroup]: prev[activeGroup].map((track) => ({
        ...track,
        steps: track.steps.map(() => ({ active: false })),
      })),
    }));
    setShowInstructions(false);
  };

  const instructions = generateInstructions(activeGroup, tracks, timing);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          EP-133 K.O.II GUIDE
        </h1>
        <p className="text-text-muted text-xs mt-1">
          12 PADS × 4 GROUPS — 99 PATTERNS — 99 SCENES — 96 PPQN SEQUENCER.
        </p>
      </div>

      {/* Device info */}
      <div className="panel">
        <div className="flex gap-6 text-[10px] text-text-muted tracking-widest">
          <span>64 MB MEMORY</span>
          <span>999 SAMPLE SLOTS</span>
          <span>96 PPQN</span>
          <span>TIMING: {timing}</span>
          <span>STEPS/BAR: {stepsCount}</span>
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
                onClick={() => {
                  setActiveGroup(g);
                  setSelectedPad(0);
                }}
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
        <div className="panel w-64">
          <div className="panel-header">Timing mode</div>
          <div className="grid grid-cols-5 gap-0">
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
          <p className="text-[9px] text-text-muted mt-2">
            T = triplet. Press TIMING + turn Knob X on device.
          </p>
        </div>
      </div>

      {/* Pad selector (3×4 grid like the device) */}
      <div className="panel">
        <div className="panel-header">
          Pads — Group {activeGroup} ({GROUP_ROLES[activeGroup].label})
        </div>
        <div className="grid grid-cols-3 gap-1 max-w-xs">
          {/* Pads numbered 7-9, 4-6, 1-3, ., 0, enter — matching device layout */}
          {[
            [6, 7, 8],   /* top row: pads 7, 8, 9 */
            [3, 4, 5],   /* mid row: pads 4, 5, 6 */
            [0, 1, 2],   /* bot row: pads 1, 2, 3 */
            [9, 10, 11],  /* extra row: pads 10, 11, 12 */
          ].map((row, ri) => (
            <div key={ri} className="contents">
              {row.map((padIdx) => {
                const track = tracks[padIdx];
                const hasSteps = track.steps.slice(0, stepsCount).some((s) => s.active);
                return (
                  <button
                    key={padIdx}
                    onClick={() => setSelectedPad(padIdx)}
                    className={`aspect-square flex flex-col items-center justify-center border transition-colors duration-100 ${
                      selectedPad === padIdx
                        ? "bg-accent-green/15 text-accent-green border-accent-green"
                        : hasSteps
                          ? "bg-surface-2 text-text-secondary border-surface-3"
                          : "bg-surface-0 text-text-muted border-surface-3 hover:bg-surface-2"
                    }`}
                  >
                    <span className="text-xs font-bold">{padIdx + 1}</span>
                    <span className="text-[8px] tracking-wider mt-0.5 truncate max-w-full px-1">
                      {track.name}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Step sequencer */}
      <div className="panel">
        <div className="panel-header">
          Step sequencer — {tracks[selectedPad].name} (Pad {selectedPad + 1}) — {timing}
        </div>

        {/* Step numbers */}
        <div className="flex gap-0 mb-1">
          {Array.from({ length: stepsCount }, (_, i) => (
            <div
              key={i}
              className="flex-1 text-center text-[8px] text-text-muted"
            >
              {i + 1}
            </div>
          ))}
        </div>

        {/* Steps */}
        <div className="flex gap-0">
          {tracks[selectedPad].steps.slice(0, stepsCount).map((step, i) => (
            <button
              key={i}
              onClick={() => toggleStep(selectedPad, i)}
              className={`flex-1 h-8 border transition-colors duration-75 ${
                step.active
                  ? "bg-accent-green border-accent-green"
                  : "bg-surface-0 border-surface-3 hover:bg-surface-2"
              }`}
            />
          ))}
        </div>

        {/* Beat markers */}
        <div className="flex gap-0 mt-0.5">
          {Array.from({ length: stepsCount }, (_, i) => {
            const beatsPerBar = stepsCount / 4;
            return (
              <div
                key={i}
                className={`flex-1 h-0.5 ${
                  i % beatsPerBar === 0 ? "bg-text-muted" : "bg-transparent"
                }`}
              />
            );
          })}
        </div>

        {/* All pads overview for this group */}
        <div className="mt-4">
          <span className="label">All pads — Group {activeGroup}</span>
          <div className="space-y-0.5 mt-1">
            {tracks.map((track, pi) => {
              const visibleSteps = track.steps.slice(0, stepsCount);
              return (
                <div key={pi} className="flex items-center gap-2">
                  <span
                    className={`w-14 text-[8px] uppercase tracking-wider truncate ${
                      pi === selectedPad
                        ? "text-accent-green"
                        : "text-text-muted"
                    }`}
                  >
                    {track.name}
                  </span>
                  <div className="flex gap-0 flex-1">
                    {visibleSteps.map((step, si) => (
                      <button
                        key={si}
                        onClick={() => {
                          setSelectedPad(pi);
                          toggleStep(pi, si);
                        }}
                        className={`flex-1 h-2.5 border-r border-surface-0 transition-colors duration-75 ${
                          step.active
                            ? pi === selectedPad
                              ? "bg-accent-green"
                              : "bg-accent-green/50"
                            : "bg-surface-2"
                        }`}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
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
        <button className="btn-secondary" onClick={clearGroup}>
          CLEAR GROUP {activeGroup}
        </button>
      </div>

      {/* Instructions */}
      {showInstructions && (
        <div className="panel">
          <div className="panel-header">
            EP-133 Programming instructions — Group {activeGroup}
          </div>
          <div className="space-y-2">
            {instructions.map((inst, i) => (
              <div key={i} className="text-xs text-text-primary leading-relaxed">
                {inst}
              </div>
            ))}
          </div>
        </div>
      )}

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
        <p className="text-[9px] text-text-muted mt-2">
          Press FX while playing. Use -/+ to browse. Fader controls FX level per group.
          Hold FX + Group pad to solo. SHIFT + FX for master compressor.
        </p>
      </div>

      {/* Workflow reference */}
      <div className="panel">
        <div className="panel-header">EP-133 Workflow reference</div>
        <div className="space-y-1.5 text-[10px] text-text-secondary">
          <div><span className="text-accent-green">RECORD + PAD</span> — record pad to current step</div>
          <div><span className="text-accent-green">-/+</span> — navigate steps forward/backward</div>
          <div><span className="text-accent-green">RECORD + -/+</span> — change pattern length</div>
          <div><span className="text-accent-green">KEYS</span> — chromatic keyboard mode for selected pad</div>
          <div><span className="text-accent-green">KEYS + -/+</span> — change octave</div>
          <div><span className="text-accent-green">TIMING + Knob X</span> — set note interval</div>
          <div><span className="text-accent-green">TIMING + Knob Y</span> — set swing</div>
          <div><span className="text-accent-green">SHIFT + MAIN</span> — commit scene</div>
          <div><span className="text-accent-green">ERASE + PAD</span> — erase pad notes</div>
          <div><span className="text-accent-green">SHIFT + Group</span> — find next empty pattern</div>
          <div><span className="text-accent-green">HOLD MAIN + -/+</span> — select scene</div>
        </div>
      </div>
    </div>
  );
}
