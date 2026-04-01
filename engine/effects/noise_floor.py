"""
engine/effects/noise_floor.py

Block 1 — Noise Floor & Environmental Constraints.

Source:
    MASTER_DATASET Part 5 (Anti-GIGO environmental constraints)
    Mackie CR-1604 (bus crosstalk, pre-VLZ warm overdrive)

Historical context:
    The Mackie CR-1604 (pre-VLZ) was the standard mixing hub in IDM studios
    of the early 90s. Its characteristic warm overdrive at full channel load
    and summing bus crosstalk became an integral feature of underground sound.

    MASTER_DATASET spec:
        - Noise floor: -78 dB RMS
        - Noise type:  Pink (1/f) + 50 Hz hum (UK) or 60 Hz (Detroit)
        - Crosstalk:   inter-channel bleed via summing bus

Signal position: INPUT → [Block 1] → Bitcrusher → ...
"""

from __future__ import annotations

import numpy as np
from engine.effects.base import BaseEffect


class NoiseFloor(BaseEffect):
    """
    Anti-GIGO noise floor emulation with Mackie CR-1604 bus crosstalk.

    Adds historically accurate analogue noise to prevent the "too clean"
    digital sound that would break period authenticity.

    Args:
        noise_floor_db: Target RMS noise level in dB. Default: -78.0 dB
                        (MASTER_DATASET Part 5 spec).
        noise_type:     Noise character. Options:
                            'pink'    — 1/f pink noise (default, most natural)
                            'white'   — flat-spectrum white noise
                            'hum_uk'  — pink noise + 50 Hz mains hum (UK)
                            'hum_us'  — pink noise + 60 Hz mains hum (Detroit)
        hum_freq:       Mains hum frequency in Hz. Auto-set by noise_type
                        but can be overridden. Default: 50.0 Hz.
        crosstalk_db:   Inter-channel crosstalk level in dB.
                        Models Mackie CR-1604 summing bus bleed.
                        Default: -65.0 dB.
        sr:             Sample rate in Hz. Default: 44100.

    Example:
        >>> nf = NoiseFloor(noise_floor_db=-78.0, noise_type='hum_uk')
        >>> output = nf(signal)
    """

    _VALID_NOISE_TYPES = {"pink", "white", "hum_uk", "hum_us"}

    def __init__(
        self,
        noise_floor_db: float = -78.0,
        noise_type: str = "pink",
        hum_freq: float = 50.0,
        crosstalk_db: float = -65.0,
        sr: int = 44100,
    ) -> None:
        if noise_type not in self._VALID_NOISE_TYPES:
            raise ValueError(
                f"Invalid noise_type '{noise_type}'. "
                f"Options: {sorted(self._VALID_NOISE_TYPES)}"
            )

        self.noise_floor_db = noise_floor_db
        self.noise_type = noise_type
        self.hum_freq = hum_freq
        self.crosstalk_db = crosstalk_db
        self.sr = sr

        # Auto-set hum frequency from noise_type if not explicitly overridden
        if noise_type == "hum_uk":
            self.hum_freq = 50.0
        elif noise_type == "hum_us":
            self.hum_freq = 60.0

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Add noise floor and bus crosstalk to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Signal with added noise and crosstalk.
        """
        n = len(signal)
        rms_linear = 10.0 ** (self.noise_floor_db / 20.0)

        noise = self._generate_noise(n, rms_linear)
        crosstalk = self._generate_crosstalk(signal)

        return signal + noise + crosstalk

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""
        pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_noise(self, n: int, rms_linear: float) -> np.ndarray:
        """Generate noise of the configured type at the target RMS level."""

        if self.noise_type == "pink":
            return self._pink_noise(n, rms_linear)

        elif self.noise_type == "white":
            return np.random.randn(n) * rms_linear

        elif self.noise_type in ("hum_uk", "hum_us"):
            t = np.arange(n) / self.sr
            hum = np.sin(2.0 * np.pi * self.hum_freq * t) * rms_linear * 0.3
            white = np.random.randn(n) * rms_linear * 0.7
            return hum + white

        else:
            # Fallback: white noise
            return np.random.randn(n) * rms_linear

    def _pink_noise(self, n: int, rms_linear: float) -> np.ndarray:
        """
        Generate pink (1/f) noise via frequency-domain shaping.

        1/f weighting gives a natural, warm noise floor that closely
        matches the spectral character of analogue hardware.
        """
        white = np.random.randn(n)
        freqs = np.fft.rfftfreq(n, d=1.0 / self.sr)
        freqs[0] = 1.0  # avoid division by zero at DC
        pink_filter = 1.0 / np.sqrt(freqs)
        pink = np.fft.irfft(np.fft.rfft(white) * pink_filter, n=n)
        # Normalise to target RMS
        current_rms = np.std(pink) + 1e-8
        return pink / current_rms * rms_linear

    def _generate_crosstalk(self, signal: np.ndarray) -> np.ndarray:
        """
        Simulate Mackie CR-1604 summing bus inter-channel crosstalk.

        A low-level, phase-shifted copy of the signal bleeds from an
        adjacent channel — 64-sample offset approximates the propagation
        delay across the analogue summing bus.
        """
        crosstalk_linear = 10.0 ** (self.crosstalk_db / 20.0)
        return np.roll(signal, 64) * crosstalk_linear
