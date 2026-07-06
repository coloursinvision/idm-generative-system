---
name: idm-architecture
description: >-
  System map of the IDM Generative System (repo coloursinvision/idm-generative-system
  at ~/dev/IDM_Generative_System_app). Use when navigating the codebase, locating a
  module or endpoint, explaining the frontend/backend split, tracing the audio render
  or ML serving path, adding a new API route or frontend tab, or answering "where does
  X live / how do the pieces connect" questions about this project.
---

# IDM Generative System — architecture map

Vite + React 18 + TypeScript SPA over a FastAPI (Python 3.11) backend. The frontend
guides interactive audio sequencing for Teenage Engineering PO-33 and EP-133 devices;
the backend renders audio, generates device code, and serves an ML tuning model.

## Repository layout (top level)

```
api/            FastAPI app — single module api/main.py (routes, schemas, lifespan)
engine/         DSP core: generators, effects chain, codegen, ML subpackage
frontend/       Vite + React SPA (dev server :5173, proxies /api → :8000)
knowledge/      RAG layer: qdrant_client.py (vector search), rag.py (OpenAI calls)
tests/          Backend pytest suite (repo root, fixtures in conftest.py)
scripts/        Operational scripts incl. run-with-env.sh (credential wrapper)
secrets/        SOPS-encrypted credentials (app.enc.yaml) — never plaintext
models/         Trained-model artefacts and metrics (DVC-tracked)
data/           Generated datasets (DVC-tracked)
docs/           User-facing docs served/shipped with the app
notebooks/      Exploration notebooks (not part of the app)
streamlit_app/  Legacy Streamlit UI (superseded by frontend/, kept for reference)
```

## Frontend ↔ backend contract

- **Dev:** `npm run dev` on `localhost:5173`; Vite proxies `/api/*` to
  `localhost:8000`. Backend must be booted through `./scripts/run-with-env.sh`.
- **Prod:** FastAPI serves the built SPA via `StaticFiles` (a catch-all
  `GET /{full_path:path}` route registered last in `api/main.py`); nginx in front
  strips the `/api` prefix before FastAPI sees the path.
- **Audio I/O contract:** all API audio in/out is **24-bit WAV @ 44.1 kHz**
  (`soundfile`, `subtype="PCM_24"` — see `_wav_response` around `api/main.py:465`
  and `engine/sample_maker.py` `write_wav`). The legacy `engine/acid_engine_v2.py`
  renders 16-bit PCM, but only for dataset validation — it is NOT the export path.
  Do not conflate the two.

## Frontend structure

8 tabs, defined in `frontend/src/components/layout/NavBar.tsx`:
ADVISOR, COMPOSER, EFFECTS, GENERATOR, PO-33, EP-133, CODEGEN, TUNING.

- Components live in `frontend/src/components/<area>/`; API clients in
  `frontend/src/api/`; shared types in `frontend/src/types/`.
- Audio sequencing hooks: `frontend/src/hooks/useSequencer.ts` (PO-33, single
  pattern) and `useEP133Sequencer.ts` (EP-133, 4 groups on one master clock).
  Their AudioContext lifecycle handling is deliberately duplicated (known debt,
  tracked for a shared util) — do not "fix" one side only.
- Tests live in the central tree `frontend/src/tests/<module>/`, never co-located.

## Backend surface (`api/main.py`)

| Route | Purpose |
|---|---|
| `GET /health` | liveness + version (version read via `importlib.metadata`) |
| `GET /effects` | effects-chain catalogue |
| `POST /generate` | render a sample (generator + effects) → 24-bit WAV |
| `POST /process` | apply effects chain to an uploaded WAV |
| `POST /synthdef` | SuperCollider SynthDef code generation |
| `POST /tidal` | TidalCycles code generation |
| `POST /ask` | RAG Q&A over the knowledge base (Qdrant + OpenAI) |
| `POST /compose` | RAG-driven composition guidance |
| `POST /tuning` | ML tuning-profile estimation — **conditionally registered** |
| `POST /tuning/extract` | derive tuning request fields from audio |
| `GET /{full_path:path}` | SPA static catch-all (registered last) |

External services wired in the backend: Qdrant (vector search), OpenAI
(generation + embeddings), Langfuse (tracing), MLflow (model registry).

## Generators — availability differs per endpoint

Four generators exist in `engine/sample_maker.py`: `glitch_click`, `noise_burst`,
`fm_blip`, `fm_analog`.

- `/generate` supports **all four**.
- `/synthdef` and `/tidal` (codegen) support **only the first three** — `fm_analog`
  is renderer-only by design (its SuperCollider/codegen stage is deferred work,
  not an omission). Do not add it to codegen enumerations without implementing
  the mapping in `engine/codegen/`.
- `fm_analog` delivers a raw voice: the effects chain is not its default path
  (callers pass `bypass_chain: true`).

## Graceful-degradation patterns (load-bearing — preserve when editing)

1. **`engine/ml/__init__.py` lazy-import flag `_HAS_ML_EXTRAS`:** the package
   imports cleanly with or without the `[ml]` pip extras. CI installs `[dev]`
   only, so any top-level import of sklearn/mlflow/etc. in `engine/ml` breaks CI.
   New ML code must go behind this flag.
2. **`api/main.py` flag `_HAS_MLFLOW` + fail-soft lifespan:** the `/tuning` route
   is registered only when mlflow imports; the lifespan loads the model once at
   startup and logs a WARNING (leaving `/tuning` unavailable) instead of crashing
   the app when the registry is unreachable. Keep new model-serving code fail-soft.

## engine/ modules

```
engine/sample_maker.py       4 generators + WAV write (PCM_24)
engine/generator.py          pattern/rhythm generation (Euclidean, Markov)
engine/acid_dsp_model.py     TB-303 slide model (recursive one-pole glide,
                             default slide_time_ms=50)
engine/effects/              10 hardware-modelled blocks + base.py (BaseEffect
                             contract) + chain.py (ordering)
engine/codegen/              synthdef.py, tidal.py, mappings.py, base.py
engine/ml/                   dataset_schema, dataset_generator, gaussian_noise,
                             deterministic_mapper, regional_profiles,
                             resonance_rules, model_training
engine/AcidSynthEngine.cpp   C++ reference implementation (not in the API path)
```

## Where deeper knowledge lives

- DSP contracts, effect parameters, device domain knowledge → skill `idm-audio-dsp`.
- DVC/MLflow pipeline discipline and model caveats → skill `idm-ml-pipeline`.
- Secrets flow, conda env, machine setup → skill `idm-dev-environment`.
- Git Flow, verification order, doc conventions → skill `idm-project-protocol`.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `00-Project/PROJECT_ARCHITECTURE.md`,
`00-Project/SPECS.md`, `03-Code/_CODE_POINTERS.md`,
`02-Knowledge/END_USER_MANUAL.md`. Verified against `develop` v0.10.1
(2026-07-05). On any conflict with vault docs, the repo wins.*
