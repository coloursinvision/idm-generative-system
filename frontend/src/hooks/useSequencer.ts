/* Web Audio step sequencer - shared between PO-33 and EP-133 guides  */

import { useState, useRef, useCallback, useEffect } from "react";
import { postGenerate } from "../api/client";
import { useAudioContext } from "./useAudioContext";

/**
 * Scheduler pump interval (ms) for the setTimeout-based lookahead clock.
 *
 * setTimeout - not requestAnimationFrame - drives the scheduler: rAF is paused
 * or throttled in background tabs, which would stall note scheduling and break
 * the very background-tab robustness the visibilitychange handler protects.
 * Canonical "A Tale of Two Clocks" pattern: a coarse setTimeout pump advances a
 * fine-grained Web Audio lookahead window (see `scheduler` below).
 */
export const SCHEDULER_INTERVAL_MS = 25;

export interface SequencerTrack {
  name: string;
  generator: string;
  steps: boolean[];
  buffer: AudioBuffer | null;
  loading: boolean;
}

interface UseSequencerOptions {
  numSteps: number;
  defaultBpm?: number;
}

/**
 * Web Audio step sequencer hook - shared between PO-33 and EP-133 guides.
 *
 * IMPORTANT (WebKit / Safari):
 * - The first call to `play()` MUST originate from a synchronous user gesture
 *   handler (onClick, onPointerDown). Calling `play()` from a useEffect,
 *   setTimeout, or async callback chain will produce silent playback on Safari.
 * - Consumers should call `unlockAudioContext()` on the first interactive
 *   button click (LOAD SAMPLES or PLAY) to pre-warm Safari's audio output.
 *   The call is idempotent and cheap.
 * - `play()` returns a `Promise<void>`. Consumers must attach a `.catch(...)`
 *   handler at the call site to satisfy the no-unhandled-promise contract.
 *
 * @param options.numSteps   - step count for the active pattern grid
 * @param options.defaultBpm - initial BPM, default 120
 */
export function useSequencer({ numSteps, defaultBpm = 120 }: UseSequencerOptions) {
  const [bpm, setBpm] = useState(defaultBpm);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [tracks, setTracks] = useState<SequencerTrack[]>([]);
  const [loadingAll, setLoadingAll] = useState(false);

  const { audioCtxRef, getAudioContext, unlockAudioContext } =
    useAudioContext("[useSequencer]");
  const timerRef = useRef<number | null>(null);
  const stepRef = useRef(0);
  const nextNoteTimeRef = useRef(0);
  const tracksRef = useRef<SequencerTrack[]>([]);
  const bpmRef = useRef(defaultBpm);

  // Keep refs in sync
  useEffect(() => {
    tracksRef.current = tracks;
  }, [tracks]);
  useEffect(() => {
    bpmRef.current = bpm;
  }, [bpm]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  /* ---- Init tracks ---- */
  /**
   * (Re-)initialises the track list.
   *
   * @param trackDefs      - Track name/generator definitions.
   * @param initialSteps   - Optional per-track step arrays (restored from saved
   *                         group state). When provided the array must be
   *                         non-empty; otherwise the fallback empty pattern of
   *                         length `numSteps` is used.
   * @param initialBuffers - Optional per-track AudioBuffer references (restored
   *                         from saved group state). Allows sample buffers to
   *                         survive group switches without re-fetching.
   */
  const initTracks = useCallback(
    (
      trackDefs: { name: string; generator: string }[],
      initialSteps?: boolean[][],
      initialBuffers?: (AudioBuffer | null)[]
    ) => {
      setTracks(
        trackDefs.map((def, i) => ({
          name: def.name,
          generator: def.generator,
          steps:
            (initialSteps?.[i]?.length ?? 0) > 0
              ? initialSteps![i]
              : Array(numSteps).fill(false),
          buffer: initialBuffers?.[i] ?? null,
          loading: false,
        }))
      );
    },
    [numSteps]
  );

  /* ---- Toggle step ---- */
  const toggleStep = useCallback((trackIdx: number, stepIdx: number) => {
    setTracks((prev) =>
      prev.map((t, i) =>
        i === trackIdx
          ? { ...t, steps: t.steps.map((s, j) => (j === stepIdx ? !s : s)) }
          : t
      )
    );
  }, []);

  /* ---- Load single track sample ---- */
  const loadTrackSample = useCallback(
    async (trackIdx: number) => {
      const ctx = await getAudioContext();
      setTracks((prev) =>
        prev.map((t, i) => (i === trackIdx ? { ...t, loading: true } : t))
      );

      try {
        const blob = await postGenerate({
          generator: tracksRef.current[trackIdx].generator,
        });
        const arrayBuf = await blob.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(arrayBuf);

        setTracks((prev) =>
          prev.map((t, i) =>
            i === trackIdx ? { ...t, buffer: audioBuffer, loading: false } : t
          )
        );
      } catch (err) {
        console.error(`Failed to load track ${trackIdx}:`, err);
        setTracks((prev) =>
          prev.map((t, i) => (i === trackIdx ? { ...t, loading: false } : t))
        );
      }
    },
    [getAudioContext]
  );

  /* ---- Load all track samples ---- */
  const loadAllSamples = useCallback(async () => {
    setLoadingAll(true);
    const ctx = await getAudioContext();

    const promises = tracksRef.current.map(async (track, idx) => {
      setTracks((prev) =>
        prev.map((t, i) => (i === idx ? { ...t, loading: true } : t))
      );

      try {
        const blob = await postGenerate({ generator: track.generator });
        const arrayBuf = await blob.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(arrayBuf);
        return { idx, buffer: audioBuffer, error: false };
      } catch {
        return { idx, buffer: null, error: true };
      }
    });

    const results = await Promise.all(promises);

    setTracks((prev) =>
      prev.map((t, i) => {
        const result = results.find((r) => r.idx === i);
        return result
          ? { ...t, buffer: result.buffer, loading: false }
          : { ...t, loading: false };
      })
    );

    setLoadingAll(false);
  }, [getAudioContext]);

  /* ---- Schedule & play ---- */
  const scheduleNote = useCallback((step: number, time: number) => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    for (const track of tracksRef.current) {
      if (track.steps[step] && track.buffer) {
        const source = ctx.createBufferSource();
        source.buffer = track.buffer;
        source.connect(ctx.destination);
        source.start(time);
      }
    }
  }, [audioCtxRef]);

  /**
   * Starts playback. Async because the AudioContext may need to be resumed
   * before the first note is scheduled (Safari requirement).
   *
   * Guards against the WebKit failure mode where `resume()` resolves but the
   * context state has not transitioned to `"running"` - in that case we abort
   * with a single console warning rather than producing silent playback.
   *
   * Consumers MUST attach a `.catch(...)` at the call site. Returns once the
   * scheduler is armed; the scheduler then re-arms itself through
   * `setTimeout` on every pass.
   */
  const play = useCallback(async (): Promise<void> => {
    const hasBuffers = tracksRef.current.some((t) => t.buffer !== null);
    if (!hasBuffers) return;

    // Re-entrancy guard: a scheduler loop is already armed - don't spawn a
    // second one (a double play() would double-schedule every note).
    if (timerRef.current !== null) return;

    const ctx = await getAudioContext();

    if (ctx.state !== "running") {
      console.warn(
        `[useSequencer] AudioContext failed to resume (state=${ctx.state}). ` +
          `WebKit may require user gesture re-invocation.`
      );
      return;
    }

    stepRef.current = 0;
    nextNoteTimeRef.current = ctx.currentTime;
    setIsPlaying(true);
    setCurrentStep(0);

    const scheduler = () => {
      const audioCtx = audioCtxRef.current;
      if (!audioCtx) return;

      const secondsPerStep = 60.0 / bpmRef.current / 4; // 16th-note base grid
      const lookahead = 0.1; // seconds

      while (nextNoteTimeRef.current < audioCtx.currentTime + lookahead) {
        scheduleNote(stepRef.current, nextNoteTimeRef.current);
        setCurrentStep(stepRef.current);

        nextNoteTimeRef.current += secondsPerStep;
        stepRef.current = (stepRef.current + 1) % numSteps;
      }

      timerRef.current = setTimeout(scheduler, SCHEDULER_INTERVAL_MS);
    };

    timerRef.current = setTimeout(scheduler, SCHEDULER_INTERVAL_MS);
  }, [audioCtxRef, getAudioContext, numSteps, scheduleNote]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setIsPlaying(false);
    setCurrentStep(-1);
  }, []);

  /* ---- Clear pattern ---- */
  const clearPattern = useCallback(() => {
    stop();
    setTracks((prev) =>
      prev.map((t) => ({ ...t, steps: Array(numSteps).fill(false) }))
    );
  }, [stop, numSteps]);

  return {
    tracks,
    bpm,
    setBpm,
    isPlaying,
    currentStep,
    loadingAll,
    initTracks,
    toggleStep,
    loadTrackSample,
    loadAllSamples,
    unlockAudioContext,
    play,
    stop,
    clearPattern,
  };
}
