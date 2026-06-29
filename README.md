# IDM Generative System

A generative audio application for experimental IDM production. Reconstructs the analog and digital signal chain of 1987–1999 underground electronic music through DSP modeling, algorithmic composition, RAG-augmented sound design, and a knowledge-informed ML tuning pipeline.

Built around a 10-block effects chain that models specific hardware units — from the Mackie CR-1604 noise floor through SP-1200 bitcrushing, TB-303 resonant filtering, Alesis Quadraverb reverb, Roland Space Echo tape delay, to DAT brick-wall mastering. Every block is parameterised against documented specifications from the original equipment.

Output targets: **Teenage Engineering PO-33 K.O!** and **EP-133 K.O.II** — the application generates samples, maps them to device-specific slot configurations, and produces step-by-step programming instructions for each hardware sequencer.

**Live:** [idm.coloursinvision.ai](https://idm.coloursinvision.ai) · **Release:** `v0.9.0`

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        React Frontend                        │
│         React 18 + Vite + TypeScript + Tailwind CSS          │
│  Advisor │ Composer │ Effects │ Generator │ PO-33 │ EP-133    │
│                     Codegen │ Tuning                         │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP  (/api/* — nginx strips prefix)
┌───────────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend (v0.9.0)                   │
│  /generate /process /ask /compose /effects /health           │
│  /codegen /tuning /tuning/extract                            │
└──────┬───────────────────┬───────────────────────┬───────────┘
       │                   │                       │
┌──────▼──────┐   ┌────────▼────────┐   ┌──────────▼───────────┐
│   Engine    │   │    Knowledge    │   │   ML Tuning Pipeline │
│  Generators │   │  Qdrant Cloud   │   │  engine/ml — L1→L6   │
│  Effects    │   │  GPT-4o RAG     │   │  XGBoost · MLflow    │
│  Chain      │   │  Langfuse       │   │  DVC · DO Spaces     │
└─────────────┘   └─────────────────┘   └──────────────────────┘
```

Two operating modes:

| Mode | Generator | LLM role |
|------|-----------|----------|
| **Manual** | Full algorithmic control | Sound design advisor — translates timbral descriptions into synthesis parameters |
| **Auto** | Algorithmic + LLM-guided | Composer — generates effect configs, pattern names, form evolution |

---

## Signal Chain

Ten processing blocks in fixed order. Each block models a specific piece of hardware from the 1987–1999 era.

```
INPUT → [1] Noise Floor → [2] Bitcrusher → [3] Resonant Filter → [4] Saturation
      → [5] Reverb → [6] Tape Delay → [7] Spatial → [8] Glitch Engine
      → [9] Compressor → [10] Vinyl Mastering → OUTPUT (24-bit WAV, 44100 Hz)
```

| Block | Module | Hardware model | Function |
|-------|--------|---------------|----------|
| 1 | `noise_floor.py` | Mackie CR-1604 | Pink/white noise, 50/60Hz hum, bus crosstalk |
| 2 | `bitcrusher.py` | E-mu SP-1200, Akai S950, Casio RZ-1 | Bit depth and sample rate reduction |
| 3 | `filter.py` | Roland TB-303 (18dB/oct), SH-101 (24dB/oct) | LP/HP/BP with resonance and accent coupling |
| 4 | `saturation.py` | Mackie CR-1604 bus overdrive | Asymmetric soft-clipper, wavefold |
| 5 | `reverb.py` | Alesis Quadraverb | Schroeder diffusion network: plate, hall, room, chamber, spring |
| 6 | `delay.py` | Roland Space Echo RE-201 | Wow and flutter, tape age modeling, self-oscillation |
| 7 | `spatial.py` | Period-correct stereo rules | Width control, bass mono below 200Hz, phase decorrelation |
| 8 | `glitch.py` | Ensoniq ASR-10, Autechre-era techniques | Stutter, reverse, loop-point modulation, XOR bit mangle |
| 9 | `compressor.py` | Alesis 3630, analog bus summing | Soft knee compression, DR 8–10 target |
| 10 | `vinyl.py` | DAT mastering chain | Vinyl S-curve pre-emphasis (2–5kHz), brick-wall LPF at 16kHz |

Tail padding: 2s zero-pad before chain processing. Reverb and delay tails decay into the extended buffer. Trailing silence trimmed at -60 dB with 0.1s safety margin.

---

## Features

### Advisor (`/advisor`)
Sound design Q&A powered by RAG retrieval over the project's technical knowledge base (Qdrant Cloud, embedded with `text-embedding-3-large`). Ask about hardware characteristics, DSP techniques, or regional aesthetics — responses are grounded in documented specifications with source attribution.

### Composer (`/composer`)
Describe an aesthetic direction in natural language. GPT-4o interprets the description against the knowledge base and returns a JSON effects chain configuration with reasoning. Send the config directly to the Generator.

### Generator (`/generator`)
Three algorithmic sample generators:
- **glitch_click** — percussive click with exponential decay and spectral shaping
- **noise_burst** — filtered noise burst with tone control (LP/HP/BP)
- **fm_blip** — FM synthesis modeled on Yamaha DX100/TX81Z operator ratios

Each generator feeds through the 10-block effects chain with per-block skip toggles. Output: 24-bit WAV with canvas-based waveform display and Web Audio playback.

### Effects Explorer (`/effects`)
Read-only signal chain visualisation. Horizontal flow diagram of all 10 blocks with expandable parameter cards and hardware source references.

### Codegen (`/codegen`)
Translates generated patterns into live-coding source for **SuperCollider** and **TidalCycles**. SC / TIDAL tabs, a 3-click live flow, solarized-dark syntax highlighting, a config drawer, and a pop-out window synchronised via `BroadcastChannel` (with heartbeat and graceful degradation).

### Tuning (`/tuning`)
Frontend for the V2 ML tuning pipeline. Describe a tuning intent in free text (TuningExtract → GPT-4o), review/adjust the structured request (TuningForm), and compute resonant tuning points (TuningResult) for a region/profile via the `TuningEstimator` model. Conditional `sub_region` for `JAPAN_IDM`; philosophical region captions.

### PO-33 Guide (`/guide/po33`)
Interactive programming guide for the Teenage Engineering PO-33 K.O!

- 16-step grid (4×4) matching the physical device layout
- Pattern visualiser with per-sound step activation
- Sample slot mapping: auto-assign (kick→1, snare→2, hat→3, glitch→4-8, textures→9-16) or manual drag-and-drop
- Instruction generator: converts algorithmic patterns into step-by-step PO-33 button sequences
- Effects reference: FX 1-16 descriptions with usage context
- Pattern chaining: visual chain builder for patterns 1-16
- 8-track Web Audio sequencer with BPM control

### EP-133 Guide (`/guide/ep133`)
Interactive programming guide for the Teenage Engineering EP-133 K.O.II

- 12-pad grid (3×4) × 4 groups (A/B/C/D) matching the physical device
- Group management: A=Drums, B=Bass, C=Melodic, D=Samples
- Timing modes: 1/8, 1/8T, 1/16, 1/16T, 1/32
- **Simultaneous multi-group transport (v0.9.0):** all four groups A/B/C/D play together under one master clock (1/32 grid, per-group stride for polyrhythm), a master/global play control, and a `gain → DynamicsCompressor` master bus that prevents multi-voice clipping. Mute/solo per group (solo wins over mute); per-group sample loading.
- Step input and live record simulation
- Instruction generator: converts patterns into EP-133 workflow with button combinations
- Keys mode: chromatic keyboard for melodic input

---

## V2 — Knowledge-to-DSP ML Tuning Pipeline

A supervised model (`TuningEstimator`) that maps a regional/aesthetic profile to a set of resonant tuning frequencies, trained end-to-end on a synthetic dataset derived from the project's documented knowledge. The pipeline is a six-layer chain (`engine/ml/`), reproducible via DVC and tracked in MLflow.

| Layer | Module | Role |
|-------|--------|------|
| **L1** | knowledge spokes (vault) | Human knowledge — label rosters, hardware facts, regional history |
| **L2** | regional profiles + resonance rules | Formalised DSP-target specs (`regional_profiles.py`, `resonance_rules.py`) |
| **L3** | `deterministic_mapper.py` | Maps profile + resonance rules → deterministic DSP targets |
| **L4** | `gaussian_noise.py` | Calibrated per-parameter sigma → synthetic perturbation |
| **L5** | `dataset_generator.py` + `dataset_schema.py` | Composes a labeled synthetic dataset (pandera-validated DataFrame) |
| **L6** | `model_training.py` | XGBoost + Optuna HPO, MLflow tracking → `TuningEstimator` |

- **Reproducibility:** DVC pipeline (`dvc.yaml`: `generate → validate → train`); model artifacts and the synthetic dataset are content-hashed (`dvc_dataset_hash` MLflow tag).
- **Registry:** `TuningEstimator/Production` (served by `/tuning`); newer baselines land at `Staging` first.
- **Serving:** the FastAPI lifespan loads `models:/TuningEstimator/Production` from the MLflow registry (artifacts on DigitalOcean Spaces). `/tuning` returns resonant points; `/tuning/extract` turns free text into a structured `TuningRequest` via GPT-4o. Both endpoints emit Langfuse traces.

> Pipeline execution (training / `dvc repro`) runs on a workstation, **never** on the production droplet. See `06-MLOps/` in the project vault for the full pipeline state, decisions, and runbook.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| LLM | GPT-4o (OpenAI API) via RAG pipeline |
| Vector DB | Qdrant Cloud (`text-embedding-3-large`, 3072 dims) |
| ML | XGBoost, Optuna (HPO), scikit-learn, pandera |
| ML tracking | MLflow (model registry + tracking server), DVC (pipeline + data versioning) |
| Object storage | DigitalOcean Spaces (S3-compatible — DVC remote + MLflow artifacts) |
| Observability | Langfuse (LLM tracing) |
| Auxiliary UI | Streamlit (parameter inspection, RAG testing) |
| Audio export | 24-bit WAV via soundfile |
| Secrets | SOPS + age (`./scripts/run-with-env.sh`) |
| Container / CI-CD | Docker Compose, GitHub Actions, GHCR |
| Environment | Miniconda (`idm` environment) |

Visual direction: **The Designers Republic / Warp Records (1992–1999)** — brutalist typography, industrial grids, high-contrast monochrome with neon accents. No rounded corners, no icons, text labels only.

---

## Getting Started

### Prerequisites

- Python 3.11+ (Miniconda recommended)
- Node.js 18+ (22 LTS recommended, via `nvm`)
- OpenAI API key, Qdrant Cloud instance
- (ML pipeline only) DigitalOcean Spaces credentials + MLflow tracking URI

### Backend

```bash
git clone https://github.com/coloursinvision/idm-generative-system.git
cd idm-generative-system

conda env create -f environment.yml
conda activate idm
pip install -e ".[dev]"          # add ".[ml]" for the V2 tuning pipeline

# Provide secrets (SOPS + age) — see the secrets architecture docs
export OPENAI_API_KEY="your-key"
export QDRANT_URL="your-qdrant-url"
export QDRANT_API_KEY="your-qdrant-key"

# Start API server (or wrap with ./scripts/run-with-env.sh to inject SOPS secrets)
uvicorn api.main:app --reload --port 8000
```

Secrets are managed with SOPS + age: encrypted values live in `secrets/app.enc.yaml`, non-secret shared config in `.env.shared`. The entry point `./scripts/run-with-env.sh <command>` decrypts and injects them for any process.

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Verify

```bash
curl http://localhost:8000/health        # {"status":"ok","version":"0.9.0"}
pytest                                    # backend test suite
npm --prefix frontend run test            # frontend vitest
```

---

## API Reference

| Endpoint | Method | Function |
|----------|--------|----------|
| `/health` | GET | Health check (version-stamped via `importlib.metadata`; polled by the frontend StatusBar) |
| `/effects` | GET | Returns full chain configuration and per-block parameters |
| `/generate` | POST | Generate sample through effects chain → 24-bit WAV |
| `/process` | POST | Process uploaded audio through effects chain |
| `/ask` | POST | RAG-augmented sound design Q&A (Advisor mode) |
| `/compose` | POST | Aesthetic description → JSON effects config (Composer mode) |
| `/codegen` | POST | Pattern → SuperCollider / TidalCycles source |
| `/tuning` | POST | Region/profile request → resonant tuning points (`TuningEstimator`) |
| `/tuning/extract` | POST | Free text → structured `TuningRequest` (GPT-4o) |

In production, an nginx reverse proxy strips the `/api` prefix; the frontend calls `/api/*` and the backend serves the routes at root.

---

## Testing

```bash
pytest                    # Backend suite (engine, effects, API, ML)
pytest -v                 # Verbose output
npm --prefix frontend run test    # Frontend vitest
```

CI (`ci.yml`) runs `ruff check` + `ruff format --check`, `mypy`, the pytest suite, and a Docker build on every PR to `main` and push to `develop`/`main`.

---

## Deployment

Production runs on a DigitalOcean droplet (AMS3) behind nginx, via Docker Compose (`idm-api` + `mlflow` containers).

- **Git Flow:** feature branches → `develop` (integration) → `main` (release). Production deploys **only** from `main`.
- **CI/CD:** a push to `main` triggers `ci.yml`, which builds and pushes the image to GHCR (`ghcr.io/coloursinvision/idm-generative-system:latest`). On CI success, `deploy.yml` SSHes the droplet and runs `docker compose pull idm-api && docker compose up -d idm-api`.
- **MLflow:** the tracking/registry server runs on the droplet, behind a Tailscale-restricted vhost (`mlflow.idm.coloursinvision.ai`); artifacts are stored in DigitalOcean Spaces.

---

## Hardware Reference

This application generates audio and programming instructions for two Teenage Engineering devices.

### PO-33 K.O!

Micro sampler with built-in microphone, 16-step sequencer, and 40-second sample memory.

| Specification | Value |
|--------------|-------|
| Sample slots | 8 melodic + 8 drum (16 total) |
| Sequencer | 16 steps per pattern, 16 patterns |
| Effects | 16 built-in (hold FX + 1-16) |
| Sync | 3.5mm mini-jack (SY-1 protocol) |
| Sample input | Built-in microphone or 3.5mm line-in |

**Resources:**
- Product page: [teenage.engineering/store/po-33](https://teenage.engineering/store/po-33/)
- User guide: [teenage.engineering/guides/po-33](https://teenage.engineering/guides/po-33/)

### EP-133 K.O.II

Sampler, drum machine, and sequencer with 12 velocity-sensitive pads, 4 groups, and 64MB sample memory.

| Specification | Value |
|--------------|-------|
| Pads | 12 velocity-sensitive × 4 groups (A/B/C/D) |
| Sample slots | 1-99 per category (kicks, snares, hats, etc.) |
| Sequencer | 99 patterns × 99 scenes, 96 PPQN resolution |
| Timing modes | 1/8, 1/8T, 1/16, 1/16T, 1/32 |
| Effects | Per-group FX routing with parameter control |
| Sync | USB-C MIDI, 3.5mm sync |
| Sample input | 3.5mm line-in, USB-C audio |

**Resources:**
- Product page: [teenage.engineering/store/ep-133](https://teenage.engineering/store/ep-133/)
- User guide: [teenage.engineering/guides/ep-133](https://teenage.engineering/guides/ep-133/)

---

## Project Structure

```
IDM_Generative_System_app/
├── engine/
│   ├── generator.py              ← Euclidean rhythms, Markov chain, mutate_pattern
│   ├── sample_maker.py           ← glitch_click, noise_burst, fm_blip
│   ├── effects/                  ← 10-block signal chain (base, chain, blocks 1–10)
│   └── ml/                       ← V2 tuning pipeline (Layers 3–6)
│       ├── regional_profiles.py  ← L2 spoke parsing
│       ├── resonance_rules.py    ← L2 resonance rules
│       ├── deterministic_mapper.py  ← L3
│       ├── gaussian_noise.py     ← L4
│       ├── dataset_generator.py  ← L5
│       ├── dataset_schema.py     ← L5 pandera schema
│       └── model_training.py     ← L6 XGBoost + Optuna + MLflow
├── api/
│   └── main.py                   ← FastAPI backend
├── knowledge/
│   ├── qdrant_client.py          ← Qdrant vector DB connector
│   └── rag.py                    ← RAG pipeline (Advisor, /tuning/extract)
├── scripts/                      ← run-with-env.sh, train pipeline helpers
├── streamlit_app/                ← Auxiliary UI
├── frontend/                     ← React 18 + Vite + TS app
├── dvc.yaml / params.yaml        ← DVC pipeline definition
├── pyproject.toml                ← Single source of truth (metadata, deps, tooling)
├── Dockerfile                    ← 3-stage build (frontend + python + runtime)
├── environment.yml
├── CHANGELOG.md
└── README.md
```

---

## Knowledge Base

The RAG and ML pipelines draw on **THE_MASTER_DATASET_SPECIFICATION** and its Layer-2 spokes, covering:

- **Hardware specifications:** TR-808, TR-909, SP-1200, S950, TB-303, SH-101, DX100, Quadraverb, RE-201, Mackie CR-1604
- **Regional aesthetics:** UK IDM (Warp, Rephlex, Skam), Detroit Techno (UR, Model 500), Japan (Sublime, Frogman, Far East Recording)
- **DSP algorithms:** acid slide (30ms RC glide), accent coupling, Detroit chord memory, Autechre-style stochastic granular distribution
- **Environmental constraints:** 16kHz DAT brick-wall, -75dB pink noise floor, asymmetric saturation curves, DR 8–10 dynamic range targets
- **Resonant frequency architecture:** Solfeggio series, Schumann resonance, brainwave entrainment bands, atonal/alikwotic sources

Indexed in Qdrant with `text-embedding-3-large` (3072 dimensions); cosine-similarity retrieval with configurable context depth.

---

## References

### Hardware Documentation
- Teenage Engineering — [teenage.engineering](https://teenage.engineering/)
- Roland TB-303 Service Notes, Akai S950 Technical Manual, E-mu SP-1200 Service Manual, Alesis Quadraverb Owner's Manual

### Cultural and Technical Sources
- Warp Records — [warp.net](https://warp.net/) · Rephlex Records archive
- The Designers Republic — [thedesignersrepublic.com](https://thedesignersrepublic.com/)
- Hans Cousto — *The Cosmic Octave* (Earth frequency calculations)

### Academic
- Bjorklund, E. (2003) — "The Theory of Rep-Rate Pattern Generation in the SNS Timing System" (Euclidean rhythm algorithm)
- Schroeder, M.R. (1962) — "Natural Sounding Artificial Reverberation" (diffusion network architecture)
- Roads, C. (2001) — *Microsound* (granular synthesis theory)

---

## License

AGPL-3.0-or-later

---

## Author

**Tom Boro** — [github.com/coloursinvision](https://github.com/coloursinvision)
