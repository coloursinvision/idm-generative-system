/*
 * The scheduler pump of the EP-133 hook: how play() arms the setTimeout clock,
 * what each pass schedules on the 1/32 master grid, and how stop() and a second
 * play() treat the armed timer.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useEP133Sequencer } from "../../hooks/useEP133Sequencer";
import type { TimingMode } from "../../hooks/useEP133Sequencer";
import { SCHEDULER_INTERVAL_MS } from "../../hooks/useSequencer";

vi.mock("../../api/client", () => ({
  postGenerate: vi.fn(async () => ({
    arrayBuffer: async () => new ArrayBuffer(8),
  })),
}));

/* AudioContext mock: function-form constructor (arrow fns lack [[Construct]]). */

interface MockAudioContext {
  state: "suspended" | "running" | "closed";
  currentTime: number;
  destination: object;
  resume: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  createBufferSource: ReturnType<typeof vi.fn>;
  createGain: ReturnType<typeof vi.fn>;
  createDynamicsCompressor: ReturnType<typeof vi.fn>;
  decodeAudioData: ReturnType<typeof vi.fn>;
  starts: number[];
}

function createMockAudioContext(): MockAudioContext {
  const ctx: MockAudioContext = {
    state: "suspended",
    currentTime: 0,
    destination: {},
    resume: vi.fn(),
    close: vi.fn(),
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
    decodeAudioData: vi.fn(async () => ({}) as AudioBuffer),
    starts: [],
  };
  ctx.resume.mockImplementation(async () => {
    ctx.state = "running";
  });
  ctx.createBufferSource.mockImplementation(() => ({
    buffer: null,
    connect: vi.fn(),
    start: vi.fn((time?: number) => {
      ctx.starts.push(time ?? 0);
    }),
  }));
  return ctx;
}

let ctx: MockAudioContext;
let armed: (() => void) | null;
let arms: number;
let cleared: number[];
let pumpIds: Set<number>;

const PUMP_ID_BASE = 1_000_000;
const realSetTimeout = globalThis.setTimeout.bind(globalThis);
const realClearTimeout = globalThis.clearTimeout.bind(globalThis);

beforeEach(() => {
  ctx = createMockAudioContext();
  armed = null;
  arms = 0;
  cleared = [];
  pumpIds = new Set();

  vi.stubGlobal(
    "AudioContext",
    vi.fn(function (this: unknown) { return ctx; })
  );
  // Only the pump, armed at SCHEDULER_INTERVAL_MS, is held as a one-shot timer that
  // the test fires by hand; every other timer stays real for React and act().
  vi.stubGlobal(
    "setTimeout",
    vi.fn((callback: () => void, delay?: number) => {
      if (delay === SCHEDULER_INTERVAL_MS) {
        armed = callback;
        arms += 1;
        const id = PUMP_ID_BASE + arms;
        pumpIds.add(id);
        return id;
      }
      return realSetTimeout(callback, delay);
    })
  );
  vi.stubGlobal(
    "clearTimeout",
    vi.fn((id?: number) => {
      if (id !== undefined && pumpIds.has(id)) {
        cleared.push(id);
        armed = null;
        return;
      }
      realClearTimeout(id);
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* Helpers                                                             */

const GROUPS = ["A", "B", "C", "D"] as const;
const GROUP_TRACKS = {
  A: [{ name: "A0", generator: "noise_burst" }],
  B: [{ name: "B0", generator: "fm_blip" }],
  C: [{ name: "C0", generator: "fm_blip" }],
  D: [{ name: "D0", generator: "noise_burst" }],
};

/**
 * Render the hook, load group A, set its timing, turn on the given steps of its
 * track and press play. Groups B, C and D keep their defaults and no buffers.
 */
async function startPlaying(steps: number[], timing: TimingMode = "1/16") {
  const hook = renderHook(() =>
    useEP133Sequencer({ groups: GROUPS, groupTracks: GROUP_TRACKS, defaultBpm: 120 })
  );
  await act(async () => {
    await hook.result.current.loadGroupSamples("A");
  });
  act(() => {
    hook.result.current.setTiming("A", timing);
  });
  act(() => {
    for (const step of steps) hook.result.current.toggleStep("A", 0, step);
  });
  await act(async () => {
    await hook.result.current.play();
  });
  return hook;
}

/** Fire the armed pump once at the given audio clock time, as the timer would. */
function fire(currentTime: number) {
  const callback = armed;
  armed = null;
  expect(callback).not.toBeNull();
  ctx.currentTime = currentTime;
  act(() => {
    callback?.();
  });
}

const ALL_STEPS_1_32 = Array.from({ length: 32 }, (_, i) => i);

/* Tests                                                               */

describe("useEP133Sequencer scheduler pump", () => {
  it("play() arms the pump once and schedules nothing before the first pass", async () => {
    const { result } = await startPlaying([0, 1, 3]);

    expect(result.current.isPlaying).toBe(true);
    expect(result.current.currentStepByGroup).toEqual({ A: 0, B: 0, C: 0, D: 0 });
    expect(arms).toBe(1);
    expect(armed).not.toBeNull();
    expect(ctx.starts).toEqual([]);
  });

  it("a pass schedules the active steps of the lookahead window on the 1/32 master grid", async () => {
    const { result } = await startPlaying([0, 1, 3]);

    // 120 BPM gives 0.0625 s per master tick; the 0.1 s lookahead reaches 0.24 s,
    // so ticks 0 to 3 run, and a 1/16 group plays on every second tick.
    fire(0.14);

    expect(ctx.starts).toEqual([0, 0.125]);
    expect(result.current.currentStepByGroup).toEqual({ A: 1, B: 1, C: 1, D: 1 });
    expect(arms).toBe(2);
  });

  it("each pass re-arms the pump and the playhead wraps after the 32 ticks of a bar", async () => {
    const { result } = await startPlaying([0, 1, 3]);

    fire(0.14);
    fire(2.04);

    expect(ctx.starts).toEqual([0, 0.125, 0.375, 2, 2.125]);
    expect(result.current.currentStepByGroup).toEqual({ A: 1, B: 1, C: 1, D: 1 });
    expect(arms).toBe(3);
  });

  it("a BPM change applies from the next pass", async () => {
    const { result } = await startPlaying(ALL_STEPS_1_32, "1/32");

    fire(0.14);
    act(() => {
      result.current.setBpm(60);
    });
    fire(0.64);

    expect(ctx.starts).toEqual([0, 0.0625, 0.125, 0.1875, 0.25, 0.375, 0.5, 0.625]);
  });

  it("play() while armed arms no second loop, and stop() clears the armed pump", async () => {
    const { result } = await startPlaying([0, 1, 3]);

    await act(async () => {
      await result.current.play();
    });
    expect(arms).toBe(1);

    act(() => {
      result.current.stop();
    });
    expect(cleared).toEqual([PUMP_ID_BASE + 1]);
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.currentStepByGroup).toEqual({ A: -1, B: -1, C: -1, D: -1 });

    await act(async () => {
      await result.current.play();
    });
    expect(arms).toBe(2);
  });
});
