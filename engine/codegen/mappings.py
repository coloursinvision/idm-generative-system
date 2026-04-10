"""
engine/codegen/mappings.py

Central parameter translation layer for the IDM Generative System codegen module.

Maps every Python engine parameter (generators, effects, patterns) to its
SuperCollider and TidalCycles equivalent. Provides value transforms for
range/unit conversions and tracks unmappable parameters explicitly.

Architecture:
    - Pure data module — no I/O, no audio, no dependencies beyond stdlib
    - Consumed by synthdef.py and tidal.py via lookup helpers
    - Single source of truth for all parameter translations
    - Every engine parameter is either mapped or in UNMAPPED_* sets (zero silent drops)

Usage:
    from engine.codegen.mappings import (
        get_sc_generator, get_sc_effect_params,
        get_tidal_effect_params, get_tidal_pattern,
        SC_GENERATORS, TIDAL_GENERATORS,
    )
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParamMapping:
    """Single parameter mapping from Python engine to a target language.

    Attributes:
        target_name:  Name in target language (SC arg name / Tidal effect name).
        transform:    Callable to convert Python value → target value.
                      None means identity (pass-through).
        default:      Default value in the target language.
        description:  Human-readable note for code comments.
        approximate:  True if this is not a 1:1 mapping (triggers a warning).
    """

    target_name: str
    transform: Callable[[Any], Any] | None = None
    default: Any = None
    description: str = ""
    approximate: bool = False


@dataclass(frozen=True, slots=True)
class GeneratorMapping:
    """Generator mapping — Python sample generator to target language.

    Attributes:
        python_name:     Python function name (e.g. 'fm_blip').
        sc_name:         SuperCollider SynthDef name (e.g. 'idm_fm_blip').
        sc_ugens:        Primary SC UGens used in the SynthDef.
        tidal_name:      TidalCycles sound name.
        params:          Dict of Python param name → ParamMapping (SC-specific).
        tidal_params:    Dict of Python param name → ParamMapping (Tidal-specific).
        description:     Human-readable description.
    """

    python_name: str
    sc_name: str
    sc_ugens: list[str]
    tidal_name: str
    params: dict[str, ParamMapping] = field(default_factory=dict)
    tidal_params: dict[str, ParamMapping] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True, slots=True)
class EffectBlockMapping:
    """Effect block mapping — Python effect class to target language.

    Attributes:
        block_key:       Canonical chain key (e.g. 'reverb', 'delay').
        python_class:    Python class name (e.g. 'Reverb').
        sc_name:         SuperCollider SynthDef name for this effect.
        sc_ugens:        Primary SC UGens used.
        sc_params:       Python param name → SC ParamMapping.
        tidal_params:    Python param name → Tidal ParamMapping.
        unmapped_sc:     Params with no SC equivalent (documented, not dropped).
        unmapped_tidal:  Params with no Tidal equivalent.
        description:     Human-readable description.
        chain_position:  Position in canonical chain (1-10).
    """

    block_key: str
    python_class: str
    sc_name: str
    sc_ugens: list[str]
    sc_params: dict[str, ParamMapping] = field(default_factory=dict)
    tidal_params: dict[str, ParamMapping] = field(default_factory=dict)
    unmapped_sc: dict[str, str] = field(default_factory=dict)
    unmapped_tidal: dict[str, str] = field(default_factory=dict)
    description: str = ""
    chain_position: int = 0


# ---------------------------------------------------------------------------
# Value transforms — named functions for clarity and testability
# ---------------------------------------------------------------------------


def _ms_to_s(ms: float) -> float:
    """Milliseconds → seconds."""
    return ms / 1000.0


def _db_to_linear(db: float) -> float:
    """Decibels → linear amplitude."""
    return float(10.0 ** (db / 20.0))


def _resonance_to_rq(res: float) -> float:
    """Python resonance [0–1] → SC reciprocal-Q for RLPF/RHPF.

    res=0 → rq=1.0 (no resonance, wide bandwidth)
    res=1 → rq=0.01 (extreme resonance, narrow bandwidth)
    Logarithmic mapping for perceptually linear control.
    """
    clamped = max(0.0, min(res, 0.99))
    return float(max(10.0 ** (-clamped * 2.0), 0.01))


def _feedback_to_decaytime(feedback: float, delay_s: float = 0.375) -> float:
    """Feedback coefficient [0–0.98] → CombC decaytime in seconds.

    Based on: decaytime = -3 * delay / log10(feedback)
    Clamped to [0.01, 60.0] for safety.
    """
    fb = max(abs(feedback), 0.001)
    if fb >= 1.0:
        return 60.0
    decay = -3.0 * delay_s / math.log10(fb)
    return float(max(0.01, min(decay, 60.0)))


def _drive_to_pregain(drive: float) -> float:
    """Saturation drive [0.1–10] → SC pre-gain multiplier.

    Maps to a range suitable for tanh soft-clipping in SC.
    """
    return max(0.1, drive)


def _ratio_to_slope_above(ratio: float) -> float:
    """Compression ratio → Compander slopeAbove.

    ratio=1 → slope=1.0 (no compression)
    ratio=4 → slope=0.25
    ratio=20 → slope=0.05
    """
    return 1.0 / max(ratio, 1.0)


def _knee_to_clamp(knee_db: float) -> float:
    """Soft knee width → Compander clampTime approximation.

    Wider knee ≈ slower onset. Maps to [0.001, 0.05] range.
    """
    return float(0.001 + (knee_db / 20.0) * 0.049)


def _width_to_sc(width: float) -> float:
    """Stereo width [0–2] → SC Splay spread parameter [0–1]."""
    return max(0.0, min(width / 2.0, 1.0))


def _riaa_to_sc_shelf(intensity: float) -> tuple[float, float]:
    """RIAA intensity [0–1] → (bass_db, treble_db) shelf gains.

    Approximates the RIAA curve as two shelving EQ bands.
    """
    bass_boost = intensity * 3.0  # up to +3 dB bass
    treble_cut = intensity * -4.0  # up to -4 dB treble
    return (bass_boost, treble_cut)


def _crush_to_tidal(bit_depth: int) -> float:
    """Python bit_depth [4–24] → Tidal # crush [1–16].

    Tidal crush: lower = more crushed. Inverted and scaled.
    """
    return max(1.0, min(float(bit_depth) / 1.5, 16.0))


def _sr_reduction_to_coarse(factor: int) -> float:
    """Sample rate reduction factor [1–16] → Tidal # coarse [0–1].

    coarse=0: no reduction. coarse=1: maximum reduction.
    """
    return max(0.0, min((factor - 1) / 15.0, 1.0))


def _decay_to_tidal_sz(decay_s: float) -> float:
    """Reverb decay [0.1–10] → Tidal # sz (room size) [0–1].

    Logarithmic mapping: sz=0.5 ≈ 2.5s decay.
    """
    return max(0.0, min(math.log10(decay_s + 0.1) / math.log10(10.1), 1.0))


def _delay_ms_to_tidal(ms: float, bpm: float = 120.0) -> float:
    """Delay time in ms → Tidal # delaytime [0–1] (cycles).

    Converts absolute delay time to cycle-relative time at given BPM.
    """
    cycle_ms = 60000.0 / bpm * 4  # one cycle = 4 beats at given BPM
    return max(0.0, min(ms / cycle_ms, 1.0))


def _feedback_to_tidal(feedback: float) -> float:
    """Feedback [0–0.98] → Tidal # delayfeedback [0–1]."""
    return max(0.0, min(feedback, 1.0))


def _cutoff_to_tidal(hz: float) -> float:
    """Cutoff frequency Hz → Tidal # lpf / # hpf (Hz, direct pass-through)."""
    return hz


def _resonance_to_tidal(res: float) -> float:
    """Resonance [0–1] → Tidal # resonance [0–1] (direct)."""
    return res


def _drive_to_tidal_distort(drive: float) -> float:
    """Saturation drive [0.1–10] → Tidal # distort [0–1].

    Logarithmic mapping: drive=1 → ~0.1, drive=5 → ~0.7, drive=10 → 1.0.
    """
    return max(0.0, min(math.log10(drive + 0.1) / math.log10(10.1), 1.0))


def _pan_to_tidal(pan: float) -> float:
    """Pan [-1, 1] → Tidal # pan [0, 1].

    Python: -1=left, 0=center, 1=right
    Tidal:   0=left, 0.5=center, 1=right
    """
    return (pan + 1.0) / 2.0


# ---------------------------------------------------------------------------
# Generator mappings
# ---------------------------------------------------------------------------

SC_GENERATORS: dict[str, GeneratorMapping] = {
    "glitch_click": GeneratorMapping(
        python_name="glitch_click",
        sc_name="idm_glitch_click",
        sc_ugens=["WhiteNoise", "EnvGen", "Env.perc"],
        tidal_name="click",
        params={
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.2,
                description="Duration in seconds",
            ),
            "decay": ParamMapping(
                target_name="decay_rate",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.25,
                description="Envelope release time (inverse of Python decay rate)",
            ),
        },
        tidal_params={
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.2,
                description="Note sustain in seconds",
            ),
            "decay": ParamMapping(
                target_name="release",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.25,
                description="Envelope release",
            ),
        },
        description="Percussive glitch click — band-limited noise with exponential decay",
    ),
    "noise_burst": GeneratorMapping(
        python_name="noise_burst",
        sc_name="idm_noise_burst",
        sc_ugens=["WhiteNoise", "LPF", "EnvGen", "Env.perc"],
        tidal_name="noise",
        params={
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.5,
                description="Duration in seconds",
            ),
            "tone": ParamMapping(
                target_name="lpf_mix",
                transform=None,
                default=0.3,
                description="Low-pass blend ratio (0=white, 1=filtered)",
            ),
            "decay": ParamMapping(
                target_name="decay_rate",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.333,
                description="Envelope release time",
            ),
        },
        tidal_params={
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.5,
                description="Note sustain in seconds",
            ),
            "tone": ParamMapping(
                target_name="lpf",
                transform=lambda t: 200.0 + (1.0 - t) * 15000.0,
                default=10700.0,
                description="Tone mapped to LPF cutoff (tone=0 → open, tone=1 → dark)",
                approximate=True,
            ),
            "decay": ParamMapping(
                target_name="release",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.333,
                description="Envelope release",
            ),
        },
        description="Filtered noise burst with tone control",
    ),
    "fm_blip": GeneratorMapping(
        python_name="fm_blip",
        sc_name="idm_fm_blip",
        sc_ugens=["SinOsc", "EnvGen", "Env.perc"],
        tidal_name="supermandolin",
        params={
            "freq": ParamMapping(
                target_name="freq",
                transform=None,
                default=300.0,
                description="Carrier frequency in Hz",
            ),
            "mod_freq": ParamMapping(
                target_name="mod_freq",
                transform=None,
                default=80.0,
                description="Modulator frequency in Hz",
            ),
            "mod_index": ParamMapping(
                target_name="mod_index",
                transform=None,
                default=2.0,
                description="FM modulation index",
            ),
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.5,
                description="Duration in seconds",
            ),
            "decay": ParamMapping(
                target_name="decay_rate",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.333,
                description="Envelope release time",
            ),
        },
        tidal_params={
            "freq": ParamMapping(
                target_name="freq",
                transform=None,
                default=300.0,
                description="Note frequency (can also use 'note' or 'n' in Tidal)",
            ),
            "mod_freq": ParamMapping(
                target_name="fmod",
                transform=None,
                default=80.0,
                description="FM modulator frequency",
                approximate=True,
            ),
            "mod_index": ParamMapping(
                target_name="imod",
                transform=None,
                default=2.0,
                description="FM modulation depth",
                approximate=True,
            ),
            "length_ms": ParamMapping(
                target_name="sustain",
                transform=_ms_to_s,
                default=0.5,
                description="Note sustain",
            ),
            "decay": ParamMapping(
                target_name="release",
                transform=lambda d: 1.0 / max(d, 0.1),
                default=0.333,
                description="Envelope release",
            ),
        },
        description="FM synthesis blip — single operator pair (modulator → carrier)",
    ),
}


# ---------------------------------------------------------------------------
# Effect block mappings — SuperCollider
# ---------------------------------------------------------------------------

SC_EFFECTS: dict[str, EffectBlockMapping] = {
    "noise_floor": EffectBlockMapping(
        block_key="noise_floor",
        python_class="NoiseFloor",
        sc_name="idm_fx_noise_floor",
        sc_ugens=["PinkNoise", "SinOsc", "In", "Out", "ReplaceOut"],
        sc_params={
            "noise_floor_db": ParamMapping(
                target_name="noise_amp",
                transform=_db_to_linear,
                default=0.000126,
                description="Noise floor amplitude (linear)",
            ),
            "hum_freq": ParamMapping(
                target_name="hum_freq",
                transform=None,
                default=50.0,
                description="Mains hum frequency in Hz",
            ),
            "crosstalk_db": ParamMapping(
                target_name="crosstalk_amp",
                transform=_db_to_linear,
                default=0.000562,
                description="Bus crosstalk amplitude (linear)",
            ),
        },
        unmapped_sc={
            "noise_type": "Controlled via SynthDef variant selection (pink/white/hum)",
        },
        description="Analogue noise floor — Mackie CR-1604 bus emulation",
        chain_position=1,
    ),
    "bitcrusher": EffectBlockMapping(
        block_key="bitcrusher",
        python_class="Bitcrusher",
        sc_name="idm_fx_bitcrusher",
        sc_ugens=["Decimator", "Latch", "Impulse", "In", "ReplaceOut"],
        sc_params={
            "bit_depth": ParamMapping(
                target_name="bits",
                transform=lambda b: float(b),
                default=12.0,
                description="Target bit depth for Decimator UGen",
            ),
            "sample_rate_reduction": ParamMapping(
                target_name="downsamp_rate",
                transform=lambda f: 44100.0 / max(f, 1),
                default=44100.0,
                description="Effective sample rate after reduction",
            ),
        },
        unmapped_sc={
            "dither": "SC Decimator has no built-in dither; add manual TPDF if needed",
            "mode": "SC Decimator uses fixed quantisation (round); truncate/floor "
            "require manual implementation",
            "hardware_preset": "Resolved to bit_depth + sample_rate_reduction before codegen",
        },
        description="DAC emulation — bit depth and sample rate reduction",
        chain_position=2,
    ),
    "filter": EffectBlockMapping(
        block_key="filter",
        python_class="ResonantFilter",
        sc_name="idm_fx_filter",
        sc_ugens=["RLPF", "RHPF", "BPF", "In", "ReplaceOut"],
        sc_params={
            "cutoff_hz": ParamMapping(
                target_name="freq",
                transform=None,
                default=1200.0,
                description="Filter cutoff frequency in Hz",
            ),
            "resonance": ParamMapping(
                target_name="rq",
                transform=_resonance_to_rq,
                default=0.5,
                description="Reciprocal Q — lower rq = narrower bandwidth = more resonance",
            ),
            "accent": ParamMapping(
                target_name="accent",
                transform=None,
                default=0.0,
                description="TB-303 accent coupling (drives resonance boost + tanh saturation)",
            ),
            "envelope_mod": ParamMapping(
                target_name="env_mod",
                transform=None,
                default=0.5,
                description="Filter envelope modulation depth",
            ),
        },
        unmapped_sc={
            "filter_type": "Controlled via UGen selection (RLPF/RHPF/BPF) in SynthDef template",
            "poles": "Controlled via UGen selection and cascading in SynthDef template",
        },
        description="VCF emulation — TB-303 / SH-101 resonant filter",
        chain_position=3,
    ),
    "saturation": EffectBlockMapping(
        block_key="saturation",
        python_class="Saturation",
        sc_name="idm_fx_saturation",
        sc_ugens=["In", "ReplaceOut"],
        sc_params={
            "drive": ParamMapping(
                target_name="drive",
                transform=_drive_to_pregain,
                default=1.5,
                description="Pre-gain before tanh soft-clipping",
            ),
            "mix": ParamMapping(
                target_name="mix",
                transform=None,
                default=0.8,
                description="Dry/wet blend",
            ),
            "output_gain": ParamMapping(
                target_name="out_gain",
                transform=None,
                default=1.0,
                description="Post-saturation output level",
            ),
        },
        unmapped_sc={
            "mode": "Controlled via SynthDef variant (asymmetric/symmetric/tanh/wavefold); "
            "default SynthDef uses asymmetric (MASTER_DATASET Part 5 formula)",
        },
        description="Console saturation — asymmetric soft-clipper (Mackie CR-1604)",
        chain_position=4,
    ),
    "reverb": EffectBlockMapping(
        block_key="reverb",
        python_class="Reverb",
        sc_name="idm_fx_reverb",
        sc_ugens=["FreeVerb", "In", "ReplaceOut"],
        sc_params={
            "decay_s": ParamMapping(
                target_name="room",
                transform=lambda d: max(0.0, min(d / 10.0, 1.0)),
                default=0.25,
                description="FreeVerb room size [0–1] (mapped from decay 0–10s)",
                approximate=True,
            ),
            "mix": ParamMapping(
                target_name="mix",
                transform=None,
                default=0.25,
                description="Dry/wet blend",
            ),
            "hf_decay": ParamMapping(
                target_name="damp",
                transform=lambda hf: 1.0 - max(0.0, min(hf, 1.0)),
                default=0.6,
                description="FreeVerb damping (inverse of HF decay)",
            ),
            "pre_delay_ms": ParamMapping(
                target_name="predelay",
                transform=_ms_to_s,
                default=0.015,
                description="Pre-delay in seconds (requires DelayN before FreeVerb)",
            ),
        },
        unmapped_sc={
            "reverb_type": "FreeVerb has no type parameter; use GVerb or custom Schroeder "
            "for type-specific character. Reverb type noted in code comments",
            "diffusion": "FreeVerb has no diffusion control; affects Schroeder allpass gains",
            "density": "FreeVerb has no density control; affects comb filter feedback blend",
            "lf_decay": "FreeVerb has no LF decay; use BHiShelf in sidechain for approximation",
            "colour": "Approximated via post-reverb EQ shelf if non-zero",
        },
        description="Reverb — FreeVerb approximation of Quadraverb Schroeder architecture",
        chain_position=5,
    ),
    "delay": EffectBlockMapping(
        block_key="delay",
        python_class="TapeDelay",
        sc_name="idm_fx_delay",
        sc_ugens=["CombC", "DelayC", "SinOsc", "LPF", "In", "ReplaceOut"],
        sc_params={
            "delay_ms": ParamMapping(
                target_name="delaytime",
                transform=_ms_to_s,
                default=0.375,
                description="Delay time in seconds",
            ),
            "feedback": ParamMapping(
                target_name="decaytime",
                transform=lambda fb: _feedback_to_decaytime(fb),
                default=3.0,
                description="CombC decay time (derived from feedback coefficient)",
                approximate=True,
            ),
            "tape_saturation": ParamMapping(
                target_name="sat_drive",
                transform=lambda s: 1.0 + s * 3.0,
                default=2.2,
                description="Saturation gain in feedback path (tanh)",
            ),
            "wow_flutter_hz": ParamMapping(
                target_name="mod_freq",
                transform=None,
                default=0.8,
                description="Wow & flutter LFO rate in Hz",
            ),
            "wow_depth": ParamMapping(
                target_name="mod_depth",
                transform=None,
                default=0.004,
                description="Pitch modulation depth",
            ),
            "mix": ParamMapping(
                target_name="mix",
                transform=None,
                default=0.35,
                description="Dry/wet blend",
            ),
        },
        unmapped_sc={
            "tape_age": "Approximated via LPF cutoff in feedback path "
            "(new=14kHz, used=8kHz, worn=4.5kHz)",
        },
        description="Tape delay — Roland Space Echo RE-201 emulation",
        chain_position=6,
    ),
    "spatial": EffectBlockMapping(
        block_key="spatial",
        python_class="SpatialProcessor",
        sc_name="idm_fx_spatial",
        sc_ugens=["Pan2", "LPF", "HPF", "DelayN", "In", "ReplaceOut"],
        sc_params={
            "width": ParamMapping(
                target_name="spread",
                transform=_width_to_sc,
                default=0.5,
                description="Stereo spread [0–1] for mid/side processing",
            ),
            "bass_mono_hz": ParamMapping(
                target_name="mono_freq",
                transform=None,
                default=200.0,
                description="Crossover frequency for bass mono enforcement",
            ),
            "pan": ParamMapping(
                target_name="pos",
                transform=None,
                default=0.0,
                description="Pan position [-1, 1] for Pan2",
            ),
            "decorrelation": ParamMapping(
                target_name="decorr",
                transform=lambda d: d * 0.023,
                default=0.0,
                description="Haas delay in seconds (decorrelation * 23ms)",
            ),
        },
        description="Stereo width — bass mono enforcement + Haas decorrelation",
        chain_position=7,
    ),
    "glitch": EffectBlockMapping(
        block_key="glitch",
        python_class="GlitchEngine",
        sc_name="idm_fx_glitch",
        sc_ugens=["PlayBuf", "BufWr", "BufRd", "SinOsc", "In", "ReplaceOut"],
        sc_params={
            "stutter_density": ParamMapping(
                target_name="stutter_prob",
                transform=None,
                default=0.15,
                description="Probability of stutter per grain window",
            ),
            "stutter_min_ms": ParamMapping(
                target_name="grain_min",
                transform=_ms_to_s,
                default=0.005,
                description="Minimum stutter grain length in seconds",
            ),
            "stutter_max_ms": ParamMapping(
                target_name="grain_max",
                transform=_ms_to_s,
                default=0.06,
                description="Maximum stutter grain length in seconds",
            ),
            "stutter_max_repeats": ParamMapping(
                target_name="max_repeats",
                transform=lambda r: float(r),
                default=8.0,
                description="Maximum repetitions per stutter event",
            ),
            "loop_mod_hz": ParamMapping(
                target_name="loop_rate",
                transform=None,
                default=2.0,
                description="ASR-10 loop modulation LFO rate in Hz",
            ),
            "loop_mod_depth": ParamMapping(
                target_name="loop_depth",
                transform=None,
                default=0.3,
                description="Loop modulation intensity",
            ),
            "mix": ParamMapping(
                target_name="mix",
                transform=None,
                default=0.5,
                description="Dry/wet blend",
            ),
        },
        unmapped_sc={
            "xor_mode": "Approximated via bitwise operations on integer signal representation; "
            "SC equivalent uses .bitXor on integer-scaled signal",
            "xor_density": "Controlled via probabilistic sample-level application mask",
            "loop_window_ms": "Mapped to BufRd offset range in SynthDef template",
            "seed": "SC uses thisThread.randSeed for deterministic sequences",
        },
        description="Glitch engine — stutter + ASR-10 loop mod + XOR bit mangle",
        chain_position=8,
    ),
    "compressor": EffectBlockMapping(
        block_key="compressor",
        python_class="Compressor",
        sc_name="idm_fx_compressor",
        sc_ugens=["Compander", "HPF", "In", "ReplaceOut"],
        sc_params={
            "threshold_db": ParamMapping(
                target_name="thresh",
                transform=_db_to_linear,
                default=0.126,
                description="Compander threshold (linear amplitude)",
            ),
            "ratio": ParamMapping(
                target_name="slopeAbove",
                transform=_ratio_to_slope_above,
                default=0.25,
                description="Compander slope above threshold (1/ratio)",
            ),
            "attack_ms": ParamMapping(
                target_name="attackTime",
                transform=_ms_to_s,
                default=0.01,
                description="Attack time in seconds",
            ),
            "release_ms": ParamMapping(
                target_name="releaseTime",
                transform=_ms_to_s,
                default=0.1,
                description="Release time in seconds",
            ),
            "sidechain_hpf_hz": ParamMapping(
                target_name="sc_hpf_freq",
                transform=None,
                default=80.0,
                description="Sidechain high-pass cutoff in Hz",
            ),
            "mix": ParamMapping(
                target_name="mix",
                transform=None,
                default=1.0,
                description="Dry/wet blend (parallel compression)",
            ),
        },
        unmapped_sc={
            "knee_db": "Compander has no soft knee; approximated via clampTime",
            "auto_release": "Modelled via dual Compander (fast+slow) in SynthDef template",
            "rms_window_ms": "Compander uses built-in RMS detection",
            "makeup_db": "Applied as post-Compander gain stage in SynthDef",
            "auto_makeup": "Calculated and applied as static gain in SynthDef template",
        },
        description="Bus compressor — SSL/Neve/dbx style dynamics",
        chain_position=9,
    ),
    "vinyl": EffectBlockMapping(
        block_key="vinyl",
        python_class="VinylMastering",
        sc_name="idm_fx_vinyl",
        sc_ugens=["LPF", "HPF", "BHiShelf", "BLowShelf", "PinkNoise", "Dust", "In", "ReplaceOut"],
        sc_params={
            "riaa_intensity": ParamMapping(
                target_name="riaa_mix",
                transform=None,
                default=0.3,
                description="RIAA curve depth (crossfade between flat and EQ'd signal)",
            ),
            "noise_mix": ParamMapping(
                target_name="noise_amp",
                transform=None,
                default=0.15,
                description="Surface noise blend level",
            ),
            "limiter_ceiling_db": ParamMapping(
                target_name="ceiling",
                transform=_db_to_linear,
                default=0.966,
                description="Peak limiter ceiling (linear amplitude)",
            ),
        },
        unmapped_sc={
            "dat_mode": "Mapped to LPF cutoff in SynthDef template "
            "(dat_lp=16kHz, dat_sp=20kHz, cd=22.05kHz)",
            "dat_filter_order": "SC LPF is fixed 2nd-order; use cascaded LPFs for steeper roll-off",
            "vinyl_condition": "Resolved to hiss_level + crackle_rate before codegen; "
            "SC uses PinkNoise + Dust UGens",
            "seed": "SC uses thisThread.randSeed for deterministic noise sequences",
        },
        description="Vinyl mastering — RIAA EQ + DAT ceiling + surface noise + limiter",
        chain_position=10,
    ),
}


# ---------------------------------------------------------------------------
# TidalCycles effect mappings
# ---------------------------------------------------------------------------

TIDAL_EFFECTS: dict[str, dict[str, ParamMapping]] = {
    "noise_floor": {},  # No standard SuperDirt equivalent — omitted from Tidal output
    "bitcrusher": {
        "bit_depth": ParamMapping(
            target_name="crush",
            transform=_crush_to_tidal,
            default=8.0,
            description="Tidal bit crush depth (1=extreme, 16=subtle)",
        ),
        "sample_rate_reduction": ParamMapping(
            target_name="coarse",
            transform=_sr_reduction_to_coarse,
            default=0.0,
            description="Sample rate coarsening",
        ),
    },
    "filter": {
        "cutoff_hz": ParamMapping(
            target_name="lpf",
            transform=_cutoff_to_tidal,
            default=1200.0,
            description="Low-pass filter cutoff in Hz (default; overridden by filter_type)",
        ),
        "resonance": ParamMapping(
            target_name="resonance",
            transform=_resonance_to_tidal,
            default=0.3,
            description="Filter resonance",
        ),
    },
    "saturation": {
        "drive": ParamMapping(
            target_name="distort",
            transform=_drive_to_tidal_distort,
            default=0.17,
            description="Distortion amount",
        ),
    },
    "reverb": {
        "mix": ParamMapping(
            target_name="room",
            transform=None,
            default=0.25,
            description="Reverb room amount",
        ),
        "decay_s": ParamMapping(
            target_name="sz",
            transform=_decay_to_tidal_sz,
            default=0.4,
            description="Room size (mapped from decay time)",
            approximate=True,
        ),
    },
    "delay": {
        "delay_ms": ParamMapping(
            target_name="delaytime",
            transform=_delay_ms_to_tidal,
            default=0.1875,
            description="Delay time in cycles",
            approximate=True,
        ),
        "feedback": ParamMapping(
            target_name="delayfeedback",
            transform=_feedback_to_tidal,
            default=0.45,
            description="Delay feedback amount",
        ),
        "mix": ParamMapping(
            target_name="delay",
            transform=None,
            default=0.35,
            description="Delay wet level",
        ),
    },
    "spatial": {
        "pan": ParamMapping(
            target_name="pan",
            transform=_pan_to_tidal,
            default=0.5,
            description="Stereo pan position (0=left, 0.5=center, 1=right)",
        ),
    },
    "glitch": {
        "stutter_density": ParamMapping(
            target_name="squiz",
            transform=lambda d: max(1.0, 2.0 + d * 6.0),
            default=2.0,
            description="Squiz pitch-shifting distortion (nearest stutter approximation)",
            approximate=True,
        ),
    },
    "compressor": {},  # No standard SuperDirt compressor — omitted
    "vinyl": {
        "riaa_intensity": ParamMapping(
            target_name="lpf",
            transform=lambda i: 20000.0 - i * 8000.0,
            default=17600.0,
            description="RIAA treble roll-off approximated as LPF cutoff",
            approximate=True,
        ),
    },
}

# Explicitly unmappable params per effect for Tidal (documented, not silent)
UNMAPPED_TIDAL: dict[str, dict[str, str]] = {
    "noise_floor": {
        "noise_floor_db": "No SuperDirt equivalent — noise floor is a synthesis concept",
        "noise_type": "No SuperDirt equivalent",
        "hum_freq": "No SuperDirt equivalent",
        "crosstalk_db": "No SuperDirt equivalent",
    },
    "bitcrusher": {
        "dither": "No Tidal equivalent — SuperDirt crush has no dither option",
        "mode": "No Tidal equivalent — crush uses fixed quantisation",
        "hardware_preset": "Resolved to bit_depth + sample_rate_reduction before codegen",
    },
    "filter": {
        "filter_type": "Controls which Tidal effect name to use (lpf/hpf/bpf)",
        "poles": "No Tidal equivalent — SuperDirt uses fixed-order filters",
        "accent": "No Tidal equivalent — TB-303 accent coupling",
        "envelope_mod": "No Tidal equivalent — use 'cutoff' pattern modulation instead",
    },
    "saturation": {
        "mode": "No Tidal equivalent — distort uses fixed algorithm",
        "mix": "No separate dry/wet for Tidal distort",
        "output_gain": "Use # gain for output level control",
    },
    "reverb": {
        "reverb_type": "No Tidal equivalent — SuperDirt uses fixed reverb algorithm",
        "pre_delay_ms": "No Tidal equivalent",
        "diffusion": "No Tidal equivalent",
        "density": "No Tidal equivalent",
        "lf_decay": "No Tidal equivalent",
        "hf_decay": "No Tidal equivalent",
        "colour": "No Tidal equivalent",
    },
    "delay": {
        "tape_saturation": "No Tidal equivalent — SuperDirt delay has no saturation",
        "wow_flutter_hz": "No Tidal equivalent",
        "wow_depth": "No Tidal equivalent",
        "tape_age": "No Tidal equivalent",
    },
    "spatial": {
        "width": "No Tidal equivalent — use stereo samples or # leslie for width",
        "bass_mono_hz": "No Tidal equivalent",
        "decorrelation": "No Tidal equivalent",
    },
    "glitch": {
        "stutter_min_ms": "Use pattern subdivision for stutter timing in Tidal",
        "stutter_max_ms": "Use pattern subdivision for stutter timing in Tidal",
        "stutter_max_repeats": "Use pattern repetition operators (* and !) in Tidal",
        "loop_mod_hz": "No Tidal equivalent — use pattern-level modulation",
        "loop_mod_depth": "No Tidal equivalent",
        "loop_window_ms": "No Tidal equivalent",
        "xor_mode": "No Tidal equivalent",
        "xor_density": "No Tidal equivalent",
        "mix": "No separate dry/wet for Tidal squiz",
        "seed": "Tidal uses deterministic cycle evaluation",
    },
    "compressor": {
        "threshold_db": "No standard SuperDirt compressor — use custom SynthDef",
        "ratio": "No standard SuperDirt compressor",
        "attack_ms": "No standard SuperDirt compressor",
        "release_ms": "No standard SuperDirt compressor",
        "knee_db": "No standard SuperDirt compressor",
        "auto_release": "No standard SuperDirt compressor",
        "sidechain_hpf_hz": "No standard SuperDirt compressor",
        "rms_window_ms": "No standard SuperDirt compressor",
        "makeup_db": "No standard SuperDirt compressor",
        "auto_makeup": "No standard SuperDirt compressor",
        "mix": "No standard SuperDirt compressor",
    },
    "vinyl": {
        "dat_mode": "Approximated via # lpf in Tidal",
        "dat_filter_order": "No Tidal equivalent — SuperDirt LPF is fixed order",
        "vinyl_condition": "No Tidal equivalent",
        "noise_mix": "No Tidal equivalent",
        "limiter_ceiling_db": "No Tidal equivalent — use # gain for output control",
        "mix": "No separate dry/wet in Tidal",
        "seed": "Tidal uses deterministic cycle evaluation",
    },
}


# ---------------------------------------------------------------------------
# Tape age → LPF cutoff lookup (used by synthdef.py for delay SynthDef)
# ---------------------------------------------------------------------------

TAPE_AGE_SC_CUTOFF: dict[str, float] = {
    "new": 14000.0,
    "used": 8000.0,
    "worn": 4500.0,
}


# ---------------------------------------------------------------------------
# DAT mode → bandwidth ceiling lookup (used by synthdef.py for vinyl SynthDef)
# ---------------------------------------------------------------------------

DAT_MODE_SC_CUTOFF: dict[str, float] = {
    "dat_lp": 16000.0,
    "dat_sp": 20000.0,
    "cd": 22050.0,
    "none": 0.0,
}


# ---------------------------------------------------------------------------
# Vinyl condition → noise parameters (used by synthdef.py)
# ---------------------------------------------------------------------------

VINYL_CONDITION_SC: dict[str, dict[str, float]] = {
    "mint": {"hiss_amp": 0.0003, "crackle_density": 0.5, "crackle_amp": 0.005},
    "good": {"hiss_amp": 0.0008, "crackle_density": 2.0, "crackle_amp": 0.015},
    "worn": {"hiss_amp": 0.002, "crackle_density": 8.0, "crackle_amp": 0.04},
    "trashed": {"hiss_amp": 0.005, "crackle_density": 32.0, "crackle_amp": 0.08},
}


# ---------------------------------------------------------------------------
# Pattern mapping — Tidal mini-notation equivalents
# ---------------------------------------------------------------------------

TIDAL_PATTERN_MAP: dict[str, str] = {
    "euclidean": "e",  # e(k, n) — native Tidal Euclidean
    "probabilistic": "?",  # ? operator — per-step probability
    "density": "?",  # density → uniform probability per step
    "markov": "markov",  # no native Tidal; approximated with weighted choice
    "mutation": "degrade",  # degrade / degradeBy — probabilistic step removal
}


# ---------------------------------------------------------------------------
# Lookup helpers — public API consumed by synthdef.py and tidal.py
# ---------------------------------------------------------------------------


def get_sc_generator(name: str) -> GeneratorMapping | None:
    """Look up a generator mapping for SuperCollider.

    Args:
        name: Python generator function name (e.g. 'fm_blip').

    Returns:
        GeneratorMapping or None if not found.
    """
    return SC_GENERATORS.get(name)


def get_sc_effect(block_key: str) -> EffectBlockMapping | None:
    """Look up an effect block mapping for SuperCollider.

    Args:
        block_key: Canonical chain key (e.g. 'reverb', 'delay').

    Returns:
        EffectBlockMapping or None if not found.
    """
    return SC_EFFECTS.get(block_key)


def get_tidal_effect_params(block_key: str) -> dict[str, ParamMapping]:
    """Look up Tidal effect parameter mappings for a given block.

    Args:
        block_key: Canonical chain key (e.g. 'reverb', 'delay').

    Returns:
        Dict of Python param name → Tidal ParamMapping. Empty dict if
        the effect has no Tidal equivalent.
    """
    return TIDAL_EFFECTS.get(block_key, {})


def get_tidal_unmapped(block_key: str) -> dict[str, str]:
    """Look up unmappable Tidal parameters for a given block.

    Args:
        block_key: Canonical chain key.

    Returns:
        Dict of Python param name → explanation string.
    """
    return UNMAPPED_TIDAL.get(block_key, {})


def transform_param(mapping: ParamMapping, value: Any) -> Any:
    """Apply a parameter mapping's transform to a value.

    Args:
        mapping: The ParamMapping to apply.
        value:   The Python engine value.

    Returns:
        Transformed value for the target language. Returns value unchanged
        if mapping.transform is None.
    """
    if mapping.transform is None:
        return value
    return mapping.transform(value)


def get_all_sc_effect_keys() -> list[str]:
    """Return all effect block keys in canonical chain order."""
    return sorted(SC_EFFECTS.keys(), key=lambda k: SC_EFFECTS[k].chain_position)


def get_sc_effect_by_position(position: int) -> EffectBlockMapping | None:
    """Look up an effect by its chain position (1-10)."""
    for mapping in SC_EFFECTS.values():
        if mapping.chain_position == position:
            return mapping
    return None


# ---------------------------------------------------------------------------
# Validation — completeness check (used by tests)
# ---------------------------------------------------------------------------


def validate_mapping_completeness() -> dict[str, list[str]]:
    """Check that every known engine parameter is either mapped or
    explicitly listed in unmapped sets.

    Returns:
        Dict of block_key → list of unaccounted parameter names.
        Empty dict means all parameters are accounted for.

    This function is called by test_mappings.py to ensure zero
    silent parameter drops when new params are added to effect blocks.
    """
    # Known parameter sets per block (from __init__ signatures)
    known_params: dict[str, set[str]] = {
        "noise_floor": {"noise_floor_db", "noise_type", "hum_freq", "crosstalk_db", "sr"},
        "bitcrusher": {
            "bit_depth",
            "sample_rate_reduction",
            "dither",
            "mode",
            "hardware_preset",
            "sr",
        },
        "filter": {
            "cutoff_hz",
            "resonance",
            "filter_type",
            "poles",
            "accent",
            "envelope_mod",
            "sr",
        },
        "saturation": {"drive", "mode", "mix", "output_gain"},
        "reverb": {
            "reverb_type",
            "decay_s",
            "pre_delay_ms",
            "diffusion",
            "density",
            "lf_decay",
            "hf_decay",
            "mix",
            "colour",
            "sr",
        },
        "delay": {
            "delay_ms",
            "feedback",
            "tape_saturation",
            "wow_flutter_hz",
            "wow_depth",
            "tape_age",
            "mix",
            "sr",
        },
        "spatial": {"width", "bass_mono_hz", "decorrelation", "pan", "sr"},
        "glitch": {
            "stutter_density",
            "stutter_min_ms",
            "stutter_max_ms",
            "stutter_max_repeats",
            "loop_mod_hz",
            "loop_mod_depth",
            "loop_window_ms",
            "xor_mode",
            "xor_density",
            "mix",
            "seed",
            "sr",
        },
        "compressor": {
            "threshold_db",
            "ratio",
            "attack_ms",
            "release_ms",
            "knee_db",
            "auto_release",
            "sidechain_hpf_hz",
            "rms_window_ms",
            "makeup_db",
            "auto_makeup",
            "mix",
            "sr",
        },
        "vinyl": {
            "riaa_intensity",
            "dat_mode",
            "dat_filter_order",
            "vinyl_condition",
            "noise_mix",
            "limiter_ceiling_db",
            "mix",
            "seed",
            "sr",
        },
    }

    # 'sr' is universally handled at SynthDef level, not per-param
    universal_params = {"sr"}

    missing: dict[str, list[str]] = {}

    for block_key, params in known_params.items():
        sc_mapped = set(
            SC_EFFECTS.get(
                block_key,
                EffectBlockMapping(
                    block_key="",
                    python_class="",
                    sc_name="",
                    sc_ugens=[],
                ),
            ).sc_params.keys()
        )
        sc_unmapped = set(
            SC_EFFECTS.get(
                block_key,
                EffectBlockMapping(
                    block_key="",
                    python_class="",
                    sc_name="",
                    sc_ugens=[],
                ),
            ).unmapped_sc.keys()
        )
        tidal_mapped = set(TIDAL_EFFECTS.get(block_key, {}).keys())
        tidal_unmapped = set(UNMAPPED_TIDAL.get(block_key, {}).keys())

        all_accounted = sc_mapped | sc_unmapped | tidal_mapped | tidal_unmapped | universal_params
        unaccounted = params - all_accounted

        if unaccounted:
            missing[block_key] = sorted(unaccounted)

    return missing
