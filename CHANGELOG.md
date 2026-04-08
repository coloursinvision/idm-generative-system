# Changelog

All notable changes to the IDM Generative System are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.5.2] — 2026-04-08 — Security Patches + V1 Hardening

### Fixed

- **ComposerPanel reasoning rendering** (`frontend/src/components/composer/ComposerPanel.tsx`) — The Reasoning panel never rendered despite the API returning a valid `reasoning` field. Root cause: condition checked `parsed.reasoning` where `parsed = data.config` (the inner config object containing `generator`, `generator_params`, and `chain_overrides`). The `reasoning` field is a top-level property of `ComposeResponse`. Condition and render expression corrected to `result.reasoning`. Resolves GUI_TEST_SPECIFICATION.md T-03.3.

- **Playwright webkit clipboard skip** (`frontend/e2e/codegen.spec.ts`) — T-08.6 (COPY button clipboard test) skipped on Firefox only. WebKit Playwright context also does not support `grantPermissions(["clipboard-write"])`. Skip condition extended to `browserName === "firefox" || browserName === "webkit"`.

### Added

- **`.gitignore` — Playwright artefact exclusion** — `frontend/playwright-report/` and `frontend/test-results/` added. Both directories are generated on test run and are not tracked.

- **`.env.example`** — Environment variable template at repo root. Documents all required variables (`OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`) with placeholder values. Safe to commit.

- **`ruff` in `idm` conda environment** — installed via `pip install ruff`. Required for local lint verification before push.

### Security

- **CR-15 — SHA-256 for `_deterministic_id`** (`knowledge/qdrant_client.py`) — `hashlib.md5` replaced with `hashlib.sha256`. Output truncated to 32 hex characters (consistent with prior MD5 output length). MD5 is deprecated for identifier generation in security-conscious contexts. **Re-ingest required:** all existing Qdrant point IDs generated under MD5 are invalid and must be regenerated. Coordinate with Qdrant NULL subsection cleanup — run both in one pass.

- **CR-17 — Union/Optional type hint handling** (`api/main.py`) — `_extract_param_schema()` extended with `_format_type_hint()` helper. Handles `Optional[X]` (rendered as `"X | null"`), `Union[X, Y]`, and plain types. The previous `getattr(__name__)` call produced raw `typing.*` string representations for compound types, rendering the `/effects` self-documentation endpoint response unreadable for Optional parameters.

- **CR-18 — Upload size limit on `/process`** (`api/main.py`) — `MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024` (50 MB) constant added at module level. Enforced in `process_audio()` immediately after `file.read()`, before audio decoding. Returns HTTP 413 with a human-readable detail string (`"File too large (X.X MB). Maximum: 50 MB."`). Prevents unbounded memory allocation from malicious or accidental large file uploads.

- **CR-19 — Explicit environment variable validation** (`knowledge/qdrant_client.py`, `knowledge/rag.py`) — Both modules now raise `OSError` at instantiation time if required environment variables are missing, rather than failing at request time with an obscure connection error.
  - `KnowledgeBase.__init__`: raises if `QDRANT_URL` is unset. The silent fallback to `http://localhost:6333` is removed — explicit configuration is required in all environments.
  - `RAGPipeline.__init__`: raises if `OPENAI_API_KEY` is unset. `OpenAI(api_key=api_key)` called with the explicit key rather than relying on the SDK's implicit environment lookup.
  - `import os` added to `knowledge/rag.py` module-level imports.

### CI

- **CI failures resolved** — First push of CR-15/CR-19 failed on `ruff check` (rule UP024: `EnvironmentError` is an aliased builtin; `OSError` required). Second push failed on `ruff format --check` (`api/main.py`, `knowledge/rag.py` formatting non-conformant after patch). Both resolved. Third push: all jobs green (Lint & Format, Type Check, Test Suite, Docker, E2E).

---

## [0.5.1] — 2026-04-07 — Playwright E2E Test Suite

### Added
- **Playwright E2E test suite** (`frontend/e2e/`) — 56 browser-level tests across 9 spec files covering all 7 tabs, codegen popout window, error states, and console audit. Tests run against Vite dev server with mocked API routes (zero backend dependency).
  - `fixtures.ts` — shared test fixture with auto-mocking (`mockApi`), deterministic API response payloads matching exact backend response shapes (`EffectBlock[]`, `CodegenResponse`, `AskResponse`, etc.), minimal WAV binary generator, and page helpers (`navigateToTab`, `getCodeBlockText`, `collectConsoleErrors`).
  - `navigation.spec.ts` — 7 tests: app shell render, 7-tab navigation, routing, active indicator, responsive layout, StatusBar health, default redirect.
  - `advisor.spec.ts` — 4 tests: input render, typing, submit→answer+sources, content validation.
  - `composer.spec.ts` — 3 tests: input render, submit→JSON config, sources display.
  - `effects.spec.ts` — 3 tests: 10-block display, signal chain order, parameter expansion.
  - `generator.spec.ts` — 5 tests: controls render, waveform display, play/download buttons, WAV file save.
  - `guides.spec.ts` — 7 tests: PO-33 sequencer grid + step toggle + play + BPM, EP-133 group layout + pad interaction + play.
  - `codegen.spec.ts` — 20 tests: SC/TIDAL generation flow, solarized dark background, COPY/DOWNLOAD, toolbar labels, config drawer (expand/collapse/summary/mode), popout route + standalone generate.
  - `error-states.spec.ts` — 7 tests: backend failure handling (advisor/codegen/generator), unhandled rejection check, console error audit across all tabs, rapid navigation stability, codegen flow pageerror check.

- **CI pipeline** (`.github/workflows/e2e.yml`) — GitHub Actions job: checkout → Node 24 → `npm ci` → Playwright browser install (Chromium + Firefox) → `npm run e2e` → report/trace upload. 112 tests (56×2 browsers), 15-minute timeout, retry 2 on CI.

- **package.json scripts** — `"e2e": "playwright test"` and `"e2e:install": "playwright install"` added for CI-safe binary resolution (avoids `npx` downloading standalone Playwright outside project `node_modules`).

### Fixed
- **E2E mock data shape** — `EFFECTS_RESPONSE` rebuilt to match `EffectBlock` interface (`key`, `class_name`, `position`, `params: { name: { type, default } }`, `docstring`). Previous mock caused EffectsExplorer crash on `block.class_name === undefined`.
- **Firefox clipboard test** — `test.skip(browserName === "firefox")` on T-08.6 (clipboard permissions not supported in Firefox Playwright context).
- **Firefox responsive tolerance** — scrollbar width varies across browsers; overflow check tolerance increased from 1px to 10px.

### Discovered
- **ComposerPanel reasoning bug** — `ComposerPanel.tsx` checks `parsed.reasoning` (inside `data.config` object) instead of `result.reasoning` (top-level response field). Reasoning section never renders. Fixed in v0.5.2.

---

## [0.5.0] — 2026-04-06 — Frontend Codegen Panel (SC / TidalCycles)

### Added
- **Codegen panel** (`frontend/src/components/codegen/`) — 7th tab in the React frontend for generating and exporting SuperCollider (sclang) and TidalCycles (Haskell DSL) code from engine configurations.
  - `CodegenPanel.tsx` — docked tab with SC|TIDAL target tabs, collapsible CONFIG drawer (generator, mode, BPM, effects chain toggles), popout window management via `⧉` button. 3-click live flow: target → GENERATE → COPY.
  - `CodegenPopout.tsx` — standalone detached window for dual-monitor live performance workflows. Receives state from main app via BroadcastChannel, falls back to local config when opened standalone (graceful degradation).
  - `CodeBlock.tsx` — production code display with solarized dark background (#002b36), dual syntax highlighting (sclang keywords/UGens + Haskell/Tidal functions/operators), line numbers, copy to clipboard, and download as `.scd`/`.tidal`.
  - `useBroadcastChannel.ts` — generic typed React hook for inter-window communication via native BroadcastChannel API. Heartbeat mechanism (2s interval, 5s timeout) for connection status tracking.

- **API client helpers** (`frontend/src/api/codegen.ts`) — `postSynthdef()` and `postTidal()` with typed error handling: FastAPI HTTPException detail extraction, Pydantic validation error array joining, and network failure wrapping. Uses `/api` proxy consistent with existing `client.ts`.

- **TypeScript types** (`frontend/src/types/codegen.ts`) — `CodegenRequest`, `CodegenResponse`, `PatternConfig` (tagged union: euclidean/probabilistic/density), `CodegenTarget`, `CodegenMode`, `CodegenBroadcastMessage`. Full contract mirror of FastAPI Pydantic models.

- **Frontend test infrastructure** — Vitest + React Testing Library + jsdom added to the project.
  - `vite.config.ts` — test configuration block added (globals, jsdom environment, setup file).
  - `tests/setup.ts` — global jest-dom matcher import.
  - `tests/codegen/codegen.test.tsx` — **48 unit tests** across 6 sections: Type contracts (6), API helpers (6), useBroadcastChannel hook (9), CodeBlock rendering (8), CodegenPanel flow (12), CodegenPopout sync (7). All passing.

- **Navigation** — CODEGEN tab added to NavBar. Routes `/codegen` and `/codegen-popout` registered in App.tsx.

### Changed
- `frontend/src/types/index.ts` — re-exports codegen types.
- `frontend/src/api/client.ts` — re-exports `postSynthdef`, `postTidal`.
- `frontend/src/App.tsx` — CodegenPanel and CodegenPopout routes added.
- `frontend/src/components/layout/NavBar.tsx` — CODEGEN tab added after EP-133.
- `frontend/package.json` — `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` added as dev dependencies. `test` and `test:watch` scripts added.
- `frontend/vite.config.ts` — Vitest test configuration added.

### Design Decisions
- **Layout v4 (live-ready)** — informed by UX research on Sonic Pi, Ableton Live Control Bar, and Ableton UX redesign study. Live performance requires minimal visible controls; config is set once then hidden. SC|TIDAL tabs + GENERATE button are the only always-visible interactive elements.
- **Solarized dark code blocks** — overrides UX_UI_ALIGNMENT.md §2 (which specified light background #e4e4e7). Night-use studio environments require dark code blocks. Solarized base03 (#002b36) with TE orange keywords, project amber strings, solarized cyan numbers, solarized magenta UGens/functions.
- **Popout window via BroadcastChannel** — follows Ableton Live `Shift+Cmd+W` and Chrome DevTools undock conventions. Zero server involvement, same-origin native API.
- **Label precision** — toggle buttons use short `SC | TIDAL`, code block toolbar shows precise `SCLANG .SCD` / `HASKELL / TIDAL .TIDAL`.

### Resolved from v0.4.0
- "Not Yet Implemented: Frontend code display panels" — **fully implemented** in this release.

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

---

## [0.3.0] — 2026-04-02 — Infrastructure & CI Pipeline (Phase 5)

### Added
- **pyproject.toml** — single source of truth for project metadata, dependencies, and tool configuration. Replaces scattered `setup.py`, `requirements.txt`, and individual tool configs. Includes: `[project]` metadata, `[tool.ruff]` lint + format rules, `[tool.mypy]` strict config with per-module overrides, `[tool.pytest.ini_options]`.
- **Dockerfile** — multi-stage build targeting Digital Ocean App Platform. Stage 1: full build with `numba` pre-compilation (AOT cache warm). Stage 2: slim runtime image (`python:3.11-slim`), copies only `__pycache__` for Numba kernels + application code. Exposes port 8000, runs via `uvicorn`.
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — 4-job pipeline: Lint & Format (ruff), Type Check (mypy strict), Test Suite (pytest 209 cases), Docker Build (multi-stage verify). Runs on push/PR to `develop` and `main`.
- **Pre-commit hooks** (`.pre-commit-config.yaml`) — ruff lint + format, mypy type check, gitleaks secret scanning, commitizen conventional commit format.
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

- **Parameter validation** across 8 configurable effect blocks (10 string parameters). Invalid values now raise `ValueError` with the list of valid options instead of falling back to defaults silently. (CR-05)
- **Chain key validation** — unrecognised `chain_overrides` or `chain_skip` keys in `/generate` and `/process` return HTTP 400 with the valid key set. (CR-11)
- **RAG pipeline single-search** — `_retrieve_context()` returns both the assembled context string and raw search results in a single call. Eliminates a redundant embedding + Qdrant query per request. (CR-02)
- **Composer output validation** — `compose()` parses and validates GPT-4o JSON output via `_parse_compose_output()`. Strips markdown code fences, verifies required keys, returns a parsed dict instead of a raw string. (CR-14)
- **Numba JIT on DSP hot paths** — 5 per-sample Python loops extracted to module-level `@njit(cache=True)` functions. Targets: reverb comb filter bank, reverb allpass diffusor chain, tape delay line, and compressor envelope followers (single + auto-release). (CR-04)
- **Compressor RMS envelope** — `_compute_rms_envelope()` per-sample loop replaced with vectorised NumPy index arrays. (CR-04)

### Added

- **DSP effects test suite** (`tests/test_effects.py`) — 166 test cases across 14 classes.
- **RAG endpoint test suite** (`tests/test_rag.py`) — 20 test cases with mocked OpenAI and Qdrant dependencies.
- **Retry logic** on all external API calls via `tenacity`. Retries up to 3 times with exponential backoff on transient errors. (CR-06)
- `tenacity` added to `requirements.txt` and `environment.yml`.
- `numba` >=0.59 added to `environment.yml` (conda channel).
- Total test coverage: **209 cases** (208 passed, 1 skipped).

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
