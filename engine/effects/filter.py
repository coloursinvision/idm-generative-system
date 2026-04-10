"""
engine/effects/filter.py

Block 3 — Resonant Filter (VCF Emulation).

Source:
    MASTER_DATASET Part 1.2 — Synthesis & Tone Generation
    MASTER_DATASET Part 4.1 — Acid Slide (Nonlinear Glide Logic)
    MASTER_DATASET Part 4.2 — Acid Accent (Parameter Coupling & Saturation)

Hardware references:
    - Roland TB-303  : 18 dB/oct 3-pole low-pass filter — nonlinear accent/
                       resonance coupling; 30ms glide constant. The defining
                       filter of acid music.
    - Roland SH-101  : 24 dB/oct 4-pole (IR3109 chip) — rubber-like bass
                       response; perfect linear tracking.
    - Korg M1        : Digital filter — used in Japanese IDM and Detroit Techno
                       for clean, precise filtering.

Historical context:
    The TB-303's filter is a non-standard 3-pole (18 dB/oct) low-pass design
    with strongly nonlinear behaviour at high resonance values. It is the most
    imitated filter in electronic music history.

    Accent coupling (MASTER_DATASET Part 4.2):
        - Trigger: velocity > 100
        - Boosts resonance by ~15%
        - Shortens VCF decay by ~50%
        - Applies tanh saturation on the VCA output

Signal position: Bitcrusher → [Block 3] → Saturation → ...
"""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal

from engine.effects.base import BaseEffect


class ResonantFilter(BaseEffect):
    """
    VCF (Voltage-Controlled Filter) emulation.

    Models the TB-303 (3-pole, 18 dB/oct) and SH-101 (4-pole, 24 dB/oct)
    filter characteristics including nonlinear resonance feedback and
    TB-303 accent coupling.

    Args:
        cutoff_hz:    Filter cutoff frequency in Hz [20–16000].
                      Default: 1200.0 Hz.
        resonance:    Resonance amount [0.0–1.0].
                      Values above 0.7 produce self-oscillation character.
                      Default: 0.3.
        filter_type:  Filter topology.
                        'lp' — low-pass  (default, TB-303/SH-101 style)
                        'hp' — high-pass
                        'bp' — band-pass
        poles:        Filter order / pole count.
                        3 — TB-303 (18 dB/oct)
                        4 — SH-101 (24 dB/oct, default)
                        2 — gentle 12 dB/oct
        accent:       TB-303 accent coupling strength [0.0–1.0].
                      At accent > 0:
                          - resonance boosted by +15%
                          - tanh saturation applied at filter output
                      Default: 0.0 (no accent).
        envelope_mod: Filter envelope modulation depth [-1.0–1.0].
                      Positive: envelope opens the filter.
                      Negative: envelope closes the filter.
                      Default: 0.5.
        sr:           Sample rate in Hz. Default: 44100.

    Example:
        >>> f = ResonantFilter(cutoff_hz=800, resonance=0.7, poles=3)
        >>> output = f(signal)

        >>> # TB-303 accent mode
        >>> f = ResonantFilter(cutoff_hz=600, resonance=0.6, poles=3, accent=0.8)
        >>> output = f(signal)
    """

    _VALID_FILTER_TYPES = {"lp", "hp", "bp"}

    def __init__(
        self,
        cutoff_hz: float = 1200.0,
        resonance: float = 0.3,
        filter_type: str = "lp",
        poles: int = 4,
        accent: float = 0.0,
        envelope_mod: float = 0.5,
        sr: int = 44100,
    ) -> None:
        if filter_type not in self._VALID_FILTER_TYPES:
            raise ValueError(
                f"Invalid filter_type '{filter_type}'. Options: {sorted(self._VALID_FILTER_TYPES)}"
            )

        self.cutoff_hz = cutoff_hz
        self.resonance = resonance
        self.filter_type = filter_type
        self.poles = poles
        self.accent = accent
        self.envelope_mod = envelope_mod
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply resonant filter to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Filtered audio array.
        """
        # TB-303 accent coupling: boost resonance (MASTER_DATASET Part 4.2)
        effective_resonance = self.resonance
        if self.accent > 0:
            effective_resonance = min(self.resonance + self.accent * 0.15, 0.98)

        # Build filter coefficients
        cutoff_norm = np.clip(self.cutoff_hz / (self.sr / 2.0), 0.001, 0.999)
        sos = self._build_filter(cutoff_norm)
        filtered = scipy_signal.sosfilt(sos, signal)

        # Resonance feedback injection (self-oscillation character)
        if effective_resonance > 0.1:
            filtered = self._apply_resonance_feedback(filtered, cutoff_norm, effective_resonance)

        # Nonlinear VCA saturation (TB-303 accent / high resonance)
        if self.accent > 0 or effective_resonance > 0.6:
            filtered = self._apply_vca_saturation(filtered, effective_resonance)

        return filtered

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_filter(self, cutoff_norm: float) -> np.ndarray:
        """Build second-order sections (SOS) for the configured filter."""
        order = self.poles

        if self.filter_type == "lp":
            return scipy_signal.butter(order, cutoff_norm, btype="low", output="sos")
        if self.filter_type == "hp":
            return scipy_signal.butter(order, cutoff_norm, btype="high", output="sos")
        if self.filter_type == "bp":
            bw = cutoff_norm * 0.3
            low = max(cutoff_norm - bw, 0.001)
            high = min(cutoff_norm + bw, 0.999)
            return scipy_signal.butter(max(order // 2, 1), [low, high], btype="band", output="sos")
        # Fallback: low-pass
        return scipy_signal.butter(order, cutoff_norm, btype="low", output="sos")

    def _apply_resonance_feedback(
        self,
        filtered: np.ndarray,
        cutoff_norm: float,
        resonance: float,
    ) -> np.ndarray:
        """
        Inject band-limited feedback to simulate resonance peak.

        At high resonance values this creates the characteristic
        'singing' quality of the TB-303 and SH-101 at cutoff.
        """
        feedback_gain = resonance**2 * 0.6
        fb_sos = scipy_signal.butter(2, cutoff_norm, btype="low", output="sos")
        feedback = scipy_signal.sosfilt(fb_sos, filtered) * feedback_gain
        return filtered + feedback

    def _apply_vca_saturation(
        self,
        signal: np.ndarray,
        resonance: float,
    ) -> np.ndarray:
        """
        Apply tanh saturation at the VCA output.

        Models the nonlinear behaviour of the TB-303's VCA during accent
        (MASTER_DATASET Part 4.2: tanh saturation on VCA).
        """
        drive = 1.0 + resonance * 2.0
        return np.tanh(signal * drive) / np.tanh(drive)
