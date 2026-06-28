/*
 * EP-133 simultaneous multi-group playback.
 *
 * PO-33 no-regression is covered by the useSequencer.test.ts suite.
 * Both hooks use the setTimeout-based scheduler clock.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useEP133Sequencer } from "../../hooks/useEP133Sequencer";
import { SCHEDULER_INTERVAL_MS } from "../../hooks/useSequencer";

/* ------------------------------------------------------------------ */
/* api/client mock — postGenerate returns a blob-like with arrayBuffer */
/* ------------------------------------------------------------------ */

vi.mock("../../api/client", () => ({
  postGenerate: vi.fn(async () => ({
    arrayBuffer: async () => new ArrayBuffer(8),
  })),
}));

/* ------------------------------------------------------------------ */
/* Test fixtures                                                       */
/* ------------------------------------------------------------------ */

const GROUPS = ["A", "B", "C", "D"] as const;
type Group = (typeof GROUPS)[number];

const GROUP_TRACKS: Record<Group, { name: string; generator: string }[]> = {
  A: [
    { name: "A0", generator: "noise_burst" },
    { name: "A1", generator: "fm_blip" },
  ],
  B: [{ name: "B0", generator: "fm_blip" }],
  C: [{ name: "C0", generator: "fm_blip" }],
  D: [{ name: "D0", generator: "noise_burst" }],
};

/* AudioContext mock: function-form constructor (arrow fns lack [[Construct]]). */

type MockState = "suspended" | "running" | "closed" | "interrupted";

interface ScheduledNote {
  buffer: unknown;
  time: number;
}

interface MockAudioContext {
  state: MockState;
  currentTime: number;
  destination: object;
  resume: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  createBuffer: ReturnType<typeof vi.fn>;
  createBufferSource: ReturnType<typeof vi.fn>;
  createGain: ReturnType<typeof vi.fn>;
  createDynamicsCompressor: ReturnType<typeof vi.fn>;
  decodeAudioData: ReturnType<typeof vi.fn>;
  __scheduled: ScheduledNote[];
}

/** Tag stamped onto the next decoded buffer — set before each group load so
 *  scheduled notes can be attributed back to their group. */
let decodeTag = "?";

function createMockAudioContext(initialState: MockState = "suspended"): MockAudioContext {
  const ctx: MockAudioContext = {
    state: initialState,
    currentTime: 0,
    destination: {},
    resume: vi.fn(),
    close: vi.fn(),
    createBuffer: vi.fn(() => ({})),
    createBufferSource: vi.fn(),
    createGain: vi.fn(() => ({ gain: { value: 0 }, connect: vi.fn() })),
    createDynamicsCompressor: vi.fn(() => ({
      threshold: { value: 0 },
      knee: { value: 0 },
      ratio: { value: 0 },
      attack: { value: 0 },
      release: { value: 0 },
      connect: vi.fn(),
    })),
    decodeAudioData: vi.fn(async () => ({ __group: decodeTag }) as unknown as AudioBuffer),
    __scheduled: [],
  };

  ctx.resume.mockImplementation(async () => {
    ctx.state = "running";
  });

  // Records every started source so tests can assert what was scheduled.
  ctx.createBufferSource.mockImplementation(() => {
    const node = {
      buffer: null as unknown,
      connect: vi.fn(),
      start: vi.fn((time?: number) => {
        ctx.__scheduled.push({ buffer: node.buffer, time: time ?? 0 });
      }),
    };
    return node;
  });

  return ctx;
}

let currentMockCtx: MockAudioContext;
let schedulerCb: (() => void) | null;

// Capture the real timer before any stub replaces the global, so non-scheduler
// setTimeout calls (React / act() async flushing) keep working.
const realSetTimeout = globalThis.setTimeout.bind(globalThis);

beforeEach(() => {
  decodeTag = "?";
  schedulerCb = null;
  currentMockCtx = createMockAudioContext("suspended");

  vi.stubGlobal(
    "AudioContext",
    vi.fn(function (this: unknown) { return currentMockCtx; })
  );
  // Capture the scheduler pump callback (the setTimeout at SCHEDULER_INTERVAL_MS)
  // instead of running it on a real timer, so tests can pump the master clock
  // deterministically. All other setTimeout calls pass through to the real timer
  // so React / act() async flushing keeps working.
  vi.stubGlobal(
    "setTimeout",
    vi.fn((cb: () => void, delay?: number) => {
      if (delay === SCHEDULER_INTERVAL_MS) {
        schedulerCb = cb;
        return 1;
      }
      return realSetTimeout(cb, delay);
    })
  );
  vi.stubGlobal("clearTimeout", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

type Api = ReturnType<typeof useEP133Sequencer<Group>>;

function render() {
  return renderHook(() =>
    useEP133Sequencer({ groups: GROUPS, groupTracks: GROUP_TRACKS, defaultBpm: 120 })
  );
}

/** Load one group's samples with its scheduled notes tagged for attribution. */
async function loadGroup(api: () => Api, group: Group) {
  decodeTag = group;
  await act(async () => {
    await api().loadGroupSamples(group);
  });
}

/** Activate steps [0, n) of a group's track 0 (defaults are all-off). */
function fillTrack0(api: () => Api, group: Group, n: number) {
  act(() => {
    for (let i = 0; i < n; i++) api().toggleStep(group, 0, i);
  });
}

/** Advance the mock clock and run one scheduler pass under act(). */
async function pump(currentTime: number) {
  currentMockCtx.currentTime = currentTime;
  await act(async () => {
    schedulerCb?.();
  });
}

function notesByGroup(): Record<string, number> {
  const out: Record<string, number> = {};
  for (const n of currentMockCtx.__scheduled) {
    const g = (n.buffer as { __group?: string } | null)?.__group;
    if (g) out[g] = (out[g] ?? 0) + 1;
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Tests                                                               */
/* ------------------------------------------------------------------ */

describe("useEP133Sequencer multi-group playback", () => {
  it("initialises every group playhead to -1 and exposes all groups", () => {
    const { result } = render();
    expect(result.current.currentStepByGroup).toEqual({ A: -1, B: -1, C: -1, D: -1 });
    expect(Object.keys(result.current.groups)).toEqual(["A", "B", "C", "D"]);
    expect(result.current.isPlaying).toBe(false);
  });

  it("AC1: plays all four groups simultaneously from one transport", async () => {
    const { result } = render();
    const api = () => result.current;

    for (const g of GROUPS) {
      await loadGroup(api, g);
      fillTrack0(api, g, 1); // step 0 active
    }

    await act(async () => { await result.current.play(); });
    expect(result.current.isPlaying).toBe(true);

    await pump(0.05); // master ticks m=0..2 — all groups fire their step 0 at m=0

    expect(notesByGroup()).toEqual({ A: 1, B: 1, C: 1, D: 1 });
  });

  it("AC2: STOP halts playback and resets every playhead on the same tick", async () => {
    const { result } = render();
    const api = () => result.current;
    await loadGroup(api, "A");
    fillTrack0(api, "A", 1);

    await act(async () => { await result.current.play(); });
    await pump(0.05);

    act(() => { result.current.stop(); });

    expect(result.current.isPlaying).toBe(false);
    expect(clearTimeout).toHaveBeenCalled();
    expect(result.current.currentStepByGroup).toEqual({ A: -1, B: -1, C: -1, D: -1 });
  });

  it("AC3: editing a group during playback does not interrupt the transport", async () => {
    const { result } = render();
    const api = () => result.current;
    await loadGroup(api, "A");
    fillTrack0(api, "A", 1);

    await act(async () => { await result.current.play(); });
    await pump(0.05);

    (clearTimeout as unknown as ReturnType<typeof vi.fn>).mockClear();

    // Edit a different group's pattern + timing mid-playback.
    act(() => {
      result.current.toggleStep("B", 0, 3);
      result.current.setTiming("C", "1/32");
    });

    expect(result.current.isPlaying).toBe(true);
    expect(clearTimeout).not.toHaveBeenCalled();
  });

  it("AC4: muting silences a group on the next tick; unmuting restores it", async () => {
    const { result } = render();
    const api = () => result.current;
    await loadGroup(api, "A");
    act(() => { result.current.setTiming("A", "1/32"); }); // stride 1 — fires every tick
    fillTrack0(api, "A", 32);

    await act(async () => { await result.current.play(); });

    currentMockCtx.__scheduled = [];
    await pump(0.1); // audible
    expect(notesByGroup().A).toBeGreaterThan(0);

    act(() => { result.current.toggleMute("A"); });
    currentMockCtx.__scheduled = [];
    await pump(0.2); // muted — ticks still advance, but produce no notes
    expect(notesByGroup().A ?? 0).toBe(0);

    act(() => { result.current.toggleMute("A"); }); // unmute
    currentMockCtx.__scheduled = [];
    await pump(0.3); // audible again
    expect(notesByGroup().A).toBeGreaterThan(0);

    expect(result.current.isPlaying).toBe(true); // never restarted
  });

  it("AC5: solo silences the others; clearing solo restores prior mute state", async () => {
    const { result } = render();
    const api = () => result.current;
    for (const g of ["A", "B", "C"] as const) {
      await loadGroup(api, g);
      act(() => { result.current.setTiming(g, "1/32"); });
      fillTrack0(api, g, 32);
    }
    act(() => { result.current.toggleMute("A"); }); // A muted before solo

    await act(async () => { await result.current.play(); });

    // Solo C — only C audible (A muted anyway, B silenced by solo).
    act(() => { result.current.toggleSolo("C"); });
    currentMockCtx.__scheduled = [];
    await pump(0.1);
    let notes = notesByGroup();
    expect(notes.C).toBeGreaterThan(0);
    expect(notes.A ?? 0).toBe(0);
    expect(notes.B ?? 0).toBe(0);

    // Clear solo — A stays muted (prior state), B + C audible.
    act(() => { result.current.toggleSolo("C"); });
    currentMockCtx.__scheduled = [];
    await pump(0.2);
    notes = notesByGroup();
    expect(notes.A ?? 0).toBe(0); // prior mute restored
    expect(notes.B).toBeGreaterThan(0);
    expect(notes.C).toBeGreaterThan(0);
  });

  it("AC6: group A @1/16 and C @1/32 play polyrhythmically (C fires twice per A step)", async () => {
    const { result } = render();
    const api = () => result.current;

    await loadGroup(api, "A");
    fillTrack0(api, "A", 16); // default 1/16, all steps

    await loadGroup(api, "C");
    act(() => { result.current.setTiming("C", "1/32"); });
    fillTrack0(api, "C", 32); // 1/32, all steps

    await act(async () => { await result.current.play(); });

    currentMockCtx.__scheduled = [];
    await pump(0.4); // master ticks m=0..7

    const notes = notesByGroup();
    expect(notes.A).toBe(4); // stride 2 → m=0,2,4,6
    expect(notes.C).toBe(8); // stride 1 → m=0..7
    expect(notes.C).toBe(notes.A * 2);
  });

  it("AC7: BPM changes apply globally on the next scheduled tick", async () => {
    const { result } = render();
    const api = () => result.current;
    await loadGroup(api, "A");
    act(() => { result.current.setTiming("A", "1/32"); });
    fillTrack0(api, "A", 32);

    await act(async () => { await result.current.play(); });

    currentMockCtx.__scheduled = [];
    await pump(0.1); // bpm 120 → secondsPerTick 0.0625

    act(() => { result.current.setBpm(60); }); // → secondsPerTick 0.125
    await pump(0.4);

    const times = currentMockCtx.__scheduled.map((n) => n.time);
    const lastDelta = times[times.length - 1] - times[times.length - 2];
    expect(lastDelta).toBeCloseTo(0.125, 5);
  });

  it("AC8: a group with zero loaded buffers does not crash the scheduler", async () => {
    const { result } = render();
    const api = () => result.current;
    await loadGroup(api, "A");
    fillTrack0(api, "A", 1);
    // B, C, D have active steps but no buffers loaded.
    fillTrack0(api, "B", 1);

    await act(async () => { await result.current.play(); });
    await expect(pump(0.05)).resolves.not.toThrow();

    const notes = notesByGroup();
    expect(notes.A).toBe(1);
    expect(notes.B ?? 0).toBe(0); // active step, no buffer → silent, no crash
  });

  it("does not start playback when no group has any loaded buffer", async () => {
    const { result } = render();
    fillTrack0(() => result.current, "A", 1); // pattern but no buffers

    await act(async () => { await result.current.play(); });
    expect(result.current.isPlaying).toBe(false);
  });

  it("unlockAudioContext is idempotent — context constructed once across calls", async () => {
    const AudioContextSpy = vi.fn(function (this: unknown) { return currentMockCtx; });
    vi.stubGlobal("AudioContext", AudioContextSpy);

    const { result } = render();
    await act(async () => {
      await result.current.unlockAudioContext();
      await result.current.unlockAudioContext();
      await result.current.unlockAudioContext();
    });

    expect(AudioContextSpy).toHaveBeenCalledOnce();
  });
});
