# Changelog

All notable changes to the IDM Generative System are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.4.0] — 2026-04-03 — SuperCollider + TidalCycles Code Generation

### Added
- **Code generation module** (`engine/codegen/`) — generates runnable SuperCollider and TidalCycles code from engine configurations. Pure string transforms, no new dependencies.
  - `mappings.py` — central parameter translation layer mapping all ~80 engine parameters to SC and Tidal equivalents with named value transform functions. Zero silent parameter drops: every param is mapped or explicitly documented as unmappable. `validate_mapping_completeness()` enforces this via test.
  - `base.py` — `BaseCodegen` abstract class, `CodegenInput`/`CodegenResult`/`CodegenOptions` dataclasses, `CodegenMode` StrEnum (studio/live).
  - `synthdef.py` — SuperCollider codegen: composable SynthDefs (3 generators, 10 effects) with private bus routing (`In.ar`/`ReplaceOut.ar`), Group-based execution ordering (`genGroup` → `fxGroup` with `addToTail`), Pbind (studio) / Pdef (live) pattern output.
  - `tidal.py` — TidalCycles codegen: native Euclidean `e(k,n)` syntax, `degradeBy` for probabilistic patterns, `stack []` for multi-track, full effects mapping (`# room`, `# crush`, `# lpf`, `# delay`, `# distort`, `# pan`, etc.).
  - `__init__.py` — public API with `generate_synthdef()` and `generate_tidal()` convenience functions.

- **API endpoints** — two new FastAPI routes for code generation.
  - `POST /synthdef` — generates SuperCollider (.scd) code. Returns structured `CodegenResponse` with code, warnings, unmapped parameters, metadata (SynthDef names, bus allocation, effects chain), and setup notes.
  - `POST /tidal` — generates TidalCycles (Haskell DSL) code. Returns structured `CodegenResponse` with code, warnings, metadata (Tidal sound name, orbit assignments, BPM), and setup notes.
  - Shared `CodegenRequest` model: generator, generator_params, effects, pattern, mode (studio/live), include_pattern, bpm, bus_offset.
  - Shared `CodegenResponse` model: code, target, mode, warnings, unmapped_params, metadata, setup_notes.

- **Studio / Live modes** — two generation modes for different workflows.
  - Studio: self-contained script with server boot, full comments, cleanup. Copy-paste-evaluate.
  - Live: minimal boilerplate, hot-swap via Pdef/Ndef (SC) or bare d1 (Tidal). Assumes server running.

- **Test suite expansion** — 109 new tests (69 unit + 40 integration).
  - `tests/test_codegen.py` — mapping completeness, value transforms, SC/Tidal output validation, mode switching, edge cases.
  - `tests/test_codegen_api.py` — FastAPI TestClient integration tests for `/synthdef` and `/tidal` endpoints (schema, all generators, effects chain order, error handling, cross-endpoint consistency).
  - Total suite: **318 cases** (317 passed, 1 skipped).

### Changed
- `api/main.py` — added codegen imports, `CodegenRequest`/`CodegenResponse` Pydantic models, two endpoints, `_codegen_result_to_response()` helper. No modifications to existing endpoints or models.

### Not Yet Implemented
- Frontend code display panels for SuperCollider and TidalCycles output. API contract (`CodegenResponse`) is ready; frontend work (collapsible code panel, syntax highlighting, copy-to-clipboard, studio/live toggle) deferred to next session.

---

## [0.3.0] — 2026-04-02 — Infrastructure & CI Pipeline (Phase 5)

### Added
- **pyproject.toml** — single source of truth for project metadata, dependencies (core + dev/ml/monitoring/streamlit extras), and all tool configurations (ruff, mypy, pytest, coverage).
- **Dockerfile** — multi-stage production build (Python 3.11-slim). Builder stage compiles native extensions; runtime stage runs as unprivileged user with healthcheck. Numba kernels pre-compiled during build. Target: Digital Ocean App Platform.
- **GitHub Actions CI pipeline** (`.github/workflows/ci.yml`) — gitflow-aware: `develop` runs lint → typecheck → test → Docker build; `main` adds GHCR push; hotfix branches run lint → typecheck → test.
- **Pre-commit hooks** (`.pre-commit-config.yaml`) — ruff lint+format, mypy, trailing whitespace, gitleaks (secrets detection), commitizen (conventional commits).
- `.env.example` — environment variable template for onboarding.
- `.dockerignore` — lean Docker build context.
- `api/__init__.py` — `__version__` from `importlib.metadata`, reads version from pyproject.toml (CR-16). `__all__` defined (CR-20).
- `knowledge/__init__.py` — `__all__` with `KnowledgeBase`, `RAGPipeline` exports (CR-20).

### Changed
- **requirements.txt** — cleaned, synchronised with pyproject.toml. Exists only for Streamlit Cloud deployment.
- **22 Python files** — ruff lint fixes (import sorting, `raise...from`, unused vars, `contextlib.suppress`) + ruff format applied.
- **engine/generator.py** — lazy import `matplotlib.pyplot` (moved into `plot_pattern()`). Prevents import failure in environments without matplotlib.
- **knowledge/qdrant_client.py** — `zip(..., strict=True)` on chunk/embedding pairing. Payload `None` guard on search results.
- **streamlit_app/app.py** — `contextlib.suppress` replacing try/except/pass in secrets bridge.

### Fixed
- **mypy strict** — project-wide strict type checking with pragmatic per-module relaxation for DSP/NumPy code. Third-party stub ignores for numba, scipy, qdrant_client, soundfile, pandas, matplotlib.
- **pandas** added to core dependencies — required by `engine/generator.py` at import time.

### Infrastructure
- **Gitflow adopted** — `develop` for active work, `main` for releases only, `hotfix/*` for emergency patches.
- **CI status** — all 4 jobs passing: Lint & Format, Type Check (mypy), Test Suite (208/209, 1 pre-existing skip), Docker Build.

---

## [0.2.2] — 2026-04-02

Critical bug fix release. All five bugs trace to a single root cause: CR-14 (2026-04-01) changed the return type of `rag.compose()` from JSON string to parsed dict, but the change was not propagated to the three downstream consumers (Streamlit, React frontend, FastAPI docstring). A secondary environment-loading order bug prevented the FastAPI backend from connecting to Qdrant Cloud.

### Fixed

- **[CRITICAL] Streamlit Composer TypeError** — removed `json.loads()` call on already-parsed dict in `streamlit_app/app.py`. Added `ValueError`/`Exception` handling around `rag.compose()` with `st.error()` + `st.stop()` for graceful UI feedback. (BUG-01)
- **GPT-4o JSON extraction hardening** — replaced naive `startswith("```")` fence stripping in `rag.py:_parse_compose_output()` with regex fence extraction (`re.search`) and brace-pair fallback (`find("{")` / `rfind("}")`). Handles preamble text before fences, missing fences, and other LLM output edge cases. (BUG-02)
- **React Composer crash** — removed `JSON.parse(data.config)` in `ComposerPanel.tsx` (config is already a parsed object since v0.2.1 CR-14). Fallback render uses `JSON.stringify` for safety. Updated `ComposeResponse.config` type from `string` to `Record<string, unknown>` in `types/index.ts`. (BUG-03)
- **FastAPI Qdrant connection refused** — `QDRANT_URL` module-level constant in `qdrant_client.py` evaluated at import time before `.env` was loaded, always falling back to `localhost:6333`. Added `load_dotenv()` before knowledge module imports in `api/main.py`. (BUG-04)
- **`/compose` docstring** — corrected return type description from "JSON string" to "parsed dict". (BUG-05)

### Maintenance

- **Rollup native module** — regenerated `frontend/package-lock.json` and `node_modules` to resolve `@rollup/rollup-linux-x64-gnu` missing module error (npm optional dependency bug).
- `import re` added to `knowledge/rag.py` module-level imports (stdlib, no new external dependency).

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
