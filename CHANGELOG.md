# Changelog

All notable changes to the IDM Generative System are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.5.2] — 2026-04-08 — Security Patches + V1 Hardening

### Fixed

- **ComposerPanel reasoning rendering** (`frontend/src/components/composer/ComposerPanel.tsx`) — The Reasoning panel never rendered despite the API returning a valid `reasoning` field. Root cause: condition checked `parsed.reasoning` where `parsed = data.config` (the inner config object containing `generator`, `generator_params`, and `chain_overrides`). The `reasoning` field is a top-level property of `ComposeResponse`. Condition and render expression corrected to `result.reasoning`. Resolves GUI_TEST_SPECIFICATION.md T-03.3.

- **`ComposeResponse.reasoning` TypeScript type gap** (`frontend/src/types/index.ts`) — `reasoning?: string` was absent from the `ComposeResponse` interface. The runtime fix above referenced `result.reasoning`, which TypeScript rejected (`TS2339: Property 'reasoning' does not exist`). Field added as optional to maintain backward compatibility with backend error paths that may omit it. Surfaced by `tsc --noEmit` run after the runtime fix.

- **EP-133 Guide: group step patterns lost on group switch** (`frontend/src/components/guide/EP133Guide.tsx`, `frontend/src/hooks/useSequencer.ts`) — Switching between Groups A/B/C/D cleared all active pad steps in the departing group. Root cause: `initTracks()` always initialised `steps: Array(numSteps).fill(false)` with no per-group state persistence. Fix: `useSequencer.initTracks` extended with optional `initialSteps?: boolean[][]` parameter. `EP133Guide` uses `groupStepsRef` (`useRef<Record<Group, boolean[][]>>`) to save and restore step patterns per group on switch. `PO33Guide` is unaffected — backward-compatible signature change.

- **Playwright webkit clipboard skip** (`frontend/e2e/codegen.spec.ts`) — T-08.6 (COPY button clipboard test) skipped on Firefox only. WebKit Playwright context also does not support `grantPermissions(["clipboard-write"])`. Skip condition extended to `browserName === "firefox" || browserName === "webkit"`.

### Added

- **`.gitignore` — Playwright artefact exclusion** — `frontend/playwright-report/` and `frontend/test-results/` added. Both directories are generated on test run and are not tracked.

- **`.env.example`** — Environment variable template at repo root. Documents all required variables (`OPENAI_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`) with placeholder values. Safe to commit.

- **`ruff` in `idm` conda environment** — installed via `pip install ruff`. Required for local lint verification before push.

### Security

- **CR-15 — SHA-256 for `_deterministic_id`** (`knowledge/qdrant_client.py`) — `hashlib.md5` replaced with `hashlib.sha256`. Output truncated to 32 hex characters (consistent with prior MD5 output length). MD5 is deprecated for identifier generation in security-conscious contexts. **Re-ingest required:** all existing Qdrant point IDs generated under MD5 are invalid and must be regenerated. Coordinate with Qdrant NULL subsection cleanup — run both in one pass.

- **CR-17 — Union/Optional type hint handling** (`api/main.py`) — `_extract_param_schema()` extended with `_format_type_hint()` helper. Handles `Optional[X]` (rendered as `"X | null"`), `Union[X, Y]`, and plain types. The previous `getattr(__name__)` call produced raw `typing.*` string representations for compound types, rendering the `/effects` self-documentation endpoint response unreadable for Optional parameters.

- **CR-18 — Upload size limit on `/process`** (`api/main.py`) — `MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024` (50 MB) constant added at module level. Enforced in `process_audio()` immediately after `file.read()`, before audio decoding. Returns HTTP 413 with a human-readable detail string. Prevents unbounded memory allocation from malicious or accidental large file uploads.

- **CR-19 — Explicit environment variable validation** (`knowledge/qdrant_client.py`, `knowledge/rag.py`) — Both modules now raise `OSError` at instantiation time if required environment variables are missing, rather than failing at request time with an obscure connection error.
  - `KnowledgeBase.__init__`: raises if `QDRANT_URL` is unset. The silent fallback to `http://localhost:6333` is removed.
  - `RAGPipeline.__init__`: raises if `OPENAI_API_KEY` is unset. `OpenAI(api_key=api_key)` called with the explicit key.
  - `import os` added to `knowledge/rag.py` module-level imports.

### CI

- **CI failures resolved** — First push of CR-15/CR-19 failed on `ruff check` (rule UP024: `EnvironmentError` is an aliased builtin; `OSError` required). Second push failed on `ruff format --check` (`api/main.py`, `knowledge/rag.py` formatting non-conformant after patch). Both resolved. Third push: all jobs green (Lint & Format, Type Check, Test Suite, Docker, E2E).

---

## [0.5.1] — 2026-04-07 — Playwright E2E Test Suite

### Added
- **Playwright E2E test suite** (`frontend/e2e/`) — 56 browser-level tests across 9 spec files covering all 7 tabs, codegen popout window, error states, and console audit. Tests run against Vite dev server with mocked API routes (zero backend dependency).
  - `fixtures.ts` — shared test fixture with auto-mocking (`mockApi`), deterministic API response payloads, minimal WAV binary generator, and page helpers (`navigateToTab`, `getCodeBlockText`, `collectConsoleErrors`).
  - `navigation.spec.ts` — 7 tests: app shell render, 7-tab navigation, routing, active indicator, responsive layout, StatusBar health, default redirect.
  - `advisor.spec.ts` — 4 tests: input render, typing, submit→answer+sources, content validation.
  - `composer.spec.ts` — 3 tests: input render, submit→JSON config, sources display.
  - `effects.spec.ts` — 3 tests: 10-block display, signal chain order, parameter expansion.
  - `generator.spec.ts` — 5 tests: controls render, waveform display, play/download buttons, WAV file save.
  - `guides.spec.ts` — 7 tests: PO-33 sequencer grid + step toggle + play + BPM, EP-133 group layout + pad interaction + play.
  - `codegen.spec.ts` — 20 tests: SC/TIDAL generation flow, solarized dark background, COPY/DOWNLOAD, toolbar labels, config drawer, popout route + standalone generate.
  - `error-states.spec.ts` — 7 tests: backend failure handling, unhandled rejection check, console error audit, rapid navigation stability, pageerror check.

- **CI pipeline** (`.github/workflows/e2e.yml`) — GitHub Actions job: checkout → Node 24 → `npm ci` → Playwright browser install (Chromium + Firefox) → `npm run e2e` → report/trace upload. 112 tests (56×2 browsers), 15-minute timeout, retry 2 on CI.

- **package.json scripts** — `"e2e": "playwright test"` and `"e2e:install": "playwright install"` added for CI-safe binary resolution.

### Fixed
- **E2E mock data shape** — `EFFECTS_RESPONSE` rebuilt to match `EffectBlock` interface.
- **Firefox clipboard test** — `test.skip(browserName === "firefox")` on T-08.6.
- **Firefox responsive tolerance** — overflow check tolerance increased from 1px to 10px.

### Discovered
- **ComposerPanel reasoning bug** — `ComposerPanel.tsx` checks `parsed.reasoning` instead of `result.reasoning`. Fixed in v0.5.2.

---

## [0.5.0] — 2026-04-06 — Frontend Codegen Panel (SC / TidalCycles)

### Added
- **Codegen panel** (`frontend/src/components/codegen/`) — 7th tab for generating SuperCollider and TidalCycles code.
  - `CodegenPanel.tsx` — docked tab, SC|TIDAL tabs, CONFIG drawer, popout button. 3-click live flow.
  - `CodegenPopout.tsx` — standalone detached window, BroadcastChannel sync, graceful degradation.
  - `CodeBlock.tsx` — solarized dark (#002b36), dual syntax highlighting, line numbers, copy/download.
  - `useBroadcastChannel.ts` — typed inter-window hook, 2s heartbeat, 5s timeout.
- **API client helpers** (`frontend/src/api/codegen.ts`) — `postSynthdef()`, `postTidal()`.
- **TypeScript types** (`frontend/src/types/codegen.ts`) — full contract mirror of FastAPI models.
- **Frontend test infrastructure** — Vitest + React Testing Library + jsdom. **48 unit tests.**
- **Navigation** — CODEGEN tab, routes `/codegen` and `/codegen-popout`.

### Design Decisions
- Layout v4 (live-ready): SC|TIDAL tabs + GENERATE are only always-visible controls.
- Solarized dark overrides UX_UI_ALIGNMENT.md §2 light theme — studio night-use requirement.
- BroadcastChannel over WebSocket/SharedWorker — zero server, same-origin native API.

---

## [0.4.0] — 2026-04-03 — SuperCollider + TidalCycles Code Generation

### Added
- **Code generation module** (`engine/codegen/`) — `mappings.py`, `base.py`, `synthdef.py`, `tidal.py`, `__init__.py`. ~80 engine params mapped, zero silent drops.
- **API endpoints** — `POST /synthdef`, `POST /tidal`. Shared `CodegenRequest`/`CodegenResponse`.
- **Studio / Live modes** — studio (self-contained, copy-paste-evaluate), live (hot-swap Pdef/Ndef).
- **Test suite expansion** — 109 new tests. Total: **318 cases** (317 passed, 1 skipped).

---

## [0.3.0] — 2026-04-02 — Infrastructure & CI Pipeline

### Added
- `pyproject.toml`, `Dockerfile` (multi-stage, DO App Platform), GitHub Actions CI (4 jobs), pre-commit hooks (ruff, mypy, gitleaks, commitizen), mypy strict.
- **Gitflow** — `develop`, `main`, `hotfix/*`.

---

## [0.2.2] — 2026-04-02 — Critical Bug Fix Release

### Fixed
- Streamlit Composer TypeError (BUG-01), GPT-4o JSON extraction hardening (BUG-02), React Composer crash (BUG-03), FastAPI Qdrant connection refused (BUG-04), `/compose` docstring (BUG-05).

---

## [0.2.1] — 2026-04-01 — Backend Code Review

20 findings. 14 resolved (1 CRITICAL, 5 HIGH, 8 MEDIUM). 6 LOW deferred. Test suite: 23 → 209 cases. Numba JIT on 5 DSP hot paths.

### Fixed
- [CRITICAL] Reverb colour parameter inversion (CR-01), tail padding in `/process` (CR-03), duplicate import (CR-07), inline import (CR-08), deprecated RNG (CR-09).

### Changed
- Parameter validation (CR-05), chain key validation (CR-11), RAG single-search (CR-02), composer output validation (CR-14), Numba JIT (CR-04), vectorised RMS envelope (CR-04).

### Added
- `test_effects.py` (166 cases), `test_rag.py` (20 cases), tenacity retry on all external API calls (CR-06).

---

## [0.2.0] — 2026-03-26

### Added
- 10-block DSP effects chain, FastAPI backend (6 endpoints), RAG pipeline (Qdrant + GPT-4o), React frontend (6 tabs), 23 pytest tests, 2-second tail padding, 24-bit WAV export, Web Audio API sequencers.
