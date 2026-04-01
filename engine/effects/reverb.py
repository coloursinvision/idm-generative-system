"""
engine/effects/reverb.py

Block 5 — Reverb (Quadraverb IDM Diffusion).

Source:
    MASTER_DATASET Part 8 — Spatial Processing & Time-Based Effects
    Alesis Quadraverb (IDM Diffusion)
    Roland Space Echo RE-201 (spring reverb)

Hardware references:
    - Alesis Quadraverb (1988): 16-bit PCM, hybrid analog/digital dry path
      through VCA chips (CEM 3381). Reverb is grainy and metallic — a direct
      consequence of 1988 DSP limits running four simultaneous effects at
      16-bit. Defined the spatial sound of IDM, hip-hop and ambient music of
      the early 90s.
      Notable users: Aphex Twin, Global Communication, Orbital, FSOL.

    - Roland Space Echo RE-201: Spring reverb component used for shorter,
      more organic ambience — characteristic of dub-techno and Basic Channel.

Historical context:
    The Quadraverb used a Schroeder reverberator architecture — a network of
    parallel comb filters feeding into allpass diffusors. The 16-bit converters
    and limited DSP precision produced "thick, smeared, atmospheric reverb
    tails" that are deeply embedded in the IDM aesthetic.

    Original Quadraverb parameters modelled here:
        Decay, Diffusion, Density, LF Decay, HF Decay, Colour (Predelay Mix)

    Reverb types (from Quadraverb manual):
        Room, Chamber, Hall, Plate, Reverse (spring approximated separately)

Signal position: Saturation → [Block 5] → TapeDelay → ...
"""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal
from engine.effects.base import BaseEffect


# ---------------------------------------------------------------------------
# Decay multipliers per reverb type (relative to base decay_s)
# Calibrated against Quadraverb factory presets
# ---------------------------------------------------------------------------

REVERB_TYPE_DECAY: dict[str, float] = {
    "room":    0.4,
    "chamber": 0.6,
    "plate":   1.0,   # reference — Quadraverb plate is the IDM standard
    "hall":    1.4,
    "spring":  0.7,
}

# Comb filter delay times in ms — tuned to Quadraverb plate character
# (prime-number ratios to avoid resonant beating)
COMB_DELAYS_MS: list[float] = [29.7, 37.1, 41.1, 43.7, 47.3, 53.1]


class Reverb(BaseEffect):
    """
    Alesis Quadraverb IDM reverb emulation (Schroeder architecture).

    Implements a parallel comb filter bank followed by allpass diffusors,
    modelling the specific grain and metallic character of the Quadraverb.

    Args:
        reverb_type:   Space type. Options:
                         'plate'   — Quadraverb plate (default, IDM standard)
                         'room'    — small room, short tail
                         'chamber' — medium diffuse space
                         'hall'    — large, lush tail
                         'spring'  — spring reverb character (RE-201 style)
        decay_s:       Reverb time RT60 in seconds [0.1–10.0].
                       Default: 2.5 s.
        pre_delay_ms:  Pre-delay before reverb onset in ms [0–100].
                       Default: 15.0 ms.
        diffusion:     Early reflection density [0.0–1.0].
                       Controls allpass gain — higher = smoother attack.
                       Default: 0.7.
        density:       Reverb tail density [0.0–1.0].
                       Blends LF and HF decay in the comb filter feedback.
                       Default: 0.8.
        lf_decay:      Low-frequency decay multiplier [0.1–3.0].
                       >1.0 = longer LF tail (warmer). Default: 0.8.
        hf_decay:      High-frequency decay multiplier [0.1–1.0].
                       <1.0 = shorter HF tail (darker). Default: 0.4.
        mix:           Dry/wet blend [0.0–1.0]. Default: 0.25.
        colour:        Reverb colour [-1.0–1.0].
                         -1.0 = dark (low-pass filtered tail)
                          0.0 = neutral (default)
                         +1.0 = bright (high-pass filtered tail)
        sr:            Sample rate in Hz. Default: 44100.

    Example:
        >>> rev = Reverb(reverb_type='plate', decay_s=3.0, mix=0.3)
        >>> output = rev(signal)

        >>> # Dark atmospheric IDM pad reverb
        >>> rev = Reverb(decay_s=6.0, diffusion=0.9, colour=-0.6, mix=0.4)
    """

    def __init__(
        self,
        reverb_type: str = "plate",
        decay_s: float = 2.5,
        pre_delay_ms: float = 15.0,
        diffusion: float = 0.7,
        density: float = 0.8,
        lf_decay: float = 0.8,
        hf_decay: float = 0.4,
        mix: float = 0.25,
        colour: float = 0.0,
        sr: int = 44100,
    ) -> None:
        if reverb_type not in REVERB_TYPE_DECAY:
            raise ValueError(
                f"Invalid reverb_type '{reverb_type}'. "
                f"Options: {sorted(REVERB_TYPE_DECAY.keys())}"
            )

        self.reverb_type = reverb_type
        self.decay_s = decay_s
        self.pre_delay_ms = pre_delay_ms
        self.diffusion = diffusion
        self.density = density
        self.lf_decay = lf_decay
        self.hf_decay = hf_decay
        self.mix = mix
        self.colour = colour
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply reverb to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Reverberated audio array.
        """
        dry = signal.copy()
        n = len(signal)

        # Pre-delay
        delayed = self._apply_pre_delay(signal, n)

        # Effective decay adjusted for reverb type
        type_mult = REVERB_TYPE_DECAY.get(self.reverb_type, 1.0)
        effective_decay = max(self.decay_s * type_mult, 0.01)

        # Parallel comb filter bank
        wet = self._comb_filter_bank(delayed, n, effective_decay)

        # Allpass diffusor chain
        wet = self._allpass_chain(wet, n)

        # Colour filter (Quadraverb HF/LF decay control)
        if abs(self.colour) > 0.01:
            wet = self._apply_colour(wet)

        # Normalise wet signal to match dry level
        dry_peak = np.max(np.abs(signal)) + 1e-8
        wet_peak = np.max(np.abs(wet)) + 1e-8
        wet = wet / wet_peak * dry_peak

        return dry * (1.0 - self.mix) + wet * self.mix

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""
        pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_pre_delay(self, signal: np.ndarray, n: int) -> np.ndarray:
        """Shift signal by pre_delay_ms samples."""
        pre_delay_samples = int(self.pre_delay_ms * self.sr / 1000)
        if pre_delay_samples <= 0 or pre_delay_samples >= n:
            return signal
        delayed = np.zeros(n)
        delayed[pre_delay_samples:] = signal[: n - pre_delay_samples]
        return delayed

    def _comb_filter_bank(
        self,
        signal: np.ndarray,
        n: int,
        effective_decay: float,
    ) -> np.ndarray:
        """
        Parallel comb filter bank — core Schroeder reverberator.

        Each comb filter contributes a decaying echo stream.
        The combination of 6 prime-spaced delays produces the characteristic
        Quadraverb "thick" tail without obvious flutter echo.
        """
        wet = np.zeros(n)

        for d_ms in COMB_DELAYS_MS:
            delay_samp = int(d_ms * self.sr / 1000)
            if delay_samp < 1 or delay_samp >= n:
                continue

            # RT60-based feedback gain
            g_base = 10.0 ** (-3.0 * delay_samp / (self.sr * effective_decay))

            # Blend LF and HF decay via density parameter
            g_eff = (
                g_base * self.lf_decay * (1.0 - self.density)
                + g_base * self.hf_decay * self.density
            )
            g_eff = np.clip(g_eff, 0.0, 0.999)

            # Feedback comb filter
            buf = np.zeros(delay_samp + n)
            buf[:n] += signal
            for i in range(n):
                buf[i + delay_samp] += buf[i] * g_eff * self.density
            wet += buf[:n]

        return wet

    def _allpass_chain(self, wet: np.ndarray, n: int) -> np.ndarray:
        """
        Allpass diffusor chain — smooths early reflections.

        Three allpass filters with delay times derived from diffusion
        parameter. Higher diffusion = smoother, less grainy attack.
        Emulates the Quadraverb's EQ → Pitch → Delay signal path.
        """
        allpass_delays_ms = [5.0, 1.7, 3.5 * self.diffusion]

        for d_ms in allpass_delays_ms:
            d = int(d_ms * self.sr / 1000)
            if d <= 0 or d >= n:
                continue

            g_ap = 0.7 * self.diffusion
            out = np.zeros(n)
            buf = np.zeros(d)
            ptr = 0

            for i in range(n):
                xh = wet[i] - g_ap * buf[ptr]
                out[i] = g_ap * xh + buf[ptr]
                buf[ptr] = xh
                ptr = (ptr + 1) % d

            wet = out

        return wet

    def _apply_colour(self, wet: np.ndarray) -> np.ndarray:
        """
        Apply colour filter to the reverb tail.

        Replicates the Quadraverb's HF/LF decay colour control:
            colour > 0 → high-pass (brighter tail, removes low-end mud)
            colour < 0 → low-pass (darker tail, removes high-frequency content)
        """
        if self.colour > 0:
            # Positive = bright: high-pass removes low-end
            cutoff = max(0.001, 200.0 * (1.0 + self.colour) / (self.sr / 2.0))
            btype = "high"
        else:
            # Negative = dark: low-pass removes treble
            cutoff = min(0.99, 4000.0 * (1.0 + abs(self.colour)) / (self.sr / 2.0))
            btype = "low"

        cutoff = np.clip(cutoff, 0.001, 0.999)
        sos = scipy_signal.butter(1, cutoff, btype=btype, output="sos")
        return scipy_signal.sosfilt(sos, wet)
