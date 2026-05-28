/* ------------------------------------------------------------------ */
/* hooks/useSequencer.test.ts                                          */
/* Vitest unit coverage for CR-F13 AudioContext lifecycle behaviour    */
/* ------------------------------------------------------------------ */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useSequencer } from "../../hooks/useSequencer";

/* ------------------------------------------------------------------ */
/* AudioContext mock                                                   */
/* ------------------------------------------------------------------ */

/**
 * Minimal AudioContext mock with a controllable state machine.
 *
 * Tests can drive transitions explicitly (`ctx.__setState("running")`) and
 * inspect side-effects (`ctx.resume` is a vi.fn that resolves after applying
 * the next queued state, or "running" by default).
 *
 * Modelled to cover the three CR-F13 hypotheses:
 *  H1 — unawaited resume() → silent playback
 *  H2 — gesture-scoped unlock failure (context stuck in "suspended")
 *  H3 — WebKit "interrupted" state after BFCache / visibility change
 */
type MockState = "suspended" | "running" | "closed" | "interrupted";

interface MockAudioContext {
  state: MockState;
  currentTime: number;
  destination: object;
  resume: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  createBuffer: ReturnType<typeof vi.fn>;
  createBufferSource: ReturnType<typeof vi.fn>;
  decodeAudioData: ReturnType<typeof vi.fn>;
  __setState: (next: MockState) => void;
  __resumeQueue: MockState[];
}

function createMockAudioContext(initialState: MockState = "suspended"): MockAudioContext {
  const ctx: MockAudioContext = {
    state: initialState,
    currentTime: 0,
    destination: {},
    resume: vi.fn(),
    close: vi.fn(),
    createBuffer: vi.fn(() => ({})),
    createBufferSource: vi.fn(() => ({
      buffer: null,
      connect: vi.fn(),
      start: vi.fn(),
    })),
    decodeAudioData: vi.fn(),
    __resumeQueue: [],
    __setState(next) {
      this.state = next;
    },
  };

  // Default resume behaviour — transitions to next queued state, or "running".
  ctx.resume.mockImplementation(async () => {
    const next = ctx.__resumeQueue.shift() ?? "running";
    ctx.state = next;
  });

  return ctx;
}

let currentMockCtx: MockAudioContext;

beforeEach(() => {
  currentMockCtx = createMockAudioContext("suspended");
  // Replace global AudioContext constructor with a factory that returns the
  // shared mock so tests can observe a single instance across hook calls.
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function (this: unknown) { return currentMockCtx; })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ------------------------------------------------------------------ */
/* Tests                                                               */
/* ------------------------------------------------------------------ */

describe("useSequencer — CR-F13 AudioContext lifecycle", () => {
  it("unlockAudioContext awaits resume() before completing (H1)", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    let resumeResolved = false;
    currentMockCtx.resume.mockImplementation(async () => {
      // Simulate async resume — state transitions only after the awaited tick.
      await Promise.resolve();
      currentMockCtx.state = "running";
      resumeResolved = true;
    });

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    expect(resumeResolved).toBe(true);
    expect(currentMockCtx.state).toBe("running");
    expect(currentMockCtx.resume).toHaveBeenCalledOnce();
  });

  it("unlockAudioContext plays a silent buffer to release WebKit gate (H2)", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    // Silent buffer trick: createBuffer(1, 1, 22050) → source → start(0)
    expect(currentMockCtx.createBuffer).toHaveBeenCalledWith(1, 1, 22050);
    expect(currentMockCtx.createBufferSource).toHaveBeenCalledOnce();
  });

  it("getAudioContext handles WebKit 'interrupted' state (H3)", async () => {
    currentMockCtx = createMockAudioContext("interrupted");
    vi.stubGlobal(
      "AudioContext",
      vi.fn(function (this: unknown) { return currentMockCtx; })
    );

    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    // resume() must be called for "interrupted" just as for "suspended"
    expect(currentMockCtx.resume).toHaveBeenCalledOnce();
    expect(currentMockCtx.state).toBe("running");
  });

  it("play() aborts with warning if context fails to reach 'running' state", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Configure resume() to NOT transition state — simulating WebKit gesture-scope failure
    currentMockCtx.resume.mockImplementation(async () => {
      // state remains "suspended"
    });

    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    // Seed a track with a buffer so the hasBuffers guard does not short-circuit play()
    act(() => {
      result.current.initTracks([{ name: "T1", generator: "noise_burst" }]);
    });

    // Inject a fake buffer through the public toggleStep + manual mutation path is
    // not available, so we simulate the post-load state by re-initialising with a
    // pre-decoded buffer.
    act(() => {
      result.current.initTracks(
        [{ name: "T1", generator: "noise_burst" }],
        undefined,
        [{} as AudioBuffer]
      );
    });

    await act(async () => {
      await result.current.play();
    });

    expect(warnSpy).toHaveBeenCalledOnce();
    expect(warnSpy.mock.calls[0][0]).toMatch(/failed to resume/);
    expect(result.current.isPlaying).toBe(false);
  });

  it("play() succeeds when context resumes to 'running'", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    act(() => {
      result.current.initTracks(
        [{ name: "T1", generator: "noise_burst" }],
        undefined,
        [{} as AudioBuffer]
      );
    });

    await act(async () => {
      await result.current.play();
    });

    await waitFor(() => {
      expect(result.current.isPlaying).toBe(true);
    });
    expect(currentMockCtx.resume).toHaveBeenCalled();
    expect(currentMockCtx.state).toBe("running");

    // Cleanup the rAF scheduler to keep the test runner quiet
    act(() => {
      result.current.stop();
    });
  });

  it("visibilitychange listener resumes a suspended context on tab restore", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    // Create a context first (simulating that the user has interacted at least once)
    await act(async () => {
      await result.current.unlockAudioContext();
    });

    // Simulate tab backgrounding: state drifts to "suspended"
    currentMockCtx.state = "suspended";
    currentMockCtx.resume.mockClear();

    // Simulate tab returning to foreground
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      // allow microtask queue to flush
      await Promise.resolve();
    });

    expect(currentMockCtx.resume).toHaveBeenCalledOnce();
  });

  it("visibilitychange listener handles WebKit 'interrupted' state on restore", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    currentMockCtx.state = "interrupted";
    currentMockCtx.resume.mockClear();

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    expect(currentMockCtx.resume).toHaveBeenCalledOnce();
  });

  it("visibilitychange listener does not resume a closed context", async () => {
    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    currentMockCtx.state = "closed";
    currentMockCtx.resume.mockClear();

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    expect(currentMockCtx.resume).not.toHaveBeenCalled();
  });

  it("unlockAudioContext is idempotent — subsequent calls do not re-create context", async () => {
    const AudioContextSpy = vi.fn(function (this: unknown) { return currentMockCtx; });
    vi.stubGlobal("AudioContext", AudioContextSpy);

    const { result } = renderHook(() => useSequencer({ numSteps: 16 }));

    await act(async () => {
      await result.current.unlockAudioContext();
      await result.current.unlockAudioContext();
      await result.current.unlockAudioContext();
    });

    // AudioContext constructor invoked exactly once across three unlock calls
    expect(AudioContextSpy).toHaveBeenCalledOnce();
  });
});
