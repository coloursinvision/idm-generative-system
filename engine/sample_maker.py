"""
engine/sample_maker.py

Algorithmic sample generator for the IDM Generative System.
Extracted and refactored from: notebooks/sample_maker.ipynb

Generators:
    - glitch_click  : percussive click with exponential decay
    - noise_burst   : filtered noise burst with tone control
    - fm_blip       : FM synthesis blip with envelope

All generators return normalised float32 numpy arrays in range [-1.0, 1.0].
Use save_sample() to export to WAV, or pass directly into the effects chain.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE: int = 44100


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def normalize(x: np.ndarray) -> np.ndarray:
    """
    Peak-normalise a signal to [-1.0, 1.0].

    Args:
        x: Input audio array.

    Returns:
        Normalised array. Returns zeros if input is silent.
    """
    peak = np.max(np.abs(x))
    if peak < 1e-8:
        return np.zeros_like(x)
    return x / peak


# ---------------------------------------------------------------------------
# Sample generators
# ---------------------------------------------------------------------------


def glitch_click(
    length_ms: float = 200.0,
    decay: float = 4.0,
    sr: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """
    Percussive glitch click: band-limited noise with exponential decay.

    Emulates the transient artefacts found in early digital hardware —
    characteristic of Autechre's Braindance micro-percussion style.

    Args:
        length_ms: Duration in milliseconds (default 200ms).
        decay: Envelope decay rate. Lower = longer sustain. (default 4.0)
        sr: Sample rate in Hz.
        rng: NumPy random Generator instance. None = default_rng().

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    if rng is None:
        rng = np.random.default_rng()
    length = int(sr * length_ms / 1000)
    noise = rng.standard_normal(length)
    envelope = np.exp(-np.linspace(0, decay, length))
    return normalize(noise * envelope).astype(np.float32)


def noise_burst(
    length_ms: float = 500.0,
    tone: float = 0.3,
    decay: float = 3.0,
    sr: int = SAMPLE_RATE,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """
    Noise burst with adjustable tone character.

    Blends white noise with a low-passed (smoothed) version of itself.
    tone=0.0 → pure white noise; tone=1.0 → smooth low-frequency noise.

    Useful for snare, rim shot, and percussive texture generation.

    Args:
        length_ms: Duration in milliseconds (default 500ms).
        tone: Blend ratio between white noise (0.0) and smoothed noise (1.0).
        decay: Envelope decay rate. Lower = longer sustain. (default 3.0)
        sr: Sample rate in Hz.
        rng: NumPy random Generator instance. None = default_rng().

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    if rng is None:
        rng = np.random.default_rng()
    length = int(sr * length_ms / 1000)
    noise = rng.standard_normal(length)

    t = np.linspace(0, 1, length)
    envelope = np.exp(-decay * t)

    # Simple boxcar smoothing as a low-pass proxy
    smooth_kernel = 10
    low_noise = np.convolve(noise, np.ones(smooth_kernel) / smooth_kernel, mode="same")

    blended = (1 - tone) * noise + tone * low_noise
    return normalize(blended * envelope).astype(np.float32)


def fm_blip(
    freq: float = 300.0,
    mod_freq: float = 80.0,
    mod_index: float = 2.0,
    length_ms: float = 500.0,
    decay: float = 3.0,
    sr: int = SAMPLE_RATE,
    *,
    mod_index_end: float | None = None,
    ratio: float | None = None,
    feedback: float = 0.0,
    attack_ms: float = 0.0,
) -> np.ndarray:
    """
    FM synthesis blip with a time-varying modulation index and shaped envelope.

    Two-operator FM (modulator -> carrier), inspired by the DX100 and Yamaha
    TX81Z tones used in Detroit Techno and Sheffield IDM. Four optional,
    additive controls widen the timbral palette; each defaults to the original
    behaviour, so a bare fm_blip() call reproduces the original signal exactly.

    Args:
        freq: Carrier frequency in Hz.
        mod_freq: Modulator frequency in Hz. Ignored when ``ratio`` is set.
        mod_index: Modulation index at note onset (controls harmonic richness).
        length_ms: Duration in milliseconds (default 500ms).
        decay: Envelope decay rate. Lower = longer sustain. (default 3.0)
        sr: Sample rate in Hz.
        mod_index_end: Modulation index at note end. None keeps the index
            static at ``mod_index`` (legacy behaviour); a value sweeps the index
            linearly from ``mod_index`` to ``mod_index_end`` across the note, so
            the spectrum evolves over time rather than only the amplitude.
        ratio: Modulator-to-carrier frequency ratio. When set, the modulator
            frequency is derived as ``freq * ratio`` (overriding ``mod_freq``);
            integer ratios read harmonic, non-integer ratios inharmonic. None
            uses the absolute ``mod_freq`` (legacy behaviour).
        feedback: Operator self-feedback depth, applied as a single-iteration
            phase self-modulation of the modulator (a cheap, vectorised
            approximation of true recursive feedback). 0.0 disables it (legacy
            behaviour); higher values add brighter, more inharmonic content.
        attack_ms: Linear amplitude attack in milliseconds. 0.0 keeps the
            instant onset (legacy behaviour); a value fades the onset in for
            softer, pad-like articulations.

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    length = int(sr * length_ms / 1000)
    t = np.linspace(0, length_ms / 1000, length)

    if ratio is not None:
        mod_freq = freq * ratio

    index_env: float | np.ndarray = (
        mod_index if mod_index_end is None else np.linspace(mod_index, mod_index_end, length)
    )

    mod_phase = 2 * np.pi * mod_freq * t
    modulator = np.sin(mod_phase + feedback * np.sin(mod_phase)) * index_env
    carrier = np.sin(2 * np.pi * freq * t + modulator)

    envelope = np.exp(-decay * t / (length_ms / 1000))
    if attack_ms > 0.0:
        attack_len = min(int(sr * attack_ms / 1000), length)
        if attack_len > 0:
            envelope[:attack_len] *= np.linspace(0.0, 1.0, attack_len)

    return normalize(carrier * envelope).astype(np.float32)


# ---------------------------------------------------------------------------
# Analog voice — subtractive layer over the FM core
# ---------------------------------------------------------------------------


def _soft_saturate(x: np.ndarray, drive: float) -> np.ndarray:
    """Soft tanh saturation, output-normalised so drive only adds harmonics."""
    if drive <= 0.0:
        return x
    return np.tanh(x * drive) / np.tanh(drive)


def _svf_lowpass(x: np.ndarray, cutoff: np.ndarray, resonance: float) -> np.ndarray:
    """Topology-preserving (Zavalishin) state-variable low-pass, time-varying cutoff.

    An analog-modelling filter: the per-sample recursion is inherent to an IIR
    state-variable design and cannot be vectorised. ``cutoff`` is a per-sample
    array in Hz; ``resonance`` in [0.0, 1.0) (0 = none, -> 1 strongly resonant).
    """
    fc = np.minimum(cutoff, 0.45 * float(SAMPLE_RATE))
    g = np.tan(np.pi * fc / SAMPLE_RATE)
    k = 2.0 - 1.8 * resonance  # damping = 1/Q; lower k = more resonance
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    out = np.empty_like(x)
    ic1 = 0.0
    ic2 = 0.0
    for i in range(len(x)):
        v3 = x[i] - ic2
        v1 = a1[i] * ic1 + a2[i] * v3
        v2 = ic2 + a2[i] * ic1 + a3[i] * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out[i] = v2
    return out


def fm_analog(
    freq: float = 110.0,
    ratio: float = 1.0,
    index: float = 2.0,
    length_ms: float = 600.0,
    sr: int = SAMPLE_RATE,
    *,
    detune_cents: float = 8.0,
    cutoff_hz: float = 300.0,
    cutoff_env: float = 2500.0,
    resonance: float = 0.6,
    drive: float = 2.0,
    attack_ms: float = 5.0,
    decay: float = 3.0,
) -> np.ndarray:
    """
    Warm, analog-character voice: a harmonic FM core shaped subtractively.

    Two slightly detuned FM oscillators are summed for analog thickness, soft-
    saturated for warmth, then run through a resonant low-pass filter whose
    cutoff tracks an attack/decay envelope (the classic filter sweep that gives
    the sound movement and analog life). The warm, filtered counterpart to
    ``fm_blip`` (raw digital FM).

    Args:
        freq: Carrier frequency in Hz.
        ratio: Modulator:carrier ratio (integer ratios read harmonic).
        index: FM modulation index (harmonic richness fed into the filter).
        length_ms: Duration in milliseconds.
        sr: Sample rate in Hz.
        detune_cents: Detune between the two stacked voices (analog thickness).
        cutoff_hz: Base filter cutoff in Hz (envelope floor).
        cutoff_env: Envelope depth added to the cutoff in Hz (sweep range).
        resonance: Filter resonance in [0.0, 1.0); higher = more vocal/squelchy.
        drive: Soft-saturation drive (warmth); higher adds harmonics.
        attack_ms: Amplitude/filter attack in milliseconds.
        decay: Envelope decay rate. Lower = longer sustain.

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    n = int(sr * length_ms / 1000)
    t = np.arange(n) / sr

    detune = 2.0 ** (detune_cents / 1200.0)
    voice_a = np.sin(2 * np.pi * freq * t + index * np.sin(2 * np.pi * (freq * ratio) * t))
    voice_b = np.sin(
        2 * np.pi * (freq * detune) * t + index * np.sin(2 * np.pi * (freq * detune * ratio) * t)
    )
    osc = _soft_saturate(0.5 * (voice_a + voice_b), drive)

    shape = np.exp(-decay * np.linspace(0.0, 1.0, n))
    attack_len = min(int(sr * attack_ms / 1000), n)
    if attack_len > 0:
        shape[:attack_len] *= np.linspace(0.0, 1.0, attack_len)

    cutoff = cutoff_hz + cutoff_env * shape
    filtered = _svf_lowpass(osc, cutoff, resonance)
    return normalize(filtered * shape).astype(np.float32)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def save_sample(
    x: np.ndarray,
    path: str | Path,
    sr: int = SAMPLE_RATE,
) -> None:
    """
    Write a sample to a WAV file (24-bit PCM via soundfile).

    Args:
        x: Audio array in range [-1.0, 1.0].
        path: Output file path (str or Path). Extension should be .wav.
        sr: Sample rate in Hz.
    """
    sf.write(str(path), x, sr, subtype="PCM_24")


def batch_export(
    output_dir: str | Path,
    n: int = 8,
    sr: int = SAMPLE_RATE,
    seed: int | None = None,
) -> None:
    """
    Generate and export a batch of randomised samples.

    Produces n variations each of: glitch_click, noise_burst, fm_blip, fm_analog.
    Files are named A{i}_glitch.wav, B{i}_noise.wav, C{i}_fm.wav, D{i}_analog.wav.

    Intended for bulk sample generation for PO-33 / EP-133 slot population.

    Args:
        output_dir: Directory to write WAV files into.
        n: Number of variations per generator.
        sr: Sample rate in Hz.
        seed: Optional random seed for reproducibility.
    """
    rng = np.random.default_rng(seed)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for i in range(1, n + 1):
        save_sample(
            glitch_click(
                length_ms=float(rng.integers(5, 25)),
                sr=sr,
                rng=rng,
            ),
            out / f"A{i}_glitch.wav",
            sr=sr,
        )
        save_sample(
            noise_burst(
                length_ms=float(rng.integers(40, 120)),
                sr=sr,
                rng=rng,
            ),
            out / f"B{i}_noise.wav",
            sr=sr,
        )
        save_sample(
            fm_blip(
                freq=float(rng.integers(150, 1200)),
                mod_freq=float(rng.integers(40, 300)),
                mod_index=float(rng.uniform(0.5, 6.0)),
                mod_index_end=float(rng.uniform(0.5, 6.0)),
                feedback=float(rng.uniform(0.0, 0.8)),
                attack_ms=float(rng.uniform(0.0, 60.0)),
                sr=sr,
            ),
            out / f"C{i}_fm.wav",
            sr=sr,
        )
        save_sample(
            fm_analog(
                freq=float(rng.uniform(36, 300)),
                ratio=float(rng.choice([0.5, 1.0, 1.0, 2.0, 2.0, 3.0, 1.5])),
                index=float(rng.uniform(1.0, 4.0)),
                length_ms=float(rng.uniform(300, 1200)),
                detune_cents=float(rng.uniform(4, 18)),
                cutoff_hz=float(rng.uniform(150, 600)),
                cutoff_env=float(rng.uniform(1200, 3800)),
                resonance=float(rng.uniform(0.2, 0.7)),
                drive=float(rng.uniform(1.2, 3.0)),
                attack_ms=float(rng.uniform(2, 200)),
                decay=float(rng.uniform(1.0, 4.5)),
                sr=sr,
            ),
            out / f"D{i}_analog.wav",
            sr=sr,
        )
