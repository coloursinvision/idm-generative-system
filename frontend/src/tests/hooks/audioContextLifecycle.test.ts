/*
 * Both sequencer hooks must keep one AudioContext lifecycle, so the same contract
 * runs against each of them; the master bus the EP-133 hook builds on every new
 * context is pinned on top.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useSequencer, SCHEDULER_INTERVAL_MS } from "../../hooks/useSequencer";
import { useEP133Sequencer } from "../../hooks/useEP133Sequencer";

vi.mock("../../api/client", () => ({
  postGenerate: vi.fn(async () => ({
    arrayBuffer: async () => new ArrayBuffer(8),
  })),
}));

/* AudioContext mock: function-form constructor (arrow fns lack [[Construct]]). */

type MockState = "suspended" | "running" | "closed" | "interrupted";

interface MockParam {
  value: number;
}

interface MockSource {
  buffer: unknown;
  connect: ReturnType<typeof vi.fn>;
  start: ReturnType<typeof vi.fn>;
}

interface MockGain {
  gain: MockParam;
  connect: ReturnType<typeof vi.fn>;
}

interface MockCompressor {
  threshold: MockParam;
  knee: MockParam;
  ratio: MockParam;
  attack: MockParam;
  release: MockParam;
  connect: ReturnType<typeof vi.fn>;
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
  buffers: object[];
  sources: MockSource[];
  gains: MockGain[];
  compressors: MockCompressor[];
}

let contexts: MockAudioContext[];
let initialState: MockState;
let resumeTo: MockState;
let resumeGate: Promise<void>;
let visibility: DocumentVisibilityState;
let AudioContextSpy: ReturnType<typeof vi.fn>;

function createMockAudioContext(): MockAudioContext {
  const ctx: MockAudioContext = {
    state: initialState,
    currentTime: 0,
    destination: {},
    resume: vi.fn(),
    close: vi.fn(),
    createBuffer: vi.fn(),
    createBufferSource: vi.fn(),
    createGain: vi.fn(),
    createDynamicsCompressor: vi.fn(),
    decodeAudioData: vi.fn(async () => ({}) as AudioBuffer),
    buffers: [],
    sources: [],
    gains: [],
    compressors: [],
  };
  // resume() settles asynchronously, as in a browser; a test holds it pending
  // through resumeGate to see what the caller does before it settles.
  ctx.resume.mockImplementation(async () => {
    await resumeGate;
    ctx.state = resumeTo;
  });
  ctx.createBuffer.mockImplementation(() => {
    const buffer = {};
    ctx.buffers.push(buffer);
    return buffer;
  });
  ctx.createBufferSource.mockImplementation(() => {
    const source: MockSource = { buffer: null, connect: vi.fn(), start: vi.fn() };
    ctx.sources.push(source);
    return source;
  });
  ctx.createGain.mockImplementation(() => {
    const gain: MockGain = { gain: { value: 0 }, connect: vi.fn() };
    ctx.gains.push(gain);
    return gain;
  });
  ctx.createDynamicsCompressor.mockImplementation(() => {
    const compressor: MockCompressor = {
      threshold: { value: 0 },
      knee: { value: 0 },
      ratio: { value: 0 },
      attack: { value: 0 },
      release: { value: 0 },
      connect: vi.fn(),
    };
    ctx.compressors.push(compressor);
    return compressor;
  });
  return ctx;
}

beforeEach(() => {
  contexts = [];
  initialState = "suspended";
  resumeTo = "running";
  resumeGate = Promise.resolve();
  visibility = "visible";
  AudioContextSpy = vi.fn(function (this: unknown) {
    const ctx = createMockAudioContext();
    contexts.push(ctx);
    return ctx;
  });
  vi.stubGlobal("AudioContext", AudioContextSpy);
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
});

afterEach(() => {
  Reflect.deleteProperty(document, "visibilityState");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const GROUPS = ["A", "B", "C", "D"] as const;
const GROUP_TRACKS = {
  A: [{ name: "A0", generator: "noise_burst" }],
  B: [{ name: "B0", generator: "fm_blip" }],
  C: [{ name: "C0", generator: "fm_blip" }],
  D: [{ name: "D0", generator: "noise_burst" }],
};

function renderEP133() {
  return renderHook(() =>
    useEP133Sequencer({ groups: GROUPS, groupTracks: GROUP_TRACKS, defaultBpm: 120 })
  );
}

interface MountedHook {
  unlock: () => Promise<void>;
  unmount: () => void;
}

interface Subject {
  name: string;
  prefix: string;
  render: () => MountedHook;
}

const SUBJECTS: Subject[] = [
  {
    name: "useSequencer",
    prefix: "[useSequencer]",
    render: () => {
      const hook = renderHook(() => useSequencer({ numSteps: 16 }));
      return {
        unlock: () => hook.result.current.unlockAudioContext(),
        unmount: hook.unmount,
      };
    },
  },
  {
    name: "useEP133Sequencer",
    prefix: "[useEP133Sequencer]",
    render: () => {
      const hook = renderEP133();
      return {
        unlock: () => hook.result.current.unlockAudioContext(),
        unmount: hook.unmount,
      };
    },
  },
];

async function unlockIn(hook: MountedHook) {
  await act(async () => {
    await hook.unlock();
  });
}

/** Set the tab's visibility and dispatch the event the hooks listen for. */
async function changeVisibility(state: DocumentVisibilityState) {
  visibility = state;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
    await Promise.resolve();
  });
}

const PUMP_ID = 1_000_001;

/**
 * Hold the scheduler pump, armed at SCHEDULER_INTERVAL_MS, and return a function
 * that fires one pass by hand; every other timer stays real for React and act().
 */
function holdPump(): () => void {
  let pump: (() => void) | null = null;
  const realSetTimeout = globalThis.setTimeout.bind(globalThis);
  vi.stubGlobal(
    "setTimeout",
    vi.fn((callback: () => void, delay?: number) => {
      if (delay === SCHEDULER_INTERVAL_MS) {
        pump = callback;
        return PUMP_ID;
      }
      return realSetTimeout(callback, delay);
    })
  );
  return () => {
    const callback = pump;
    pump = null;
    expect(callback).not.toBeNull();
    act(() => {
      callback?.();
    });
  };
}

describe.each(SUBJECTS)("$name AudioContext lifecycle", (subject) => {
  it("creates no context before first use, then one context at 44.1 kHz", async () => {
    const hook = subject.render();
    expect(AudioContextSpy).not.toHaveBeenCalled();

    await unlockIn(hook);

    expect(AudioContextSpy).toHaveBeenCalledOnce();
    expect(AudioContextSpy).toHaveBeenCalledWith({ sampleRate: 44100 });
  });

  it("awaits the resume of a suspended context before using it", async () => {
    let settleResume: () => void = () => {};
    resumeGate = new Promise<void>((resolve) => {
      settleResume = resolve;
    });
    const hook = subject.render();

    await act(async () => {
      const unlocking = hook.unlock();
      expect(contexts[0].sources).toHaveLength(0);
      settleResume();
      await unlocking;
    });

    const [ctx] = contexts;
    expect(ctx.resume).toHaveBeenCalledOnce();
    expect(ctx.state).toBe("running");
    expect(ctx.sources).toHaveLength(1);
  });

  it("resumes an interrupted context as it does a suspended one", async () => {
    initialState = "interrupted";
    const hook = subject.render();

    await unlockIn(hook);

    const [ctx] = contexts;
    expect(ctx.resume).toHaveBeenCalledOnce();
    expect(ctx.state).toBe("running");
  });

  it("reuses a running context without resuming it again", async () => {
    const hook = subject.render();

    await unlockIn(hook);
    await unlockIn(hook);
    await unlockIn(hook);

    expect(AudioContextSpy).toHaveBeenCalledOnce();
    expect(contexts[0].resume).toHaveBeenCalledOnce();
  });

  it("replaces a closed context with a new one", async () => {
    const hook = subject.render();
    await unlockIn(hook);
    contexts[0].state = "closed";

    await unlockIn(hook);

    expect(AudioContextSpy).toHaveBeenCalledTimes(2);
    const [first, second] = contexts;
    expect(second.resume).toHaveBeenCalledOnce();
    expect(second.sources).toHaveLength(1);
    expect(first.sources).toHaveLength(1);
  });

  it("unlock plays a one-sample silent buffer into the destination", async () => {
    const hook = subject.render();

    await unlockIn(hook);

    const [ctx] = contexts;
    expect(ctx.createBuffer).toHaveBeenCalledWith(1, 1, 22050);
    const [source] = ctx.sources;
    expect(source.buffer).toBe(ctx.buffers[0]);
    expect(source.connect).toHaveBeenCalledWith(ctx.destination);
    expect(source.start).toHaveBeenCalledWith(0);
  });

  it("unlock plays nothing when the context does not reach running", async () => {
    resumeTo = "suspended";
    const hook = subject.render();

    await unlockIn(hook);

    const [ctx] = contexts;
    expect(ctx.createBuffer).not.toHaveBeenCalled();
    expect(ctx.sources).toHaveLength(0);
  });

  it("a tab restore resumes a suspended context", async () => {
    const hook = subject.render();
    await unlockIn(hook);
    const [ctx] = contexts;
    ctx.state = "suspended";
    ctx.resume.mockClear();

    await changeVisibility("visible");

    expect(ctx.resume).toHaveBeenCalledOnce();
  });

  it("a tab restore resumes an interrupted context", async () => {
    const hook = subject.render();
    await unlockIn(hook);
    const [ctx] = contexts;
    ctx.state = "interrupted";
    ctx.resume.mockClear();

    await changeVisibility("visible");

    expect(ctx.resume).toHaveBeenCalledOnce();
  });

  it("leaves a running or closed context, and a hidden tab, alone", async () => {
    const hook = subject.render();
    await unlockIn(hook);
    const [ctx] = contexts;
    ctx.resume.mockClear();

    await changeVisibility("visible");
    ctx.state = "closed";
    await changeVisibility("visible");
    ctx.state = "suspended";
    await changeVisibility("hidden");

    expect(ctx.resume).not.toHaveBeenCalled();
  });

  it("a failed resume on tab restore logs a warning with the hook's prefix", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const hook = subject.render();
    await unlockIn(hook);
    const [ctx] = contexts;
    ctx.state = "suspended";
    const error = new Error("resume refused");
    ctx.resume.mockRejectedValueOnce(error);

    await changeVisibility("visible");

    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalledOnce();
    });
    expect(warnSpy).toHaveBeenCalledWith(
      `${subject.prefix} resume on visibility restore failed:`,
      error
    );
  });

  it("before first use, neither a tab restore nor unmount creates a context", async () => {
    const hook = subject.render();

    await changeVisibility("visible");
    hook.unmount();

    expect(AudioContextSpy).not.toHaveBeenCalled();
  });

  it("unmount closes the context and stops listening for tab restores", async () => {
    const hook = subject.render();
    await unlockIn(hook);
    const [ctx] = contexts;

    hook.unmount();
    ctx.state = "suspended";
    ctx.resume.mockClear();
    await changeVisibility("visible");

    expect(ctx.close).toHaveBeenCalledOnce();
    expect(ctx.resume).not.toHaveBeenCalled();
  });
});

describe("useEP133Sequencer master bus", () => {
  it("the first context gets a 0.35 gain stage into a limiting compressor", async () => {
    const { result } = renderEP133();

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    const [ctx] = contexts;
    const [gain] = ctx.gains;
    const [compressor] = ctx.compressors;
    expect(gain.gain.value).toBe(0.35);
    expect({
      threshold: compressor.threshold.value,
      knee: compressor.knee.value,
      ratio: compressor.ratio.value,
      attack: compressor.attack.value,
      release: compressor.release.value,
    }).toEqual({ threshold: -10, knee: 6, ratio: 12, attack: 0.003, release: 0.25 });
    expect(gain.connect).toHaveBeenCalledWith(compressor);
    expect(compressor.connect).toHaveBeenCalledWith(ctx.destination);
  });

  it("the bus is built once per context", async () => {
    const { result } = renderEP133();

    await act(async () => {
      await result.current.unlockAudioContext();
      await result.current.unlockAudioContext();
      await result.current.loadGroupSamples("A");
    });

    const [ctx] = contexts;
    expect(ctx.gains).toHaveLength(1);
    expect(ctx.compressors).toHaveLength(1);
  });

  it("a replacement context gets a bus of its own", async () => {
    const { result } = renderEP133();
    await act(async () => {
      await result.current.unlockAudioContext();
    });
    contexts[0].state = "closed";

    await act(async () => {
      await result.current.unlockAudioContext();
    });

    const [first, second] = contexts;
    expect(first.gains).toHaveLength(1);
    expect(second.gains).toHaveLength(1);
    expect(second.compressors).toHaveLength(1);
    expect(second.gains[0].connect).toHaveBeenCalledWith(second.compressors[0]);
    expect(second.compressors[0].connect).toHaveBeenCalledWith(second.destination);
  });

  it("scheduled voices play into the master gain", async () => {
    const firePump = holdPump();
    const { result } = renderEP133();
    await act(async () => {
      await result.current.loadGroupSamples("A");
    });
    act(() => {
      result.current.toggleStep("A", 0, 0);
    });
    await act(async () => {
      await result.current.play();
    });

    firePump();

    const [ctx] = contexts;
    expect(ctx.sources).toHaveLength(1);
    expect(ctx.sources[0].connect).toHaveBeenCalledWith(ctx.gains[0]);
    expect(ctx.sources[0].start).toHaveBeenCalledWith(0);
  });

  it("after a replacement, voices play into the master gain of the new context", async () => {
    const firePump = holdPump();
    const { result } = renderEP133();
    await act(async () => {
      await result.current.unlockAudioContext();
    });
    contexts[0].state = "closed";
    await act(async () => {
      await result.current.loadGroupSamples("A");
    });
    act(() => {
      result.current.toggleStep("A", 0, 0);
    });
    await act(async () => {
      await result.current.play();
    });

    firePump();

    const [, second] = contexts;
    expect(second.gains).toHaveLength(1);
    expect(second.sources).toHaveLength(1);
    expect(second.sources[0].connect).toHaveBeenCalledWith(second.gains[0]);
  });
});
