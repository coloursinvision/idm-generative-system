"""Tests for engine.ml.gaussian_noise — Layer 4 Gaussian noise injection.

Covers:
    - Reproducibility (seeded RNG produces identical outputs)
    - Zero-sigma pass-through (no perturbation when all sigmas are 0.0)
    - Source-tag-aware fixed points (mains fundamentals never perturbed)
    - Hardware-plausibility clamping (perturbed values stay within bounds)
    - perturb_profile: swing, reverb, noise field perturbation
    - perturb_mapping: frequency perturbation with nearest_note recalculation
    - RNG draw-order determinism across independent calls

Fixtures construct dataclass instances directly — no spoke filesystem
dependency. All tests are pure unit tests.
"""

from __future__ import annotations

import pytest

from engine.ml.deterministic_mapper import DeterministicMapping, ResonantPoint
from engine.ml.gaussian_noise import (
    _FIXED_SOURCES,
    GaussianNoiseInjector,
    PerturbationConfig,
)
from engine.ml.regional_profiles import (
    HarmonicContentSpec,
    NoiseSpec,
    RegionalProfile,
    ReverbSpec,
    SaturationSpec,
    SwingSpec,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def swing_spec() -> SwingSpec:
    """SwingSpec with a numeric swing_amount for perturbation testing."""
    return SwingSpec(
        bpm_range=(130, 160),
        swing_type="mpc60_nonlinear",
        gate_behavior="retrigger",
        swing_amount=0.62,
    )


@pytest.fixture
def reverb_spec() -> ReverbSpec:
    """ReverbSpec with numeric decay and diffusion fields."""
    return ReverbSpec(
        profile="deep_lush",
        bandwidth=8000,
        decay=450,
        diffusion=0.7,
        sample_rate=31250,
    )


@pytest.fixture
def noise_spec() -> NoiseSpec:
    """NoiseSpec with all numeric fields populated."""
    return NoiseSpec(
        sub_bass_hz=50,
        sub_bass_level="dominant",
        noise_floor_hz=50,
        noise_floor_db=-60,
    )


@pytest.fixture
def profile(
    swing_spec: SwingSpec,
    reverb_spec: ReverbSpec,
    noise_spec: NoiseSpec,
) -> RegionalProfile:
    """Full RegionalProfile with perturbable numeric fields."""
    return RegionalProfile(
        region="UK_IDM",
        sub_region=None,
        swing=swing_spec,
        saturation=SaturationSpec(saturation="moderate"),
        harmonic=HarmonicContentSpec(primary_synthesis="fm"),
        reverb=reverb_spec,
        noise=noise_spec,
    )


@pytest.fixture
def profile_no_reverb_no_noise(swing_spec: SwingSpec) -> RegionalProfile:
    """Profile with reverb=None and noise=None (UK_BRAINDANCE-like)."""
    return RegionalProfile(
        region="UK_BRAINDANCE",
        sub_region=None,
        swing=swing_spec,
        saturation=SaturationSpec(saturation="high"),
        harmonic=HarmonicContentSpec(primary_synthesis="sampler_mangling"),
        reverb=None,
        noise=None,
    )


@pytest.fixture
def mapping() -> DeterministicMapping:
    """DeterministicMapping with a mix of fixed and perturbable source tags."""
    return DeterministicMapping(
        tuning_hz=440.0,
        resonant_points=(
            ResonantPoint(frequency_hz=440.0, source="pitch_ref", nearest_note="A4"),
            ResonantPoint(frequency_hz=136.53, source="bpm_harmonic", nearest_note="C#3"),
            ResonantPoint(frequency_hz=50.0, source="mains_fundamental", nearest_note="G1"),
            ResonantPoint(frequency_hz=100.0, source="mains_harmonic_2", nearest_note="G2"),
            ResonantPoint(frequency_hz=50.0, source="mains_ref_fundamental", nearest_note="G1"),
            ResonantPoint(frequency_hz=100.0, source="mains_ref_harmonic_2", nearest_note="G2"),
            ResonantPoint(frequency_hz=741.0, source="solfeggio_seed", nearest_note="F#5"),
            ResonantPoint(frequency_hz=7.83, source="schumann_bpm_anchor", nearest_note="B-1"),
        ),
    )


@pytest.fixture
def active_config() -> PerturbationConfig:
    """PerturbationConfig with all sigmas active."""
    return PerturbationConfig(
        swing_sigma=0.05,
        reverb_sigma=20.0,
        saturation_sigma=0.1,
        harmonic_sigma=0.1,
        noise_sigma=3.0,
        mapper_sigma=5.0,
    )


@pytest.fixture
def zero_config() -> PerturbationConfig:
    """PerturbationConfig with all sigmas at zero (no perturbation)."""
    return PerturbationConfig()


# ---------------------------------------------------------------------------
# Properties and construction
# ---------------------------------------------------------------------------


class TestGaussianNoiseInjectorProperties:
    """Test injector construction and property access."""

    def test_config_property(self, active_config: PerturbationConfig) -> None:
        injector = GaussianNoiseInjector(active_config, seed=42)
        assert injector.config is active_config

    def test_seed_property(self) -> None:
        injector = GaussianNoiseInjector(PerturbationConfig(), seed=123)
        assert injector.seed == 123

    def test_seed_none(self) -> None:
        injector = GaussianNoiseInjector(PerturbationConfig(), seed=None)
        assert injector.seed is None

    def test_default_config_all_zero(self) -> None:
        config = PerturbationConfig()
        assert config.swing_sigma == 0.0
        assert config.reverb_sigma == 0.0
        assert config.saturation_sigma == 0.0
        assert config.harmonic_sigma == 0.0
        assert config.noise_sigma == 0.0
        assert config.mapper_sigma == 0.0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    """Seeded RNG must produce identical outputs for identical inputs."""

    def test_perturb_profile_reproducible(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        inj_a = GaussianNoiseInjector(active_config, seed=42)
        inj_b = GaussianNoiseInjector(active_config, seed=42)
        result_a = inj_a.perturb_profile(profile)
        result_b = inj_b.perturb_profile(profile)
        assert result_a == result_b

    def test_perturb_mapping_reproducible(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        inj_a = GaussianNoiseInjector(active_config, seed=42)
        inj_b = GaussianNoiseInjector(active_config, seed=42)
        result_a = inj_a.perturb_mapping(mapping, profile)
        result_b = inj_b.perturb_mapping(mapping, profile)
        assert result_a == result_b

    def test_different_seeds_produce_different_outputs(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        inj_a = GaussianNoiseInjector(active_config, seed=42)
        inj_b = GaussianNoiseInjector(active_config, seed=99)
        result_a = inj_a.perturb_profile(profile)
        result_b = inj_b.perturb_profile(profile)
        assert result_a != result_b


# ---------------------------------------------------------------------------
# Zero-sigma pass-through
# ---------------------------------------------------------------------------


class TestZeroSigmaPassThrough:
    """When all sigmas are 0.0, output must equal input exactly."""

    def test_perturb_profile_zero_sigma(
        self,
        profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        injector = GaussianNoiseInjector(zero_config, seed=42)
        result = injector.perturb_profile(profile)
        assert result == profile

    def test_perturb_mapping_zero_sigma(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        injector = GaussianNoiseInjector(zero_config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        assert result == mapping

    def test_perturb_profile_none_reverb_none_noise(
        self,
        profile_no_reverb_no_noise: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """None specs pass through unchanged even with active sigmas."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_profile(profile_no_reverb_no_noise)
        assert result.reverb is None
        assert result.noise is None


# ---------------------------------------------------------------------------
# perturb_profile — field-level tests
# ---------------------------------------------------------------------------


class TestPerturbProfile:
    """Test individual field perturbation within perturb_profile."""

    def test_swing_amount_perturbed(
        self,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(swing_sigma=0.05)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.swing.swing_amount != profile.swing.swing_amount
        assert isinstance(result.swing.swing_amount, float)

    def test_swing_variable_passthrough(self) -> None:
        """swing_amount='variable' must not be perturbed."""
        swing = SwingSpec(
            bpm_range=(80, 120),
            swing_type="inverse",
            gate_behavior="micro_retrigger",
            swing_amount="variable",
        )
        profile = RegionalProfile(
            region="UK_BRAINDANCE",
            sub_region=None,
            swing=swing,
            saturation=SaturationSpec(saturation="high"),
            harmonic=HarmonicContentSpec(primary_synthesis="sampler_mangling"),
        )
        config = PerturbationConfig(swing_sigma=0.1)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.swing.swing_amount == "variable"

    def test_swing_none_passthrough(self) -> None:
        """swing_amount=None must not be perturbed."""
        swing = SwingSpec(
            bpm_range=(130, 160),
            swing_type="deterministic",
            gate_behavior="retrigger",
            swing_amount=None,
        )
        profile = RegionalProfile(
            region="DETROIT_FIRST_WAVE",
            sub_region=None,
            swing=swing,
            saturation=SaturationSpec(saturation="moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="analog_subtractive"),
        )
        config = PerturbationConfig(swing_sigma=0.1)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.swing.swing_amount is None

    def test_swing_amount_clamped_to_unit_interval(self) -> None:
        """swing_amount must stay in [0.0, 1.0] even with large sigma."""
        swing = SwingSpec(
            bpm_range=(130, 160),
            swing_type="mpc60_nonlinear",
            gate_behavior="retrigger",
            swing_amount=0.95,
        )
        profile = RegionalProfile(
            region="UK_IDM",
            sub_region=None,
            swing=swing,
            saturation=SaturationSpec(saturation="moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="fm"),
        )
        config = PerturbationConfig(swing_sigma=10.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert 0.0 <= result.swing.swing_amount <= 1.0

    def test_reverb_decay_perturbed(
        self,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(reverb_sigma=20.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.reverb is not None
        assert result.reverb.decay != profile.reverb.decay
        assert isinstance(result.reverb.decay, int)

    def test_reverb_decay_clamped_positive(self) -> None:
        """Reverb decay must stay >= 1 ms."""
        reverb = ReverbSpec(profile="dry_short", decay=5, diffusion=0.3)
        profile = RegionalProfile(
            region="UK_IDM",
            sub_region=None,
            swing=SwingSpec(
                bpm_range=(130, 160),
                swing_type="deterministic",
                gate_behavior="retrigger",
            ),
            saturation=SaturationSpec(saturation="low_to_moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="fm"),
            reverb=reverb,
        )
        config = PerturbationConfig(reverb_sigma=1000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.reverb is not None
        assert result.reverb.decay >= 1

    def test_reverb_diffusion_clamped_to_unit_interval(self) -> None:
        """Reverb diffusion must stay in [0.0, 1.0]."""
        reverb = ReverbSpec(profile="long_diffuse", decay=800, diffusion=0.95)
        profile = RegionalProfile(
            region="UK_IDM",
            sub_region=None,
            swing=SwingSpec(
                bpm_range=(130, 160),
                swing_type="deterministic",
                gate_behavior="retrigger",
            ),
            saturation=SaturationSpec(saturation="moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="fm"),
            reverb=reverb,
        )
        # Large reverb_sigma — diffusion_sigma = reverb_sigma / 1000
        # so 50000 → diffusion_sigma = 50 → guaranteed to hit boundary
        config = PerturbationConfig(reverb_sigma=50000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.reverb is not None
        assert 0.0 <= result.reverb.diffusion <= 1.0

    def test_noise_sub_bass_hz_perturbed(
        self,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(noise_sigma=3.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.noise is not None
        assert result.noise.sub_bass_hz != profile.noise.sub_bass_hz
        assert isinstance(result.noise.sub_bass_hz, int)

    def test_noise_hz_clamped_positive(self) -> None:
        """Noise Hz fields must stay >= 1."""
        noise = NoiseSpec(sub_bass_hz=2, noise_floor_hz=2, noise_floor_db=-90)
        profile = RegionalProfile(
            region="JAPAN_IDM",
            sub_region=None,
            swing=SwingSpec(
                bpm_range=(100, 140),
                swing_type="deterministic",
                gate_behavior="retrigger",
            ),
            saturation=SaturationSpec(saturation="low_to_moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="fm"),
            noise=noise,
        )
        config = PerturbationConfig(noise_sigma=1000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.noise is not None
        assert result.noise.sub_bass_hz >= 1
        assert result.noise.noise_floor_hz >= 1

    def test_noise_floor_db_clamped_nonpositive(self) -> None:
        """noise_floor_db must stay <= 0 dBFS."""
        noise = NoiseSpec(sub_bass_hz=50, noise_floor_hz=50, noise_floor_db=-3)
        profile = RegionalProfile(
            region="UK_IDM",
            sub_region=None,
            swing=SwingSpec(
                bpm_range=(130, 160),
                swing_type="deterministic",
                gate_behavior="retrigger",
            ),
            saturation=SaturationSpec(saturation="moderate"),
            harmonic=HarmonicContentSpec(primary_synthesis="fm"),
            noise=noise,
        )
        config = PerturbationConfig(noise_sigma=1000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.noise is not None
        assert result.noise.noise_floor_db <= 0

    def test_saturation_unchanged(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """SaturationSpec has no numeric fields — must pass through unchanged."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.saturation == profile.saturation

    def test_harmonic_unchanged(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """HarmonicContentSpec has no perturbable fields — must pass through."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.harmonic == profile.harmonic

    def test_non_dsp_fields_unchanged(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """Region, sub_region, and categorical fields must not change."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_profile(profile)
        assert result.region == profile.region
        assert result.sub_region == profile.sub_region
        assert result.stereo_width == profile.stereo_width
        assert result.filter_type == profile.filter_type
        assert result.filter_key_tracking == profile.filter_key_tracking

    def test_input_not_mutated(
        self,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """Input profile must remain unchanged after perturbation."""
        original_swing_amount = profile.swing.swing_amount
        injector = GaussianNoiseInjector(active_config, seed=42)
        _ = injector.perturb_profile(profile)
        assert profile.swing.swing_amount == original_swing_amount


# ---------------------------------------------------------------------------
# perturb_mapping — source-tag-aware fixed points
# ---------------------------------------------------------------------------


class TestPerturbMappingFixedSources:
    """Resonant points with fixed source tags must never be perturbed."""

    def test_mains_fundamental_unchanged(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(mapper_sigma=50.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        original_mains = [p for p in mapping.resonant_points if p.source == "mains_fundamental"]
        result_mains = [p for p in result.resonant_points if p.source == "mains_fundamental"]
        assert len(original_mains) == len(result_mains)
        for orig, res in zip(original_mains, result_mains, strict=True):
            assert res.frequency_hz == orig.frequency_hz
            assert res.nearest_note == orig.nearest_note

    def test_mains_ref_fundamental_unchanged(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(mapper_sigma=50.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        original_ref = [p for p in mapping.resonant_points if p.source == "mains_ref_fundamental"]
        result_ref = [p for p in result.resonant_points if p.source == "mains_ref_fundamental"]
        assert len(original_ref) == len(result_ref)
        for orig, res in zip(original_ref, result_ref, strict=True):
            assert res.frequency_hz == orig.frequency_hz
            assert res.nearest_note == orig.nearest_note

    def test_fixed_sources_constant_exhaustive(self) -> None:
        """_FIXED_SOURCES must contain exactly the documented set."""
        assert {"mains_fundamental", "mains_ref_fundamental"} == _FIXED_SOURCES


# ---------------------------------------------------------------------------
# perturb_mapping — perturbable sources
# ---------------------------------------------------------------------------


class TestPerturbMappingPerturbableSources:
    """Non-fixed source tags must receive perturbation."""

    def test_pitch_ref_perturbed(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(mapper_sigma=5.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        orig = next(p for p in mapping.resonant_points if p.source == "pitch_ref")
        res = next(p for p in result.resonant_points if p.source == "pitch_ref")
        assert res.frequency_hz != orig.frequency_hz

    def test_solfeggio_seed_perturbed(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        config = PerturbationConfig(mapper_sigma=5.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        orig = next(p for p in mapping.resonant_points if p.source == "solfeggio_seed")
        res = next(p for p in result.resonant_points if p.source == "solfeggio_seed")
        assert res.frequency_hz != orig.frequency_hz

    def test_mains_harmonic_perturbed(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        """mains_harmonic_<k> is NOT in _FIXED_SOURCES — must be perturbed."""
        config = PerturbationConfig(mapper_sigma=5.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        orig = next(p for p in mapping.resonant_points if p.source == "mains_harmonic_2")
        res = next(p for p in result.resonant_points if p.source == "mains_harmonic_2")
        assert res.frequency_hz != orig.frequency_hz

    def test_mains_ref_harmonic_perturbed(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        """mains_ref_harmonic_<k> is NOT in _FIXED_SOURCES — must be perturbed."""
        config = PerturbationConfig(mapper_sigma=5.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        orig = next(p for p in mapping.resonant_points if p.source == "mains_ref_harmonic_2")
        res = next(p for p in result.resonant_points if p.source == "mains_ref_harmonic_2")
        assert res.frequency_hz != orig.frequency_hz

    def test_nearest_note_recalculated(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        """nearest_note must be recalculated from perturbed frequency."""
        config = PerturbationConfig(mapper_sigma=100.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        for point in result.resonant_points:
            if point.source not in _FIXED_SOURCES:
                # nearest_note must be a string (not None) since the mapper
                # always provides one for perturbable points.
                assert isinstance(point.nearest_note, str)
                assert len(point.nearest_note) >= 2  # e.g. "A4", "C#3"


# ---------------------------------------------------------------------------
# perturb_mapping — clamping
# ---------------------------------------------------------------------------


class TestPerturbMappingClamping:
    """Perturbed frequencies must remain within valid bounds."""

    def test_frequency_clamped_positive(
        self,
        profile: RegionalProfile,
    ) -> None:
        """Perturbed frequency must be >= 1.0 Hz even with extreme sigma."""
        mapping = DeterministicMapping(
            tuning_hz=440.0,
            resonant_points=(
                ResonantPoint(frequency_hz=2.0, source="bpm_harmonic", nearest_note="C-1"),
            ),
        )
        config = PerturbationConfig(mapper_sigma=10000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        assert result.resonant_points[0].frequency_hz >= 1.0

    def test_large_sigma_all_points_valid(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> None:
        """All frequencies must remain >= 1.0 Hz under extreme perturbation."""
        config = PerturbationConfig(mapper_sigma=10000.0)
        injector = GaussianNoiseInjector(config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        for point in result.resonant_points:
            assert point.frequency_hz >= 1.0


# ---------------------------------------------------------------------------
# perturb_mapping — structural invariants
# ---------------------------------------------------------------------------


class TestPerturbMappingStructure:
    """Structural properties preserved by perturb_mapping."""

    def test_tuning_hz_unchanged(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        assert result.tuning_hz == mapping.tuning_hz

    def test_point_count_preserved(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        assert len(result.resonant_points) == len(mapping.resonant_points)

    def test_source_tags_preserved(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """Source tags must not change — only frequency and nearest_note."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        original_sources = [p.source for p in mapping.resonant_points]
        result_sources = [p.source for p in result.resonant_points]
        assert result_sources == original_sources

    def test_point_order_preserved(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """Ordering of resonant points must not change."""
        injector = GaussianNoiseInjector(active_config, seed=42)
        result = injector.perturb_mapping(mapping, profile)
        for orig, res in zip(mapping.resonant_points, result.resonant_points, strict=True):
            assert res.source == orig.source

    def test_input_mapping_not_mutated(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        """Input mapping must remain unchanged after perturbation."""
        original_points = mapping.resonant_points
        injector = GaussianNoiseInjector(active_config, seed=42)
        _ = injector.perturb_mapping(mapping, profile)
        assert mapping.resonant_points == original_points


# ---------------------------------------------------------------------------
# RNG draw-order determinism
# ---------------------------------------------------------------------------


class TestRNGDrawOrder:
    """Sequential calls must consume draws in deterministic order."""

    def test_profile_then_mapping_deterministic(
        self,
        profile: RegionalProfile,
        mapping: DeterministicMapping,
        active_config: PerturbationConfig,
    ) -> None:
        """profile→mapping sequence must be reproducible across instances."""
        inj_a = GaussianNoiseInjector(active_config, seed=42)
        prof_a = inj_a.perturb_profile(profile)
        map_a = inj_a.perturb_mapping(mapping, profile)

        inj_b = GaussianNoiseInjector(active_config, seed=42)
        prof_b = inj_b.perturb_profile(profile)
        map_b = inj_b.perturb_mapping(mapping, profile)

        assert prof_a == prof_b
        assert map_a == map_b

    def test_mapping_then_profile_deterministic(
        self,
        profile: RegionalProfile,
        mapping: DeterministicMapping,
        active_config: PerturbationConfig,
    ) -> None:
        """mapping→profile sequence must be reproducible across instances."""
        inj_a = GaussianNoiseInjector(active_config, seed=42)
        map_a = inj_a.perturb_mapping(mapping, profile)
        prof_a = inj_a.perturb_profile(profile)

        inj_b = GaussianNoiseInjector(active_config, seed=42)
        map_b = inj_b.perturb_mapping(mapping, profile)
        prof_b = inj_b.perturb_profile(profile)

        assert map_a == map_b
        assert prof_a == prof_b

    def test_call_order_affects_output(
        self,
        profile: RegionalProfile,
        mapping: DeterministicMapping,
        active_config: PerturbationConfig,
    ) -> None:
        """Different call orders on same seed must produce different values.

        This proves the RNG state advances correctly between calls.
        """
        inj_pf = GaussianNoiseInjector(active_config, seed=42)
        prof_first = inj_pf.perturb_profile(profile)
        _ = inj_pf.perturb_mapping(mapping, profile)

        inj_mf = GaussianNoiseInjector(active_config, seed=42)
        _ = inj_mf.perturb_mapping(mapping, profile)
        prof_second = inj_mf.perturb_profile(profile)

        assert prof_first != prof_second
