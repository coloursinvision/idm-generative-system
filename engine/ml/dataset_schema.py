"""dataset_schema — pandera schemas for synthetic training and inference validation.

Pipeline layer: 5–6 boundary (DATASET_SCHEMA) + V2.3 endpoint (InferenceSchema)
Consumes:       dataset_generator (SyntheticDatasetGenerator output)
                regional_profiles (RegionCode, SubRegion — type-level enums)
Consumed by:    Layer 6 (DVC pipeline validation stage, model_training.py)
                V2.3 /tuning endpoint (api/main.py — InferenceSchema)
Status:         complete

Two pandera DataFrameSchemas live here.

:data:`DATASET_SCHEMA`
    Validates the **wide-format synthetic training DataFrame** produced by
    :meth:`SyntheticDatasetGenerator.generate_dataset`. Includes feature
    columns, perturbed DSP columns, metadata, and regex-matched ``freq_*``
    target columns. ``strict=False`` to tolerate generator-appended
    "remaining" columns.

:data:`InferenceSchema`
    Validates the **narrow inference DataFrame** built by the V2.3
    ``/tuning`` endpoint handler from a single :class:`TuningRequest`,
    after the ``swing_pct → swing`` boundary conversion (D-S7-04) and the
    Pydantic-level cross-field validation. Five columns only; ``strict=True``
    to reject any accidental feature injection upstream.

Design principles:
    - **Spoke-derived enumerations:** Valid ``region`` and ``sub_region``
      values are extracted from :data:`RegionCode` and :data:`SubRegion`
      type aliases via ``typing.get_args``. No hard-coded region lists.
    - **Regex-matched frequency columns (DATASET_SCHEMA only):** Columns
      matching ``^freq_`` are validated with a single pattern rule
      (nullable, positive when present). InferenceSchema has no ``freq_*``
      columns — those are model *targets*, not inputs.
    - **Declarative construction:** Both schemas built via direct
      :class:`pa.DataFrameSchema` constructor (no ``add_columns()`` /
      mutation patterns — Gotcha #16: pandera 0.31 drops ``regex=True``
      in ``add_columns``).
    - **DataFrame-level cross-column checks:** Sub-region scope rule
      enforced via ``pa.Check`` callables at the schema level on both
      schemas (defence in depth — also enforced in TuningRequest
      ``@model_validator`` and in DATASET_SCHEMA generator output).
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
# DATASET_SCHEMA — wide-format training DataFrame (Layer 5 generator output)
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
                "Swing ratio in [0.0, 1.0]. NaN when swing is 'variable' or None in TrackSpec."
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
            description=("Sub-region discriminator. Non-NaN only for JAPAN_IDM (TOKYO or OSAKA)."),
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
            error=("Metadata inconsistency: is_perturbed must be True iff perturbation_idx > 0."),
        ),
        # Cross-column check: sub_region non-NaN only for JAPAN_IDM.
        pa.Check(
            lambda df: df.loc[df["sub_region"].notna() & (df["region"] != "JAPAN_IDM")].empty,
            error=("sub_region must be NaN for all regions except JAPAN_IDM."),
        ),
    ],
    description=(
        "Schema for the wide-format synthetic training DataFrame produced "
        "by SyntheticDatasetGenerator.generate_dataset(). Validates column "
        "types, value ranges, nullability, and cross-column consistency."
    ),
)


# ---------------------------------------------------------------------------
# InferenceSchema — narrow inference DataFrame (V2.3 /tuning endpoint input)
# ---------------------------------------------------------------------------
#
# Validates the single-row DataFrame built by the V2.3 endpoint handler
# from a TuningRequest payload, AFTER:
#   1. Pydantic field-level validation (bpm, pitch_midi, swing_pct, region,
#      sub_region — each with its own range / Literal constraints)
#   2. Pydantic @model_validator cross-field check (sub_region ↔ JAPAN_IDM)
#   3. Boundary conversion swing = swing_pct / 100.0 (D-S7-04)
#
# Schema width vs DATASET_SCHEMA:
#   - INCLUDES:  bpm, pitch_midi, swing, region, sub_region
#                (the 5 features consumed by the trained model — see
#                 _CATEGORICAL_FEATURES + _NUMERIC_FEATURES in
#                 engine.ml.model_training)
#   - EXCLUDES:  tuning_hz, freq_*           (model targets, not inputs)
#                swing_amount, reverb_*, noise_*  (profile DSP outputs,
#                                                  generated by Layer 4,
#                                                  not user-supplied)
#                is_perturbed, perturbation_idx   (Layer 5 metadata only)
#
# Strict mode (vs DATASET_SCHEMA.strict=False):
#   strict=True locks the inference DataFrame to exactly the 5 input
#   columns — rejects any accidental feature injection from upstream
#   code paths. The V2.3 handler builds this DataFrame programmatically
#   from a validated TuningRequest, so extra columns indicate a bug or
#   misuse, never legitimate input drift.
#
# swing nullable=False (vs nullable=True in DATASET_SCHEMA):
#   At inference, swing always arrives as a float from the boundary
#   conversion (swing_pct / 100.0). NaN swing at this point is unreachable
#   given the Pydantic Field(..., ge=0, le=100) constraint upstream.
#   Tighter constraint catches programming errors earlier in the pipeline.
# ---------------------------------------------------------------------------

InferenceSchema: pa.DataFrameSchema = pa.DataFrameSchema(
    columns={
        "bpm": pa.Column(
            float,
            checks=[pa.Check.ge(60.0), pa.Check.le(240.0)],
            nullable=False,
            description=(
                "Tempo in beats per minute. Range [60, 240] matches "
                "TuningRequest.bpm Field constraints."
            ),
        ),
        "pitch_midi": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(127.0)],
            nullable=False,
            description="MIDI note number (A4 = 69). Range [0, 127].",
        ),
        "swing": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=False,
            description=(
                "Internal swing ratio [0.0, 1.0] after boundary conversion "
                "(swing = swing_pct / 100.0) per D-S7-04. NaN unreachable "
                "given Pydantic upstream constraints — tighter than "
                "DATASET_SCHEMA's training-side counterpart."
            ),
        ),
        "region": pa.Column(
            checks=pa.Check.isin(list(_VALID_REGIONS)),
            nullable=False,
            description=(
                "Regional profile identifier. Spoke-derived enum via "
                "get_args(RegionCode) — no hard-coded list, mirrors "
                "DATASET_SCHEMA.region (D-S7-02)."
            ),
        ),
        "sub_region": pa.Column(
            checks=pa.Check.isin(list(_VALID_SUB_REGIONS)),
            nullable=True,
            description=(
                "Sub-region discriminator. Non-NaN only for JAPAN_IDM "
                "(TOKYO or OSAKA) — D-S3-05. Cross-field rule enforced "
                "by the DataFrame-level check below; Pydantic "
                "@model_validator provides upstream catch."
            ),
        ),
    },
    index=None,
    strict=True,
    coerce=False,
    checks=[
        # Cross-column checks (bidirectional): sub_region scope tied to
        # JAPAN_IDM. Defence in depth — TuningRequest.@_validate_sub_region
        # catches both directions earlier in the request lifecycle, but a
        # hand-built inference DataFrame (e.g., from internal callers
        # bypassing the Pydantic layer) still goes through these guards.
        #
        # Two checks (not one) because the rule has two directions and a
        # single boolean check would either (a) collapse the error message
        # for both cases — bad for debugging — or (b) miss one direction
        # entirely if naively written. Splitting yields precise error
        # messages and full coverage.
        pa.Check(
            lambda df: df.loc[(df["region"] == "JAPAN_IDM") & df["sub_region"].isna()].empty,
            error=("sub_region required when region == 'JAPAN_IDM'."),
        ),
        pa.Check(
            lambda df: df.loc[df["sub_region"].notna() & (df["region"] != "JAPAN_IDM")].empty,
            error=("sub_region must be NaN for all regions except JAPAN_IDM."),
        ),
    ],
    description=(
        "Schema for the inference-time DataFrame built by the V2.3 "
        "/tuning endpoint handler. Validates the 5 input features "
        "(bpm, pitch_midi, swing, region, sub_region) that match the "
        "trained model's feature schema. Narrower and stricter than "
        "DATASET_SCHEMA: 5 columns only, strict mode (no extras "
        "allowed), swing nullable=False."
    ),
)
