"""engine.ml — Layers 3–5 of the IDM Generative System pipeline.

Pipeline layer: 3–5
Consumes:       02-Knowledge/supporting/profiles/*.md (6 regional profile spokes)
                02-Knowledge/supporting/resonance/*.md (5 resonance rule spokes)
Consumed by:    Layer 6 (XGBoost training + /tuning endpoint)
Status:         working (Layer 3 complete, Layer 4 complete S6, Layer 5 complete S6)

Exposes Layer 2 specifications (regional profile spokes and resonance rule
spokes) from ``02-Knowledge/supporting/`` as typed, loadable objects and pure
functions for downstream layers.

The spoke documents are the source of truth. This package loads from them; it
does not duplicate their values. Any profile or rule parameter that lives
only in Python code is a spec violation.

Public API — regional profiles and their composed specs:
    RegionalProfile          — top-level frozen dataclass per region
    SwingSpec                — tempo / swing / timing sub-spec
    ReverbSpec               — reverb sub-spec (Optional on RegionalProfile)
    SaturationSpec           — saturation / non-linear distortion sub-spec
    HarmonicContentSpec      — source synthesis + harmonic content sub-spec
    NoiseSpec                — sub-bass + noise-floor sub-spec (Optional)
    RegionCode               — Literal["DETROIT_FIRST_WAVE", ...]
    SubRegion                — Literal["TOKYO", "OSAKA"]
    load_profile             — memoised single-profile loader
    all_profiles             — load all six profiles in canonical form
    SpokeParseError          — raised on any parse / validation failure

Public API — resonance rules (physical — 4):
    bpm_to_hz                — BPM → audible harmonic
    AudibleHarmonic          — return type of bpm_to_hz
    schumann_mode            — Earth-ionosphere cavity mode n → Hz
    schumann_bpm_anchor      — Schumann mode → BPM anchor
    SCHUMANN_MODES_HZ        — canonical mode frequencies
    midi_to_hz, hz_to_midi   — 12-TET conversions with tuning override
    hz_to_nearest_note       — Hz → nearest 12-TET note (scientific pitch)
    tuning_difference_hz     — A4 reference delta (e.g. 432 vs 440)
    TuningReference          — Literal[432.0, 440.0]
    mains_hum_profile        — regional mains-hum harmonic stack
    MainsHarmonic            — single mains-hum harmonic
    RegionalNoiseFloor       — full mains-hum profile for a grid region
    GridRegion               — Literal["UK", "JP_TOKYO", "US", "JP_OSAKA"]
    GRID_HZ                  — grid fundamental per region

Public API — resonance rules (aesthetic — 1):
    solfeggio_cutoff_seed    — profile → Solfeggio seed Hz (NON-PHYSICAL)
    SOLFEGGIO_HZ             — full Solfeggio frequency table by label
    REGIONAL_SOLFEGGIO_SEED  — per-region seed assignment

Public API — deterministic mapper (Layer 3 — complete S5):
    deterministic_map        — scene + track → tuning + resonant stack
    DeterministicMapping     — structured mapper output
    ResonantPoint            — one resonant frequency + provenance tag

Public API — Gaussian noise injection (Layer 4 — complete S6):
    GaussianNoiseInjector    — calibrated perturbation around mapper output
    PerturbationConfig       — per-parameter sigma configuration

Public API — synthetic dataset generation (Layer 5 — complete S6):
    SyntheticDatasetGenerator — composes Layers 3+4 → pd.DataFrame
    TrackSpec                — frozen input spec for one track/scene
"""

from __future__ import annotations

from engine.ml.deterministic_mapper import (
    DeterministicMapping,
    ResonantPoint,
    deterministic_map,
)
from engine.ml.gaussian_noise import (
    GaussianNoiseInjector,
    PerturbationConfig,
)
from engine.ml.dataset_generator import (
    SyntheticDatasetGenerator,
    TrackSpec,
)
from engine.ml.regional_profiles import (
    HarmonicContentSpec,
    NoiseSpec,
    RegionalProfile,
    RegionCode,
    ReverbSpec,
    SaturationSpec,
    SpokeParseError,
    SubRegion,
    SwingSpec,
    all_profiles,
    load_profile,
)
from engine.ml.resonance_rules import (
    GRID_HZ,
    REGIONAL_SOLFEGGIO_SEED,
    SCHUMANN_MODES_HZ,
    SOLFEGGIO_HZ,
    AudibleHarmonic,
    GridRegion,
    MainsHarmonic,
    RegionalNoiseFloor,
    TuningReference,
    bpm_to_hz,
    hz_to_midi,
    hz_to_nearest_note,
    mains_hum_profile,
    midi_to_hz,
    schumann_bpm_anchor,
    schumann_mode,
    solfeggio_cutoff_seed,
    tuning_difference_hz,
)

__all__ = [
    # --- Regional profiles --------------------------------------------------
    "RegionalProfile",
    "SwingSpec",
    "ReverbSpec",
    "SaturationSpec",
    "HarmonicContentSpec",
    "NoiseSpec",
    "RegionCode",
    "SubRegion",
    "load_profile",
    "all_profiles",
    "SpokeParseError",
    # --- Resonance rules — physical ----------------------------------------
    "bpm_to_hz",
    "AudibleHarmonic",
    "schumann_mode",
    "schumann_bpm_anchor",
    "SCHUMANN_MODES_HZ",
    "midi_to_hz",
    "hz_to_midi",
    "hz_to_nearest_note",
    "tuning_difference_hz",
    "TuningReference",
    "mains_hum_profile",
    "MainsHarmonic",
    "RegionalNoiseFloor",
    "GridRegion",
    "GRID_HZ",
    # --- Resonance rules — aesthetic (NON-PHYSICAL) ------------------------
    "solfeggio_cutoff_seed",
    "SOLFEGGIO_HZ",
    "REGIONAL_SOLFEGGIO_SEED",
    # --- Deterministic mapper (Layer 3) ------------------------------------
    "deterministic_map",
    "DeterministicMapping",
    "ResonantPoint",
    # --- Gaussian noise injection (Layer 4) --------------------------------
    "GaussianNoiseInjector",
    "PerturbationConfig",
    # --- Synthetic dataset generation (Layer 5) ----------------------------
    "SyntheticDatasetGenerator",
    "TrackSpec",
]
