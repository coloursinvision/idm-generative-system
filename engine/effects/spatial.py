"""
engine/effects/spatial.py

Block 7 — Spatial Processing (Stereo Width & Phase).

Source:
    MASTER_DATASET Part 15 — Stereo Width Logic (Sonic Fingerprint)

Rules (MASTER_DATASET Part 15):
    - Kick & Bass : strictly mono below 200 Hz
    - Percussion  : 70% width (TR-909 style panning)
    - Pads/Reverbs: full stereo via phase decorrelation

Historical context:
    Underground IDM and techno of the 1987-1999 era followed strict
    low-frequency mono rules driven by practical necessity: vinyl cutting
    and club PA systems both require mono bass to avoid phase cancellation.
    The Haas effect (inter-channel delays up to 23ms) was used to create
    width in pads and reverb tails without pitch-shifting artefacts.

Signal position: TapeDelay → [Block 7] → GlitchEngine → ...

Note:
    This block operates on stereo signals (two arrays).
    For mono input, pass the same array for both left and right,
    or use process_mono() which handles the conversion internally.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal

from engine.effects.base import BaseEffect


class SpatialProcessor(BaseEffect):
    """
    Stereo width control with bass mono enforcement and phase decorrelation.

    Implements the MASTER_DATASET Part 15 stereo width rules:
        - Sub/bass frequencies forced to mono below bass_mono_hz
        - Mid/high frequencies scaled by width parameter
        - Optional Haas-zone phase decorrelation for pads and reverb tails

    Args:
        width:          Stereo field width multiplier [0.0–2.0].
                        0.0 = full mono, 1.0 = unchanged, 2.0 = extra wide.
                        Default: 1.0.
        bass_mono_hz:   Frequency below which signal is forced to mono [0–400].
                        MASTER_DATASET spec: 200 Hz (kick & bass strictly mono).
                        Default: 200.0 Hz.
        decorrelation:  L/R phase decorrelation amount [0.0–1.0].
                        Introduces a Haas-zone delay (up to 23ms) on one
                        channel to create width without pitch artefacts.
                        Use for pads and reverb tails.
                        0.0 = no decorrelation (default).
        pan:            Stereo pan position [-1.0–1.0].
                        -1.0 = hard left, 0.0 = centre, +1.0 = hard right.
                        Uses constant-power (-3dB centre) pan law.
                        Default: 0.0.
        sr:             Sample rate in Hz. Default: 44100.

    Example:
        >>> sp = SpatialProcessor(width=1.2, bass_mono_hz=200)
        >>> left, right = sp.process_stereo(left, right)

        >>> # Mono input — returns stereo pair
        >>> left, right = sp.process_mono(signal)

        >>> # Wide pad with decorrelation
        >>> sp = SpatialProcessor(width=1.8, decorrelation=0.6)
        >>> left, right = sp.process_stereo(left, right)
    """

    def __init__(
        self,
        width: float = 1.0,
        bass_mono_hz: float = 200.0,
        decorrelation: float = 0.0,
        pan: float = 0.0,
        sr: int = 44100,
    ) -> None:
        self.width = width
        self.bass_mono_hz = bass_mono_hz
        self.decorrelation = np.clip(decorrelation, 0.0, 1.0)
        self.pan = np.clip(pan, -1.0, 1.0)
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Process a mono signal through the spatial processor.

        Converts mono to stereo, applies all spatial processing,
        and returns the left channel (for chain compatibility).
        Use process_stereo() directly for full stereo output.

        Args:
            signal: Mono input audio array, normalised to [-1.0, 1.0].

        Returns:
            Left channel of the processed stereo pair.
        """
        left, _right = self.process_mono(signal)
        return left

    def process_mono(
        self, signal: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Convert mono signal to stereo and apply spatial processing.

        Args:
            signal: Mono input array.

        Returns:
            (left, right) stereo tuple.
        """
        return self.process_stereo(signal, signal)

    def process_stereo(
        self,
        signal_l: np.ndarray,
        signal_r: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Apply full spatial processing to a stereo signal pair.

        Processing order:
            1. Mid/Side decomposition
            2. Stereo width applied to side channel
            3. Bass mono enforcement (LPF bass to mid only)
            4. Haas decorrelation on side channel (if decorrelation > 0)
            5. Mid/Side reconstruction
            6. Constant-power pan law

        Args:
            signal_l: Left channel audio array.
            signal_r: Right channel audio array.

        Returns:
            (left, right) processed stereo tuple.
        """
        # Mid/Side decomposition
        mid  = (signal_l + signal_r) * 0.5
        side = (signal_l - signal_r) * 0.5

        # Apply stereo width to side channel
        side_wide = side * self.width

        # Bass mono enforcement — split at bass_mono_hz
        sos_lp = scipy_signal.butter(
            4, self.bass_mono_hz / (self.sr / 2.0), btype="low", output="sos"
        )
        sos_hp = scipy_signal.butter(
            4, self.bass_mono_hz / (self.sr / 2.0), btype="high", output="sos"
        )

        mid_bass = scipy_signal.sosfilt(sos_lp, mid)    # mono below cutoff
        mid_high = scipy_signal.sosfilt(sos_hp, mid)
        side_high = scipy_signal.sosfilt(sos_hp, side_wide)

        # Haas-zone phase decorrelation (up to 23ms — Haas effect boundary)
        if self.decorrelation > 0.0:
            side_high = self._apply_decorrelation(side_high)

        # Mid/Side reconstruction
        # Bass is fully mono (side_bass = 0), highs retain width
        left  = mid_bass + mid_high + side_high
        right = mid_bass + mid_high - side_high

        # Constant-power pan law (-3dB at centre)
        pan_l = np.sqrt(0.5 * (1.0 - self.pan))
        pan_r = np.sqrt(0.5 * (1.0 + self.pan))

        return left * pan_l, right * pan_r

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_decorrelation(self, side: np.ndarray) -> np.ndarray:
        """
        Apply Haas-zone phase decorrelation to the side channel.

        Blends the original side signal with a delayed version.
        The delay is within the Haas effect zone (< 23ms) — the brain
        fuses the two signals into a single, wider perceived image rather
        than hearing a distinct echo.
        """
        n = len(side)
        # Maximum delay: 23ms * decorrelation amount
        delay_samples = int(self.decorrelation * 0.023 * self.sr)

        if delay_samples <= 0:
            return side

        side_delayed = np.zeros(n)
        side_delayed[delay_samples:] = side[: n - delay_samples]

        return (
            side * (1.0 - self.decorrelation)
            + side_delayed * self.decorrelation
        )
