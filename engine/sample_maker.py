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

import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Optional


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
) -> np.ndarray:
    """
    Percussive glitch click: band-limited noise with exponential decay.

    Emulates the transient artefacts found in early digital hardware —
    characteristic of Autechre's Braindance micro-percussion style.

    Args:
        length_ms: Duration in milliseconds (default 200ms).
        decay: Envelope decay rate. Lower = longer sustain. (default 4.0)
        sr: Sample rate in Hz.

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    length = int(sr * length_ms / 1000)
    noise = np.random.randn(length)
    envelope = np.exp(-np.linspace(0, decay, length))
    return normalize(noise * envelope).astype(np.float32)


def noise_burst(
    length_ms: float = 500.0,
    tone: float = 0.3,
    decay: float = 3.0,
    sr: int = SAMPLE_RATE,
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

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    length = int(sr * length_ms / 1000)
    noise = np.random.randn(length)

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
) -> np.ndarray:
    """
    FM synthesis blip with exponential amplitude envelope.

    Single operator pair (modulator → carrier). Inspired by the DX100 and
    Yamaha TX81Z tones used in Detroit Techno and Sheffield IDM.

    Args:
        freq: Carrier frequency in Hz.
        mod_freq: Modulator frequency in Hz.
        mod_index: Modulation index (controls harmonic richness).
        length_ms: Duration in milliseconds (default 500ms).
        decay: Envelope decay rate. Lower = longer sustain. (default 3.0)
        sr: Sample rate in Hz.

    Returns:
        Normalised float32 array of shape (n_samples,).
    """
    length = int(sr * length_ms / 1000)
    t = np.linspace(0, length_ms / 1000, length)

    modulator = np.sin(2 * np.pi * mod_freq * t) * mod_index
    carrier = np.sin(2 * np.pi * freq * t + modulator)

    envelope = np.exp(-decay * t / (length_ms / 1000))
    return normalize(carrier * envelope).astype(np.float32)


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
    seed: Optional[int] = None,
) -> None:
    """
    Generate and export a batch of randomised samples.

    Produces n variations each of: glitch_click, noise_burst, fm_blip.
    Files are named A{i}_glitch.wav, B{i}_noise.wav, C{i}_fm.wav.

    Intended for bulk sample generation for PO-33 / EP-133 slot population.

    Args:
        output_dir: Directory to write WAV files into.
        n: Number of variations per generator.
        sr: Sample rate in Hz.
        seed: Optional random seed for reproducibility.
    """
    if seed is not None:
        np.random.seed(seed)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for i in range(1, n + 1):
        save_sample(
            glitch_click(length_ms=float(np.random.randint(5, 25)), sr=sr),
            out / f"A{i}_glitch.wav",
            sr=sr,
        )
        save_sample(
            noise_burst(length_ms=float(np.random.randint(40, 120)), sr=sr),
            out / f"B{i}_noise.wav",
            sr=sr,
        )
        save_sample(
            fm_blip(
                freq=float(np.random.randint(150, 1200)),
                mod_freq=float(np.random.randint(40, 300)),
                mod_index=float(np.random.uniform(0.5, 6.0)),
                sr=sr,
            ),
            out / f"C{i}_fm.wav",
            sr=sr,
        )
