# Changelog

All notable changes to the IDM Generative System are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.1] — 2026-04-01

Full backend code review and 4-phase implementation cycle. 20 findings identified across `engine/`, `api/`, `knowledge/`, and `tests/`. 14 findings resolved (1 CRITICAL, 5 HIGH, 8 MEDIUM). 6 LOW findings deferred. Test suite expanded from 23 to 209 cases. DSP hot paths compiled to native LLVM via Numba.

### Methodology

The review covered every Python file in the backend (excluding `acid_*.py` and `AcidSynthEngine.cpp`, deferred by owner). Code was verified against DECISIONS.md, PROJECT_ARCHITECTURE.md, and the prior session log for documentation–implementation consistency. Findings were rated by severity (CRITICAL / HIGH / MEDIUM / LOW) and implemented in four phases: correctness, validation, testing, and performance.

Validation toolchain: pytest 9.0.2 for test execution, FastAPI TestClient for in-process HTTP testing, `unittest.mock` for OpenAI and Qdrant dependency isolation, Python AST parser (3.11.15) for syntax verification of all modified files, and `git diff --stat` for change auditing. All 19 modified files passed AST validation before deployment.

### Fixed

- **[CRITICAL] Reverb colour parameter** — `_apply_colour` filter direction was inverted relative to the public API contract. `colour > 0` now correctly applies high-pass (brighter tail) and `colour < 0` applies low-pass (darker tail), matching the Quadraverb front panel convention. (`engine/effects/reverb.py`, CR-01)
- **Tail padding in `/process`** — uploaded audio processed through the effects chain was missing the 2-second zero-pad buffer required for reverb and delay tails to decay naturally. Extracted shared `_process_through_chain()` used by both `/generate` and `/process`, enforcing the 2026-03-26 architectural decision. (`api/main.py`, CR-03)
- **Duplicate `CORSMiddleware` import** in `api/main.py`. (CR-07)
- **Inline `import json`** in `process_audio()` moved to module-level imports. (CR-08)
- **Deprecated RNG** in `sample_maker.py` — `np.random.seed()` replaced with `np.random.default_rng()`. New `rng` parameter added to `glitch_click()` and `noise_burst()` for thread-safe, reproducible generation. Full propagation through `batch_export()`. (CR-09)

### Changed

- **Parameter validation** across 8 configurable effect blocks (10 string parameters: `noise_type`, `filter_type`, `mode`, `reverb_type`, `tape_age`, `xor_mode`, `vinyl_condition`, `dat_mode`, `hardware_preset`, `mode`). Invalid values now raise `ValueError` with the list of valid options instead of falling back to defaults silently. (CR-05)
- **Chain key validation** — unrecognised `chain_overrides` or `chain_skip` keys in `/generate` and `/process` return HTTP 400 with the valid key set. (CR-11)
- **RAG pipeline single-search** — `_retrieve_context()` returns both the assembled context string and raw search results in a single call. Eliminates a redundant embedding + Qdrant query per request in `ask()` and `compose()`. (CR-02)
- **Composer output validation** — `compose()` parses and validates GPT-4o JSON output via `_parse_compose_output()`. Strips markdown code fences, verifies required keys (`generator`, `generator_params`, `chain_overrides`), returns a parsed dict instead of a raw string. (CR-14)
- **Numba JIT on DSP hot paths** — 5 per-sample Python loops extracted to module-level `@njit(cache=True)` functions, compiled to native LLVM IR via Numba. Targets: reverb comb filter bank (~530k iterations), reverb allpass diffusor chain (~264k iterations), tape delay line (~88k iterations), and compressor envelope followers (single-detector ~88k + dual-detector auto-release ~176k iterations). Iteration counts are for a typical 2.5-second signal at 44.1 kHz. Cache persists to `__pycache__/` to avoid recompilation overhead on subsequent imports. (CR-04)
- **Compressor RMS envelope** — `_compute_rms_envelope()` per-sample loop replaced with vectorised NumPy index arrays (`np.arange`, `np.maximum`), eliminating Python interpreter overhead without adding a Numba dependency. (CR-04)

### Added

- **DSP effects test suite** (`tests/test_effects.py`) — 166 test cases across 14 classes. Original 9 classes (139 cases): shape preservation, mono integrity, dtype checks, edge cases (all-zeros, single sample), NaN/Inf detection, parameter validation, valid parameter construction, stateful block reset, parameter extremes, hardware presets, EffectChain operations, and seeded reproducibility. Phase 4 added 5 regression test classes (28 cases): Numba kernel output parity versus inline pure-Python reference implementations at `rtol=1e-12` tolerance, and vectorised RMS envelope parity.
- **RAG endpoint test suite** (`tests/test_rag.py`) — 20 test cases with mocked OpenAI and Qdrant dependencies: `/ask` and `/compose` integration tests, input validation, single-search verification, JSON output validation, empty context handling, and markdown chunking logic.
- **Test adaptation** — `test_process_bypass_chain_signal_unchanged` updated to verify processed output is longer than bypassed output, confirming tail padding is active.
- **Retry logic** on all external API calls via `tenacity`. `RAGPipeline._complete()` and `KnowledgeBase.embed()` retry up to 3 times with exponential backoff (1s, 2s, 4s) on `RateLimitError`, `APITimeoutError`, and `APIConnectionError`. (CR-06)
- `tenacity` added to `requirements.txt` and `environment.yml`.
- `numba` >=0.59 added to `environment.yml` (conda channel).
- Total test coverage: **209 cases** (208 passed, 1 skipped) — up from 23 at session start.

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
