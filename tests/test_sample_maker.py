"""
tests/test_sample_maker.py

Characterization tests for engine/sample_maker.py.

Purpose:
    Pin the CURRENT default-argument output of fm_blip() before the
    FM-expansion work (branch feat/fm_blip-fm-expansion). The parameters added
    in that work are optional and additive: a default fm_blip() call must keep
    producing the exact same signal. These tests fail loudly if it does not.

Coverage:
    - fm_blip() default output: shape, dtype, range, peak-normalisation
    - fm_blip() determinism (no RNG): repeated calls are identical
    - fm_blip() value pins: global min/max and sampled points (np.allclose,
      portable across platforms — no architecture-brittle full-array hash)

Refs: feat/fm_blip-fm-expansion (Stage 1, Commit 1 — pre-expansion contract)
"""

from __future__ import annotations

import numpy as np

from engine.sample_maker import SAMPLE_RATE, fm_analog, fm_blip

# ---------------------------------------------------------------------------
# Golden values — captured from the current fm_blip() default output on engine
# `idm` at the start of feat/fm_blip-fm-expansion. If a change here is
# intentional, re-capture and update these constants deliberately.
# ---------------------------------------------------------------------------

_DEFAULT_LENGTH = int(SAMPLE_RATE * 500.0 / 1000)  # 500 ms default -> 22050
_GOLDEN_MIN = -0.99309236
_GOLDEN_MAX = 1.0
_GOLDEN_SAMPLE_IDX = (0, 5512, 11025, 16537, 22049)
_GOLDEN_SAMPLE_VAL = (0.0, 0.00776526, 0.00733435, -0.00173255, 0.0)
_ATOL = 1e-6


class TestFmBlipCharacterization:
    """Pin the current fm_blip() default output (pre-expansion contract)."""

    def test_default_shape_and_dtype(self) -> None:
        """Default call returns 500 ms of float32 at SAMPLE_RATE."""
        out = fm_blip()
        assert out.shape == (_DEFAULT_LENGTH,)
        assert out.dtype == np.float32

    def test_default_is_peak_normalized(self) -> None:
        """Output is peak-normalised and bounded to [-1.0, 1.0]."""
        out = fm_blip()
        assert np.isclose(np.max(np.abs(out)), 1.0, atol=_ATOL)
        assert out.min() >= -1.0
        assert out.max() <= 1.0

    def test_default_is_deterministic(self) -> None:
        """fm_blip() uses no RNG: two calls produce identical arrays."""
        assert np.array_equal(fm_blip(), fm_blip())

    def test_default_extrema_pinned(self) -> None:
        """Global min/max match the captured baseline."""
        out = fm_blip()
        assert np.isclose(out.min(), _GOLDEN_MIN, atol=_ATOL)
        assert np.isclose(out.max(), _GOLDEN_MAX, atol=_ATOL)

    def test_default_sampled_values_pinned(self) -> None:
        """Sampled points match the captured baseline (no silent formula change)."""
        out = fm_blip()
        sampled = out[list(_GOLDEN_SAMPLE_IDX)]
        assert np.allclose(sampled, _GOLDEN_SAMPLE_VAL, atol=_ATOL)


# ---------------------------------------------------------------------------
# FM-expansion parameters (feat/fm_blip-fm-expansion): each is off by default
# and has a real effect when engaged.
# ---------------------------------------------------------------------------


class TestFmBlipExpansion:
    """Optional expansion params: legacy-preserving defaults + real effect."""

    def test_feedback_zero_is_noop(self) -> None:
        """feedback=0.0 reproduces the default output exactly."""
        assert np.array_equal(fm_blip(feedback=0.0), fm_blip())

    def test_feedback_changes_timbre(self) -> None:
        """feedback > 0 alters the waveform."""
        assert not np.allclose(fm_blip(feedback=0.6), fm_blip())

    def test_attack_zero_is_noop(self) -> None:
        """attack_ms=0.0 reproduces the default output exactly."""
        assert np.array_equal(fm_blip(attack_ms=0.0), fm_blip())

    def test_attack_softens_onset(self) -> None:
        """attack_ms > 0 lowers early-onset energy versus the instant onset."""
        window = 1000
        with_attack = fm_blip(attack_ms=50.0)
        instant = fm_blip()
        assert np.mean(np.abs(with_attack[:window])) < np.mean(np.abs(instant[:window]))

    def test_ratio_equivalent_to_derived_mod_freq(self) -> None:
        """ratio=r is exactly equivalent to mod_freq = freq * r."""
        assert np.array_equal(
            fm_blip(freq=300.0, ratio=2.0),
            fm_blip(freq=300.0, mod_freq=600.0),
        )

    def test_ratio_none_uses_absolute_mod_freq(self) -> None:
        """ratio=None keeps the absolute mod_freq (legacy behaviour)."""
        assert np.array_equal(fm_blip(ratio=None), fm_blip())

    def test_mod_index_end_static_when_equal(self) -> None:
        """mod_index_end equal to mod_index matches the static-index output."""
        assert np.allclose(fm_blip(mod_index=2.0, mod_index_end=2.0), fm_blip())

    def test_mod_index_end_sweeps_spectrum(self) -> None:
        """A differing mod_index_end changes the output (index evolves in time)."""
        assert not np.allclose(fm_blip(mod_index_end=8.0), fm_blip())


# ---------------------------------------------------------------------------
# fm_analog — warm subtractive voice (direction A, D-DSP-02)
# ---------------------------------------------------------------------------

_ANALOG_LENGTH = int(SAMPLE_RATE * 600.0 / 1000)  # 600 ms default


def _spectral_centroid(x: np.ndarray) -> float:
    """Magnitude-weighted mean frequency (Hz) — a brightness proxy."""
    mag = np.abs(np.fft.rfft(x))
    total = float(mag.sum())
    if total < 1e-12:
        return 0.0
    freqs = np.fft.rfftfreq(len(x), 1.0 / SAMPLE_RATE)
    return float((freqs * mag).sum() / total)


class TestFmAnalog:
    """Warm analog voice: shape contract, determinism, and audible controls."""

    def test_default_shape_and_dtype(self) -> None:
        """Default call returns 600 ms of float32 at SAMPLE_RATE."""
        out = fm_analog()
        assert out.shape == (_ANALOG_LENGTH,)
        assert out.dtype == np.float32

    def test_default_is_peak_normalized(self) -> None:
        """Output is peak-normalised and bounded to [-1.0, 1.0]."""
        out = fm_analog()
        assert np.isclose(np.max(np.abs(out)), 1.0, atol=_ATOL)
        assert out.min() >= -1.0
        assert out.max() <= 1.0

    def test_is_deterministic(self) -> None:
        """fm_analog() uses no RNG: two calls produce identical arrays."""
        assert np.array_equal(fm_analog(), fm_analog())

    def test_lower_cutoff_is_darker(self) -> None:
        """A lower filter cutoff yields a lower spectral centroid (the LP filter works)."""
        dark = fm_analog(cutoff_hz=120.0, cutoff_env=0.0)
        bright = fm_analog(cutoff_hz=6000.0, cutoff_env=0.0)
        assert _spectral_centroid(dark) < _spectral_centroid(bright)

    def test_resonance_changes_output(self) -> None:
        """Resonance alters the filtered output."""
        assert not np.allclose(fm_analog(resonance=0.9), fm_analog(resonance=0.0))

    def test_detune_changes_output(self) -> None:
        """Detune (second stacked voice) alters the output; 0 cents = single pitch."""
        assert not np.allclose(fm_analog(detune_cents=20.0), fm_analog(detune_cents=0.0))

    def test_attack_softens_onset(self) -> None:
        """attack_ms > 0 lowers early-onset energy versus the instant onset."""
        window = 1000
        soft = fm_analog(attack_ms=120.0)
        instant = fm_analog(attack_ms=0.0)
        assert np.mean(np.abs(soft[:window])) < np.mean(np.abs(instant[:window]))
