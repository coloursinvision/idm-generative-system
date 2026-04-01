# Changelog

All notable changes to the IDM Generative System are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.1] — 2026-04-01

### Fixed

- **Reverb colour parameter** — `_apply_colour` filter direction was inverted relative to the public API contract. `colour > 0` now correctly applies high-pass (brighter tail) and `colour < 0` applies low-pass (darker tail), matching the Quadraverb front panel convention.
- **Tail padding in `/process`** — uploaded audio processed through the effects chain was missing the 2-second zero-pad buffer required for reverb and delay tails to decay naturally. Extracted shared `_process_through_chain()` used by both `/generate` and `/process`, enforcing consistent behaviour across endpoints.
- **Duplicate `CORSMiddleware` import** in `api/main.py`.
- **Inline `import json`** in `process_audio()` moved to module-level imports.

### Changed

- **Parameter validation** across all 8 configurable effect blocks. Invalid string parameters (`noise_type`, `filter_type`, `mode`, `reverb_type`, `tape_age`, `xor_mode`, `vinyl_condition`, `dat_mode`, `hardware_preset`) now raise `ValueError` with a list of valid options instead of falling back to defaults silently.
- **Chain key validation** in `/generate` and `/process` — unrecognised `chain_overrides` or `chain_skip` keys return HTTP 400 with the valid key set.
- **RAG pipeline** — `_retrieve_context()` returns both the assembled context string and raw search results in a single call. Eliminates a redundant embedding + Qdrant query that was duplicated in `ask()` and `compose()`.
- **Composer output validation** — `compose()` now parses and validates the JSON configuration returned by GPT-4o. Strips markdown code fences, verifies required keys (`generator`, `generator_params`, `chain_overrides`), and returns a parsed dict instead of a raw string.
- **RNG modernisation** in `sample_maker.py` — replaced deprecated `np.random.seed()` with `np.random.default_rng()`. Added optional `rng: np.random.Generator` parameter to `glitch_click()` and `noise_burst()` for thread-safe, fully reproducible generation. `batch_export()` propagates a single generator instance through all calls.
- **Test suite** — `test_process_bypass_chain_signal_unchanged` updated to verify that processed output is longer than bypassed output (confirming tail padding is active).

### Added

- **Retry logic** on all external API calls via `tenacity`. `RAGPipeline._complete()` and `KnowledgeBase.embed()` retry up to 3 times with exponential backoff (1s → 2s → 4s) on `RateLimitError`, `APITimeoutError`, and `APIConnectionError`.
- `tenacity` added to `requirements.txt`.

---

## [0.2.0] — 2026-03-26

### Added

- 10-block DSP effects chain with `BaseEffect` abstract class and `EffectChain` pipeline.
- Signal chain: NoiseFloor → Bitcrusher → ResonantFilter → Saturation → Reverb → TapeDelay → SpatialProcessor → GlitchEngine → Compressor → VinylMastering.
- FastAPI backend with 6 endpoints: `/health`, `/effects`, `/generate`, `/process`, `/ask`, `/compose`.
- RAG pipeline: Qdrant Cloud (43 chunks, text-embedding-3-large) + GPT-4o.
- React 18 + Vite + TypeScript frontend with 6 tabs.
- 23 pytest end-to-end tests.
- 2-second tail padding for reverb/delay decay in `/generate`.
- 24-bit WAV export via soundfile.
- Web Audio API step sequencer for PO-33 and EP-133 guide tabs.
