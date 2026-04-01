"""
tests/test_effects.py

Unit tests for all 10 DSP effect blocks in the IDM Generative System.

Coverage:
    - Output shape preservation (length in == length out)
    - Mono signal integrity (ndim == 1)
    - Stateful block reset (Compressor envelope follower)
    - Parameter validation (ValueError on invalid string params)
    - Edge cases: all-zeros, single sample, very short signal
    - Parameter extremes: max drive, min bit depth, high feedback
    - Bypass behaviour: effects at neutral settings
    - Numba kernel regression (CR-04): output parity vs pure-Python reference
    - Vectorised RMS envelope: output parity vs sequential reference

Run:
    pytest tests/test_effects.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.effects import (
    BaseEffect,
    EffectChain,
    build_chain,
    CANONICAL_ORDER,
    NoiseFloor,
    Bitcrusher,
    ResonantFilter,
    Saturation,
    Reverb,
    TapeDelay,
    SpatialProcessor,
    GlitchEngine,
    Compressor,
    VinylMastering,
)

# Numba-compiled kernels — imported for direct regression testing
from engine.effects.reverb import _comb_filter_kernel, _allpass_kernel
from engine.effects.delay import _delay_line_kernel
from engine.effects.compressor import _smooth_envelope_single, _smooth_envelope_auto


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def signal_short() -> np.ndarray:
    """Short deterministic signal (1024 samples, ~23ms at 44100 Hz)."""
    rng = np.random.default_rng(42)
    return rng.uniform(-0.8, 0.8, 1024).astype(np.float64)


@pytest.fixture()
def signal_medium() -> np.ndarray:
    """Medium deterministic signal (8820 samples, 200ms at 44100 Hz)."""
    rng = np.random.default_rng(99)
    return rng.uniform(-0.8, 0.8, 8820).astype(np.float64)


@pytest.fixture()
def signal_zeros() -> np.ndarray:
    """All-zeros signal (2048 samples)."""
    return np.zeros(2048, dtype=np.float64)


@pytest.fixture()
def signal_single() -> np.ndarray:
    """Single-sample signal."""
    return np.array([0.5], dtype=np.float64)


# All 10 block classes with default constructors
ALL_EFFECT_CLASSES: list[type[BaseEffect]] = [
    NoiseFloor,
    Bitcrusher,
    ResonantFilter,
    Saturation,
    Reverb,
    TapeDelay,
    SpatialProcessor,
    GlitchEngine,
    Compressor,
    VinylMastering,
]


# ---------------------------------------------------------------------------
# Shape preservation
# ---------------------------------------------------------------------------

class TestShapePreservation:
    """Every effect block must preserve input signal length."""

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_output_length_matches_input(
        self, EffectClass: type[BaseEffect], signal_short: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_short)
        assert len(output) == len(signal_short), (
            f"{EffectClass.__name__}: output length {len(output)} != "
            f"input length {len(signal_short)}"
        )

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_output_is_mono(
        self, EffectClass: type[BaseEffect], signal_short: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_short)
        assert output.ndim == 1, (
            f"{EffectClass.__name__}: output ndim={output.ndim}, expected 1"
        )

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_output_is_float(
        self, EffectClass: type[BaseEffect], signal_short: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_short)
        assert np.issubdtype(output.dtype, np.floating), (
            f"{EffectClass.__name__}: output dtype={output.dtype}, expected float"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Effect blocks must handle degenerate inputs without crashing."""

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_all_zeros_input(
        self, EffectClass: type[BaseEffect], signal_zeros: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_zeros)
        assert len(output) == len(signal_zeros)
        assert np.all(np.isfinite(output)), (
            f"{EffectClass.__name__}: non-finite values in output from zeros input"
        )

    @pytest.mark.parametrize("EffectClass", [
        NoiseFloor, Bitcrusher, ResonantFilter, Saturation,
        SpatialProcessor,
    ])
    def test_single_sample_input(
        self, EffectClass: type[BaseEffect], signal_single: np.ndarray
    ) -> None:
        """Blocks that don't have minimum-length guards must handle 1 sample."""
        effect = EffectClass()
        output = effect(signal_single)
        assert len(output) == 1
        assert np.isfinite(output[0])

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_no_nan_in_output(
        self, EffectClass: type[BaseEffect], signal_short: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_short)
        assert not np.any(np.isnan(output)), (
            f"{EffectClass.__name__}: NaN detected in output"
        )

    @pytest.mark.parametrize("EffectClass", ALL_EFFECT_CLASSES)
    def test_no_inf_in_output(
        self, EffectClass: type[BaseEffect], signal_short: np.ndarray
    ) -> None:
        effect = EffectClass()
        output = effect(signal_short)
        assert not np.any(np.isinf(output)), (
            f"{EffectClass.__name__}: Inf detected in output"
        )


# ---------------------------------------------------------------------------
# Parameter validation (CR-05)
# ---------------------------------------------------------------------------

class TestParameterValidation:
    """Invalid string parameters must raise ValueError."""

    def test_noise_floor_invalid_noise_type(self) -> None:
        with pytest.raises(ValueError, match="noise_type"):
            NoiseFloor(noise_type="invalid")

    def test_bitcrusher_invalid_mode(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            Bitcrusher(mode="invalid")

    def test_bitcrusher_invalid_hardware_preset(self) -> None:
        with pytest.raises(ValueError, match="hardware_preset"):
            Bitcrusher(hardware_preset="invalid")

    def test_filter_invalid_filter_type(self) -> None:
        with pytest.raises(ValueError, match="filter_type"):
            ResonantFilter(filter_type="invalid")

    def test_saturation_invalid_mode(self) -> None:
        with pytest.raises(ValueError, match="mode"):
            Saturation(mode="invalid")

    def test_reverb_invalid_reverb_type(self) -> None:
        with pytest.raises(ValueError, match="reverb_type"):
            Reverb(reverb_type="invalid")

    def test_delay_invalid_tape_age(self) -> None:
        with pytest.raises(ValueError, match="tape_age"):
            TapeDelay(tape_age="invalid")

    def test_glitch_invalid_xor_mode(self) -> None:
        with pytest.raises(ValueError, match="xor_mode"):
            GlitchEngine(xor_mode="invalid")

    def test_vinyl_invalid_dat_mode(self) -> None:
        with pytest.raises(ValueError, match="dat_mode"):
            VinylMastering(dat_mode="invalid")

    def test_vinyl_invalid_vinyl_condition(self) -> None:
        with pytest.raises(ValueError, match="vinyl_condition"):
            VinylMastering(vinyl_condition="invalid")


# ---------------------------------------------------------------------------
# Valid parameter acceptance
# ---------------------------------------------------------------------------

class TestValidParameters:
    """Every documented option for every string parameter must be accepted."""

    @pytest.mark.parametrize("nt", ["pink", "white", "hum_uk", "hum_us"])
    def test_noise_floor_valid_types(self, nt: str) -> None:
        nf = NoiseFloor(noise_type=nt)
        assert nf.noise_type == nt

    @pytest.mark.parametrize("m", ["floor", "round", "truncate"])
    def test_bitcrusher_valid_modes(self, m: str) -> None:
        bc = Bitcrusher(mode=m)
        assert bc.mode == m

    @pytest.mark.parametrize("hp", ["sp1200", "s950", "rz1", "909_cymbal"])
    def test_bitcrusher_valid_presets(self, hp: str) -> None:
        bc = Bitcrusher(hardware_preset=hp)
        assert bc.hardware_preset == hp

    @pytest.mark.parametrize("m", ["asymmetric", "symmetric", "tanh", "wavefold"])
    def test_saturation_valid_modes(self, m: str) -> None:
        s = Saturation(mode=m)
        assert s.mode == m

    @pytest.mark.parametrize("ft", ["lp", "hp", "bp"])
    def test_filter_valid_types(self, ft: str) -> None:
        f = ResonantFilter(filter_type=ft)
        assert f.filter_type == ft

    @pytest.mark.parametrize("rt", ["room", "chamber", "plate", "hall", "spring"])
    def test_reverb_valid_types(self, rt: str) -> None:
        r = Reverb(reverb_type=rt)
        assert r.reverb_type == rt

    @pytest.mark.parametrize("age", ["new", "used", "worn"])
    def test_delay_valid_tape_ages(self, age: str) -> None:
        d = TapeDelay(tape_age=age)
        assert d.tape_age == age

    @pytest.mark.parametrize("xm", ["subtle", "moderate", "heavy", "destroy"])
    def test_glitch_valid_xor_modes(self, xm: str) -> None:
        g = GlitchEngine(xor_mode=xm)
        assert g.xor_mode == xm

    @pytest.mark.parametrize("dm", ["dat_lp", "dat_sp", "cd", "none"])
    def test_vinyl_valid_dat_modes(self, dm: str) -> None:
        v = VinylMastering(dat_mode=dm)
        assert v.dat_mode == dm

    @pytest.mark.parametrize("vc", ["mint", "good", "worn", "trashed"])
    def test_vinyl_valid_conditions(self, vc: str) -> None:
        v = VinylMastering(vinyl_condition=vc)
        assert v.vinyl_condition == vc


# ---------------------------------------------------------------------------
# Stateful block behaviour
# ---------------------------------------------------------------------------

class TestStatefulBlocks:
    """Blocks with internal state must reset correctly."""

    def test_compressor_reset_clears_envelope(self) -> None:
        comp = Compressor()
        signal = np.random.default_rng(0).uniform(-0.5, 0.5, 4410).astype(np.float64)

        # Process a signal to build up envelope state
        comp(signal)
        assert comp._env_state != 0.0, "Envelope state should be non-zero after processing"

        # Reset and verify
        comp.reset()
        assert comp._env_state == 0.0, "Envelope state should be zero after reset"

    def test_compressor_reset_between_renders_via_chain(
        self, signal_short: np.ndarray
    ) -> None:
        """EffectChain.reset() is called before each render."""
        chain = EffectChain([Compressor()])

        output_1 = chain(signal_short)
        output_2 = chain(signal_short)

        # Both renders should produce identical output because
        # the chain resets the compressor before each call
        np.testing.assert_array_equal(output_1, output_2)


# ---------------------------------------------------------------------------
# Parameter extremes
# ---------------------------------------------------------------------------

class TestParameterExtremes:
    """Extreme but valid parameter values must not produce NaN/Inf."""

    def test_bitcrusher_minimum_depth(self, signal_short: np.ndarray) -> None:
        bc = Bitcrusher(bit_depth=4, dither=False)
        output = bc(signal_short)
        assert np.all(np.isfinite(output))
        assert np.max(np.abs(output)) <= 1.0

    def test_saturation_extreme_drive(self, signal_short: np.ndarray) -> None:
        for mode in ["asymmetric", "symmetric", "tanh", "wavefold"]:
            sat = Saturation(drive=10.0, mode=mode)
            output = sat(signal_short)
            assert np.all(np.isfinite(output)), f"mode={mode}: non-finite at drive=10"

    def test_filter_high_resonance(self, signal_short: np.ndarray) -> None:
        f = ResonantFilter(resonance=0.98, cutoff_hz=800.0, poles=3, accent=0.9)
        output = f(signal_short)
        assert np.all(np.isfinite(output))

    def test_delay_near_self_oscillation(self, signal_medium: np.ndarray) -> None:
        td = TapeDelay(feedback=0.98, delay_ms=200.0, tape_saturation=0.9)
        output = td(signal_medium)
        assert np.all(np.isfinite(output))

    def test_glitch_maximum_destruction(self, signal_short: np.ndarray) -> None:
        ge = GlitchEngine(
            stutter_density=1.0,
            xor_mode="destroy",
            xor_density=1.0,
            loop_mod_depth=1.0,
            mix=1.0,
            seed=42,
        )
        output = ge(signal_short)
        assert np.all(np.isfinite(output))
        assert len(output) == len(signal_short)

    def test_vinyl_maximum_degradation(self, signal_short: np.ndarray) -> None:
        vm = VinylMastering(
            riaa_intensity=1.0,
            vinyl_condition="trashed",
            noise_mix=1.0,
            dat_mode="dat_lp",
            seed=42,
        )
        output = vm(signal_short)
        assert np.all(np.isfinite(output))

    def test_compressor_heavy_compression(self, signal_short: np.ndarray) -> None:
        comp = Compressor(threshold_db=-40.0, ratio=20.0, attack_ms=0.1, knee_db=0.0)
        output = comp(signal_short)
        assert np.all(np.isfinite(output))

    def test_reverb_long_decay(self, signal_short: np.ndarray) -> None:
        rev = Reverb(decay_s=10.0, diffusion=1.0, mix=1.0, reverb_type="hall")
        output = rev(signal_short)
        assert np.all(np.isfinite(output))


# ---------------------------------------------------------------------------
# Hardware presets
# ---------------------------------------------------------------------------

class TestHardwarePresets:
    """Hardware presets must apply correct parameters."""

    def test_sp1200_preset(self) -> None:
        bc = Bitcrusher(hardware_preset="sp1200")
        assert bc.bit_depth == 12
        assert bc.sample_rate_reduction >= 1

    def test_rz1_preset(self) -> None:
        bc = Bitcrusher(hardware_preset="rz1")
        assert bc.bit_depth == 8

    def test_909_cymbal_preset(self) -> None:
        bc = Bitcrusher(hardware_preset="909_cymbal")
        assert bc.bit_depth == 6

    def test_s950_preset_no_downsampling(self) -> None:
        bc = Bitcrusher(hardware_preset="s950")
        assert bc.bit_depth == 12
        assert bc.sample_rate_reduction == 1


# ---------------------------------------------------------------------------
# EffectChain
# ---------------------------------------------------------------------------

class TestEffectChain:
    """EffectChain pipeline behaviour."""

    def test_empty_chain_is_identity(self, signal_short: np.ndarray) -> None:
        chain = EffectChain([])
        output = chain(signal_short)
        np.testing.assert_array_equal(output, signal_short)

    def test_bypass_returns_input(self, signal_short: np.ndarray) -> None:
        chain = build_chain()
        chain.bypass = True
        output = chain(signal_short)
        np.testing.assert_array_equal(output, signal_short)

    def test_canonical_chain_has_10_blocks(self) -> None:
        chain = build_chain()
        assert len(chain) == 10

    def test_skip_reduces_chain_length(self) -> None:
        chain = build_chain(skip=["reverb", "delay", "glitch"])
        assert len(chain) == 7

    def test_build_chain_with_overrides(self, signal_short: np.ndarray) -> None:
        chain = build_chain(overrides={"bitcrusher": {"bit_depth": 6}})
        output = chain(signal_short)
        assert len(output) == len(signal_short)
        assert np.all(np.isfinite(output))

    def test_build_chain_skip_all(self, signal_short: np.ndarray) -> None:
        all_keys = [key for key, _ in CANONICAL_ORDER]
        chain = build_chain(skip=all_keys)
        assert len(chain) == 0
        output = chain(signal_short)
        np.testing.assert_array_equal(output, signal_short)

    def test_append_and_remove(self) -> None:
        chain = EffectChain([])
        chain.append(NoiseFloor())
        assert len(chain) == 1
        removed = chain.remove(0)
        assert isinstance(removed, NoiseFloor)
        assert len(chain) == 0

    def test_insert_at_position(self) -> None:
        chain = EffectChain([NoiseFloor(), Compressor()])
        chain.insert(1, Bitcrusher())
        assert len(chain) == 3
        assert isinstance(chain.effects[1], Bitcrusher)


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    """Seeded effects must produce identical output across runs."""

    def test_glitch_deterministic_with_seed(self, signal_short: np.ndarray) -> None:
        ge1 = GlitchEngine(seed=42)
        ge2 = GlitchEngine(seed=42)
        out1 = ge1(signal_short.copy())
        out2 = ge2(signal_short.copy())
        np.testing.assert_array_equal(out1, out2)

    def test_glitch_different_seeds_differ(self, signal_short: np.ndarray) -> None:
        ge1 = GlitchEngine(seed=42, stutter_density=0.5, xor_density=0.3, mix=1.0)
        ge2 = GlitchEngine(seed=99, stutter_density=0.5, xor_density=0.3, mix=1.0)
        out1 = ge1(signal_short.copy())
        out2 = ge2(signal_short.copy())
        assert not np.array_equal(out1, out2)

    def test_vinyl_deterministic_with_seed(self, signal_short: np.ndarray) -> None:
        vm1 = VinylMastering(seed=42, noise_mix=0.5)
        vm2 = VinylMastering(seed=42, noise_mix=0.5)
        out1 = vm1(signal_short.copy())
        out2 = vm2(signal_short.copy())
        np.testing.assert_array_equal(out1, out2)


# ===========================================================================
# CR-04 — Numba kernel regression tests
#
# Each test class provides a pure-Python reference implementation of the
# original pre-Numba loop, then asserts that the Numba-compiled kernel
# produces numerically identical output (within double-precision tolerance).
#
# Tolerance: rtol=1e-12, atol=1e-15 — allows for LLVM vs CPython float
# evaluation order differences, which are negligible at float64 precision.
# ===========================================================================

# Tolerance constants for Numba regression comparisons
NUMBA_RTOL = 1e-12
NUMBA_ATOL = 1e-15


class TestCombFilterKernelRegression:
    """Verify _comb_filter_kernel matches pure-Python reference."""

    @staticmethod
    def _reference_comb_filter(
        signal: np.ndarray,
        delay_samp: int,
        g_eff: float,
        density: float,
        n: int,
    ) -> np.ndarray:
        """Pure-Python reference — original pre-Numba implementation."""
        buf = np.zeros(delay_samp + n)
        buf[:n] += signal
        for i in range(n):
            buf[i + delay_samp] += buf[i] * g_eff * density
        return buf[:n]

    def test_parity_short_signal(self, signal_short: np.ndarray) -> None:
        delay_samp = 1309  # ~29.7ms at 44100 Hz
        g_eff = 0.85
        density = 0.8
        n = len(signal_short)

        ref = self._reference_comb_filter(signal_short, delay_samp, g_eff, density, n)
        jit = _comb_filter_kernel(signal_short, delay_samp, g_eff, density, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_medium_signal(self, signal_medium: np.ndarray) -> None:
        delay_samp = 1636  # ~37.1ms at 44100 Hz
        g_eff = 0.92
        density = 0.6
        n = len(signal_medium)

        ref = self._reference_comb_filter(signal_medium, delay_samp, g_eff, density, n)
        jit = _comb_filter_kernel(signal_medium, delay_samp, g_eff, density, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_zeros(self) -> None:
        """Comb filter on silence must return silence."""
        n = 2048
        signal = np.zeros(n)
        ref = self._reference_comb_filter(signal, 1000, 0.9, 0.8, n)
        jit = _comb_filter_kernel(signal, 1000, 0.9, 0.8, n)
        np.testing.assert_array_equal(jit, ref)

    def test_parity_extreme_feedback(self, signal_short: np.ndarray) -> None:
        """Near-unity feedback — maximum accumulation stress test."""
        delay_samp = 500
        g_eff = 0.999
        density = 1.0
        n = len(signal_short)

        ref = self._reference_comb_filter(signal_short, delay_samp, g_eff, density, n)
        jit = _comb_filter_kernel(signal_short, delay_samp, g_eff, density, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    @pytest.mark.parametrize("delay_samp", [1, 50, 500, 1024])
    def test_parity_varied_delays(self, signal_short: np.ndarray, delay_samp: int) -> None:
        """Verify across a range of delay lengths."""
        n = len(signal_short)
        if delay_samp >= n:
            pytest.skip("Delay exceeds signal length")
        g_eff = 0.8
        density = 0.7

        ref = self._reference_comb_filter(signal_short, delay_samp, g_eff, density, n)
        jit = _comb_filter_kernel(signal_short, delay_samp, g_eff, density, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)


class TestAllpassKernelRegression:
    """Verify _allpass_kernel matches pure-Python reference."""

    @staticmethod
    def _reference_allpass(
        wet: np.ndarray,
        delay_samp: int,
        g_ap: float,
        n: int,
    ) -> np.ndarray:
        """Pure-Python reference — original pre-Numba implementation."""
        out = np.zeros(n)
        buf = np.zeros(delay_samp)
        ptr = 0
        for i in range(n):
            xh = wet[i] - g_ap * buf[ptr]
            out[i] = g_ap * xh + buf[ptr]
            buf[ptr] = xh
            ptr = (ptr + 1) % delay_samp
        return out

    def test_parity_short_signal(self, signal_short: np.ndarray) -> None:
        delay_samp = 220  # ~5ms at 44100 Hz
        g_ap = 0.49  # 0.7 * 0.7 diffusion
        n = len(signal_short)

        ref = self._reference_allpass(signal_short, delay_samp, g_ap, n)
        jit = _allpass_kernel(signal_short, delay_samp, g_ap, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_medium_signal(self, signal_medium: np.ndarray) -> None:
        delay_samp = 75  # ~1.7ms at 44100 Hz
        g_ap = 0.63  # 0.7 * 0.9 diffusion
        n = len(signal_medium)

        ref = self._reference_allpass(signal_medium, delay_samp, g_ap, n)
        jit = _allpass_kernel(signal_medium, delay_samp, g_ap, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_zeros(self) -> None:
        """Allpass on silence must return silence."""
        n = 2048
        wet = np.zeros(n)
        ref = self._reference_allpass(wet, 100, 0.5, n)
        jit = _allpass_kernel(wet, 100, 0.5, n)
        np.testing.assert_array_equal(jit, ref)

    @pytest.mark.parametrize("delay_samp", [1, 10, 75, 220, 500])
    def test_parity_varied_delays(self, signal_short: np.ndarray, delay_samp: int) -> None:
        n = len(signal_short)
        g_ap = 0.49

        ref = self._reference_allpass(signal_short, delay_samp, g_ap, n)
        jit = _allpass_kernel(signal_short, delay_samp, g_ap, n)

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)


class TestDelayLineKernelRegression:
    """Verify _delay_line_kernel matches pure-Python reference."""

    @staticmethod
    def _reference_delay_line(
        signal: np.ndarray,
        modulation: np.ndarray,
        buf: np.ndarray,
        delay_samples: int,
        feedback: float,
        tape_saturation: float,
        sr: int,
        n: int,
        buf_len: int,
    ) -> np.ndarray:
        """Pure-Python reference — original pre-Numba implementation."""
        wet = np.zeros(n)
        for i in range(n):
            mod_offset = int(modulation[i] * sr)
            read_idx = int(
                np.clip(i + delay_samples + mod_offset, 0, buf_len - 1)
            )
            delayed_sample = buf[read_idx]

            saturated = np.tanh(
                delayed_sample * (1.0 + tape_saturation * 3.0)
            )
            wet[i] = saturated

            write_idx = i + delay_samples
            if write_idx < buf_len:
                buf[write_idx] += saturated * feedback
        return wet

    def test_parity_default_params(self, signal_short: np.ndarray) -> None:
        n = len(signal_short)
        sr = 44100
        delay_samples = int(375.0 * sr / 1000)
        feedback = 0.45
        tape_saturation = 0.4
        wow_depth = 0.004

        # Generate modulation (identical for both)
        t = np.arange(n) / sr
        modulation = (
            np.sin(2.0 * np.pi * 0.8 * t) * wow_depth
            + np.sin(2.0 * np.pi * 0.8 * 7.3 * t) * wow_depth * 0.3
        )

        max_mod_offset = int(wow_depth * sr) + 1
        buf_len = delay_samples + max_mod_offset + n + 1

        # Reference — separate buffer copy
        buf_ref = np.zeros(buf_len)
        buf_ref[:n] = signal_short
        ref = self._reference_delay_line(
            signal_short, modulation, buf_ref,
            delay_samples, feedback, tape_saturation, sr, n, buf_len,
        )

        # Numba — separate buffer copy
        buf_jit = np.zeros(buf_len)
        buf_jit[:n] = signal_short
        jit = _delay_line_kernel(
            signal_short, modulation, buf_jit,
            delay_samples, feedback, tape_saturation, sr, n, buf_len,
        )

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_high_feedback(self, signal_medium: np.ndarray) -> None:
        """Near self-oscillation — stress test for accumulated precision."""
        n = len(signal_medium)
        sr = 44100
        delay_samples = int(200.0 * sr / 1000)
        feedback = 0.97
        tape_saturation = 0.8
        wow_depth = 0.004

        t = np.arange(n) / sr
        modulation = (
            np.sin(2.0 * np.pi * 0.8 * t) * wow_depth
            + np.sin(2.0 * np.pi * 0.8 * 7.3 * t) * wow_depth * 0.3
        )

        max_mod_offset = int(wow_depth * sr) + 1
        buf_len = delay_samples + max_mod_offset + n + 1

        buf_ref = np.zeros(buf_len)
        buf_ref[:n] = signal_medium
        ref = self._reference_delay_line(
            signal_medium, modulation, buf_ref,
            delay_samples, feedback, tape_saturation, sr, n, buf_len,
        )

        buf_jit = np.zeros(buf_len)
        buf_jit[:n] = signal_medium
        jit = _delay_line_kernel(
            signal_medium, modulation, buf_jit,
            delay_samples, feedback, tape_saturation, sr, n, buf_len,
        )

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)

    def test_parity_zero_modulation(self, signal_short: np.ndarray) -> None:
        """No wow/flutter — pure delay line without pitch instability."""
        n = len(signal_short)
        sr = 44100
        delay_samples = 500
        modulation = np.zeros(n)
        buf_len = delay_samples + n + 2

        buf_ref = np.zeros(buf_len)
        buf_ref[:n] = signal_short
        ref = self._reference_delay_line(
            signal_short, modulation, buf_ref,
            delay_samples, 0.5, 0.0, sr, n, buf_len,
        )

        buf_jit = np.zeros(buf_len)
        buf_jit[:n] = signal_short
        jit = _delay_line_kernel(
            signal_short, modulation, buf_jit,
            delay_samples, 0.5, 0.0, sr, n, buf_len,
        )

        np.testing.assert_allclose(jit, ref, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)


class TestSmoothEnvelopeKernelRegression:
    """Verify _smooth_envelope_single and _smooth_envelope_auto match pure-Python references."""

    @staticmethod
    def _reference_smooth_single(
        gr_db: np.ndarray,
        n: int,
        attack_coeff: float,
        release_coeff: float,
        env_init: float,
    ) -> tuple[np.ndarray, float]:
        """Pure-Python reference — original single-detector envelope."""
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

    @staticmethod
    def _reference_smooth_auto(
        gr_db: np.ndarray,
        n: int,
        attack_coeff: float,
        fast_release_coeff: float,
        slow_release_coeff: float,
        env_init: float,
    ) -> tuple[np.ndarray, float]:
        """Pure-Python reference — original dual-detector auto-release envelope."""
        smoothed = np.zeros(n)
        env_fast = env_init
        env_slow = env_init
        for i in range(n):
            target = gr_db[i]
            if target < env_fast:
                env_fast = attack_coeff * env_fast + (1.0 - attack_coeff) * target
            else:
                env_fast = fast_release_coeff * env_fast + (1.0 - fast_release_coeff) * target
            if target < env_slow:
                env_slow = attack_coeff * env_slow + (1.0 - attack_coeff) * target
            else:
                env_slow = slow_release_coeff * env_slow + (1.0 - slow_release_coeff) * target
            smoothed[i] = min(env_fast, env_slow)
        return smoothed, min(env_fast, env_slow)

    def test_single_detector_parity(self) -> None:
        rng = np.random.default_rng(42)
        gr_db = rng.uniform(-20.0, 0.0, 4410).astype(np.float64)
        n = len(gr_db)
        attack_coeff = np.exp(-1.0 / (10.0 * 44100 / 1000))
        release_coeff = np.exp(-1.0 / (100.0 * 44100 / 1000))

        ref_out, ref_env = self._reference_smooth_single(
            gr_db, n, float(attack_coeff), float(release_coeff), 0.0,
        )
        jit_out, jit_env = _smooth_envelope_single(
            gr_db, n, float(attack_coeff), float(release_coeff), 0.0,
        )

        np.testing.assert_allclose(jit_out, ref_out, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)
        assert abs(jit_env - ref_env) < 1e-12

    def test_auto_release_parity(self) -> None:
        rng = np.random.default_rng(99)
        gr_db = rng.uniform(-30.0, 0.0, 8820).astype(np.float64)
        n = len(gr_db)
        sr = 44100
        attack_coeff = float(np.exp(-1.0 / (10.0 * sr / 1000)))
        fast_release = float(np.exp(-1.0 / (50.0 * sr / 1000)))
        slow_release = float(np.exp(-1.0 / (600.0 * sr / 1000)))

        ref_out, ref_env = self._reference_smooth_auto(
            gr_db, n, attack_coeff, fast_release, slow_release, 0.0,
        )
        jit_out, jit_env = _smooth_envelope_auto(
            gr_db, n, attack_coeff, fast_release, slow_release, 0.0,
        )

        np.testing.assert_allclose(jit_out, ref_out, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)
        assert abs(jit_env - ref_env) < 1e-12

    def test_single_detector_nonzero_init(self) -> None:
        """Verify correct state propagation from non-zero initial envelope."""
        rng = np.random.default_rng(7)
        gr_db = rng.uniform(-15.0, 0.0, 2048).astype(np.float64)
        n = len(gr_db)
        attack_coeff = float(np.exp(-1.0 / (5.0 * 44100 / 1000)))
        release_coeff = float(np.exp(-1.0 / (200.0 * 44100 / 1000)))
        env_init = -8.0

        ref_out, ref_env = self._reference_smooth_single(
            gr_db, n, attack_coeff, release_coeff, env_init,
        )
        jit_out, jit_env = _smooth_envelope_single(
            gr_db, n, attack_coeff, release_coeff, env_init,
        )

        np.testing.assert_allclose(jit_out, ref_out, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)
        assert abs(jit_env - ref_env) < 1e-12

    def test_auto_release_nonzero_init(self) -> None:
        """Verify correct state propagation from non-zero initial envelope."""
        rng = np.random.default_rng(13)
        gr_db = rng.uniform(-25.0, 0.0, 4096).astype(np.float64)
        n = len(gr_db)
        sr = 44100
        attack_coeff = float(np.exp(-1.0 / (15.0 * sr / 1000)))
        fast_release = float(np.exp(-1.0 / (50.0 * sr / 1000)))
        slow_release = float(np.exp(-1.0 / (600.0 * sr / 1000)))
        env_init = -12.0

        ref_out, ref_env = self._reference_smooth_auto(
            gr_db, n, attack_coeff, fast_release, slow_release, env_init,
        )
        jit_out, jit_env = _smooth_envelope_auto(
            gr_db, n, attack_coeff, fast_release, slow_release, env_init,
        )

        np.testing.assert_allclose(jit_out, ref_out, rtol=NUMBA_RTOL, atol=NUMBA_ATOL)
        assert abs(jit_env - ref_env) < 1e-12

    def test_single_detector_all_zeros(self) -> None:
        """Zero gain reduction input should converge to zero."""
        gr_db = np.zeros(1024)
        n = len(gr_db)
        ref_out, _ = self._reference_smooth_single(gr_db, n, 0.99, 0.999, 0.0)
        jit_out, _ = _smooth_envelope_single(gr_db, n, 0.99, 0.999, 0.0)
        np.testing.assert_array_equal(jit_out, ref_out)


class TestRMSEnvelopeVectorisation:
    """Verify vectorised _compute_rms_envelope matches sequential reference."""

    @staticmethod
    def _reference_rms_sequential(
        signal: np.ndarray,
        window_samp: int,
    ) -> np.ndarray:
        """Pure-Python reference — original sequential loop."""
        n = len(signal)
        sq = signal ** 2
        cumsum = np.cumsum(sq)
        cumsum = np.insert(cumsum, 0, 0.0)

        rms_sq = np.zeros(n)
        for i in range(n):
            start = max(0, i - window_samp + 1)
            rms_sq[i] = (cumsum[i + 1] - cumsum[start]) / (i - start + 1)

        rms_linear = np.sqrt(np.maximum(rms_sq, 1e-12))
        return 20.0 * np.log10(rms_linear)

    def test_parity_default_window(self, signal_short: np.ndarray) -> None:
        """Default 10ms window at 44100 Hz = 441 samples."""
        window_samp = 441
        comp = Compressor(rms_window_ms=10.0)
        vectorised = comp._compute_rms_envelope(signal_short)
        reference = self._reference_rms_sequential(signal_short, window_samp)

        np.testing.assert_allclose(vectorised, reference, rtol=1e-12, atol=1e-15)

    def test_parity_short_window(self, signal_short: np.ndarray) -> None:
        """1ms window — most transient-responsive setting."""
        window_samp = max(int(1.0 * 44100 / 1000), 1)
        comp = Compressor(rms_window_ms=1.0)
        vectorised = comp._compute_rms_envelope(signal_short)
        reference = self._reference_rms_sequential(signal_short, window_samp)

        np.testing.assert_allclose(vectorised, reference, rtol=1e-12, atol=1e-15)

    def test_parity_long_window(self, signal_medium: np.ndarray) -> None:
        """50ms window — smoothest RMS detection."""
        window_samp = max(int(50.0 * 44100 / 1000), 1)
        comp = Compressor(rms_window_ms=50.0)
        vectorised = comp._compute_rms_envelope(signal_medium)
        reference = self._reference_rms_sequential(signal_medium, window_samp)

        np.testing.assert_allclose(vectorised, reference, rtol=1e-12, atol=1e-15)

    def test_all_zeros_returns_floor(self) -> None:
        """Silence should produce -120 dB floor (from 1e-12 guard)."""
        signal = np.zeros(2048)
        comp = Compressor(rms_window_ms=10.0)
        result = comp._compute_rms_envelope(signal)
        expected_db = 20.0 * np.log10(np.sqrt(1e-12))
        np.testing.assert_allclose(result, expected_db, rtol=1e-10)
