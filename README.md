# IDM Generative System

A generative audio application for experimental IDM production. Reconstructs the analog and digital signal chain of 1987–1999 underground electronic music through DSP modeling, algorithmic composition, and RAG-augmented sound design.

Built around a 10-block effects chain that models specific hardware units — from the Mackie CR-1604 noise floor through SP-1200 bitcrushing, TB-303 resonant filtering, Alesis Quadraverb reverb, Roland Space Echo tape delay, to DAT brick-wall mastering. Every block is parameterised against documented specifications from the original equipment.

Output targets: **Teenage Engineering PO-33 K.O!** and **EP-133 K.O.II** — the application generates samples, maps them to device-specific slot configurations, and produces step-by-step programming instructions for each hardware sequencer.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│               React Frontend                │
│   React 18 + Vite + TypeScript + Tailwind   │
│   Advisor | Composer | Effects | Generator  │
│   PO-33 Guide | EP-133 Guide               │
└─────────────────┬───────────────────────────┘
                  │ HTTP
┌─────────────────▼───────────────────────────┐
│          FastAPI Backend v0.2.0              │
│   /generate  /process  /ask  /compose       │
│   /effects   /health                        │
└──────┬──────────────────────────┬───────────┘
       │                          │
┌──────▼──────┐          ┌────────▼────────┐
│   Engine    │          │    Knowledge    │
│  Generators │          │  Qdrant Cloud   │
│  Effects    │          │  GPT-4o RAG     │
│  Chain      │          │  Langfuse       │
└─────────────┘          └─────────────────┘
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
Sound design Q&A powered by RAG retrieval over the project's technical knowledge base (43 chunks in Qdrant, embedded with `text-embedding-3-large`). Ask about hardware characteristics, DSP techniques, or regional aesthetics — responses are grounded in documented specifications with source attribution.

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
- Step input and live record simulation
- Instruction generator: converts patterns into EP-133 workflow with button combinations
- Scene/pattern commit flow visualisation
- Keys mode: chromatic keyboard for melodic input
- 4-group Web Audio sequencer with variable timing and BPM control

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, TypeScript, Tailwind CSS |
| Backend | FastAPI (Python 3.11) |
| LLM | GPT-4o (OpenAI API) via RAG pipeline |
| Vector DB | Qdrant Cloud (text-embedding-3-large, 3072 dims) |
| Observability | Langfuse (LLM tracing) |
| Auxiliary UI | Streamlit (parameter inspection, RAG testing) |
| Audio export | 24-bit WAV via soundfile |
| Environment | Miniconda (`idm` environment) |

Visual direction: **The Designers Republic / Warp Records (1992–1999)** — brutalist typography, industrial grids, high-contrast monochrome with neon accents. No rounded corners, no icons, text labels only.

---

## Getting Started

### Prerequisites

- Python 3.11+ (Miniconda recommended)
- Node.js 18+
- OpenAI API key
- Qdrant Cloud instance (or local Qdrant)

### Backend

```bash
git clone https://github.com/coloursinvision/idm-generative-system.git
cd idm-generative-system

conda env create -f environment.yml
conda activate idm

# Set environment variables
export OPENAI_API_KEY="your-key"
export QDRANT_URL="your-qdrant-url"
export QDRANT_API_KEY="your-qdrant-key"

# Start API server
uvicorn api.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Verify

```bash
# API health check
curl http://localhost:8000/health

# Run test suite
pytest  # 23 tests, ~7s
```

---

## API Reference

| Endpoint | Method | Function |
|----------|--------|----------|
| `/health` | GET | Health check (polled by frontend StatusBar every 30s) |
| `/effects` | GET | Returns full chain configuration and per-block parameters |
| `/generate` | POST | Generate sample through effects chain → 24-bit WAV |
| `/process` | POST | Process uploaded audio through effects chain |
| `/ask` | POST | RAG-augmented sound design Q&A (Advisor mode) |
| `/compose` | POST | Aesthetic description → JSON effects config (Composer mode) |

CORS enabled for `localhost:5173` and `localhost:3000`.

---

## Testing

```bash
pytest                    # Full suite: 23 tests
pytest -v                 # Verbose output
pytest engine/            # Engine tests only
pytest api/               # API tests only
```

All tests validate signal chain integrity, effects block behavior, generator output ranges, and API endpoint responses.

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
- Quick start video: [teenage.engineering/learn/po-33](https://teenage.engineering/learn/po-33/)

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
- Sound library: [teenage.engineering/sounds/ep-133](https://teenage.engineering/sounds/ep-133/)

### Service Documentation

Teenage Engineering maintains comprehensive technical documentation, firmware updates, and sound packs at [teenage.engineering/support](https://teenage.engineering/support/). Factory reset procedures, MIDI implementation charts, and sync configuration guides are available per device.

---

## Project Structure

```
IDM_Generative_System_app/
├── engine/
│   ├── generator.py              ← Euclidean rhythms, Markov chain, mutate_pattern
│   ├── sample_maker.py           ← glitch_click, noise_burst, fm_blip
│   ├── acid_dsp_model.py         ← TB-303 slide/accent, Detroit chord memory
│   ├── acid_engine_v2.py         ← Full sequencer render to WAV
│   ├── acid_granular_experiment.py
│   ├── AcidSynthEngine.cpp       ← C++ real-time implementation
│   └── effects/
│       ├── base.py               ← BaseEffect abstract class
│       ├── chain.py              ← EffectChain sequential pipeline
│       ├── noise_floor.py        ← Block 1
│       ├── bitcrusher.py         ← Block 2
│       ├── filter.py             ← Block 3
│       ├── saturation.py         ← Block 4
│       ├── reverb.py             ← Block 5
│       ├── delay.py              ← Block 6
│       ├── spatial.py            ← Block 7
│       ├── glitch.py             ← Block 8
│       ├── compressor.py         ← Block 9
│       └── vinyl.py              ← Block 10
├── api/
│   └── main.py                   ← FastAPI backend v0.2.0
├── knowledge/
│   └── qdrant_client.py          ← Qdrant vector DB connector
├── notebooks/
│   ├── idm_project_01.ipynb      ← Reference: rhythm algorithms
│   └── sample_maker.ipynb        ← Reference: sample generators
├── streamlit_app/
│   └── app.py                    ← Auxiliary UI
├── frontend/
│   ├── src/
│   │   ├── api/client.ts         ← Fetch wrapper for FastAPI
│   │   ├── components/           ← All UI components (layout, tabs, shared)
│   │   ├── hooks/                ← useApi, useAudio
│   │   ├── types/index.ts        ← TypeScript interfaces
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
├── environment.yml
├── .gitignore
└── README.md
```

---

## Knowledge Base

The system's RAG pipeline retrieves from **THE_MASTER_DATASET_SPECIFICATION.md** — a 744-line technical document covering:

- **Hardware specifications:** TR-808, TR-909, SP-1200, S950, TB-303, SH-101, DX100, Quadraverb, RE-201, Mackie CR-1604
- **Regional aesthetics:** UK IDM (Warp, Rephlex, Skam), Detroit Techno (UR, Model 500), Japan (Sublime, Frogman, Far East Recording)
- **DSP algorithms:** Acid slide (30ms RC glide), accent coupling (filter/VCA/saturation interaction), Detroit chord memory (parallel oscillator stacking), granular synthesis (Autechre-style stochastic grain distribution)
- **Environmental constraints:** 16kHz DAT brick-wall, -75dB pink noise floor, asymmetric saturation curves, DR 8–10 dynamic range targets
- **Resonant frequency architecture:** Solfeggio series, Schumann resonance, brainwave entrainment bands, atonal/alikwotic sources

43 chunks indexed in Qdrant with `text-embedding-3-large` (3072 dimensions). Cosine similarity retrieval with configurable context depth (1–10 chunks per query).

---

## References

### Hardware Documentation
- Teenage Engineering — [teenage.engineering](https://teenage.engineering/)
- Roland TB-303 Service Notes — [Roland Corporation](https://www.roland.com/)
- Akai S950 Technical Manual
- E-mu SP-1200 Service Manual
- Alesis Quadraverb Owner's Manual

### Cultural and Technical Sources
- Warp Records — [warp.net](https://warp.net/)
- Rephlex Records archive
- The Designers Republic — [thedesignersrepublic.com](https://thedesignersrepublic.com/)
- Hans Cousto — *The Cosmic Octave* (Earth frequency calculations)

### Academic
- Bjorklund, E. (2003) — "The Theory of Rep-Rate Pattern Generation in the SNS Timing System" (Euclidean rhythm algorithm)
- Schroeder, M.R. (1962) — "Natural Sounding Artificial Reverberation" (diffusion network architecture)
- Roads, C. (2001) — *Microsound* (granular synthesis theory)

---

## License

AGPL v3 (pending)

---

## Author

**Tom Boro** — [github.com/coloursinvision](https://github.com/coloursinvision)
