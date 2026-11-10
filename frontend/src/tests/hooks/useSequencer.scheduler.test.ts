/*
 * The scheduler pump of the PO-33 hook: how play() arms the setTimeout clock,
 * what each pass schedules on the Web Audio timeline, and how stop() and a
 * second play() treat the armed timer.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { SCHEDULER_INTERVAL_MS, useSequencer } from "../../hooks/useSequencer";

/* AudioContext mock: function-form constructor (arrow fns lack [[Construct]]). */

interface MockAudioContext {
  state: "suspended" | "running" | "closed";
  currentTime: number;
  destination: object;
  resume: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  createBufferSource: ReturnType<typeof vi.fn>;
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

const TRACK = [{ name: "T1", generator: "noise_burst" }];

/** Render the hook with one loaded track holding the given steps, then press play. */
async function startPlaying(steps: boolean[]) {
  const hook = renderHook(() => useSequencer({ numSteps: steps.length, defaultBpm: 120 }));
  act(() => {
    hook.result.current.initTracks(TRACK, [steps], [{} as AudioBuffer]);
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

/* Tests                                                               */

describe("useSequencer scheduler pump", () => {
  it("play() arms the pump once and schedules nothing before the first pass", async () => {
    const { result } = await startPlaying([true, true, false, true]);

    expect(result.current.isPlaying).toBe(true);
    expect(result.current.currentStep).toBe(0);
    expect(arms).toBe(1);
    expect(armed).not.toBeNull();
    expect(ctx.starts).toEqual([]);
  });

  it("a pass schedules the active steps of the lookahead window on a 16th-note grid", async () => {
    const { result } = await startPlaying([true, true, false, true]);

    // 120 BPM gives 0.125 s per step; the 0.1 s lookahead reaches 0.25 s.
    fire(0.15);

    expect(ctx.starts).toEqual([0, 0.125]);
    expect(result.current.currentStep).toBe(1);
    expect(arms).toBe(2);
  });

  it("each pass re-arms the pump and the step wraps at numSteps", async () => {
    const { result } = await startPlaying([true, true, false, true]);

    fire(0.15);
    fire(0.55);

    expect(ctx.starts).toEqual([0, 0.125, 0.375, 0.5, 0.625]);
    expect(result.current.currentStep).toBe(1);
    expect(arms).toBe(3);
  });

  it("a BPM change applies from the next pass", async () => {
    const { result } = await startPlaying([true, true, true, true]);

    fire(0.15);
    act(() => {
      result.current.setBpm(60);
    });
    fire(0.8);

    expect(ctx.starts).toEqual([0, 0.125, 0.25, 0.5, 0.75]);
  });

  it("play() while armed arms no second loop, and stop() clears the armed pump", async () => {
    const { result } = await startPlaying([true, true, false, true]);

    await act(async () => {
      await result.current.play();
    });
    expect(arms).toBe(1);

    act(() => {
      result.current.stop();
    });
    expect(cleared).toEqual([PUMP_ID_BASE + 1]);
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.currentStep).toBe(-1);

    await act(async () => {
      await result.current.play();
    });
    expect(arms).toBe(2);
  });
});
