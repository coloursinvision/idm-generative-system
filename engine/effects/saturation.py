"""
engine/effects/saturation.py

Block 4 — Saturation & Console Warmth.

Source:
    MASTER_DATASET Part 5 — Environmental Constraints (Anti-GIGO)
    Asymmetrical soft-clipper formula (exact implementation)

Hardware references:
    - Mackie CR-1604 (pre-VLZ) : Characteristic warm overdrive at full channel
                                  load. Bus saturation adds harmonic cohesion.
                                  Distinct from the cleaner VLZ series.
    - Unit Moebius / The Hague Sound: Extreme full-chain saturation as an
                                  aesthetic choice — every element of the
                                  signal path pushed into nonlinearity.

Historical context:
    The asymmetric saturation curve from MASTER_DATASET Part 5 models the
    behaviour of analogue VCAs and mixer bus circuits. Positive and negative
    signal excursions clip differently — positive half uses tanh, negative
    half uses a softer rational function. This asymmetry produces even-order
    harmonics (2nd, 4th) characteristic of transformer and tube saturation,
    which is perceived as "warm" rather than "harsh".

    Exact MASTER_DATASET Part 5 formula:
        output = (x > 0) ? tanh(x * drive) : (x / (1 - x * drive * 0.5))

    Wavefold mode adds a second nonlinearity — the signal folds back when it
    exceeds the clipping threshold, producing complex overtone structures used
    in Braindance sound design.

Signal position: ResonantFilter → [Block 4] → Reverb → ...
"""

from __future__ import annotations

import numpy as np

from engine.effects.base import BaseEffect


class Saturation(BaseEffect):
    """
    Console bus saturation and VCA overdrive emulation.

    Four saturation algorithms, selectable via the `mode` parameter.
    The default 'asymmetric' mode is the exact MASTER_DATASET Part 5
    formula — the reference implementation for this project.

    Args:
        drive:        Saturation depth [0.1–10.0].
                      At drive=1.0 the effect is subtle.
                      At drive=5.0+ the signal clips heavily.
                      Default: 1.5.
        mode:         Saturation algorithm.
                        'asymmetric' — MASTER_DATASET Part 5 formula (default)
                                       warm, even-order harmonics
                        'symmetric'  — tanh(x * drive), classic soft clip
                        'tanh'       — normalised tanh: tanh(x*d)/tanh(d)
                                       unity gain at all drive levels
                        'wavefold'   — signal folds back past threshold,
                                       complex overtone structures (Braindance)
        mix:          Dry/wet blend [0.0–1.0].
                      1.0 = fully wet (default: 0.8).
        output_gain:  Output level compensation [0.1–2.0].
                      Use to match perceived loudness after saturation.
                      Default: 1.0.

    Example:
        >>> sat = Saturation(drive=2.0, mode='asymmetric')
        >>> output = sat(signal)

        >>> # Subtle Mackie bus warmth
        >>> sat = Saturation(drive=1.2, mode='asymmetric', mix=0.4)

        >>> # Extreme Hague-style full-chain saturation
        >>> sat = Saturation(drive=6.0, mode='wavefold', mix=1.0)
    """

    _VALID_MODES = {"asymmetric", "symmetric", "tanh", "wavefold"}

    def __init__(
        self,
        drive: float = 1.5,
        mode: str = "asymmetric",
        mix: float = 0.8,
        output_gain: float = 1.0,
    ) -> None:
        if mode not in self._VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. "
                f"Options: {sorted(self._VALID_MODES)}"
            )

        self.drive = drive
        self.mode = mode
        self.mix = mix
        self.output_gain = output_gain

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply saturation to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Saturated audio array.
        """
        dry = signal.copy()
        wet = self._apply_saturation(signal)

        # Remove DC offset introduced by asymmetric clipping
        wet = wet - np.mean(wet)

        return (dry * (1.0 - self.mix) + wet * self.mix) * self.output_gain

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_saturation(self, x: np.ndarray) -> np.ndarray:
        """Dispatch to the selected saturation algorithm."""

        if self.mode == "asymmetric":
            return self._asymmetric(x)
        if self.mode == "symmetric":
            return self._symmetric(x)
        if self.mode == "tanh":
            return self._tanh_normalised(x)
        if self.mode == "wavefold":
            return self._wavefold(x)
        return x

    def _asymmetric(self, x: np.ndarray) -> np.ndarray:
        """
        Exact MASTER_DATASET Part 5 asymmetric soft-clipper.

        Positive half:  tanh(x * drive)
        Negative half:  x / (1 - x * drive * 0.5)

        The different clipping curves for positive and negative excursions
        produce even-order harmonics — the signature of transformer and
        tube saturation, perceived as "warm" analogue colour.
        """
        # Positive half: tanh soft-clip
        pos = np.tanh(x * self.drive)

        # Negative half: rational soft-clip with safe denominator
        # np.where evaluates both branches before selecting, so we must
        # guard the denominator unconditionally to avoid divide-by-zero.
        denom = 1.0 - x * self.drive * 0.5
        # Clamp away from zero: clip positive values to [1e-8, inf]
        # and negative values to [-inf, -1e-8] to avoid division by zero.
        # np.sign(0)=0 so we cannot use sign-based clamping.
        denom = np.where(denom >= 0, np.maximum(denom, 1e-8), np.minimum(denom, -1e-8))
        neg = x / denom

        return np.where(x > 0, pos, neg)

    def _symmetric(self, x: np.ndarray) -> np.ndarray:
        """
        Symmetric tanh soft-clipper.

        Both polarities clip identically — produces odd-order harmonics
        (3rd, 5th) characteristic of transistor saturation.
        """
        return np.tanh(x * self.drive)

    def _tanh_normalised(self, x: np.ndarray) -> np.ndarray:
        """
        Unity-gain normalised tanh.

        Divides by tanh(drive) to maintain consistent output level
        regardless of drive setting. Useful when drive is automated.
        """
        denom = np.tanh(self.drive)
        if abs(denom) < 1e-8:
            return x
        return np.tanh(x * self.drive) / denom

    def _wavefold(self, x: np.ndarray) -> np.ndarray:
        """
        Wavefolding saturation.

        When the signal exceeds the threshold (1/drive), it folds back
        rather than clipping. Produces complex, inharmonic overtone
        structures — characteristic of Braindance sound design and
        extreme analogue synthesis.
        """
        threshold = 1.0 / self.drive
        folded = x.copy()
        mask = np.abs(x) > threshold
        folded[mask] = (
            (2 * threshold - np.abs(x[mask])) * np.sign(x[mask])
        )
        # Apply a secondary soft-clip to the folded signal
        return np.tanh(folded * self.drive * 0.5)
