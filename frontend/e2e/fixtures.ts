/**
 * e2e/fixtures.ts
 *
 * Shared test fixtures: API mock setup, deterministic responses,
 * and reusable page helpers for all E2E specs.
 *
 * Every test file imports `test` and `expect` from here instead of
 * @playwright/test directly — this wires up API mocking automatically.
 */

import { test as base, expect, type Page } from "@playwright/test";

/* ------------------------------------------------------------------ */
/* Deterministic API response payloads                                 */
/* ------------------------------------------------------------------ */

export const HEALTH_RESPONSE = {
  status: "ok",
  version: "0.5.0",
};

export const EFFECTS_RESPONSE = {
  chain: [
    { key: "noise_floor", class_name: "NoiseFloor", position: 0, docstring: "Analog console noise floor — Mackie CR-1604", params: { noise_type: { type: "str", default: "pink" }, level_db: { type: "float", default: -75 } } },
    { key: "bitcrusher", class_name: "Bitcrusher", position: 1, docstring: "SP-1200 12-bit quantisation", params: { bit_depth: { type: "int", default: 12 }, sample_rate: { type: "int", default: 26040 } } },
    { key: "filter", class_name: "Filter", position: 2, docstring: "TB-303 resonant filter model", params: { cutoff_hz: { type: "float", default: 800 }, resonance: { type: "float", default: 0.7 }, filter_type: { type: "str", default: "lowpass" } } },
    { key: "saturation", class_name: "Saturation", position: 3, docstring: "Mackie bus saturation", params: { drive: { type: "float", default: 0.3 }, mode: { type: "str", default: "soft" } } },
    { key: "reverb", class_name: "Reverb", position: 4, docstring: "Quadraverb plate/hall reverb", params: { decay_s: { type: "float", default: 2.0 }, reverb_type: { type: "str", default: "plate" }, colour: { type: "float", default: 0.0 } } },
    { key: "delay", class_name: "Delay", position: 5, docstring: "RE-201 tape delay model", params: { time_ms: { type: "float", default: 375 }, feedback: { type: "float", default: 0.4 }, tape_age: { type: "str", default: "new" } } },
    { key: "spatial", class_name: "Spatial", position: 6, docstring: "Stereo width and bass mono", params: { width: { type: "float", default: 0.6 }, bass_mono_hz: { type: "float", default: 200 } } },
    { key: "glitch", class_name: "Glitch", position: 7, docstring: "ASR-10 buffer glitch", params: { stutter_probability: { type: "float", default: 0.1 }, xor_mode: { type: "str", default: "off" } } },
    { key: "compressor", class_name: "Compressor", position: 8, docstring: "Bus summing compressor", params: { threshold_db: { type: "float", default: -12 }, ratio: { type: "float", default: 4.0 } } },
    { key: "vinyl", class_name: "Vinyl", position: 9, docstring: "Vinyl mastering and DAT emulation", params: { vinyl_condition: { type: "str", default: "good" }, dat_mode: { type: "str", default: "standard" } } },
  ],
};

export const GENERATE_RESPONSE_WAV = createMinimalWavBase64();

export const ASK_RESPONSE = {
  answer: "The TB-303 acid slide is created by the portamento circuit between consecutive notes with accent enabled. The slide time is approximately 60ms, and accent coupling raises the filter cutoff simultaneously.",
  sources: [
    { title: "Part 4.2 — TB-303 Accent & Slide", part: "4.2", score: 0.94 },
    { title: "Part 1.1 — Roland Instruments", part: "1.1", score: 0.87 },
  ],
  model: "gpt-4o",
  usage: { prompt_tokens: 1200, completion_tokens: 180, total_tokens: 1380 },
};

export const COMPOSE_RESPONSE = {
  config: {
    generator: "noise_burst",
    generator_params: { tone: 0.3 },
    chain_overrides: {
      reverb: { decay_s: 4.5, reverb_type: "hall", colour: -0.3 },
      bitcrusher: { bit_depth: 10 },
      vinyl: { vinyl_condition: "worn" },
    },
  },
  reasoning: "Dark cavernous reverb calls for a long hall decay with negative colour (darker tail). Bitcrushing to 10-bit adds lo-fi texture. Worn vinyl condition introduces surface noise and bandwidth limiting.",
  sources: [{ title: "Part 5 — Reverb Architecture", part: "5", score: 0.91 }],
  usage: { prompt_tokens: 1500, completion_tokens: 250, total_tokens: 1750 },
};

export const SYNTHDEF_RESPONSE = {
  code: `(
// IDM Generative System — SuperCollider SynthDef
// Generator: glitch_click | Mode: studio
s.waitForBoot({
    SynthDef(\\idm_glitch_click, {
        |out=0, freq=800, amp=0.5, dur=0.01|
        var sig = Impulse.ar(freq) * EnvGen.kr(Env.perc(0.001, dur), doneAction: 2);
        Out.ar(out, sig * amp);
    }).add;

    SynthDef(\\idm_fx_reverb, {
        |in=0, out=0, decay=2.0, mix=0.3|
        var sig = In.ar(in, 1);
        var wet = FreeVerb.ar(sig, mix, decay, 0.5);
        ReplaceOut.ar(out, wet);
    }).add;

    s.sync;
    Pbind(\\instrument, \\idm_glitch_click, \\dur, 0.25, \\freq, 800).play;
});
)`,
  target: "supercollider",
  mode: "studio",
  warnings: [],
  unmapped_params: [],
  metadata: { synthdef_names: ["idm_glitch_click", "idm_fx_reverb"], bus_offset: 16 },
  setup_notes: ["Requires SuperCollider 3.12+", "Evaluate the entire block at once"],
};

export const TIDAL_RESPONSE = {
  code: `-- IDM Generative System — TidalCycles
-- Generator: glitch_click | Mode: studio
setcps (120/60/4)

d1 $ s "click" # n (irand 8)
   # room 0.3 # sz 0.8
   # crush 12
   # lpf 800 # resonance 0.7
   # gain 0.9`,
  target: "tidalcycles",
  mode: "studio",
  warnings: [],
  unmapped_params: [],
  metadata: { sound_name: "click", orbit: 0, bpm: 120 },
  setup_notes: ["Requires TidalCycles 1.9+", "SuperDirt must be running"],
};

/* ------------------------------------------------------------------ */
/* Minimal WAV file generator (silence, 0.1s, 44100Hz, 16-bit mono)   */
/* ------------------------------------------------------------------ */

function createMinimalWavBase64(): string {
  const sampleRate = 44100;
  const numSamples = Math.floor(sampleRate * 0.1);
  const bytesPerSample = 2;
  const dataSize = numSamples * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  // fmt chunk
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  // data chunk
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);
  // silence — all zeros

  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);

  function writeString(dv: DataView, offset: number, str: string) {
    for (let i = 0; i < str.length; i++) {
      dv.setUint8(offset + i, str.charCodeAt(i));
    }
  }
}

/* ------------------------------------------------------------------ */
/* API mock setup                                                      */
/* ------------------------------------------------------------------ */

async function mockAllApiRoutes(page: Page) {
  // Health
  await page.route("**/api/health", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HEALTH_RESPONSE) })
  );

  // Effects — API returns array directly, not { chain: [...] }
  await page.route("**/api/effects", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EFFECTS_RESPONSE.chain) })
  );

  // Generate — return WAV binary
  await page.route("**/api/generate", (route) =>
    route.fulfill({
      status: 200,
      contentType: "audio/wav",
      body: Buffer.from(GENERATE_RESPONSE_WAV, "base64"),
    })
  );

  // Process — same as generate
  await page.route("**/api/process", (route) =>
    route.fulfill({
      status: 200,
      contentType: "audio/wav",
      body: Buffer.from(GENERATE_RESPONSE_WAV, "base64"),
    })
  );

  // Ask
  await page.route("**/api/ask", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ASK_RESPONSE) })
  );

  // Compose
  await page.route("**/api/compose", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(COMPOSE_RESPONSE) })
  );

  // Synthdef
  await page.route("**/api/synthdef", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SYNTHDEF_RESPONSE) })
  );

  // Tidal
  await page.route("**/api/tidal", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TIDAL_RESPONSE) })
  );
}

/* ------------------------------------------------------------------ */
/* Extended test fixture with auto-mocking                             */
/* ------------------------------------------------------------------ */

export const test = base.extend<{ mockApi: void }>({
  mockApi: [
    async ({ page }, use) => {
      await mockAllApiRoutes(page);
      await use();
    },
    { auto: true },
  ],
});

export { expect };

/* ------------------------------------------------------------------ */
/* Page helpers                                                        */
/* ------------------------------------------------------------------ */

/** Navigate to a tab and wait for route */
export async function navigateToTab(page: Page, tabName: string, expectedPath: string) {
  await page.getByRole("link", { name: tabName, exact: true }).click();
  await page.waitForURL(`**${expectedPath}`);
}

/** Collect all console errors during a callback */
export async function collectConsoleErrors(page: Page, fn: () => Promise<void>): Promise<string[]> {
  const errors: string[] = [];
  const handler = (msg: import("@playwright/test").ConsoleMessage) => {
    if (msg.type() === "error") errors.push(msg.text());
  };
  page.on("console", handler);
  await fn();
  page.off("console", handler);
  return errors;
}

/**
 * Extract full code text from CodeBlock component.
 * CodeBlock renders each line in a separate <code> element —
 * we collect all and join to get the complete source.
 */
export async function getCodeBlockText(page: Page): Promise<string> {
  const lines = await page.locator("code").allTextContents();
  return lines.join("\n");
}
