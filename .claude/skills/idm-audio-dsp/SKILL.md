---
name: idm-audio-dsp
description: >-
  Audio/DSP contracts, Web Audio transport architecture, and WebKit gotchas for the
  IDM Generative System. Use when editing engine/effects/*, engine/sample_maker.py,
  engine/codegen/*, the frontend sequencer hooks (useSequencer, useEP133Sequencer),
  debugging silent playback on Safari/WebKit, adding a generator or effect block,
  working with the PO-33/EP-133 guides, or needing hardware-era domain knowledge
  (regional profiles, resonance rules, modelled hardware). Read
  references/device-domain.md for hardware/regional domain knowledge.
---

# IDM — audio & DSP

## Engine contracts (backend)

- **Effects:** every block inherits `BaseEffect` (`engine/effects/base.py`) and
  implements `__call__(signal: np.ndarray) -> np.ndarray` plus `reset()`.
  Signals are float arrays normalised to `[-1.0, 1.0]`, same shape/dtype out.
  Stateful blocks (delay buffers, envelope followers) keep state in `__init__`
  and must reinitialise it in `reset()`.
- **Chain order is fixed** (`engine/effects/chain.py`):
  `NoiseFloor → Bitcrusher → ResonantFilter → Saturation → Reverb → TapeDelay →
  SpatialProcessor → GlitchEngine → Compressor → VinylMastering`.
- **Generators** (`engine/sample_maker.py`): return normalised float32 in
  `[-1.0, 1.0]`. Four exist: `glitch_click`, `noise_burst`, `fm_blip`,
  `fm_analog`. New parameters on an existing generator must be keyword-only
  with defaults that reproduce the previous output bit-identically (tests pin
  this — the `fm_blip` expansion is the precedent).
- **`fm_analog` specifics:** two detuned FM oscillators → tanh saturation →
  resonant SVF low-pass → amp envelope. The raw voice IS the deliverable — the
  effects chain is not its default path (callers pass `bypass_chain: true`).
  It is renderer-only: `/synthdef` and `/tidal` do not support it (codegen
  stage deferred by design). Known open fidelity caveat: the SuperCollider
  sketch scales modulation by carrier frequency (`mod_index * freq`), the
  Python renderer does not — do not assume SC/Python parity for FM depth.
- **Numba discipline:** `delay`, `compressor`, and `reverb` have `@njit` hot
  paths. Any JIT kernel must have a pure-Python reference implementation and a
  parity test asserting `rtol=1e-12, atol=1e-15` (see `tests/test_effects.py`).
  Adding a JIT path without the parity test is a regression.
- **Codegen completeness:** `engine/codegen/mappings.py` exposes
  `validate_mapping_completeness()` — when adding an effect or parameter, the
  codegen mapping must be extended and this validator kept passing.
- **Export contract:** API audio out is 24-bit WAV @ 44.1 kHz
  (`sf.write(..., subtype="PCM_24")`). The 16-bit path in `acid_engine_v2.py`
  is legacy dataset-validation only.
- **Acid model:** TB-303 slide is a recursive one-pole glide,
  `slide_time_ms=50` by default (`engine/acid_dsp_model.py`). Older docs
  saying 30 ms are wrong.

## Web Audio transport (frontend hooks)

Two hooks, two devices — architecture facts verified in code:

- **`useSequencer.ts` (PO-33):** single `AudioContext({ sampleRate: 44100 })`.
  Scheduler is the "Tale of Two Clocks" pattern: a **`setTimeout` pump every
  25 ms** (`SCHEDULER_INTERVAL_MS`) advancing a **0.1 s Web Audio lookahead
  window**. It is deliberately NOT `requestAnimationFrame`: rAF pauses in
  background tabs, which would defeat the background-robustness the
  `visibilitychange` handler provides. Keep it `setTimeout`.
- **`useEP133Sequencer.ts` (EP-133):** one `AudioContext`, one **master clock at
  32 ticks/bar**; each of the 4 groups strides over that single clock (stride
  derived from its timing mode) — this is how polyrhythm works without
  per-group transports. Master bus: `gain(0.35) → DynamicsCompressor →
  destination` to prevent clipping when groups stack. Mixer predicate: **solo
  wins over mute**, read fresh from a ref at schedule time.
- The AudioContext lifecycle logic is intentionally duplicated between the two
  hooks (registered debt, future shared util). If you change lifecycle
  behaviour, change BOTH hooks or neither.

## WebKit / Safari lifecycle rules (each guards a real production bug)

1. WebKit uses a non-standard `"interrupted"` AudioContext state (not in the
   TypeScript `AudioContextState` union). The hooks use a type predicate
   `isNonRunningState(state)` covering `"suspended" | "interrupted"` — treat
   both as "must resume before playback".
2. `context.resume()` must be **awaited before scheduling**; an un-awaited
   resume yields silent playback on Safari with no error.
3. Autoplay gate: `unlockAudioContext()` must run inside the first user
   gesture (it plays a silent buffer). Gesture scope is not transferable —
   a resume queued via setTimeout/async chain outside the gesture fails.
4. A `visibilitychange` listener recovers the context after backgrounding /
   BFCache restore; without it the context stays non-running on return.
5. `play()` has a re-entrancy guard — keep it when refactoring.

**Testing gotcha:** constructor mocks for `AudioContext` (and any `new`-ed
global) must be `function` expressions, never arrows — arrows have no
`[[Construct]]` and throw `TypeError: ... is not a constructor` under vitest.

**Dev-server gotcha:** `vite preview` does not inherit the dev proxy — it
needs `preview.proxy` configured, or `/api` calls fail while `npm run dev`
works fine.

## Known open caveats (do not "discover" these as new bugs)

- Guide audio/pattern state is lost on tab navigation (registered debt).
- EP-133 master FX panel is reference-only; master FX are unimplemented.
- EP-133 B/C/D pad rosters show 4 rows vs the hardware's 12 pads/group.
- A historical `/api/generate` 500 was resolved by environment and never
  root-caused; if it recurs, start at the DSP render path in `api/main.py`'s
  `/generate` handler, not at the frontend.

## Domain knowledge

Hardware models per effect block, PO-33/EP-133 device rules, regional profiles
(with verification status), and resonance/frequency rules live in
`references/device-domain.md` — read it when a task involves device behaviour,
hardware-era authenticity, or regional DSP parameters.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `03-Code/DSP.md` (frozen V1),
`00-Project/SPECS.md`, `00-Project/EXTENSION_GUIDE.md`,
`03-Code/FM_BLIP_EXPANSION_2026-06-16.md`, `03-Code/CR-F13_REMEDIATION_2026-05-28.md`,
`03-Code/EP133_BUG_SCOPE_2026-05-27.md`, `00-Project/DECISIONS.md` (audio decisions).
Verified against `develop` v0.10.1 (2026-07-05). EXTENSION_GUIDE's `PARAM_RANGES`
does not exist in current code and was dropped from this skill.*
