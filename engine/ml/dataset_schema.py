"""dataset_schema — pandera schema for synthetic training DataFrame validation.

Pipeline layer: 5–6 boundary
Consumes:       dataset_generator (SyntheticDatasetGenerator output)
                regional_profiles (RegionCode, SubRegion — type-level enums)
Consumed by:    Layer 6 (DVC pipeline validation stage, model_training.py)
Status:         complete

Defines a :class:`pa.DataFrameSchema` that validates the wide-format
``pd.DataFrame`` produced by :meth:`SyntheticDatasetGenerator.generate_dataset`.
The schema enforces column types, nullability constraints, value ranges,
and cross-column consistency checks.

Design principles:
    - **Spoke-derived enumerations:** Valid ``region`` and ``sub_region``
      values are extracted from :data:`RegionCode` and :data:`SubRegion`
      type aliases via ``typing.get_args``. No hard-coded region lists.
    - **Regex-matched frequency columns:** Columns matching ``^freq_``
      are validated with a single pattern rule (nullable, positive when
      present). This accommodates variable-presence frequency columns
      across regions (dual-stack mains emission, D-S5-01).
    - **Non-strict mode:** ``strict=False`` allows unexpected columns
      (the generator appends ``remaining`` columns defensively).
    - **DataFrame-level checks:** Cross-column invariants (metadata
      consistency, sub_region scope) are enforced via ``pa.Check``
      callables at the schema level.
"""

from __future__ import annotations

from typing import get_args

import pandera.pandas as pa

from engine.ml.regional_profiles import RegionCode, SubRegion

# ---------------------------------------------------------------------------
# Spoke-derived enumerations (no hard-coded region lists)
# ---------------------------------------------------------------------------

_VALID_REGIONS: tuple[str, ...] = get_args(RegionCode)
_VALID_SUB_REGIONS: tuple[str, ...] = get_args(SubRegion)

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

DATASET_SCHEMA: pa.DataFrameSchema = pa.DataFrameSchema(
    columns={
        # --- Input columns (from TrackSpec) ---
        "bpm": pa.Column(
            float,
            checks=pa.Check.gt(0),
            nullable=False,
            description="Tempo in beats per minute. Must be positive.",
        ),
        "pitch_midi": pa.Column(
            float,
            checks=[pa.Check.ge(0), pa.Check.le(127)],
            nullable=False,
            description="MIDI note number (A4 = 69). Range [0, 127].",
        ),
        "swing": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=True,
            coerce=True,
            description=(
                "Swing ratio in [0.0, 1.0]. NaN when swing is "
                "'variable' or None in TrackSpec."
            ),
        ),
        "region": pa.Column(
            checks=pa.Check.isin(list(_VALID_REGIONS)),
            nullable=False,
            description="Regional profile identifier. Must match RegionCode.",
        ),
        "sub_region": pa.Column(
            checks=pa.Check.isin(list(_VALID_SUB_REGIONS)),
            nullable=True,
            description=(
                "Sub-region discriminator. Non-NaN only for JAPAN_IDM "
                "(TOKYO or OSAKA)."
            ),
        ),
        # --- Tuning ---
        "tuning_hz": pa.Column(
            float,
            checks=pa.Check.isin([432.0, 440.0]),
            nullable=False,
            description="A4 reference frequency selected by the mapper.",
        ),
        # --- Profile DSP columns (perturbed in rows 1..n) ---
        "swing_amount": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=True,
            coerce=True,
            description="Swing amount from profile. NaN when variable or absent.",
        ),
        "reverb_decay": pa.Column(
            float,
            checks=pa.Check.ge(1),
            nullable=True,
            coerce=True,
            description="Reverb decay in ms. NaN when profile has no reverb.",
        ),
        "reverb_diffusion": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=True,
            coerce=True,
            description="Reverb diffusion coefficient [0.0, 1.0]. NaN when absent.",
        ),
        "noise_sub_bass_hz": pa.Column(
            float,
            checks=pa.Check.ge(1),
            nullable=True,
            coerce=True,
            description="Sub-bass frequency in Hz. NaN when profile has no noise spec.",
        ),
        "noise_floor_hz": pa.Column(
            float,
            checks=pa.Check.ge(1),
            nullable=True,
            coerce=True,
            description="Noise floor frequency in Hz. NaN when absent.",
        ),
        "noise_floor_db": pa.Column(
            float,
            checks=pa.Check.le(0),
            nullable=True,
            coerce=True,
            description="Noise floor in dBFS (always <= 0). NaN when absent.",
        ),
        # --- Metadata ---
        "is_perturbed": pa.Column(
            bool,
            nullable=False,
            description="Whether this row is a perturbed variant.",
        ),
        "perturbation_idx": pa.Column(
            int,
            checks=pa.Check.ge(0),
            nullable=False,
            description="0 for baseline, 1..n for perturbed variants.",
        ),
        # --- Regex-matched frequency columns ---
        "freq_.*": pa.Column(
            float,
            checks=pa.Check.gt(0),
            nullable=True,
            coerce=True,
            required=False,
            regex=True,
            description=(
                "Resonant-point frequency by provenance tag. Positive when "
                "present, NaN when absent for a given region."
            ),
        ),
    },
    index=None,
    strict=False,
    coerce=False,
    checks=[
        # Cross-column check: is_perturbed must equal (perturbation_idx > 0).
        pa.Check(
            lambda df: (df["is_perturbed"] == (df["perturbation_idx"] > 0)).all(),
            error=(
                "Metadata inconsistency: is_perturbed must be True iff "
                "perturbation_idx > 0."
            ),
        ),
        # Cross-column check: sub_region non-NaN only for JAPAN_IDM.
        pa.Check(
            lambda df: df.loc[
                df["sub_region"].notna() & (df["region"] != "JAPAN_IDM")
            ].empty,
            error=(
                "sub_region must be NaN for all regions except JAPAN_IDM."
            ),
        ),
    ],
    description=(
        "Schema for the wide-format synthetic training DataFrame produced "
        "by SyntheticDatasetGenerator.generate_dataset(). Validates column "
        "types, value ranges, nullability, and cross-column consistency."
    ),
)

