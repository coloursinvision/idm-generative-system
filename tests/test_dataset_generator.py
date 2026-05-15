"""Tests for engine.ml.dataset_generator — Layer 5 synthetic dataset generation.

Covers:
    - TrackSpec construction and frozen semantics
    - SyntheticDatasetGenerator construction and property access
    - Input validation (negative n_perturbations)
    - generate_rows: row count, baseline vs perturbed flags, column presence
    - generate_dataset: DataFrame shape, column ordering, NaN handling
    - Reproducibility (seeded master RNG → identical DataFrames)
    - Zero-perturbation mode (baseline only)
    - Empty specifications edge case

Fixtures construct RegionalProfile and TrackSpec directly — no spoke
filesystem dependency. All tests are pure unit tests.
"""

from __future__ import annotations

import pandas as pd
import pytest

from engine.ml.dataset_generator import (
    SyntheticDatasetGenerator,
    TrackSpec,
)
from engine.ml.gaussian_noise import PerturbationConfig
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
def uk_profile() -> RegionalProfile:
    """UK_IDM profile with all perturbable fields populated."""
    return RegionalProfile(
        region="UK_IDM",
        sub_region=None,
        swing=SwingSpec(
            bpm_range=(130, 160),
            swing_type="deterministic",
            gate_behavior="retrigger",
            swing_amount=0.62,
        ),
        saturation=SaturationSpec(saturation="moderate"),
        harmonic=HarmonicContentSpec(primary_synthesis="fm"),
        reverb=ReverbSpec(
            profile="deep_lush",
            bandwidth=8000,
            decay=450,
            diffusion=0.7,
        ),
        noise=NoiseSpec(
            sub_bass_hz=50,
            sub_bass_level="dominant",
            noise_floor_hz=50,
            noise_floor_db=-60,
        ),
    )


@pytest.fixture
def uk_spec() -> TrackSpec:
    """TrackSpec for UK_IDM at BPM far from Schumann anchor."""
    return TrackSpec(
        bpm=140.0,
        pitch_midi=69.0,
        swing=0.6,
        region="UK_IDM",
        effects=(),
    )


@pytest.fixture
def detroit_spec() -> TrackSpec:
    """TrackSpec for DETROIT_UR — triggers dual-stack mains."""
    return TrackSpec(
        bpm=133.0,
        pitch_midi=60.0,
        swing=0.55,
        region="DETROIT_UR",
        effects=(),
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
    """PerturbationConfig with all sigmas at zero."""
    return PerturbationConfig()


# ---------------------------------------------------------------------------
# TrackSpec
# ---------------------------------------------------------------------------


class TestTrackSpec:
    """TrackSpec construction and frozen semantics."""

    def test_construction(self) -> None:
        spec = TrackSpec(
            bpm=128.0,
            pitch_midi=69.0,
            swing=0.5,
            region="UK_IDM",
            effects=("notch_mains",),
        )
        assert spec.bpm == 128.0
        assert spec.region == "UK_IDM"
        assert spec.effects == ("notch_mains",)
        assert spec.sub_region is None

    def test_frozen(self) -> None:
        spec = TrackSpec(
            bpm=128.0,
            pitch_midi=69.0,
            swing=0.5,
            region="UK_IDM",
            effects=(),
        )
        with pytest.raises(AttributeError):
            spec.bpm = 140.0  # type: ignore[misc]

    def test_sub_region(self) -> None:
        spec = TrackSpec(
            bpm=120.0,
            pitch_midi=60.0,
            swing=None,
            region="JAPAN_IDM",
            effects=(),
            sub_region="OSAKA",
        )
        assert spec.sub_region == "OSAKA"


# ---------------------------------------------------------------------------
# SyntheticDatasetGenerator — construction
# ---------------------------------------------------------------------------


class TestGeneratorConstruction:
    """Generator construction and property access."""

    def test_properties(self, active_config: PerturbationConfig) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        assert gen.config is active_config
        assert gen.n_perturbations == 5
        assert gen.master_seed == 42

    def test_default_n_perturbations(self, zero_config: PerturbationConfig) -> None:
        gen = SyntheticDatasetGenerator(zero_config)
        assert gen.n_perturbations == 10

    def test_master_seed_none(self, zero_config: PerturbationConfig) -> None:
        gen = SyntheticDatasetGenerator(zero_config, master_seed=None)
        assert gen.master_seed is None

    def test_negative_n_perturbations_raises(self, zero_config: PerturbationConfig) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            SyntheticDatasetGenerator(zero_config, n_perturbations=-1)


# ---------------------------------------------------------------------------
# generate_rows — row structure
# ---------------------------------------------------------------------------


class TestGenerateRows:
    """Row-level output of generate_rows."""

    def test_row_count(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        assert len(rows) == 6  # 1 baseline + 5 perturbed

    def test_baseline_row_flags(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        baseline = rows[0]
        assert baseline["is_perturbed"] is False
        assert baseline["perturbation_idx"] == 0

    def test_perturbed_row_flags(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        for i, row in enumerate(rows[1:], start=1):
            assert row["is_perturbed"] is True
            assert row["perturbation_idx"] == i

    def test_input_fields_preserved(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=1, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        for row in rows:
            assert row["bpm"] == uk_spec.bpm
            assert row["pitch_midi"] == uk_spec.pitch_midi
            assert row["region"] == uk_spec.region

    def test_tuning_hz_present(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=1, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        assert rows[0]["tuning_hz"] == 440.0

    def test_freq_columns_present(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        """UK_IDM at BPM=140 should produce known freq columns."""
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        row = rows[0]
        assert "freq_pitch_ref" in row
        assert "freq_bpm_harmonic" in row
        assert "freq_mains_fundamental" in row
        assert "freq_solfeggio_seed" in row
        assert "freq_sub_bass" in row

    def test_dsp_columns_present(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        row = rows[0]
        assert "swing_amount" in row
        assert "reverb_decay" in row
        assert "reverb_diffusion" in row
        assert "noise_sub_bass_hz" in row
        assert "noise_floor_hz" in row
        assert "noise_floor_db" in row

    def test_perturbed_rows_differ_from_baseline(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        baseline = rows[0]
        perturbed = rows[1]
        # At least one DSP or freq field should differ
        dsp_keys = ["swing_amount", "reverb_decay", "noise_sub_bass_hz"]
        freq_keys = [k for k in baseline if k.startswith("freq_")]
        all_keys = dsp_keys + freq_keys
        differences = [k for k in all_keys if baseline.get(k) != perturbed.get(k)]
        assert len(differences) > 0


# ---------------------------------------------------------------------------
# generate_rows — zero perturbations
# ---------------------------------------------------------------------------


class TestZeroPerturbations:
    """n_perturbations=0 produces only baseline rows."""

    def test_single_row(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=0, master_seed=42)
        rows = gen.generate_rows(uk_spec, profile=uk_profile)
        assert len(rows) == 1
        assert rows[0]["is_perturbed"] is False


# ---------------------------------------------------------------------------
# generate_dataset — DataFrame shape and structure
# ---------------------------------------------------------------------------


class TestGenerateDataset:
    """DataFrame-level output of generate_dataset."""

    def test_shape(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        df = gen.generate_dataset([uk_spec], profile=uk_profile)
        assert len(df) == 6  # 1 baseline + 5 perturbed

    def test_multi_spec_shape(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        specs = [uk_spec, uk_spec, uk_spec]
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=2, master_seed=42)
        df = gen.generate_dataset(specs, profile=uk_profile)
        assert len(df) == 9  # 3 specs × (1 + 2)

    def test_empty_specs(self, zero_config: PerturbationConfig) -> None:
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=5, master_seed=42)
        df = gen.generate_dataset([])
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_column_ordering(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        """Columns must follow: inputs → tuning → freq_* → DSP → metadata."""
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        df = gen.generate_dataset([uk_spec], profile=uk_profile)
        cols = list(df.columns)
        # Input columns come first
        assert cols[0] == "bpm"
        assert cols[1] == "pitch_midi"
        assert cols[2] == "swing"
        assert cols[3] == "region"
        assert cols[4] == "sub_region"
        # tuning_hz next
        assert cols[5] == "tuning_hz"
        # freq_* columns are sorted
        freq_start = 6
        freq_cols = [c for c in cols[freq_start:] if c.startswith("freq_")]
        assert freq_cols == sorted(freq_cols)
        # Metadata columns come last
        assert cols[-2] == "is_perturbed"
        assert cols[-1] == "perturbation_idx"

    def test_is_perturbed_dtype(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=2, master_seed=42)
        df = gen.generate_dataset([uk_spec], profile=uk_profile)
        assert df["is_perturbed"].dtype == bool

    def test_perturbation_idx_values(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        df = gen.generate_dataset([uk_spec], profile=uk_profile)
        assert list(df["perturbation_idx"]) == [0, 1, 2, 3]

    def test_baseline_row_values_match_zero_sigma(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
        zero_config: PerturbationConfig,
    ) -> None:
        """Baseline row (idx=0) should match zero-sigma generator output."""
        gen_active = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        gen_zero = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=99)
        df_active = gen_active.generate_dataset([uk_spec], profile=uk_profile)
        df_zero = gen_zero.generate_dataset([uk_spec], profile=uk_profile)
        baseline = df_active[df_active["perturbation_idx"] == 0].iloc[0]
        zero_row = df_zero.iloc[0]
        # Compare freq and DSP columns (input + metadata may differ in idx)
        freq_cols = [c for c in df_active.columns if c.startswith("freq_")]
        for col in freq_cols:
            assert baseline[col] == zero_row[col], f"Mismatch in {col}"


# ---------------------------------------------------------------------------
# generate_dataset — NaN handling for absent columns
# ---------------------------------------------------------------------------


class TestNaNHandling:
    """Absent resonant points and DSP fields produce NaN."""

    def test_swing_nan_for_variable(
        self,
        uk_profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        """swing='variable' should produce NaN in the swing column."""
        spec = TrackSpec(
            bpm=140.0,
            pitch_midi=69.0,
            swing="variable",
            region="UK_IDM",
            effects=(),
        )
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        df = gen.generate_dataset([spec], profile=uk_profile)
        assert pd.isna(df["swing"].iloc[0])

    def test_swing_nan_for_none(
        self,
        uk_profile: RegionalProfile,
        zero_config: PerturbationConfig,
    ) -> None:
        """swing=None should produce NaN in the swing column."""
        spec = TrackSpec(
            bpm=140.0,
            pitch_midi=69.0,
            swing=None,
            region="UK_IDM",
            effects=(),
        )
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        df = gen.generate_dataset([spec], profile=uk_profile)
        assert pd.isna(df["swing"].iloc[0])

    def test_no_reverb_produces_nan(
        self,
        zero_config: PerturbationConfig,
    ) -> None:
        """Profile with reverb=None → reverb_decay and reverb_diffusion are NaN."""
        profile = RegionalProfile(
            region="UK_BRAINDANCE",
            sub_region=None,
            swing=SwingSpec(
                bpm_range=(80, 120),
                swing_type="inverse",
                gate_behavior="micro_retrigger",
                swing_amount="variable",
            ),
            saturation=SaturationSpec(saturation="high"),
            harmonic=HarmonicContentSpec(primary_synthesis="sampler_mangling"),
            reverb=None,
            noise=None,
        )
        spec = TrackSpec(
            bpm=100.0,
            pitch_midi=55.0,
            swing=None,
            region="UK_BRAINDANCE",
            effects=(),
        )
        gen = SyntheticDatasetGenerator(zero_config, n_perturbations=0, master_seed=42)
        df = gen.generate_dataset([spec], profile=profile)
        assert pd.isna(df["reverb_decay"].iloc[0])
        assert pd.isna(df["reverb_diffusion"].iloc[0])
        assert pd.isna(df["noise_sub_bass_hz"].iloc[0])


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    """Seeded master RNG must produce identical DataFrames."""

    def test_same_seed_identical(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen_a = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        gen_b = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        df_a = gen_a.generate_dataset([uk_spec], profile=uk_profile)
        df_b = gen_b.generate_dataset([uk_spec], profile=uk_profile)
        pd.testing.assert_frame_equal(df_a, df_b)

    def test_different_seeds_differ(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        gen_a = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=42)
        gen_b = SyntheticDatasetGenerator(active_config, n_perturbations=5, master_seed=99)
        df_a = gen_a.generate_dataset([uk_spec], profile=uk_profile)
        df_b = gen_b.generate_dataset([uk_spec], profile=uk_profile)
        # Perturbed rows should differ
        perturbed_a = df_a[df_a["is_perturbed"]].reset_index(drop=True)
        perturbed_b = df_b[df_b["is_perturbed"]].reset_index(drop=True)
        assert not perturbed_a.equals(perturbed_b)

    def test_multi_spec_reproducible(
        self,
        uk_spec: TrackSpec,
        uk_profile: RegionalProfile,
        active_config: PerturbationConfig,
    ) -> None:
        specs = [uk_spec, uk_spec, uk_spec]
        gen_a = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        gen_b = SyntheticDatasetGenerator(active_config, n_perturbations=3, master_seed=42)
        df_a = gen_a.generate_dataset(specs, profile=uk_profile)
        df_b = gen_b.generate_dataset(specs, profile=uk_profile)
        pd.testing.assert_frame_equal(df_a, df_b)
