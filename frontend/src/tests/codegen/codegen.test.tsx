/**
 * tests/codegen/codegen.test.ts
 *
 * Unit tests for the codegen frontend module.
 *
 * Test runner: Vitest + React Testing Library + jsdom
 *
 * Coverage:
 *   - Type contracts (compile-time — validated by tsc, listed here for documentation)
 *   - API helpers: postSynthdef, postTidal — request/response, error handling
 *   - useBroadcastChannel hook — message passing, heartbeat, cleanup
 *   - CodeBlock component — render, syntax highlighting, copy, download
 *   - CodegenPanel component — tab switching, config drawer, generate flow
 *   - CodegenPopout component — standalone render, BroadcastChannel reception
 *
 * Run:
 *   cd frontend && npx vitest run src/tests/codegen/
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";

/* ------------------------------------------------------------------ */
/* 1. Type contract tests (compile-time — tsc validates these)         */
/*    Listed explicitly so test coverage report shows intent.          */
/* ------------------------------------------------------------------ */

import type {
  CodegenTarget,
  CodegenMode,
  PatternConfigEuclidean,
  PatternConfigDensity,
  PatternConfigProbabilistic,
  CodegenRequest,
  CodegenResponse,
  CodegenBroadcastMessage,
} from "../../types/codegen";

describe("Type contracts", () => {
  it("CodegenTarget accepts valid values", () => {
    const sc: CodegenTarget = "supercollider";
    const td: CodegenTarget = "tidalcycles";
    expect(sc).toBe("supercollider");
    expect(td).toBe("tidalcycles");
  });

  it("CodegenMode accepts valid values", () => {
    const studio: CodegenMode = "studio";
    const live: CodegenMode = "live";
    expect(studio).toBe("studio");
    expect(live).toBe("live");
  });

  it("PatternConfig tagged union discriminates on type", () => {
    const euclidean: PatternConfigEuclidean = {
      type: "euclidean",
      pulses: { glitch_click: 5 },
      steps: 16,
    };
    const density: PatternConfigDensity = {
      type: "density",
      density: 0.4,
      steps: 16,
    };
    const probabilistic: PatternConfigProbabilistic = {
      type: "probabilistic",
      density: 0.3,
      steps: 8,
    };
    expect(euclidean.type).toBe("euclidean");
    expect(density.type).toBe("density");
    expect(probabilistic.type).toBe("probabilistic");
  });

  it("CodegenRequest has all required and optional fields", () => {
    const minimal: CodegenRequest = { generator: "glitch_click" };
    const full: CodegenRequest = {
      generator: "fm_blip",
      generator_params: { freq: 440 },
      effects: { filter: { freq: 800 } },
      pattern: { type: "euclidean", pulses: { fm_blip: 3 }, steps: 8 },
      mode: "live",
      include_pattern: true,
      bpm: 140,
      bus_offset: 32,
    };
    expect(minimal.generator).toBe("glitch_click");
    expect(full.bpm).toBe(140);
  });

  it("CodegenResponse has all fields", () => {
    const response: CodegenResponse = {
      code: "s.waitForBoot({ ... })",
      target: "supercollider",
      mode: "studio",
      warnings: ["reverb.room approximated"],
      unmapped_params: { reverb: ["reverb_type", "diffusion"] },
      metadata: { synthdef_names: ["idm_glitch_click"] },
      setup_notes: ["Boot server first"],
    };
    expect(response.target).toBe("supercollider");
    expect(response.warnings).toHaveLength(1);
    expect(response.unmapped_params.reverb).toHaveLength(2);
  });

  it("CodegenBroadcastMessage discriminates on type", () => {
    const messages: CodegenBroadcastMessage[] = [
      {
        type: "state_update",
        generator: "glitch_click",
        effects: { filter: {} },
        bpm: 120,
        mode: "studio",
      },
      { type: "popout_ready" },
      { type: "popout_closed" },
      { type: "heartbeat" },
    ];
    expect(messages).toHaveLength(4);
    expect(messages[0].type).toBe("state_update");
  });
});

/* ------------------------------------------------------------------ */
/* 2. API helper tests                                                 */
/* ------------------------------------------------------------------ */

import { postSynthdef, postTidal } from "../../api/codegen";

describe("API helpers", () => {
  const mockResponse: CodegenResponse = {
    code: '(\ns.waitForBoot({ ... });\n)',
    target: "supercollider",
    mode: "studio",
    warnings: [],
    unmapped_params: {},
    metadata: {},
    setup_notes: [],
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("postSynthdef sends POST to /synthdef with correct body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    const body: CodegenRequest = {
      generator: "glitch_click",
      effects: { filter: {} },
      bpm: 120,
    };

    const result = await postSynthdef(body);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, options] = fetchSpy.mock.calls[0];
    expect(url).toContain("/synthdef");
    expect(options?.method).toBe("POST");
    expect(JSON.parse(options?.body as string)).toEqual(body);
    expect(result.target).toBe("supercollider");
  });

  it("postTidal sends POST to /tidal", async () => {
    const tidalResponse = { ...mockResponse, target: "tidalcycles" as const };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(tidalResponse),
    } as Response);

    const result = await postTidal({ generator: "noise_burst" });
    expect(result.target).toBe("tidalcycles");
  });

  it("throws Error with FastAPI detail on 400", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: () => Promise.resolve({ detail: "Invalid generator: unknown" }),
    } as unknown as Response);

    await expect(postSynthdef({ generator: "unknown" })).rejects.toThrow(
      "Invalid generator: unknown",
    );
  });

  it("throws Error with status text when response is not JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("not json")),
    } as unknown as Response);

    await expect(postSynthdef({ generator: "glitch_click" })).rejects.toThrow(
      "Internal Server Error",
    );
  });

  it("throws Error on network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("Failed to fetch"),
    );

    await expect(postSynthdef({ generator: "glitch_click" })).rejects.toThrow(
      "Network error",
    );
  });

  it("handles Pydantic validation error array", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: () =>
        Promise.resolve({
          detail: [
            { msg: "field required", loc: ["body", "generator"] },
            { msg: "value is not valid", loc: ["body", "bpm"] },
          ],
        }),
    } as unknown as Response);

    await expect(postSynthdef({ generator: "" })).rejects.toThrow(
      "field required; value is not valid",
    );
  });
});

/* ------------------------------------------------------------------ */
/* 3. useBroadcastChannel hook tests                                   */
/* ------------------------------------------------------------------ */

import { renderHook } from "@testing-library/react";
import { useBroadcastChannel } from "../../components/codegen/useBroadcastChannel";

describe("useBroadcastChannel", () => {
  let mockChannel: {
    postMessage: ReturnType<typeof vi.fn>;
    close: ReturnType<typeof vi.fn>;
    onmessage: ((event: MessageEvent) => void) | null;
  };

  beforeEach(() => {
    mockChannel = {
      postMessage: vi.fn(),
      close: vi.fn(),
      onmessage: null,
    };

    vi.stubGlobal("BroadcastChannel", vi.fn(function(this: Record<string, unknown>) {
      this.postMessage = vi.fn();
      this.close = vi.fn();
      this.onmessage = null;
      mockChannel = this as typeof mockChannel;
    }) as unknown as typeof BroadcastChannel);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates channel with given name", () => {
    renderHook(() => useBroadcastChannel("test-channel"));
    expect(BroadcastChannel).toHaveBeenCalledWith("test-channel");
  });

  it("postMessage sends typed message", () => {
    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    act(() => {
      result.current.postMessage({ type: "heartbeat" });
    });

    expect(mockChannel.postMessage).toHaveBeenCalledWith({ type: "heartbeat" });
  });

  it("receives messages and updates lastMessage", () => {
    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    act(() => {
      mockChannel.onmessage?.({
        data: {
          type: "state_update",
          generator: "fm_blip",
          effects: {},
          bpm: 140,
          mode: "live",
        },
      } as unknown as MessageEvent);
    });

    expect(result.current.lastMessage?.type).toBe("state_update");
  });

  it("sets isConnected on heartbeat reception", () => {
    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    expect(result.current.isConnected).toBe(false);

    act(() => {
      mockChannel.onmessage?.({
        data: { type: "heartbeat" },
      } as unknown as MessageEvent);
    });

    expect(result.current.isConnected).toBe(true);
  });

  it("sets isConnected on popout_ready", () => {
    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    act(() => {
      mockChannel.onmessage?.({
        data: { type: "popout_ready" },
      } as unknown as MessageEvent);
    });

    expect(result.current.isConnected).toBe(true);
  });

  it("sets isConnected false on popout_closed", () => {
    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    // First connect
    act(() => {
      mockChannel.onmessage?.({
        data: { type: "heartbeat" },
      } as unknown as MessageEvent);
    });
    expect(result.current.isConnected).toBe(true);

    // Then disconnect
    act(() => {
      mockChannel.onmessage?.({
        data: { type: "popout_closed" },
      } as unknown as MessageEvent);
    });
    expect(result.current.isConnected).toBe(false);
  });

  it("closes channel on unmount", () => {
    const { unmount } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    unmount();
    expect(mockChannel.close).toHaveBeenCalledOnce();
  });

  it("starts heartbeat interval when sendHeartbeat is true", () => {
    vi.useFakeTimers();

    renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test", true),
    );

    act(() => {
      vi.advanceTimersByTime(4000); // 2 heartbeats at 2000ms interval
    });

    expect(mockChannel.postMessage).toHaveBeenCalledWith({ type: "heartbeat" });
    expect(mockChannel.postMessage.mock.calls.length).toBeGreaterThanOrEqual(2);

    vi.useRealTimers();
  });

  it("handles missing BroadcastChannel gracefully", () => {
    vi.stubGlobal("BroadcastChannel", undefined);

    const { result } = renderHook(() =>
      useBroadcastChannel<CodegenBroadcastMessage>("test"),
    );

    // Should not throw, should return defaults
    expect(result.current.lastMessage).toBeNull();
    expect(result.current.isConnected).toBe(false);

    // postMessage should not throw
    act(() => {
      result.current.postMessage({ type: "heartbeat" });
    });
  });
});

/* ------------------------------------------------------------------ */
/* 4. CodeBlock component tests                                        */
/* ------------------------------------------------------------------ */

import { CodeBlock } from "../../components/codegen/CodeBlock";

describe("CodeBlock", () => {
  const SC_CODE = `// test
SynthDef(\\test, {
    arg freq = 440;
    var sig = SinOsc.ar(freq);
    Out.ar(0, sig);
}).add;`;

  const TIDAL_CODE = `-- test
setcps (120/60/4)
d1 $ sound "bd" # lpf 800`;

  it("renders sclang code with line numbers", () => {
    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );

    // Should have line numbers
    expect(container.textContent).toContain("1");
    expect(container.textContent).toContain("6");

    // Should contain code text
    expect(container.textContent).toContain("SynthDef");
    expect(container.textContent).toContain("SinOsc");
  });

  it("renders Tidal code with line numbers", () => {
    const { container } = render(
      <CodeBlock code={TIDAL_CODE} target="tidalcycles" />,
    );

    expect(container.textContent).toContain("setcps");
    expect(container.textContent).toContain("sound");
    expect(container.textContent).toContain("lpf");
  });

  it("displays correct label for supercollider", () => {
    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );
    expect(container.textContent).toContain("SCLANG .SCD");
  });

  it("displays correct label for tidalcycles", () => {
    const { container } = render(
      <CodeBlock code={TIDAL_CODE} target="tidalcycles" />,
    );
    expect(container.textContent).toContain("HASKELL / TIDAL .TIDAL");
  });

  it("displays line count", () => {
    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );
    expect(container.textContent).toContain("6 LINES");
  });

  it("has COPY and SAVE buttons", () => {
    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );
    const buttons = container.querySelectorAll("button");
    const labels = Array.from(buttons).map((b) => b.textContent);
    expect(labels).toContain("COPY");
    expect(labels).toContain("SAVE");
  });

  it("copy button calls navigator.clipboard.writeText", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: { writeText },
    });

    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );

    const copyBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === "COPY",
    )!;

    await act(async () => {
      fireEvent.click(copyBtn);
    });

    expect(writeText).toHaveBeenCalledWith(SC_CODE);
  });

  it("applies solarized dark background", () => {
    const { container } = render(
      <CodeBlock code={SC_CODE} target="supercollider" />,
    );

    expect(container.innerHTML).toContain("rgb(0, 43, 54)");
  });
});

/* ------------------------------------------------------------------ */
/* 5. CodegenPanel component tests                                     */
/* ------------------------------------------------------------------ */

import { CodegenPanel } from "../../components/codegen/CodegenPanel";

describe("CodegenPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Mock BroadcastChannel
    vi.stubGlobal("BroadcastChannel", vi.fn(function(this: Record<string, unknown>) {
      this.postMessage = vi.fn();
      this.close = vi.fn();
      this.onmessage = null;
    }) as unknown as typeof BroadcastChannel);
  });

  it("renders top bar with SC and TIDAL tabs", () => {
    render(<CodegenPanel />);
    expect(screen.getByText("SC")).toBeInTheDocument();
    expect(screen.getByText("TIDAL")).toBeInTheDocument();
  });

  it("renders GENERATE button", () => {
    render(<CodegenPanel />);
    expect(screen.getByText("GENERATE")).toBeInTheDocument();
  });

  it("renders CONFIG drawer toggle with summary", () => {
    render(<CodegenPanel />);
    expect(screen.getByText("CONFIG")).toBeInTheDocument();
    // Summary should contain default values
    expect(screen.getByText(/GLITCH.*STUDIO.*120 BPM.*3 FX/)).toBeInTheDocument();
  });

  it("CONFIG drawer is collapsed by default", () => {
    render(<CodegenPanel />);
    // Generator buttons should NOT be visible
    expect(screen.queryByText("NOISE")).not.toBeInTheDocument();
  });

  it("CONFIG drawer opens on click", () => {
    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("CONFIG"));
    // Now generator buttons should be visible
    expect(screen.getByText(/^noise$/i)).toBeInTheDocument();
    expect(screen.getByText(/^fm$/i)).toBeInTheDocument();
  });

  it("SC tab is active by default", () => {
    render(<CodegenPanel />);
    const scButton = screen.getByText("SC");
    expect(scButton.className).toContain("text-text-primary");
  });

  it("switches to TIDAL tab on click", () => {
    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("TIDAL"));
    const tidalButton = screen.getByText("TIDAL");
    expect(tidalButton.className).toContain("text-text-primary");
  });

  it("renders popout button ⧉", () => {
    render(<CodegenPanel />);
    expect(screen.getByTitle("Open in separate window")).toBeInTheDocument();
  });

  it("calls API and displays code on GENERATE click", async () => {
    const mockResponse: CodegenResponse = {
      code: "// generated code",
      target: "supercollider",
      mode: "studio",
      warnings: ["test warning"],
      unmapped_params: { reverb: ["diffusion"] },
      metadata: { synthdef_names: ["test"] },
      setup_notes: ["Boot server"],
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    } as Response);

    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("GENERATE"));

    await waitFor(() => {
      expect(screen.getByText(/SCLANG .SCD/)).toBeInTheDocument();
    });

    // Code should be visible
    expect(screen.getByText(/generated code/)).toBeInTheDocument();

    // Warnings strip should be visible
    expect(screen.getByText(/WARNINGS/)).toBeInTheDocument();
  });

  it("displays error on API failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: () => Promise.resolve({ detail: "Invalid generator" }),
    } as unknown as Response);

    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("GENERATE"));

    await waitFor(() => {
      expect(screen.getByText("Invalid generator")).toBeInTheDocument();
    });
  });

  it("updates config summary when generator changes", () => {
    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("CONFIG"));
    fireEvent.click(screen.getByText(/^noise$/i));
    expect(screen.getByText(/NOISE.*STUDIO.*120 BPM/i)).toBeInTheDocument();
  });

  it("toggles effects in config drawer", () => {
    render(<CodegenPanel />);
    fireEvent.click(screen.getByText("CONFIG"));

    // Click "reverb" to deactivate
    fireEvent.click(screen.getByText("reverb"));
    expect(screen.getByText(/2 FX/)).toBeInTheDocument();

    // Click "reverb" again to reactivate
    fireEvent.click(screen.getByText("reverb"));
    expect(screen.getByText(/3 FX/)).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* 6. CodegenPopout component tests                                    */
/* ------------------------------------------------------------------ */

import { CodegenPopout } from "../../components/codegen/CodegenPopout";

describe("CodegenPopout", () => {
  let mockChannel: {
    postMessage: ReturnType<typeof vi.fn>;
    close: ReturnType<typeof vi.fn>;
    onmessage: ((event: MessageEvent) => void) | null;
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    mockChannel = {
      postMessage: vi.fn(),
      close: vi.fn(),
      onmessage: null,
    };
    vi.stubGlobal("BroadcastChannel", vi.fn(function(this: Record<string, unknown>) {
      this.postMessage = vi.fn();
      this.close = vi.fn();
      this.onmessage = null;
      mockChannel = this as typeof mockChannel;
    }) as unknown as typeof BroadcastChannel);
  });

  it("renders top bar with SC and TIDAL tabs", () => {
    render(<CodegenPopout />);
    expect(screen.getByText("SC")).toBeInTheDocument();
    expect(screen.getByText("TIDAL")).toBeInTheDocument();
  });

  it("renders GENERATE button", () => {
    render(<CodegenPopout />);
    expect(screen.getByText("GENERATE")).toBeInTheDocument();
  });

  it("CONFIG drawer is open by default (standalone mode)", () => {
    render(<CodegenPopout />);
    // Generator buttons should be visible
    expect(screen.getByText(/^noise$/i)).toBeInTheDocument();
  });

  it("sends popout_ready on mount", () => {
    render(<CodegenPopout />);
    expect(mockChannel.postMessage).toHaveBeenCalledWith({
      type: "popout_ready",
    });
  });

  it("receives state_update and collapses config", () => {
    render(<CodegenPopout />);

    // Config should be open initially
    expect(screen.getByText(/^noise$/i)).toBeInTheDocument();

    // Simulate receiving state_update
    act(() => {
      mockChannel.onmessage?.({
        data: {
          type: "state_update",
          generator: "fm_blip",
          effects: { reverb: {} },
          bpm: 140,
          mode: "live",
        },
      } as unknown as MessageEvent);
    });

    // Config should collapse after receiving remote state
    expect(screen.queryByText("NOISE")).not.toBeInTheDocument();

    // Summary should reflect received state
    expect(screen.getByText(/FM.*LIVE.*140 BPM.*1 FX/)).toBeInTheDocument();
  });

  it("shows sync indicator after receiving remote state", () => {
    render(<CodegenPopout />);

    act(() => {
      mockChannel.onmessage?.({
        data: {
          type: "state_update",
          generator: "glitch_click",
          effects: {},
          bpm: 120,
          mode: "studio",
        },
      } as unknown as MessageEvent);
    });

    expect(screen.getByText("SYNCED WITH MAIN APP")).toBeInTheDocument();
  });

  it("does not have popout ⧉ button (already in popout)", () => {
    render(<CodegenPopout />);
    expect(screen.queryByTitle("Open in separate window")).not.toBeInTheDocument();
  });
});
