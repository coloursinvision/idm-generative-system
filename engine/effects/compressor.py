"""
engine/effects/compressor.py

Block 9 — Bus Compressor (SSL-Style Glue · Soft Knee · DR8–DR10 Target).

Source:
    MASTER_DATASET — Bus Summing, Dynamics Processing
    IDM mastering references: DR8–DR10 target dynamic range

Hardware references:
    - SSL 4000 G Series Bus Compressor (1987): The defining mix-bus
      compressor for electronic music. Auto-release circuit with
      program-dependent time constants — fast transients trigger short
      release, sustained material triggers longer release. The "glue"
      effect that bonds disparate elements into a cohesive stereo image.
      Ratio selections: 2:1, 4:1, 10:1. Fixed attack detents.
      Used on virtually every major IDM release from 1992 onward.

    - Neve 33609 (1969, updated 1985): Diode-bridge compressor with
      soft-knee transfer curve. Warm, harmonically rich compression
      with a slower, more "breathing" character than SSL. The inherent
      soft knee comes from the diode bridge topology — gain reduction
      onset is gradual rather than abrupt.
      Notable: Autechre's Warp-era masters, Boards of Canada.

    - dbx 160A (1976): VCA compressor, hard-knee, ultra-fast attack
      (<1 ms). Extreme transient shaping on drums. The aggressive,
      punchy sound of breakbeat processing.

Historical context:
    Dynamic range in IDM sits in a narrow sweet spot: DR8–DR10. This
    range preserves micro-dynamic detail (ghost notes, velocity layers,
    reverb tails) while maintaining enough density to translate on
    small speakers and club systems.

    Below DR8: crushed, lifeless — micro-dynamics destroyed. The loudness
    war sound that kills IDM's textural depth.

    Above DR10: too open for dense arrangements — elements fight for
    attention, bass doesn't sit, and the mix falls apart on earbuds.

    The compressor design here models three behaviours:
        1. Soft-knee transfer curve (Neve 33609 topology)
        2. Program-dependent release (SSL auto-release circuit)
        3. Sidechain high-pass filter (prevents sub-bass from driving
           gain reduction — critical for bass-heavy IDM)

    Gain reduction is computed in dB domain via RMS envelope detection,
    smoothed with separate attack/release time constants, and applied
    in linear domain. This mirrors the analog signal path of hardware
    bus compressors.

Signal position: GlitchEngine → [Block 9] → VinylMastering → OUTPUT
"""

from __future__ import annotations

import numpy as np
from numba import njit
from scipy import signal as scipy_signal
from engine.effects.base import BaseEffect


# ---------------------------------------------------------------------------
# Preset configurations — calibrated against hardware behaviour
# ---------------------------------------------------------------------------

COMPRESSOR_PRESETS: dict[str, dict] = {
    "ssl_glue": {
        "threshold_db":  -18.0,
        "ratio":         4.0,
        "attack_ms":     10.0,
        "release_ms":    100.0,
        "knee_db":       4.0,
        "auto_release":  True,
    },
    "neve_warm": {
        "threshold_db":  -14.0,
        "ratio":         3.0,
        "attack_ms":     20.0,
        "release_ms":    200.0,
        "knee_db":       10.0,
        "auto_release":  False,
    },
    "dbx_punch": {
        "threshold_db":  -20.0,
        "ratio":         8.0,
        "attack_ms":     0.5,
        "release_ms":    50.0,
        "knee_db":       2.0,
        "auto_release":  False,
    },
}


# ---------------------------------------------------------------------------
# Numba-compiled DSP kernels (CR-04)
#
# Envelope smoothing loops extracted to module-level @njit functions.
# These are the compressor's tightest inner loops — per-sample attack/release
# ballistics that cannot be vectorised (each sample depends on the previous).
# ---------------------------------------------------------------------------

@njit(cache=True)
def _smooth_envelope_single(
    gr_db: np.ndarray,
    n: int,
    attack_coeff: float,
    release_coeff: float,
    env_init: float,
) -> tuple[np.ndarray, float]:
    """
    Standard single-detector attack/release envelope — Numba-compiled.

    One-pole IIR smoother: attack coefficient when gain reduction
    increases (signal getting louder), release coefficient when it
    decreases (signal getting quieter). The asymmetric time constants
    produce the musical "grab and release" character of analog compressors.

    Returns:
        Tuple of (smoothed gain reduction array, final envelope state).
    """
    smoothed = np.zeros(n)
    env = env_init
    for i in range(n):
        target = gr_db[i]
        if target < env:
            env = attack_coeff * env + (1.0 - attack_coeff) * target
        else:
            env = release_coeff * env + (1.0 - release_coeff) * target
        smoothed[i] = env
    return smoothed, env


@njit(cache=True)
def _smooth_envelope_auto(
    gr_db: np.ndarray,
    n: int,
    attack_coeff: float,
    fast_release_coeff: float,
    slow_release_coeff: float,
    env_init: float,
) -> tuple[np.ndarray, float]:
    """
    SSL 4000 G dual-detector auto-release envelope — Numba-compiled.

    Two parallel envelope followers with different release time constants:
      - Fast detector (50 ms release): tracks transient peaks
      - Slow detector (600 ms release): tracks programme level

    Output is the deeper (more negative) gain reduction of the two.
    This produces natural, breathing compression that doesn't pump
    on transients but recovers quickly during sustained passages.

    Returns:
        Tuple of (smoothed gain reduction array, final envelope state).
    """
    smoothed = np.zeros(n)
    env_fast = env_init
    env_slow = env_init

    for i in range(n):
        target = gr_db[i]

        # Fast detector
        if target < env_fast:
            env_fast = attack_coeff * env_fast + (1.0 - attack_coeff) * target
        else:
            env_fast = fast_release_coeff * env_fast + (1.0 - fast_release_coeff) * target

        # Slow detector
        if target < env_slow:
            env_slow = attack_coeff * env_slow + (1.0 - attack_coeff) * target
        else:
            env_slow = slow_release_coeff * env_slow + (1.0 - slow_release_coeff) * target

        # Take the deeper gain reduction of the two
        if env_fast < env_slow:
            smoothed[i] = env_fast
        else:
            smoothed[i] = env_slow

    final_env = env_fast if env_fast < env_slow else env_slow
    return smoothed, final_env


class Compressor(BaseEffect):
    """
    IDM bus compressor with soft knee, program-dependent release,
    and sidechain high-pass filter.

    Models the analogue signal path: sidechain HPF → RMS envelope
    detection → soft-knee gain computation → attack/release smoothing
    → gain application → makeup gain.

    The soft knee implements a quadratic interpolation zone around the
    threshold, mirroring the gradual onset characteristic of diode-bridge
    compressor topologies (Neve 33609). Outside the knee zone, the
    transfer function is piecewise linear (hard knee).

    Program-dependent release (auto_release) models the SSL 4000 G
    auto-release circuit: transient peaks trigger fast release (~50 ms),
    sustained material triggers slow release (~600 ms), blended via
    a dual-detector envelope.

    Args:
        threshold_db:     Compression threshold in dBFS [-60.0–0.0].
                          Signal below this level passes unchanged.
                          Default: -18.0 dB.
        ratio:            Compression ratio [1.0–20.0].
                          1.0 = no compression. 20.0 ≈ limiting.
                          Default: 4.0 (SSL 4:1).
        attack_ms:        Attack time in ms [0.1–100.0].
                          Time for gain reduction to reach ~63% of target.
                          Default: 10.0 ms.
        release_ms:       Release time in ms [10.0–2000.0].
                          Time for gain reduction to decay by ~63%.
                          Overridden per-sample when auto_release=True.
                          Default: 100.0 ms.
        knee_db:          Soft knee width in dB [0.0–20.0].
                          0.0 = hard knee. 10.0+ = very gradual onset.
                          Default: 6.0 dB.
        auto_release:     Enable program-dependent release [bool].
                          Models SSL auto-release dual-detector circuit.
                          Default: True.
        sidechain_hpf_hz: Sidechain high-pass cutoff in Hz [0–500].
                          0 = no sidechain filtering.
                          Prevents sub-bass from driving gain reduction.
                          Default: 80 Hz.
        rms_window_ms:    RMS detection window in ms [1.0–50.0].
                          Shorter = more transient-responsive.
                          Default: 10.0 ms.
        makeup_db:        Manual makeup gain in dB [0.0–24.0].
                          Applied after compression.
                          Default: 0.0 (use auto_makeup).
        auto_makeup:      Automatic makeup gain [bool].
                          Estimates gain compensation from threshold and
                          ratio. Overrides makeup_db when True.
                          Default: True.
        mix:              Dry/wet blend [0.0–1.0].
                          Enables parallel (NY-style) compression.
                          Default: 1.0.
        sr:               Sample rate in Hz. Default: 44100.

    Example:
        >>> # SSL-style glue on mix bus (IDM standard)
        >>> comp = Compressor(threshold_db=-18, ratio=4, auto_release=True)
        >>> output = comp(signal)

        >>> # Parallel compression (NY-style — retains transient punch)
        >>> comp = Compressor(threshold_db=-24, ratio=8, mix=0.4)

        >>> # Neve-style warm bus compression
        >>> comp = Compressor(threshold_db=-14, ratio=3, knee_db=10,
        ...                   attack_ms=20, release_ms=200)

        >>> # dbx-style aggressive drum bus
        >>> comp = Compressor(threshold_db=-20, ratio=8, attack_ms=0.5,
        ...                   knee_db=2, auto_makeup=True)
    """

    def __init__(
        self,
        threshold_db: float = -18.0,
        ratio: float = 4.0,
        attack_ms: float = 10.0,
        release_ms: float = 100.0,
        knee_db: float = 6.0,
        auto_release: bool = True,
        sidechain_hpf_hz: float = 80.0,
        rms_window_ms: float = 10.0,
        makeup_db: float = 0.0,
        auto_makeup: bool = True,
        mix: float = 1.0,
        sr: int = 44100,
    ) -> None:
        self.threshold_db = np.clip(threshold_db, -60.0, 0.0)
        self.ratio = np.clip(ratio, 1.0, 20.0)
        self.attack_ms = np.clip(attack_ms, 0.1, 100.0)
        self.release_ms = np.clip(release_ms, 10.0, 2000.0)
        self.knee_db = np.clip(knee_db, 0.0, 20.0)
        self.auto_release = auto_release
        self.sidechain_hpf_hz = max(sidechain_hpf_hz, 0.0)
        self.rms_window_ms = np.clip(rms_window_ms, 1.0, 50.0)
        self.makeup_db = np.clip(makeup_db, 0.0, 24.0)
        self.auto_makeup = auto_makeup
        self.mix = np.clip(mix, 0.0, 1.0)
        self.sr = sr

        # Envelope follower state — persists across calls, cleared by reset()
        self._env_state: float = 0.0

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply bus compression to the input signal.

        Processing chain: sidechain HPF → RMS envelope → soft-knee
        gain computation → attack/release smoothing → gain application
        → makeup gain → dry/wet mix.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Compressed audio array.
        """
        if len(signal) < 2:
            return signal

        dry = signal.copy()

        # Sidechain path — HPF removes sub-bass from detection
        sidechain = self._apply_sidechain_hpf(signal)

        # RMS envelope detection (in dB)
        env_db = self._compute_rms_envelope(sidechain)

        # Gain reduction curve (soft knee)
        gain_reduction_db = self._compute_gain_reduction(env_db)

        # Smooth gain reduction via attack/release
        smoothed_gr_db = self._smooth_envelope(gain_reduction_db)

        # Apply gain reduction (dB → linear)
        gain_linear = np.power(10.0, smoothed_gr_db / 20.0)
        wet = signal * gain_linear

        # Makeup gain
        makeup_linear = self._compute_makeup_gain()
        wet = wet * makeup_linear

        # Soft clip — only engage when makeup gain pushes peaks above ±1.0
        # Transparent otherwise (no colouration at unity or below)
        if np.max(np.abs(wet)) > 1.0:
            wet = np.tanh(wet)

        return dry * (1.0 - self.mix) + wet * self.mix

    def reset(self) -> None:
        """Reset envelope follower state."""
        self._env_state = 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_sidechain_hpf(self, signal: np.ndarray) -> np.ndarray:
        """
        High-pass filter the sidechain detection path.

        Prevents sub-bass energy from driving gain reduction — critical
        for bass-heavy IDM where kick drums and sub-bass would otherwise
        cause excessive pumping on every hit.
        """
        if self.sidechain_hpf_hz <= 0.0:
            return signal

        cutoff_norm = np.clip(
            self.sidechain_hpf_hz / (self.sr / 2.0), 0.001, 0.999
        )
        sos = scipy_signal.butter(2, cutoff_norm, btype="high", output="sos")
        return scipy_signal.sosfilt(sos, signal)

    def _compute_rms_envelope(self, signal: np.ndarray) -> np.ndarray:
        """
        Compute RMS envelope in dB using a sliding window.

        RMS detection is more musical than peak detection for bus
        compression — it responds to average energy rather than
        individual transient spikes, producing smoother gain reduction.

        Vectorised implementation using cumulative sum — no per-sample
        Python loop. Window boundaries computed via NumPy broadcasting.
        """
        n = len(signal)
        window_samp = max(int(self.rms_window_ms * self.sr / 1000), 1)

        # Squared signal — cumulative sum for efficient windowed RMS
        sq = signal ** 2
        cumsum = np.cumsum(sq)
        cumsum = np.insert(cumsum, 0, 0.0)

        # Vectorised windowed mean: start indices clamp to 0
        indices = np.arange(n)
        starts = np.maximum(indices - window_samp + 1, 0)
        window_sizes = indices - starts + 1

        # Windowed mean of squared signal (no per-sample loop)
        rms_sq = (cumsum[indices + 1] - cumsum[starts]) / window_sizes

        # RMS → dB (floor at -120 dB to avoid log(0))
        rms_linear = np.sqrt(np.maximum(rms_sq, 1e-12))
        return 20.0 * np.log10(rms_linear)

    def _compute_gain_reduction(self, env_db: np.ndarray) -> np.ndarray:
        """
        Compute gain reduction via soft-knee transfer function.

        Below the knee zone: no gain reduction (1:1 mapping).
        Within the knee zone: quadratic interpolation (soft onset).
        Above the knee zone: linear compression at the set ratio.

        The soft knee produces the gradual, musical onset characteristic
        of diode-bridge compressor topologies (Neve 33609).
        """
        half_knee = self.knee_db / 2.0
        threshold = float(self.threshold_db)
        ratio = float(self.ratio)

        # Output level on the transfer curve
        output_db = np.copy(env_db)

        if self.knee_db > 0.01:
            # --- Soft knee: three regions ---

            # Region 1: below knee — no compression
            below = env_db < (threshold - half_knee)

            # Region 2: within knee — quadratic interpolation
            in_knee = (~below) & (env_db < (threshold + half_knee))

            # Region 3: above knee — full compression
            above = env_db >= (threshold + half_knee)

            # Quadratic knee (peaking at threshold ± half_knee)
            knee_delta = env_db[in_knee] - threshold + half_knee
            output_db[in_knee] = (
                env_db[in_knee]
                + (1.0 / ratio - 1.0)
                * (knee_delta ** 2)
                / (2.0 * self.knee_db)
            )

            # Linear compression above knee
            output_db[above] = (
                threshold + (env_db[above] - threshold) / ratio
            )
        else:
            # --- Hard knee ---
            above = env_db > threshold
            output_db[above] = (
                threshold + (env_db[above] - threshold) / ratio
            )

        # Gain reduction = difference between input level and output level
        # (always ≤ 0 dB)
        return np.minimum(output_db - env_db, 0.0)

    def _smooth_envelope(self, gr_db: np.ndarray) -> np.ndarray:
        """
        Smooth gain reduction with attack/release time constants.

        When auto_release is enabled, models the SSL 4000 G dual-detector
        auto-release circuit:
            - Fast detector: 50 ms release (tracks transients)
            - Slow detector: 600 ms release (tracks programme level)
            - Output: maximum gain reduction of the two detectors

        This produces natural, breathing compression that doesn't pump
        on transients but recovers quickly during sustained passages.

        Inner loops delegated to Numba-compiled kernels (CR-04).
        """
        n = len(gr_db)
        attack_coeff = np.exp(-1.0 / (self.attack_ms * self.sr / 1000))
        release_coeff = np.exp(-1.0 / (self.release_ms * self.sr / 1000))

        if self.auto_release:
            # SSL dual-detector auto-release
            fast_release_coeff = np.exp(-1.0 / (50.0 * self.sr / 1000))
            slow_release_coeff = np.exp(-1.0 / (600.0 * self.sr / 1000))

            smoothed, final_env = _smooth_envelope_auto(
                gr_db, n,
                float(attack_coeff),
                float(fast_release_coeff),
                float(slow_release_coeff),
                float(self._env_state),
            )
            self._env_state = float(final_env)
        else:
            # Standard single-detector attack/release
            smoothed, final_env = _smooth_envelope_single(
                gr_db, n,
                float(attack_coeff),
                float(release_coeff),
                float(self._env_state),
            )
            self._env_state = float(final_env)

        return smoothed

    def _compute_makeup_gain(self) -> float:
        """
        Compute makeup gain in linear domain.

        Auto-makeup estimates the average gain reduction at threshold
        for the given ratio, compensating so perceived loudness stays
        roughly constant when compression is applied.

        Formula: makeup_dB ≈ -threshold_dB × (1 - 1/ratio) × 0.5
        The 0.5 factor accounts for programme material spending roughly
        half its time above threshold (empirical, SSL-calibrated).
        """
        if self.auto_makeup:
            estimated_gr = (
                -float(self.threshold_db)
                * (1.0 - 1.0 / float(self.ratio))
                * 0.5
            )
            return float(np.power(10.0, estimated_gr / 20.0))
        else:
            return float(np.power(10.0, self.makeup_db / 20.0))
