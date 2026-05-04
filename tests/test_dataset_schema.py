"""Tests for engine.ml.dataset_schema — pandera schema validation.

Covers:
    - Schema accepts valid DataFrames (baseline + perturbed rows).
    - Schema rejects malformed DataFrames (bad types, out-of-range values,
      missing columns, metadata inconsistencies, cross-column violations).
    - Regex-matched freq_* columns validated correctly.
    - spoke-derived enumerations (no hard-coded region lists).
"""

from __future__ import annotations

from typing import Any, get_args

import pandas as pd
import pandera.errors
import pytest

from engine.ml.dataset_schema import (
    _VALID_REGIONS,
    _VALID_SUB_REGIONS,
    DATASET_SCHEMA,
)
from engine.ml.regional_profiles import RegionCode, SubRegion

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_valid_df(**overrides: Any) -> pd.DataFrame:
    """Build a minimal valid DataFrame for schema testing.

    Keyword arguments override or add columns to the base DataFrame.
    """
    base: dict[str, Any] = {
        "bpm": [120.0, 120.0, 145.0],
        "pitch_midi": [69.0, 69.0, 48.0],
        "swing": [0.6, 0.6, None],
        "region": ["UK_IDM", "UK_IDM", "DETROIT_FIRST_WAVE"],
        "sub_region": [None, None, None],
        "tuning_hz": [440.0, 440.0, 432.0],
        "freq_pitch_ref": [440.0, 441.2, 432.0],
        "freq_bpm_harmonic": [220.0, 219.5, 265.0],
        "swing_amount": [0.6, 0.62, 0.55],
        "reverb_decay": [800.0, 810.0, 600.0],
        "reverb_diffusion": [0.7, 0.71, 0.5],
        "noise_sub_bass_hz": [40.0, 42.0, 35.0],
        "noise_floor_hz": [100.0, 98.0, 80.0],
        "noise_floor_db": [-60.0, -58.0, -72.0],
        "is_perturbed": [False, True, False],
        "perturbation_idx": [0, 1, 0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# Spoke-derived enumeration tests
# ---------------------------------------------------------------------------


class TestSpokeEnumerations:
    """Verify enumerations are derived from type aliases, not hard-coded."""

    def test_regions_match_region_code(self) -> None:
        assert set(_VALID_REGIONS) == set(get_args(RegionCode))

    def test_sub_regions_match_sub_region(self) -> None:
        assert set(_VALID_SUB_REGIONS) == set(get_args(SubRegion))

    def test_all_six_regions_present(self) -> None:
        expected = {
            "DETROIT_FIRST_WAVE",
            "DETROIT_UR",
            "DREXCIYA",
            "UK_IDM",
            "UK_BRAINDANCE",
            "JAPAN_IDM",
        }
        assert set(_VALID_REGIONS) == expected


# ---------------------------------------------------------------------------
# Valid DataFrame acceptance
# ---------------------------------------------------------------------------


class TestSchemaAcceptsValid:
    """Schema must accept well-formed DataFrames without raising."""

    def test_baseline_valid(self) -> None:
        df = _make_valid_df()
        DATASET_SCHEMA.validate(df)

    def test_all_regions(self) -> None:
        """One row per region — all accepted."""
        n = len(_VALID_REGIONS)
        df = _make_valid_df(
            bpm=[120.0] * n,
            pitch_midi=[69.0] * n,
            swing=[0.5] * n,
            region=list(_VALID_REGIONS),
            sub_region=[None] * n,
            tuning_hz=[440.0] * n,
            freq_pitch_ref=[440.0] * n,
            freq_bpm_harmonic=[220.0] * n,
            swing_amount=[0.5] * n,
            reverb_decay=[500.0] * n,
            reverb_diffusion=[0.5] * n,
            noise_sub_bass_hz=[40.0] * n,
            noise_floor_hz=[100.0] * n,
            noise_floor_db=[-60.0] * n,
            is_perturbed=[False] * n,
            perturbation_idx=[0] * n,
        )
        DATASET_SCHEMA.validate(df)

    def test_japan_with_sub_region(self) -> None:
        df = _make_valid_df(
            region=["JAPAN_IDM", "JAPAN_IDM", "JAPAN_IDM"],
            sub_region=["TOKYO", "OSAKA", None],
        )
        DATASET_SCHEMA.validate(df)

    def test_nullable_swing(self) -> None:
        """swing=NaN is valid (TrackSpec swing='variable' or None)."""
        df = _make_valid_df(swing=[None, None, None])
        DATASET_SCHEMA.validate(df)

    def test_nullable_dsp_columns(self) -> None:
        """All DSP columns NaN — valid for profiles without those specs."""
        df = _make_valid_df(
            reverb_decay=[None, None, None],
            reverb_diffusion=[None, None, None],
            noise_sub_bass_hz=[None, None, None],
            noise_floor_hz=[None, None, None],
            noise_floor_db=[None, None, None],
        )
        DATASET_SCHEMA.validate(df)

    def test_extra_columns_accepted(self) -> None:
        """strict=False allows unexpected columns."""
        df = _make_valid_df()
        df["extra_column"] = [1, 2, 3]
        DATASET_SCHEMA.validate(df)

    def test_tuning_432(self) -> None:
        df = _make_valid_df(tuning_hz=[432.0, 432.0, 432.0])
        DATASET_SCHEMA.validate(df)

    def test_perturbed_rows(self) -> None:
        """Multiple perturbation indices — valid."""
        df = _make_valid_df(
            is_perturbed=[False, True, True],
            perturbation_idx=[0, 1, 2],
        )
        DATASET_SCHEMA.validate(df)

    def test_freq_columns_nullable(self) -> None:
        """freq_* columns with NaN — valid (absent resonant points)."""
        df = _make_valid_df(
            freq_pitch_ref=[440.0, None, None],
            freq_bpm_harmonic=[None, None, 265.0],
        )
        DATASET_SCHEMA.validate(df)


# ---------------------------------------------------------------------------
# Invalid DataFrame rejection
# ---------------------------------------------------------------------------


class TestSchemaRejectsInvalid:
    """Schema must raise on malformed DataFrames."""

    def test_negative_bpm(self) -> None:
        df = _make_valid_df(bpm=[-10.0, 120.0, 145.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_zero_bpm(self) -> None:
        df = _make_valid_df(bpm=[0.0, 120.0, 145.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_pitch_midi_out_of_range(self) -> None:
        df = _make_valid_df(pitch_midi=[130.0, 69.0, 48.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_pitch_midi_negative(self) -> None:
        df = _make_valid_df(pitch_midi=[-1.0, 69.0, 48.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_swing_out_of_range(self) -> None:
        df = _make_valid_df(swing=[1.5, 0.6, 0.5])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_invalid_region(self) -> None:
        df = _make_valid_df(region=["MARS_TECHNO", "UK_IDM", "UK_IDM"])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_invalid_sub_region(self) -> None:
        df = _make_valid_df(
            region=["JAPAN_IDM", "JAPAN_IDM", "JAPAN_IDM"],
            sub_region=["KYOTO", "OSAKA", None],
        )
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_invalid_tuning_hz(self) -> None:
        df = _make_valid_df(tuning_hz=[435.0, 440.0, 432.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_negative_freq(self) -> None:
        df = _make_valid_df(freq_pitch_ref=[-5.0, 440.0, 432.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_reverb_diffusion_out_of_range(self) -> None:
        df = _make_valid_df(reverb_diffusion=[1.5, 0.7, 0.5])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_noise_floor_db_positive(self) -> None:
        df = _make_valid_df(noise_floor_db=[3.0, -58.0, -72.0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_perturbation_idx_negative(self) -> None:
        df = _make_valid_df(perturbation_idx=[-1, 1, 0])
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)


# ---------------------------------------------------------------------------
# Cross-column checks
# ---------------------------------------------------------------------------


class TestCrossColumnChecks:
    """Schema DataFrame-level checks for cross-column invariants."""

    def test_metadata_inconsistency_idx_zero_perturbed(self) -> None:
        """perturbation_idx=0 but is_perturbed=True."""
        df = _make_valid_df(
            is_perturbed=[True, True, False],
            perturbation_idx=[0, 1, 0],
        )
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_metadata_inconsistency_idx_nonzero_not_perturbed(self) -> None:
        """perturbation_idx > 0 but is_perturbed=False."""
        df = _make_valid_df(
            is_perturbed=[False, False, False],
            perturbation_idx=[0, 1, 0],
        )
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_sub_region_on_non_japan(self) -> None:
        """sub_region set on UK_IDM — rejected."""
        df = _make_valid_df(
            region=["UK_IDM", "UK_IDM", "UK_IDM"],
            sub_region=["TOKYO", None, None],
        )
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)

    def test_sub_region_on_detroit(self) -> None:
        """sub_region set on DETROIT_FIRST_WAVE — rejected."""
        df = _make_valid_df(
            region=["DETROIT_FIRST_WAVE", "DETROIT_FIRST_WAVE", "UK_IDM"],
            sub_region=["OSAKA", None, None],
        )
        with pytest.raises(pandera.errors.SchemaError):
            DATASET_SCHEMA.validate(df)
