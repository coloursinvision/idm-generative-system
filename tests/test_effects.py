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
# Valid parameter construction
# ---------------------------------------------------------------------------

class TestValidParameters:
    """All documented parameter values must construct without error."""

    @pytest.mark.parametrize("noise_type", ["pink", "white", "hum_uk", "hum_us"])
    def test_noise_floor_valid_types(self, noise_type: str) -> None:
        nf = NoiseFloor(noise_type=noise_type)
        assert nf.noise_type == noise_type

    @pytest.mark.parametrize("preset", ["sp1200", "s950", "rz1", "909_cymbal", None])
    def test_bitcrusher_valid_presets(self, preset: str | None) -> None:
        bc = Bitcrusher(hardware_preset=preset)
        assert bc.hardware_preset == preset

    @pytest.mark.parametrize("mode", ["round", "truncate", "floor"])
    def test_bitcrusher_valid_modes(self, mode: str) -> None:
        bc = Bitcrusher(mode=mode)
        assert bc.mode == mode

    @pytest.mark.parametrize("ft", ["lp", "hp", "bp"])
    def test_filter_valid_types(self, ft: str) -> None:
        f = ResonantFilter(filter_type=ft)
        assert f.filter_type == ft

    @pytest.mark.parametrize("mode", ["asymmetric", "symmetric", "tanh", "wavefold"])
    def test_saturation_valid_modes(self, mode: str) -> None:
        s = Saturation(mode=mode)
        assert s.mode == mode

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
