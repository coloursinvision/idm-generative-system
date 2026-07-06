# IDM — device & domain reference

Hardware-era and regional domain knowledge. Facts marked **UNVERIFIED**
come from vault docs still in `draft` status — never present them as settled.

## Contents

1. [Target devices: PO-33 and EP-133](#1-target-devices)
2. [Modelled hardware per effect block](#2-modelled-hardware-per-effect-block)
3. [Environmental "anti-GIGO" constraints](#3-environmental-constraints)
4. [Regional profiles](#4-regional-profiles)
5. [Resonance / frequency rules](#5-resonance--frequency-rules)

## 1. Target devices

**Teenage Engineering PO-33 KO!** — pocket sampler. One pattern lane in the app's
guide; samples imported via audio (hence the 24-bit/44.1 kHz export contract —
it survives the device's ingest path best).

**Teenage Engineering EP-133 KO II** — 4 sample groups (A=drums, B=bass,
C=melody, D=samples), 12 pads per group. Hardware truths the app must respect:

- **One global BPM** for all groups (per the hardware manual) — per-group BPM
  contradicts the device; polyrhythm is achieved by per-group timing stride
  over a single master clock, never by separate transports.
- The hardware runs a master compressor on the output bus — the app mirrors
  this (`gain(0.35) → DynamicsCompressor`).
- Solo overrides mute on the mixer.
- Hardware note: `CR-1604` in this codebase means the **Mackie CR-1604 mixing
  console** (a modelled hardware unit), not any kind of ticket — the same goes
  for TB-303, TR-808/909, SP-1200, S950, SH-101, DX100, RE-201, Quadraverb,
  Alesis 3630. These names must survive any comment/reference cleanup.

## 2. Modelled hardware per effect block

Chain order and the era hardware each block emulates:

| # | Block (module) | Modelled hardware | Character |
|---|---|---|---|
| 1 | NoiseFloor (`noise_floor.py`) | studio noise floor + mains hum | −78 dB RMS default; hum type `hum_uk` (50 Hz) / US (60 Hz); crosstalk −65 dB |
| 2 | Bitcrusher (`bitcrusher.py`) | E-mu SP-1200 (12-bit), Akai S950 | sample-rate/bit-depth reduction, era grit |
| 3 | ResonantFilter (`filter.py`) | analog ladder/SVF behaviour | resonant LPF, self-oscillation territory |
| 4 | Saturation (`saturation.py`) | console/tape drive incl. Mackie CR-1604 | asymmetric tanh curves |
| 5 | Reverb (`reverb.py`) | Alesis Quadraverb (1988, 16-bit hybrid) | comb + allpass diffusion; UK-era bandwidth ~11 kHz, diffusion >0.8 |
| 6 | TapeDelay (`delay.py`) | Roland RE-201 Space Echo | wow/flutter modulated delay |
| 7 | SpatialProcessor (`spatial.py`) | mixing-desk width/pan tricks | stereo field shaping |
| 8 | GlitchEngine (`glitch.py`) | Ensoniq ASR-10 loop-point abuse | int16 XOR corruption, retrigger/micro-edit |
| 9 | Compressor (`compressor.py`) | Alesis 3630 | era bus compression |
| 10 | VinylMastering (`vinyl.py`) | vinyl pre-emphasis + DAT ceiling | RIAA pre-emphasis → brick-wall → surface noise |

DAT bandwidth-ceiling presets in `vinyl.py` (verified):
`dat_lp` = 16 kHz, `dat_sp` = 20 kHz, `cd` = 22.05 kHz, `none` = bypass.

## 3. Environmental constraints

The "anti-GIGO" rules that keep output era-authentic rather than clinically
clean (from the frozen V1 DSP reference; defaults verified in code):

- Noise floor present at **−78 dB RMS** by default (never digital silence).
- Bandwidth ceiling per era medium (see DAT presets above).
- Micro-timing: swing/jitter, not grid-perfect quantisation; MPC60-style
  nonlinear swing for Detroit material; PPQN-conscious timing (UK profile
  uses 192).
- Dynamic range target ~8–10 dB (era mastering), asymmetric saturation.
- Acid (TB-303) model: recursive one-pole glide, default `slide_time_ms=50`;
  accent couples level + filter envelope.

## 4. Regional profiles

Six profiles, editorially owned by the vault spokes
(`02-Knowledge/supporting/profiles/`), consumed by
`engine/ml/regional_profiles.py` (needs `IDM_VAULT_PATH`). Key parameters —
status per spoke frontmatter:

| Region | Status | Signature (selected params) |
|---|---|---|
| `DETROIT_FIRST_WAVE` | complete | 118–132 BPM, 60 Hz grid, MPC60 nonlinear swing 0.54, FM-inharmonic chords (DX100 minor-9th stacks) |
| `DETROIT_UR` | **draft — UNVERIFIED** (gain-staging methodology open) | 128–145 BPM, swing 0.50, heavy asymmetric-tanh 909 overdrive |
| `DREXCIYA` | **draft — UNVERIFIED** (sub-bass values derived from criticism, not spectral measurement) | sub-bass 35 Hz dominance, mid cut −6…−12 dB, long reverb, wide stereo |
| `JAPAN_IDM` | **draft — UNVERIFIED** (Tokyo/Osaka 50/60 Hz split is a hypothesis) | high-fidelity, soft-knee, 100% key tracking, noise floor −85 dB (intentional outlier), sub_region TOKYO/OSAKA |
| `UK_IDM` | **draft — UNVERIFIED** (Aphex 432 Hz hypothesis open) | 110–145 BPM, 50 Hz grid, Quadraverb-heavy (bw 11 kHz, diffusion 0.85), PPQN 192, vinyl noise on |
| `UK_BRAINDANCE` | complete | 140–200 BPM, inverse swing −4…−8 ms, retrigger 10–35 ms, pitch ramp +12 st, S950 grain 40–100 Hz |

When code and a spoke disagree on a value, report the discrepancy — the spokes
are the editorial source, but the code is what ships.

## 5. Resonance / frequency rules

Five rules (vault `02-Knowledge/supporting/resonance/`, mirrored in
`engine/ml/resonance_rules.py`). Critical taxonomy: four are **physical**, one
(Solfeggio) is **aesthetic-conventional** — the code and any explanation must
keep that distinction; collapsing them misrepresents the methodology.

- **BPM→Hz** (physical): `f = BPM/60 × 2^n`, octave-shifted into audio range,
  nearest-12-TET pitch identified. Pure math; safe to rely on.
- **Schumann resonances** (physical): ELF modes 7.83/14.3/20.8/27.3/33.8 Hz as
  sub-audio LFO/tempo anchors (117.45 BPM anchor). The project explicitly
  disclaims metaphysical/healing readings — preserve that stance.
- **Mains hum** (physical): 50 Hz grid (UK, Tokyo) is G-centred, 60 Hz grid
  (US, Osaka) is B-centred; feeds NoiseFloor hum tonality.
- **432 vs 440 tuning** (physical arithmetic, spoke in draft): the popular
  claim "C4 = 256 Hz exactly under 432 Hz tuning" is **arithmetically false**
  under 12-TET (exact 256 Hz would need A4 ≈ 430.539 Hz). Older hub text
  asserting it is wrong — always use the corrected version. Operationally,
  `tuning_hz` is a constant 440.0 in the ML pipeline (see `idm-ml-pipeline`).
- **Solfeggio filter seeding** (aesthetic convention, draft): Solfeggio
  frequencies used only as deterministic filter-cutoff seeds; the per-region
  seed map (UR=396, Japan=528, UK=741, Drexciya=852) is **speculative** —
  flag it as such wherever it surfaces.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `03-Code/DSP.md` (frozen V1),
`02-Knowledge/THE_MASTER_DATASET_SPECIFICATION.md`, the profile and resonance
spokes under `02-Knowledge/supporting/`, `03-Code/EP133_BUG_SCOPE_2026-05-27.md`.
Numeric defaults verified against `develop` v0.10.1 (2026-07-05); draft-status
hypotheses are labelled UNVERIFIED above.*
