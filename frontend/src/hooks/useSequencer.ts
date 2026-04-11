/* ------------------------------------------------------------------ */
/* hooks/useSequencer.ts                                               */
/* Web Audio step sequencer — shared between PO-33 and EP-133 guides  */
/* ------------------------------------------------------------------ */

import { useState, useRef, useCallback, useEffect } from "react";
import { postGenerate } from "../api/client";

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

export function useSequencer({ numSteps, defaultBpm = 120 }: UseSequencerOptions) {
  const [bpm, setBpm] = useState(defaultBpm);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(-1);
  const [tracks, setTracks] = useState<SequencerTrack[]>([]);
  const [loadingAll, setLoadingAll] = useState(false);

  const audioCtxRef = useRef<AudioContext | null>(null);
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
      if (timerRef.current) cancelAnimationFrame(timerRef.current);
      if (audioCtxRef.current) audioCtxRef.current.close();
    };
  }, []);

  const getAudioContext = useCallback(() => {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext({ sampleRate: 44100 });
    }
    if (audioCtxRef.current.state === "suspended") {
      audioCtxRef.current.resume();
    }
    return audioCtxRef.current;
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
            initialSteps?.[i]?.length > 0
              ? initialSteps[i]
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
      const ctx = getAudioContext();
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
    const ctx = getAudioContext();

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
  }, []);

  const scheduler = useCallback(() => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    const secondsPerStep = 60.0 / bpmRef.current / 4; // 16th-note base grid
    const lookahead = 0.1; // seconds

    while (nextNoteTimeRef.current < ctx.currentTime + lookahead) {
      scheduleNote(stepRef.current, nextNoteTimeRef.current);
      setCurrentStep(stepRef.current);

      nextNoteTimeRef.current += secondsPerStep;
      stepRef.current = (stepRef.current + 1) % numSteps;
    }

    timerRef.current = requestAnimationFrame(scheduler);
  }, [numSteps, scheduleNote]);

  /* ---- Play / Stop ---- */
  const play = useCallback(() => {
    const hasBuffers = tracksRef.current.some((t) => t.buffer !== null);
    if (!hasBuffers) return;

    const ctx = getAudioContext();
    stepRef.current = 0;
    nextNoteTimeRef.current = ctx.currentTime;
    setIsPlaying(true);
    setCurrentStep(0);

    timerRef.current = requestAnimationFrame(scheduler);
  }, [getAudioContext, scheduler]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      cancelAnimationFrame(timerRef.current);
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
    play,
    stop,
    clearPattern,
  };
}
