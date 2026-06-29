/*
 * EP-133 multi-group Web Audio sequencer: single master transport
 * coordinating groups A/B/C/D so they play simultaneously.
 *
 * Distinct from useSequencer.ts (single-pool, used by the PO-33 guide),
 * which is intentionally left unchanged.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { postGenerate } from "../api/client";
import type { SequencerTrack } from "./useSequencer";
import { SCHEDULER_INTERVAL_MS } from "./useSequencer";

/* Timing model - single source of truth for the EP-133 guide          */

export const TIMING_MODES = ["1/8", "1/16", "1/32"] as const;
export type TimingMode = (typeof TIMING_MODES)[number];

/** Steps per bar for each note interval (manual §4.7; triplets out of scope). */
export const STEPS_PER_TIMING: Record<TimingMode, number> = {
  "1/8": 8,
  "1/16": 16,
  "1/32": 32,
};

/**
 * Master grid resolution. The finest supported interval (1/32) defines the
 * master clock at 32 ticks/bar; every group strides over this single clock.
 * Because 8, 16 and 32 all divide 32, all groups stay phase-aligned, which is
 * what makes correct polyrhythm possible (AC6). If triplet intervals are ever
 * added the master grid must grow to LCM(8,12,16,24,32)=96 (hardware PPQN).
 */
const MASTER_TICKS_PER_BAR = 32;

const DEFAULT_TIMING: TimingMode = "1/16";

/** Master-clock ticks between two consecutive steps of a group's pattern. */
function strideFor(timing: TimingMode): number {
  return MASTER_TICKS_PER_BAR / STEPS_PER_TIMING[timing];
}

/* Per-group state shape                                               */

export interface GroupSequencerState {
  /** Tracks for this group - reuses the PO-33 track shape (steps/buffer/loading). */
  tracks: SequencerTrack[];
  /** Note interval active for this group (per-pattern, manual §4.7). */
  timing: TimingMode;
  /** Mixer mute. Silenced unless a solo elsewhere overrides (solo wins). */
  muted: boolean;
  /** Mixer solo. Any group soloed → only soloed groups are audible. */
  solo: boolean;
  /** True while this group's samples are being (re)loaded. */
  loading: boolean;
}

interface UseEP133SequencerOptions<G extends string> {
  /** Ordered list of group identifiers, e.g. ["A","B","C","D"]. */
  groups: readonly G[];
  /** Track definitions per group. */
  groupTracks: Record<G, { name: string; generator: string }[]>;
  /** Initial global BPM (manual §8.4 - project-global, 40–399). */
  defaultBpm?: number;
}

/*
 * AudioContext lifecycle.
 *
 * The WebKit/Safari AudioContext lifecycle logic below is duplicated from
 * useSequencer.ts on purpose: a shared `useAudioContext` util is deferred to
 * a separate refactor. Keep the two copies in sync until that util lands.
 */

type NonRunningState = "suspended" | "interrupted";

function isNonRunningState(state: string): state is NonRunningState {
  return state === "suspended" || state === "interrupted";
}

/* Initial state                                                       */

function makeInitialGroups<G extends string>(
  groups: readonly G[],
  groupTracks: Record<G, { name: string; generator: string }[]>
): Record<G, GroupSequencerState> {
  const numSteps = STEPS_PER_TIMING[DEFAULT_TIMING];
  return groups.reduce((acc, g) => {
    acc[g] = {
      tracks: groupTracks[g].map((def) => ({
        name: def.name,
        generator: def.generator,
        steps: Array(numSteps).fill(false),
        buffer: null,
        loading: false,
      })),
      timing: DEFAULT_TIMING,
      muted: false,
      solo: false,
      loading: false,
    };
    return acc;
  }, {} as Record<G, GroupSequencerState>);
}

/* Hook                                                                */

/**
 * Multi-group EP-133 sequencer. One AudioContext, one master clock; every
 * group is iterated unconditionally on every tick so all four play at once.
 * Switching the editing surface in the UI does not affect playback.
 */
export function useEP133Sequencer<G extends string>({
  groups,
  groupTracks,
  defaultBpm = 120,
}: UseEP133SequencerOptions<G>) {
  const [bpm, setBpm] = useState(defaultBpm);
  const [isPlaying, setIsPlaying] = useState(false);
  const [groupsState, setGroupsState] = useState<Record<G, GroupSequencerState>>(
    () => makeInitialGroups(groups, groupTracks)
  );
  const [currentStepByGroup, setCurrentStepByGroup] = useState<Record<G, number>>(
    () => groups.reduce((acc, g) => { acc[g] = -1; return acc; }, {} as Record<G, number>)
  );

  const audioCtxRef = useRef<AudioContext | null>(null);
  const masterGainRef = useRef<GainNode | null>(null);
  const timerRef = useRef<number | null>(null);
  const masterStepRef = useRef(0);
  const nextNoteTimeRef = useRef(0);
  const groupsRef = useRef(groupsState);
  const bpmRef = useRef(defaultBpm);
  const currentStepRef = useRef<Record<G, number>>(currentStepByGroup);

  // Keep refs in sync with state for lock-free reads inside the scheduler.
  useEffect(() => { groupsRef.current = groupsState; }, [groupsState]);
  useEffect(() => { bpmRef.current = bpm; }, [bpm]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (audioCtxRef.current) audioCtxRef.current.close();
    };
  }, []);

  /** Resume the AudioContext on tab-restore (incl. Safari BFCache). */
  useEffect(() => {
    const handleVisibilityChange = async () => {
      const ctx = audioCtxRef.current;
      if (
        document.visibilityState === "visible" &&
        ctx &&
        ctx.state !== "running" &&
        ctx.state !== "closed"
      ) {
        try {
          await ctx.resume();
        } catch (err) {
          console.warn("[useEP133Sequencer] resume on visibility restore failed:", err);
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  const getAudioContext = useCallback(async (): Promise<AudioContext> => {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext({ sampleRate: 44100 });
      masterGainRef.current = null; // rebuild the master bus for the new context
    }
    const ctx = audioCtxRef.current;

    // Master bus: every group's voices sum here, so route through a gain stage
    // (headroom for up to 4 simultaneous groups) into a compressor acting as a
    // limiter, mirroring the EP-133 hardware master compressor (manual §11).
    // Without this the raw sum clips past 0 dBFS and degrades into distortion.
    if (!masterGainRef.current) {
      const gain = ctx.createGain();
      gain.gain.value = 0.35;
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -10;
      comp.knee.value = 6;
      comp.ratio.value = 12;
      comp.attack.value = 0.003;
      comp.release.value = 0.25;
      gain.connect(comp);
      comp.connect(ctx.destination);
      masterGainRef.current = gain;
    }

    if (isNonRunningState(ctx.state)) {
      await ctx.resume();
    }
    return ctx;
  }, []);

  const unlockAudioContext = useCallback(async (): Promise<void> => {
    const ctx = await getAudioContext();
    if (ctx.state !== "running") return;
    const silentBuffer = ctx.createBuffer(1, 1, 22050);
    const source = ctx.createBufferSource();
    source.buffer = silentBuffer;
    source.connect(ctx.destination);
    source.start(0);
  }, [getAudioContext]);

  /* ---- Group mutation helper ---- */

  const updateGroup = useCallback(
    (group: G, fn: (g: GroupSequencerState) => GroupSequencerState) => {
      setGroupsState((prev) => {
        const next = { ...prev };
        next[group] = fn(prev[group]);
        return next;
      });
    },
    []
  );

  const toggleStep = useCallback(
    (group: G, trackIdx: number, stepIdx: number) => {
      updateGroup(group, (g) => ({
        ...g,
        tracks: g.tracks.map((t, i) =>
          i === trackIdx
            ? { ...t, steps: t.steps.map((s, j) => (j === stepIdx ? !s : s)) }
            : t
        ),
      }));
    },
    [updateGroup]
  );

  /** Change a group's note interval, resizing its step arrays (preserving overlap). */
  const setTiming = useCallback(
    (group: G, timing: TimingMode) => {
      updateGroup(group, (g) => {
        const newLen = STEPS_PER_TIMING[timing];
        return {
          ...g,
          timing,
          tracks: g.tracks.map((t) => {
            const steps = Array(newLen).fill(false);
            const carry = Math.min(newLen, t.steps.length);
            for (let i = 0; i < carry; i++) steps[i] = t.steps[i];
            return { ...t, steps };
          }),
        };
      });
    },
    [updateGroup]
  );

  const toggleMute = useCallback(
    (group: G) => updateGroup(group, (g) => ({ ...g, muted: !g.muted })),
    [updateGroup]
  );

  const toggleSolo = useCallback(
    (group: G) => updateGroup(group, (g) => ({ ...g, solo: !g.solo })),
    [updateGroup]
  );

  const clearGroup = useCallback(
    (group: G) =>
      updateGroup(group, (g) => ({
        ...g,
        tracks: g.tracks.map((t) => ({
          ...t,
          steps: Array(t.steps.length).fill(false),
        })),
      })),
    [updateGroup]
  );

  /* ---- Sample loading ---- */

  const loadGroupSamples = useCallback(
    async (group: G) => {
      const ctx = await getAudioContext();
      const defs = groupsRef.current[group].tracks;

      updateGroup(group, (g) => ({
        ...g,
        loading: true,
        tracks: g.tracks.map((t) => ({ ...t, loading: true })),
      }));

      const results = await Promise.all(
        defs.map(async (track, idx) => {
          try {
            const blob = await postGenerate({ generator: track.generator });
            const arrayBuf = await blob.arrayBuffer();
            const audioBuffer = await ctx.decodeAudioData(arrayBuf);
            return { idx, buffer: audioBuffer };
          } catch {
            return { idx, buffer: null };
          }
        })
      );

      updateGroup(group, (g) => ({
        ...g,
        loading: false,
        tracks: g.tracks.map((t, i) => {
          const r = results.find((x) => x.idx === i);
          return r
            ? { ...t, buffer: r.buffer, loading: false }
            : { ...t, loading: false };
        }),
      }));
    },
    [getAudioContext, updateGroup]
  );

  const loadAllGroups = useCallback(async () => {
    await Promise.all(groups.map((g) => loadGroupSamples(g)));
  }, [groups, loadGroupSamples]);

  /* ---- Scheduling ---- */

  /**
   * Schedules one master tick. For every group whose stride lands on this tick,
   * advances its playhead and (if audible) fires every active track step.
   * Mute/solo is a mixer predicate read fresh from the ref, so it takes effect
   * on the next tick (AC4/AC5). Empty groups contribute silence (AC8).
   */
  const scheduleTick = useCallback((masterStep: number, time: number) => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    const groupState = groupsRef.current;
    const keys = Object.keys(groupState) as G[];
    const anySolo = keys.some((k) => groupState[k].solo);

    for (const key of keys) {
      const g = groupState[key];
      const stride = strideFor(g.timing);
      if (masterStep % stride !== 0) continue;

      const stepIdx = (masterStep / stride) % STEPS_PER_TIMING[g.timing];
      currentStepRef.current[key] = stepIdx;

      const audible = anySolo ? g.solo : !g.muted;
      if (!audible) continue;

      for (const track of g.tracks) {
        if (track.steps[stepIdx] && track.buffer) {
          const source = ctx.createBufferSource();
          source.buffer = track.buffer;
          source.connect(masterGainRef.current ?? ctx.destination);
          source.start(time);
        }
      }
    }
  }, []);

  const scheduler = useCallback(() => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    const secondsPerTick = 60.0 / bpmRef.current / 8; // 1/32 master grid
    const lookahead = 0.1; // seconds

    while (nextNoteTimeRef.current < ctx.currentTime + lookahead) {
      scheduleTick(masterStepRef.current, nextNoteTimeRef.current);
      nextNoteTimeRef.current += secondsPerTick;
      masterStepRef.current = (masterStepRef.current + 1) % MASTER_TICKS_PER_BAR;
    }

    setCurrentStepByGroup({ ...currentStepRef.current });
    timerRef.current = setTimeout(scheduler, SCHEDULER_INTERVAL_MS);
  }, [scheduleTick]);

  /* ---- Transport ---- */

  const play = useCallback(async (): Promise<void> => {
    const groupState = groupsRef.current;
    const hasBuffers = (Object.keys(groupState) as G[]).some((k) =>
      groupState[k].tracks.some((t) => t.buffer !== null)
    );
    if (!hasBuffers) return;

    // Re-entrancy guard: a scheduler loop is already armed - don't spawn a
    // second one (a double play() would double-schedule every tick).
    if (timerRef.current !== null) return;

    const ctx = await getAudioContext();
    if (ctx.state !== "running") {
      console.warn(
        `[useEP133Sequencer] AudioContext failed to resume (state=${ctx.state}). ` +
          `WebKit may require user gesture re-invocation.`
      );
      return;
    }

    masterStepRef.current = 0;
    nextNoteTimeRef.current = ctx.currentTime;
    (Object.keys(currentStepRef.current) as G[]).forEach((k) => {
      currentStepRef.current[k] = 0;
    });

    setIsPlaying(true);
    setCurrentStepByGroup({ ...currentStepRef.current });
    timerRef.current = setTimeout(scheduler, SCHEDULER_INTERVAL_MS);
  }, [getAudioContext, scheduler]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setIsPlaying(false);
    (Object.keys(currentStepRef.current) as G[]).forEach((k) => {
      currentStepRef.current[k] = -1;
    });
    setCurrentStepByGroup({ ...currentStepRef.current });
  }, []);

  return {
    bpm,
    setBpm,
    isPlaying,
    currentStepByGroup,
    groups: groupsState,
    setTiming,
    toggleStep,
    loadGroupSamples,
    loadAllGroups,
    toggleMute,
    toggleSolo,
    unlockAudioContext,
    play,
    stop,
    clearGroup,
  };
}
