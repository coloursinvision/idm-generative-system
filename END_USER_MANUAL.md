# IDM Generative System — End User Manual

**Version:** 1.1
**Revision date:** April 7, 2026
**Applicable to:** IDM Generative System V1 (FastAPI v0.5.0, React frontend v0.5.0)

---

## Table of Contents

1. Introduction
2. System Requirements
3. Installation and Configuration
4. Application Overview
5. Module Reference
   - 5.1 Advisor
   - 5.2 Composer
   - 5.3 Generator
   - 5.4 Effects Explorer
   - 5.5 PO-33 Guide
   - 5.6 EP-133 Guide
   - 5.7 Codegen
6. Signal Chain Reference
7. Algorithmic Engine Reference
8. Knowledge Base Architecture
9. Hardware Integration Workflows
10. API Reference
11. Troubleshooting
12. Glossary

---

## 1. Introduction

The IDM Generative System is a generative audio application for experimental electronic music production. It reconstructs the analog and digital signal chain of 1987–1999 underground electronic music — UK IDM, Detroit Techno, Japanese Acid, and adjacent scenes — through DSP modeling, algorithmic composition, and retrieval-augmented sound design.

The system is not a DAW, sampler, or drum machine. It is a generative engine that produces audio material through algorithmic processes, shapes it through a historically accurate effects chain, and outputs it in formats ready for hardware sequencers (Teenage Engineering PO-33 K.O! and EP-133 K.O.II).

### Who This Manual Is For

This manual assumes familiarity with:
- Electronic music production concepts (signal chain, effects processing, sequencing)
- Basic understanding of synthesis (FM, subtractive, granular)
- Comfort with terminal-based setup and configuration
- Interest in the technical and historical foundations of IDM, Techno, and related genres

### Design Philosophy

Three principles govern the system's behavior:

**Form over melody.** The system prioritises rhythm, density, texture, and temporal structure. Melody is treated as an emergent property of algorithmic processes, not a primary compositional target.

**System over song.** The application designs generative processes, not individual tracks. Output is non-repeatable — each generation pass produces unique material from the same parameter set.

**Historical fidelity over convenience.** Every effects block models specific hardware constraints from the era. The system deliberately introduces noise floors, bandwidth limits, quantisation artifacts, and saturation curves that modern production tools eliminate. This is by design — the constraints are the aesthetic.

---

## 2. System Requirements

### Backend (API server)

| Requirement | Minimum |
|-------------|---------|
| Python | 3.11+ |
| Package manager | Miniconda (recommended) or pip |
| RAM | 4 GB |
| Disk | 500 MB (excluding generated audio) |
| Network | Required for Qdrant Cloud and OpenAI API calls |

### Frontend

| Requirement | Minimum |
|-------------|---------|
| Node.js | 18+ |
| Browser | Chrome 90+, Firefox 90+, Safari 15+ (Web Audio API required) |

### External Services

| Service | Purpose | Required |
|---------|---------|----------|
| OpenAI API | GPT-4o for Advisor and Composer modes | Yes |
| Qdrant Cloud | Vector database for knowledge retrieval | Yes |
| Langfuse | LLM observability and tracing | Optional |

---

## 3. Installation and Configuration

### 3.1 Clone and Environment Setup

```bash
git clone https://github.com/coloursinvision/idm-generative-system.git
cd idm-generative-system

conda env create -f environment.yml
conda activate idm
```

The `environment.yml` specifies Python 3.11 with all backend dependencies: FastAPI, uvicorn, numpy, scipy, soundfile, openai, qdrant-client, langfuse, mlflow, and streamlit.

### 3.2 Environment Variables

Create a `.env` file in the project root or export directly:

```bash
export OPENAI_API_KEY="sk-..."
export QDRANT_URL="https://your-cluster.qdrant.io"
export QDRANT_API_KEY="your-qdrant-key"
```

Optional (Langfuse tracing):
```bash
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"
```

### 3.3 Start the Backend

```bash
uvicorn api.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` should return a JSON response with API version and status.

### 3.4 Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

The development server starts at `http://localhost:5173`. CORS is pre-configured for this origin.

### 3.5 Verify Installation

1. Open `http://localhost:5173` in your browser
2. The StatusBar at the bottom should show a green connection indicator and the API version (v0.2.0)
3. Navigate to the Effects tab — the 10-block signal chain should load and display

---

## 4. Application Overview

The application consists of six tabs accessible from the top navigation bar. Each tab corresponds to a distinct function within the generative workflow.

### Navigation

| Tab | Route | Function | Mode |
|-----|-------|----------|------|
| ADVISOR | `/advisor` | Sound design Q&A | Manual |
| COMPOSER | `/composer` | Aesthetic → JSON config | Auto |
| GENERATOR | `/generator` | Sample generation + playback | Both |
| EFFECTS | `/effects` | Signal chain reference | Both |
| PO-33 | `/guide/po33` | PO-33 programming guide | Both |
| EP-133 | `/guide/ep133` | EP-133 programming guide | Both |

### Operating Modes

**Manual mode** gives the user full control over algorithmic parameters. The LLM (GPT-4o) is available exclusively as a sound design advisor — it answers questions about hardware, techniques, and parameter selection but does not intervene in the generative process.

**Auto mode** extends Manual mode. The LLM actively participates in composition: it interprets aesthetic descriptions, generates effects chain configurations, suggests pattern evolution directions, and provides narrative context for generated material.

The mode distinction affects only the Advisor and Composer tabs. The Generator, Effects, PO-33, and EP-133 tabs function identically in both modes.

---

## 5. Module Reference

### 5.1 Advisor

**Route:** `/advisor`
**API endpoint:** `POST /ask`
**Mode:** Manual

The Advisor is a retrieval-augmented Q&A interface. It answers sound design questions by searching the project's knowledge base (THE_MASTER_DATASET_SPECIFICATION — 43 indexed chunks covering hardware specs, DSP algorithms, and regional aesthetics) and generating grounded responses via GPT-4o.

**Interface elements:**

- **Question input** — free-text field. Accepts any sound design, DSP, or production-related query. The more specific the question, the more targeted the retrieval.
- **Context chunks slider** (1–10) — controls how many knowledge base chunks are included in the LLM context. Lower values produce more focused answers; higher values provide broader context at the cost of response specificity.
- **Submit** — triggers the RAG pipeline: embed query → cosine similarity search in Qdrant → retrieve top-k chunks → construct prompt with context → GPT-4o completion.
- **Answer display** — rendered response with inline source attribution tags showing which parts of the knowledge base contributed to each claim. Each tag displays the source part number and relevance score.
- **Token usage footer** — displays prompt and completion token counts for the current query.

**Example queries:**
- "What filter topology does the TB-303 use and how does accent affect resonance?"
- "How did Autechre achieve the granular textures on Tri Repetae?"
- "What is the difference between Akai S950 and E-mu SP-1200 time-stretching artifacts?"
- "Describe the Mackie CR-1604 bus saturation characteristics for modeling purposes."

**What the Advisor does not do:** It does not generate audio, modify parameters, or control the Generator. It is a reference tool — a technically grounded alternative to searching documentation manually.

---

### 5.2 Composer

**Route:** `/composer`
**API endpoint:** `POST /compose`
**Mode:** Auto

The Composer translates natural language aesthetic descriptions into machine-readable effects chain configurations. It bridges subjective timbral language ("dark, lo-fi, tape-saturated Detroit dub") with the specific parameter values required by the Generator's effects chain.

**Interface elements:**

- **Description input** — free-text field for aesthetic direction. Accepts any combination of timbral adjectives, genre references, hardware names, spatial characteristics, and temporal qualities.
- **Submit** — triggers the RAG-augmented composition pipeline. The description is embedded, relevant knowledge chunks are retrieved, and GPT-4o generates a JSON configuration covering all 10 effects chain blocks with specific parameter values.
- **JSON config display** — the generated configuration, rendered in a collapsible JSON viewer. Each block shows the target parameters, their values, and the hardware reference informing the choice.
- **Reasoning section** — GPT-4o's explanation of why each parameter was chosen, referencing specific knowledge base entries (hardware characteristics, regional aesthetics, historical production techniques).
- **Source attribution tags** — indicate which knowledge base chunks contributed to the configuration.
- **Send to Generator** — transfers the JSON config to the Generator tab, pre-filling all parameter controls with the Composer's output. No manual transcription required.

**Example descriptions:**
- "Early Warp Records bleep techno — heavy sub-bass, clinical high-frequency content, Alesis Quadraverb plate reverb, minimal saturation, wide stereo field"
- "Rephlex-era braindance — extreme glitch processing, micro-edits, aggressive bitcrushing to 8-bit, short stutter loops, dry mix"
- "Japanese precision acid — TB-303 with full key tracking, clean resonance without distortion, surgical frequency separation, crystal reverb"
- "Basic Channel dub techno — deep delay self-oscillation, heavy tape saturation on repeats, narrow bandwidth, mono bass, fog-like spatial density"

---

### 5.3 Generator

**Route:** `/generator`
**API endpoint:** `POST /generate`
**Mode:** Both

The Generator is the core audio production module. It creates samples using one of three algorithmic generators, processes them through the 10-block effects chain, and outputs 24-bit WAV files with waveform visualisation and browser-based playback.

**Interface elements:**

- **Generator selector** — choose between `glitch_click`, `noise_burst`, or `fm_blip`. Each generator produces fundamentally different source material (see Section 7 for algorithm details).
- **Parameter controls** — dynamic controls populated from the `/effects` endpoint. Each effects block has individually adjustable parameters. Controls update when a different generator is selected.
- **Chain overrides / skip toggles** — per-block bypass switches. Disable any combination of the 10 effects blocks to isolate specific processing stages or hear raw generator output.
- **Generate** — sends the current configuration to the API. The backend generates the source sample, applies the enabled effects chain blocks in order (with 2s tail padding), trims silence, and returns a 24-bit WAV file.
- **Waveform display** — canvas-based amplitude visualisation of the generated audio. Renders after generation completes.
- **Play / Stop** — Web Audio API playback of the generated sample. Playback occurs in the browser — no external audio application required.
- **Download** — saves the generated 24-bit WAV to disk.
- **Pattern grid** — visual representation of the rhythmic pattern produced by the generator's algorithmic layer (Euclidean distribution, Markov state, or mutation result).

**Generation workflow:**
1. Select a generator
2. Adjust parameters (or load a Composer configuration via "Send to Generator")
3. Toggle effects chain blocks as needed
4. Click Generate
5. Review waveform, listen via Play, download if satisfactory
6. Repeat with parameter variations or pattern mutations

---

### 5.4 Effects Explorer

**Route:** `/effects`
**API endpoint:** `GET /effects`
**Mode:** Both

A read-only reference view of the complete signal chain. Not an editor — use the Generator tab for active parameter control.

**Interface elements:**

- **Signal chain diagram** — horizontal flow visualisation of all 10 blocks in processing order. Each block is a card showing its name, hardware source, and processing category.
- **Expandable block cards** — click any block to expand its parameter list with default values, ranges, and descriptions. Parameters are documented with their hardware-derived constraints (e.g., "Bandwidth LPF: 8–11kHz, modeling Quadraverb internal processing rate").
- **Hardware source reference** — each block card displays the specific equipment being modeled and a brief explanation of how the original hardware's characteristics are implemented in the DSP algorithm.

This tab is educational. Use it to understand what each block does before adjusting parameters in the Generator, or as a reference while formulating Composer descriptions.

---

### 5.5 PO-33 Guide

**Route:** `/guide/po33`
**Mode:** Both

An interactive programming interface for the Teenage Engineering PO-33 K.O! The Guide translates algorithmically generated patterns into device-specific button sequences, sample slot mappings, and performance workflows.

**Interface elements:**

- **16-step grid** — 4×4 matrix matching the physical PO-33 button layout. Each cell represents one step in the sequencer. Active steps are highlighted per sound.
- **Track selector** — switch between sounds (kick, snare, hat, and up to 5 additional glitch/texture layers) to view and edit their step patterns independently.
- **Step input mode** — click grid cells to toggle steps on/off. Mirrors the PO-33's write mode workflow.
- **Sample slot mapping panel:**
  - **Auto mode:** kick→slot 1, snare→slot 2, hat→slot 3, glitch→slots 4-8, textures→slots 9-16
  - **Manual mode:** drag any generated sample to any slot position
- **Instruction generator** — given a pattern, produces a numbered list of PO-33 button sequences:
  ```
  1. Hold SOUND + press 1       → Select kick sound
  2. Press WRITE                 → Enter record mode
  3. Press steps 1, 5, 9, 13    → Program four-on-the-floor kick
  4. Hold SOUND + press 2       → Select snare sound
  5. Press steps 5, 13          → Program backbeat snare
  ...
  ```
- **Effects reference** — table of PO-33 FX 1-16 with descriptions and recommended usage contexts per sound type.
- **Pattern chaining** — visual builder for linking patterns 1-16 into longer sequences. Drag patterns into a chain timeline.
- **Sync guide** — instructions for synchronising the PO-33 with external devices via the SY-1 mini-jack protocol.
- **Web Audio sequencer** — 8-track playback engine. Load generated samples into the sequencer, set BPM, and preview the full pattern in the browser before transferring to hardware.
  - **LOAD SAMPLES** — imports generated WAV files into the browser sequencer
  - **PLAY / STOP** — start and stop sequencer playback
  - **BPM slider** — adjusts tempo in real-time during playback

**Typical workflow:**
1. Generate samples in the Generator tab
2. Navigate to PO-33 Guide
3. Load samples into the sequencer
4. Program a pattern using the step grid
5. Preview via Web Audio playback
6. Read the instruction list to transfer the pattern to physical hardware
7. Use the effects reference to apply PO-33 FX on device

---

### 5.6 EP-133 Guide

**Route:** `/guide/ep133`
**Mode:** Both

An interactive programming interface for the Teenage Engineering EP-133 K.O.II. The EP-133 has a more complex architecture than the PO-33 — 4 groups, variable timing resolutions, scene management, and per-group FX routing — and the Guide reflects this complexity.

**Interface elements:**

- **12-pad grid** — 3×4 matrix × 4 groups (A/B/C/D), matching the physical EP-133 layout. Switch between groups using the group selector.
- **Group management:**
  - **Group A — Drums:** kicks (slots 1-99), snares (100-199), hats (200-299), percussion (300-399)
  - **Group B — Bass:** bass sounds (slots 400-499)
  - **Group C — Melodic:** melodic samples (slots 500-599)
  - **Group D — Samples/Loops:** user samples and loops
- **Timing mode selector** — 1/8, 1/8T (triplet), 1/16, 1/16T, 1/32. Changes the step resolution of the sequencer view. Triplet modes display a modified grid reflecting the uneven step distribution.
- **Step input mode** — click pads and steps to program patterns. Mirrors the EP-133 step sequencer workflow (RECORD + PAD at target step).
- **Live record simulation** — visual representation of real-time recording. Shows which pad would be captured at which step position when recording in real-time mode.
- **Instruction generator** — produces step-by-step EP-133 workflow with exact button combinations:
  ```
  1. Press MAIN                       → Enter main mode
  2. Press Group A                    → Select drums group
  3. Hold RECORD + press Pad 1        → Assign kick to step 1.1.1
  4. Press + to advance               → Move to step 1.2.1
  5. Hold RECORD + press Pad 3        → Assign hat to step 1.2.1
  ...
  12. Press SHIFT + MAIN              → Commit pattern to scene
  ```
- **Scene/pattern workflow** — visual representation of the EP-133 commit flow. Shows how patterns are committed to scenes (SHIFT+MAIN) and how scenes are chained into arrangements.
- **Keys mode** — chromatic keyboard visualisation for melodic input. Displays which pads correspond to which notes when Keys mode is active on the physical device.
- **FX routing panel** — per-group effects assignment. Shows how to route each group through the EP-133's built-in effects and adjust parameters.
- **Swing knob visualisation** — displays the current swing amount and its effect on step timing.
- **Sample slot reference** — category-based numbering system: 1-99 kicks, 100-199 snares, 200-299 hats, 300-399 percussion, 400-499 bass, 500-599 melodic.
- **Web Audio sequencer** — 4-group playback engine with variable timing resolution. Operates identically to the PO-33 sequencer but with group switching, variable step counts, and per-group timing modes.

**Typical workflow:**
1. Generate samples in the Generator tab (multiple generators for different sound categories)
2. Navigate to EP-133 Guide
3. Assign samples to groups (A=drums, B=bass, C=melodic, D=loops)
4. Select timing resolution per group
5. Program patterns using the step grid
6. Preview via Web Audio playback
7. Commit pattern to scene using the visual workflow
8. Read the instruction list to transfer to physical hardware
9. Apply FX routing per group on device

---

### 5.7 Codegen

**Route:** `/codegen` (docked) + `/codegen-popout` (detached window)
**API endpoints:** `POST /synthdef`, `POST /tidal`
**Mode:** Both

The Codegen tab generates runnable SuperCollider (sclang) and TidalCycles (Haskell DSL) code from the current engine configuration. It bridges the IDM Generative System's parameter space with external live-coding environments for hardware synthesis and performance.

**Interface elements:**

- **Target tabs — SC | TIDAL** — toggle between SuperCollider and TidalCycles output. Always visible in the top toolbar.
- **GENERATE button** — sends the current configuration to `/synthdef` or `/tidal`. The primary action — designed for rapid, repeated use. Always visible.
- **Code display block** — solarized dark background (`#002b36`) with dual syntax highlighting:
  - **sclang:** keywords in TE orange (#FF6600), strings in amber (#f59e0b), numbers in cyan (#2aa198), UGens in magenta (#d33682), comments in muted gray (#586e75)
  - **Haskell/Tidal:** same palette applied to Tidal functions, operators, and pattern syntax
  - Line numbers in left gutter on darker background (#073642)
- **Toolbar labels** — precise language identifiers: `SCLANG .SCD` for SuperCollider, `HASKELL / TIDAL .TIDAL` for TidalCycles. These match the actual file extensions and language names.
- **COPY button** — copies generated code to clipboard. Paste directly into SuperCollider IDE or Atom/VS Code with TidalCycles plugin.
- **DOWNLOAD button** — saves code as `.scd` (SuperCollider) or `.tidal` (TidalCycles) file.
- **CONFIG drawer** — collapsible panel (collapsed by default, one-line summary visible). Contains:
  - Generator selector (glitch_click, noise_burst, fm_blip)
  - Mode toggle: **Studio** (self-contained script with server boot, full comments, cleanup) or **Live** (minimal boilerplate, hot-swap via Pdef/Ndef)
  - BPM control
  - Effects chain block toggles (enable/disable individual blocks)
- **Popout button (⧉)** — detaches the codegen panel to a separate browser window. Enables dual-monitor workflows: main app on one screen, SuperCollider IDE on the other. State is synchronised between windows via `BroadcastChannel` API.

**Popout window:**

The detached window (`/codegen-popout`) operates in two modes:
1. **Connected** — receives config and code updates from the main window in real-time. Connection status shown by a green indicator with heartbeat monitoring (2s interval, 5s timeout).
2. **Standalone** — if the main window is closed, the popout switches to local operation with fallback defaults. All controls (GENERATE, COPY, DOWNLOAD) work independently.

**Codegen workflow:**
1. Configure generator and effects in CONFIG drawer (or accept defaults)
2. Select target: SC or TIDAL tab
3. Click GENERATE
4. Review code in the solarized dark display
5. Click COPY or DOWNLOAD
6. Paste/open in SuperCollider IDE or TidalCycles environment
7. Evaluate — the generated code is self-contained and runnable

**Studio vs Live mode:**
- **Studio** generates a complete script: `s.boot`, SynthDef definitions with bus routing and Group ordering, pattern scheduling via Pbind (SC) or full `d1 $` stack (Tidal), and cleanup (`s.freeAll`).
- **Live** generates minimal code for hot-swapping: Pdef/Ndef wrappers (SC) or bare `d1` patterns (Tidal). Assumes the server and environment are already running.

---

## 6. Signal Chain Reference

The effects chain processes audio through 10 blocks in fixed sequential order. Each block models a specific piece of hardware from the 1987–1999 era. All blocks inherit from the `BaseEffect` abstract class and implement a consistent `__call__(signal)` interface.

For a summary table of all blocks, see the README. This section provides detailed per-block documentation.

### Block 1 — Noise Floor (`noise_floor.py`)

**Hardware model:** Mackie CR-1604 mixing console

Adds a calibrated noise floor to the signal, modeling the analog mixer bus sum that was present in every 1987–1999 production. The noise floor is not an error — it is a fundamental characteristic of the era's sound. Recordings from this period have an integrated noise level of approximately -75 to -78 dB RMS.

**Parameters:**
- **Noise type:** Pink (1/f spectrum, default) or white (flat spectrum)
- **Level:** Noise floor amplitude in dB (default: -75 dB)
- **Hum frequency:** 50 Hz (UK/EU) or 60 Hz (US/Detroit) mains hum
- **Hum level:** Mains hum amplitude
- **Crosstalk:** Inter-channel leakage coefficient (L→R and R→L bleed, modeling Mackie bus routing: `L_out = L + R × 0.005`)

**Design note:** This is the Anti-GIGO block. It sets the environmental floor before any processing occurs. Without it, subsequent blocks operate on an unrealistically clean signal that has no analog equivalent from the target era.

### Block 2 — Bitcrusher (`bitcrusher.py`)

**Hardware models:** E-mu SP-1200 (12-bit, 26.04 kHz), Akai S950 (12-bit, variable), Casio RZ-1 (8-bit, 20 kHz), Roland TR-909 cymbals (6-bit)

Reduces bit depth and sample rate to model the quantisation artifacts of period-specific digital hardware. The SP-1200's 12-bit converter with its SSM2044 filter produces a distinctly different color than the S950's variable-bandwidth LPF or the RZ-1's raw 8-bit PCM.

**Parameters:**
- **Bit depth:** Target bit depth (6–24 bits)
- **Sample rate:** Target sample rate in Hz
- **Device preset:** SP-1200, S950, RZ-1, TR-909 cymbal — each preset configures bit depth, sample rate, and filter characteristics to match the specific hardware

**Design note:** Bitcrushing before filtering (Block 3) is historically accurate. In the original hardware, the DAC's quantisation artifacts existed before any analog filtering stage.

### Block 3 — Resonant Filter (`filter.py`)

**Hardware models:** Roland TB-303 (18 dB/oct, 3-pole), Roland SH-101 (24 dB/oct, 4-pole IR3109)

Voltage-controlled filter emulation with resonance, key tracking, and accent coupling. The TB-303 implementation models the specific nonlinear interaction between accent, resonance, and filter decay that defines the acid sound — accent is not a simple gain boost but a three-way parameter coupling (see THE_MASTER_DATASET_SPECIFICATION Part 4.2).

**Parameters:**
- **Filter type:** Low-pass, high-pass, or band-pass
- **Cutoff frequency:** Filter cutoff in Hz
- **Resonance (Q):** Resonance amount (0–1, self-oscillation at values approaching 1.0)
- **Topology:** 3-pole (TB-303, 18 dB/oct) or 4-pole (SH-101, 24 dB/oct)
- **Accent coupling:** When enabled, high-velocity notes shorten filter decay by ~50%, boost resonance by ~15%, and apply tanh saturation on the VCA stage
- **Key tracking:** Filter cutoff follows MIDI note (0–100%, 100% = filter tracks pitch perfectly, characteristic of Japanese acid — see Susumu Yokota entry in MASTER_DATASET Part 12.4)

### Block 4 — Saturation (`saturation.py`)

**Hardware model:** Mackie CR-1604 bus overdrive

Asymmetric soft-clipping that models the harmonic distortion of analog mixer bus stages driven into the red. The asymmetry is deliberate — positive and negative signal excursions are clipped differently, producing odd and even harmonics in the distortion spectrum.

**Parameters:**
- **Drive:** Gain before clipping (1.0 = unity, 2.0+ = overdrive)
- **Asymmetry:** Balance between positive and negative clipping curves
- **Mode:** Soft-clip (tanh) or wavefold
- **Mix:** Dry/wet blend

**Formula:** `output = (x > 0) ? tanh(x × drive) : (x / (1 - x × drive × 0.5))`

**Design note:** Division by zero is handled with a safe denominator clamp at the signal boundary where `x = 2/drive`. This was a bug fix from the March 23, 2026 session.

### Block 5 — Reverb (`reverb.py`)

**Hardware model:** Alesis Quadraverb (1989)

Schroeder diffusion network modeling the specific characteristics of the Quadraverb — the standard reverb unit of early Warp Records (Aphex Twin, Autechre, LFO). The Quadraverb's character comes from its 16-bit internal processing at 31.25 kHz, which introduces subtle aliasing in the reverb tail and a hard bandwidth ceiling on reflections.

**Parameters:**
- **Type:** Plate, hall, room, chamber, spring
- **Decay time:** Reverb tail length in seconds
- **Pre-delay:** Separation between dry transient and reverb onset (15–35 ms recommended for maintaining percussion punch)
- **Diffusion:** Density of the reflection network (>80% for the characteristic "cloud" where individual echoes become indistinguishable)
- **Bandwidth LPF:** High-frequency cutoff on reflections (8–11 kHz, modeling Quadraverb internal processing)
- **Damping:** High-frequency loss per reflection (-3 dB above 5 kHz per repetition)
- **Mix:** Dry/wet blend

**Design note:** The reverb return is stereo with phase alignment for mono compatibility. The 2s tail padding added to the signal chain in March 2026 was specifically implemented to allow this block's decay tails to ring out naturally.

### Block 6 — Tape Delay (`delay.py`)

**Hardware model:** Roland Space Echo RE-201

Models the physical tape transport of the RE-201, including wow and flutter (tape speed variation), tape age degradation, multi-head spacing, and self-oscillation behavior at feedback values exceeding unity gain.

**Parameters:**
- **Delay time:** Base delay in milliseconds
- **Feedback:** Repeat level (0–1+; values above 1.0 trigger self-oscillation with internal clipping)
- **Wow and flutter:** Tape speed modulation depth (LFO at ~0.5 Hz with noise component)
- **Tape age:** High-frequency loss per repetition, modeling tape oxide degradation
- **Head configuration:** Number of playback heads and spacing ratios (1:2, 1:3, 1:4 for rhythmic multi-tap delays)
- **Tape saturation:** Per-repetition saturation via `tanh(input × gain)` — each echo is progressively warmer and grittier
- **Mix:** Dry/wet blend

### Block 7 — Spatial (`spatial.py`)

**Hardware reference:** MASTER_DATASET Part 15 stereo field rules

Controls stereo image width with frequency-dependent processing, enforcing the stereo conventions of 1990s underground electronic production.

**Parameters:**
- **Width:** Overall stereo width (0 = mono, 1 = unprocessed, >1 = widened)
- **Bass mono cutoff:** Frequency below which the signal is summed to mono (default: 200 Hz)
- **Decorrelation:** Phase decorrelation amount for stereo widening (applied only above bass mono cutoff)

**Fixed rules:**
- Kick and bass content below 200 Hz is strictly mono (prevents phase cancellation on club systems)
- Pads and reverb returns are widened via phase decorrelation
- Percussion is set to approximately 70% width (TR-909 style panning convention)

### Block 8 — Glitch Engine (`glitch.py`)

**Hardware references:** Ensoniq ASR-10 (loop-point modulation), Autechre Tri Repetae (bit manipulation), Aphex Twin / Rephlex catalog (micro-edit techniques)

Applies destructive rhythmic processing: stutter, reverse, loop-point drift, and bitwise manipulation. This block models the "braindance" production technique of creating rhythmic interest through sample destruction rather than traditional sequencing.

**Parameters:**
- **Mode:** Stutter, reverse, loop-mod, XOR mangle, or random (randomly selects per processing pass)
- **Stutter rate:** Re-trigger rate for stutter mode (grain length in ms)
- **Stutter count:** Number of re-triggers per event
- **Loop drift:** LFO rate for loop-point modulation (models ASR-10 loop start drift: `Loop_Start = Base_Start + LFO(0.5Hz)`)
- **XOR mask:** Bit pattern for XOR mangle mode (flips specific bits in the audio data, producing unpredictable timbral destruction)
- **Mix:** Dry/wet blend (critical — 100% wet glitch is often unusable; 20–40% blends glitch artifacts into the source texture)

### Block 9 — Compressor (`compressor.py`)

**Hardware references:** Alesis 3630, analog bus summing (Mackie CR-1604 master bus)

Bus-style compression targeting a dynamic range of DR 8–10 — the characteristic loudness profile of 1990s underground releases, which were mastered louder than acoustic recordings but without the brick-wall limiting of modern EDM production.

**Parameters:**
- **Threshold:** Compression onset level in dB
- **Ratio:** Compression ratio (2:1 to 20:1)
- **Attack:** Compressor attack time in ms (<1 ms for aggressive transient control)
- **Release:** Compressor release time in ms (100–300 ms for the "pumping" effect)
- **Knee:** Soft or hard knee transition
- **Makeup gain:** Post-compression gain to restore level
- **Sidechain:** Optional sidechain input for ducking effects (kick → pad bus, modeling the Alesis 3630 "pump" technique)

**Design note:** The DR 8–10 target is a quality check, not a hard constraint. Output that falls outside this range may still be musically valid but diverges from the historical mastering aesthetic.

### Block 10 — Vinyl Mastering (`vinyl.py`)

**Hardware references:** DAT recorder anti-aliasing filters (Sony PCM-2700, Panasonic SV-3700), vinyl lathe pre-emphasis curves

The final processing stage, modeling two characteristics of 1990s distribution media:

1. **DAT brick-wall filter** — steep low-pass at 16 kHz, modeling the anti-aliasing filters of period DAT recorders. This constrains the output bandwidth to match the era's delivery medium.

2. **Vinyl pre-emphasis** — an S-curve saturation applied to the 2–5 kHz range, modeling the excitement that vinyl cutting lathes impart to the signal. Underground tracks were typically cut "hot" on vinyl, producing a subtle brightness and presence in the upper midrange.

**Parameters:**
- **DAT cutoff:** Brick-wall LPF frequency (default: 16 kHz; 19 kHz for DAT-accurate modeling)
- **Pre-emphasis amount:** Intensity of the S-curve saturation in the 2–5 kHz band
- **Pre-emphasis frequency range:** Center frequency and bandwidth of the emphasis curve

---

## 7. Algorithmic Engine Reference

### 7.1 Sample Generators

Three generator functions produce the raw source material before effects chain processing.

**glitch_click** — Percussive transient with exponential amplitude decay and spectral shaping. Produces sharp, short-duration clicks suitable for hi-hat and percussion roles. The decay curve and spectral tilt are randomised within configured bounds on each generation pass.

**noise_burst** — Filtered noise with configurable tone (low-pass, high-pass, or band-pass). Duration, filter cutoff, and resonance are parameterised. Produces textural material ranging from deep thuds (LP, low cutoff) to bright hissing transients (HP, high cutoff).

**fm_blip** — Two-operator FM synthesis modeled on the Yamaha DX100/TX81Z architecture. Carrier-to-modulator ratio, modulation index, and envelope shape determine the timbral character. At low modulation indices, produces clean tonal blips; at high indices, produces metallic, inharmonic transients characteristic of the "Detroit stab" sound.

### 7.2 Pattern Algorithms

**Euclidean rhythm** — `euclidean_rhythm(k, n)`: distributes k pulses as evenly as possible across n steps using the Bjorklund algorithm. Produces rhythmic patterns found in West African drumming, Balkan folk music, and IDM polyrhythms. The implementation was corrected during the March 23 session — the original notebook version produced incorrect output lengths for most k/n combinations.

**Probabilistic generation** — `generate_pattern()`: each step is independently activated based on a per-track probability value. Produces stochastic patterns with configurable density. No inter-step memory — purely random.

**Density generation** — `generate_pattern_density()`: generates patterns with a target density (ratio of active to total steps), distributing pulses uniformly. Unlike Euclidean distribution, does not optimise for evenness.

**Markov evolution** — `markov_evolve()`: applies a Markov transition matrix to an existing pattern. Each step's next state depends on its current state and the states of adjacent steps. Produces temporal coherence — patterns develop motifs and structural repetition over successive evolution passes.

**Mutation** — `mutate_pattern(pattern, mutation_rate)`: probabilistic bit-flip on each step with configurable mutation rate. Applied post-generation to introduce controlled entropy. At low rates (0.01–0.05), produces subtle micro-variations; at high rates (0.2+), produces radical pattern transformation.

### 7.3 Acid DSP Model

The `acid_dsp_model.py` module implements three TB-303 and Detroit Techno-specific DSP algorithms:

**Acid slide** — nonlinear frequency glide modeling the TB-303 capacitor discharge: `Current_Pitch += Alpha × (Target_Pitch - Current_Pitch)` where `Alpha = 1 - exp(-1 / (Fs × 0.03))`. The 30ms time constant is fixed — it is a physical property of the 303 circuit, not a user parameter.

**Detroit chord memory** — parallel oscillator stacking for the Minor 9th voicing (Root, +3, +7, +10, +14 semitones). All oscillators are summed before a single mono 24 dB/oct LPF. The filter processes the composite harmonic spectrum, not individual voices.

**Accent saturation** — nonlinear VCA modeling via `tanh(input × accent_gain)` where accent_gain is 2.4 for accented steps and 1.0 for normal steps. This is applied after the filter stage, matching the 303's internal signal flow.

---

## 8. Knowledge Base Architecture

The system's retrieval-augmented generation (RAG) pipeline operates over a single source document: **THE_MASTER_DATASET_SPECIFICATION.md** (744 lines, 17 parts + table of contents).

### Indexing

The document is chunked and embedded using OpenAI's `text-embedding-3-large` model (3072 dimensions). 43 chunks are indexed in a Qdrant Cloud collection with cosine similarity as the distance metric.

Chunking preserves section boundaries — each chunk corresponds to a coherent topical unit (a hardware specification table, a DSP algorithm description, a regional aesthetic profile, etc.). Chunks do not split mid-paragraph or mid-table.

### Retrieval

When the Advisor or Composer receives a query:
1. The query text is embedded using the same model (`text-embedding-3-large`)
2. Cosine similarity search returns the top-k most relevant chunks (k is configurable via the context chunks slider, range 1–10)
3. Retrieved chunks are inserted into the LLM prompt as grounding context
4. GPT-4o generates a response constrained to the provided context
5. Source attribution tags link claims in the response to specific chunks

### Knowledge Coverage

The indexed document covers:
- Hardware specifications for 15+ devices (drum machines, samplers, synthesisers, effects units, mixers, recorders)
- Regional aesthetic profiles for UK IDM, Detroit Techno, Japanese Acid/Techno, European Acid, and Dub Techno
- DSP algorithms with mathematical formulations (acid slide, accent coupling, chord memory, granular synthesis)
- Environmental constraints (noise floors, bandwidth limits, saturation curves, dynamic range targets)
- Resonant frequency architecture (Solfeggio series, Schumann resonance, brainwave entrainment bands)
- Label-specific aesthetic analyses (Rephlex, Planet Mu, Skam, Warp, Sublime, Frogman, Metalheadz, etc.)
- Synthesis patch architectures (LFO sub-bass, B12 pads, Detroit stabs, Yokota acid textures)
- Mastering and summing philosophy (Mackie bus saturation, DAT brick-wall, vinyl pre-emphasis)

---

## 9. Hardware Integration Workflows

### 9.1 PO-33 K.O! Workflow

```
Generator → Generate samples (WAV)
         → PO-33 Guide → Map samples to slots (auto or manual)
                        → Program pattern via step grid
                        → Preview via Web Audio sequencer
                        → Read instruction list
                        → Transfer to physical PO-33:
                            1. Line-in or mic sampling
                            2. Assign to melodic (1-8) or drum (9-16) slot
                            3. Enter write mode (WRITE button)
                            4. Press steps to program pattern
                            5. Apply FX (hold FX + 1-16)
                            6. Chain patterns for longer sequences
```

**Sample transfer:** The PO-33 samples audio via its built-in microphone or 3.5mm line-in jack. Play the generated WAV from your computer while the PO-33 is in sampling mode. Trim the captured sample on the device using the start/end controls.

**Limitations:** The PO-33 has 40 seconds of total sample memory and 16 slots. Plan sample selection accordingly — shorter, more percussive samples maximise the available slot count.

### 9.2 EP-133 K.O.II Workflow

```
Generator → Generate samples (WAV, multiple generators for different groups)
         → EP-133 Guide → Assign to groups (A=drums, B=bass, C=melodic, D=loops)
                         → Select timing resolution per group
                         → Program patterns via step grid
                         → Preview via Web Audio sequencer
                         → Read instruction list
                         → Transfer to physical EP-133:
                             1. USB-C audio or 3.5mm line-in sampling
                             2. Assign to group and category slot
                             3. Enter step sequencer (MAIN mode)
                             4. Hold RECORD + press pad at target step
                             5. Route groups through FX
                             6. Commit pattern to scene (SHIFT+MAIN)
                             7. Chain scenes into arrangement
```

**Sample transfer:** The EP-133 accepts audio via USB-C (direct digital transfer from computer) or 3.5mm line-in. USB-C transfer is recommended for maintaining 24-bit signal integrity.

**Advantages over PO-33:** 64MB sample memory (significantly more than PO-33's 40 seconds), 99 patterns per scene, 99 scenes, per-group FX routing, variable timing resolution, and velocity-sensitive pads.

---

## 10. API Reference

Base URL: `http://localhost:8000`

### GET /health
Returns API status and version. Used by the frontend StatusBar for connection monitoring (polled every 30 seconds).

### GET /effects
Returns the complete effects chain configuration: all 10 blocks with their parameter names, types, default values, ranges, and hardware source references. Consumed by the Effects Explorer and Generator tabs on mount.

### POST /generate
Generates a sample using the specified generator and effects chain configuration.

**Request body:**
- `generator`: string — `glitch_click`, `noise_burst`, or `fm_blip`
- `params`: object — generator-specific parameters
- `chain_config`: object — per-block parameter overrides
- `skip_blocks`: array — list of block indices to bypass (0-indexed)

**Response:** Binary WAV file (24-bit, 44100 Hz)

### POST /process
Processes an uploaded audio file through the effects chain.

**Request:** Multipart form with audio file + chain configuration
**Response:** Binary WAV file (24-bit, 44100 Hz)

### POST /ask
RAG-augmented sound design Q&A.

**Request body:**
- `question`: string — the query
- `num_chunks`: integer (1–10) — number of knowledge base chunks to retrieve

**Response:** JSON with `answer`, `sources` (array of chunk references with scores), and `usage` (token counts)

### POST /compose
Aesthetic description to effects chain configuration.

**Request body:**
- `description`: string — natural language aesthetic description
- `num_chunks`: integer (1–10) — retrieval depth

**Response:** JSON with `config` (effects chain parameter object), `reasoning` (GPT-4o explanation), `sources`, and `usage`

### POST /synthdef
Generates SuperCollider (sclang) code from engine configuration.

**Request body:**
- `generator`: string — `glitch_click`, `noise_burst`, or `fm_blip`
- `generator_params`: object — optional generator-specific parameters
- `effects`: object — per-block parameter overrides and skip list
- `pattern`: object — optional pattern configuration (euclidean/probabilistic/density)
- `mode`: string — `studio` (full script) or `live` (hot-swap)
- `include_pattern`: boolean — include pattern scheduling code
- `bpm`: integer — tempo (default: 120)
- `bus_offset`: integer — starting bus number for SynthDef routing

**Response:** JSON with `code` (sclang string), `target`, `mode`, `warnings`, `unmapped_params`, `metadata` (SynthDef names, bus allocation, effects chain), `setup_notes`

### POST /tidal
Generates TidalCycles (Haskell DSL) code from engine configuration.

**Request body:** Same as `/synthdef`

**Response:** JSON with `code` (Tidal pattern string), `target`, `mode`, `warnings`, `unmapped_params`, `metadata` (sound name, orbit assignments, BPM), `setup_notes`

---

## 11. Troubleshooting

### StatusBar shows disconnected
The frontend polls `/health` every 30 seconds. If the indicator is red:
1. Verify the API server is running: `curl http://localhost:8000/health`
2. Check that the port matches (default: 8000)
3. Verify CORS origins include your frontend URL (default: `localhost:5173`)

### No audio on Play
Web Audio API requires user interaction before first playback (browser security policy). Click Play again after the first attempt — most browsers unlock audio context on the second user gesture.

### Generated samples are silent or extremely quiet
1. Check if all effects blocks are skipped — raw generator output without the effects chain may be very short duration
2. Verify the Generator selector is set to a valid generator
3. Check the waveform display — a flat line indicates no signal generation; a visible waveform with no audio suggests a Web Audio routing issue

### Advisor/Composer returns empty or generic responses
1. Verify `OPENAI_API_KEY` is set and valid
2. Verify `QDRANT_URL` and `QDRANT_API_KEY` are set and the collection is accessible
3. Increase the context chunks slider — too few chunks may not provide sufficient grounding
4. Check Langfuse traces (if configured) for LLM completion errors

### Reverb/delay effects are inaudible
This was resolved in the March 26, 2026 session. The fix (2s tail padding) is included in V1. If effects still appear inaudible:
1. Ensure blocks 5 (reverb) and 6 (delay) are not in the skip list
2. Increase reverb decay time or delay feedback
3. Check the dry/wet mix — a low wet value will make spatial effects imperceptible

### Tests fail after environment changes
```bash
conda activate idm
pytest -v
```
Expected: 318/318 backend (317 passed, 1 skipped) + 48/48 frontend. If tests fail, verify that the conda environment matches `environment.yml` and that no dependency versions have drifted.

**Frontend tests:**
```bash
cd frontend && npx vitest run
```

---

## 12. Glossary

For the full technical glossary (30+ terms), see **THE_MASTER_DATASET_SPECIFICATION.md**, Part 16.2.

Key terms used in this manual:

| Term | Definition |
|------|-----------|
| Anti-GIGO | "Garbage In, Garbage Out" prevention — enforcing bandwidth limits, noise floors, and saturation curves to maintain historical accuracy |
| Braindance | Experimental electronic music focused on complex rhythms and hardware manipulation (term: Rephlex Records) |
| Chord memory | Triggering a parallel harmonic stack (e.g., Minor 9th) from a single note |
| DR (Dynamic Range) | Measured loudness range of audio; DR 8–10 is the target for 1990s underground mastering |
| Euclidean rhythm | Even distribution of k pulses across n steps (Bjorklund algorithm) |
| PPQN | Pulses Per Quarter Note — sequencer timing resolution (96 PPQN for TR-909, EP-133) |
| RAG | Retrieval-Augmented Generation — grounding LLM responses in retrieved knowledge base content |
| Schroeder diffusion | Reverb architecture using allpass filters and comb filters in series/parallel (Quadraverb implementation) |
| SY-1 | Teenage Engineering sync protocol via 3.5mm mini-jack |
| Tail padding | 2s silence appended before effects chain processing to allow reverb/delay decay |
