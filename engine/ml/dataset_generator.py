"""dataset_generator — synthetic labeled dataset generation for XGBoost training.

Pipeline layer: 5
Consumes:       deterministic_mapper (deterministic_map, DeterministicMapping)
                gaussian_noise (GaussianNoiseInjector, PerturbationConfig)
                regional_profiles (RegionalProfile, RegionCode, SubRegion,
                    load_profile)
Consumed by:    Layer 6 (XGBoost training pipeline, /tuning endpoint)
Status:         complete

Composes Layers 3 and 4 into a single dataset-generation workflow:

    TrackSpec → deterministic_map → DeterministicMapping
                                      ↓
                              GaussianNoiseInjector
                                      ↓
                              n perturbed variants
                                      ↓
                              pd.DataFrame (wide format)

Each :class:`TrackSpec` produces ``1 + n_perturbations`` rows:

- **Row 0** (deterministic baseline): the exact output of
  :func:`deterministic_map` with the profile's DSP parameters unperturbed.
  ``is_perturbed = False``, ``perturbation_idx = 0``.
- **Rows 1..n** (perturbed): Gaussian-noised variants produced by
  :class:`GaussianNoiseInjector`. Each variant receives a unique child
  seed derived from the master RNG for reproducibility.

DataFrame schema (wide format):
    The output DataFrame has fixed input columns, variable-presence
    frequency columns (NaN when a resonant point is absent for a given
    region), and perturbed DSP parameter columns. Column prefixes:

    - ``bpm``, ``pitch_midi``, ``swing``, ``region``, ``sub_region`` —
      input specification (from :class:`TrackSpec`).
    - ``tuning_hz`` — A4 reference selected by the mapper.
    - ``freq_<source_tag>`` — resonant-point frequency by provenance.
      Absent sources receive ``NaN``.
    - ``swing_amount``, ``reverb_decay``, ``reverb_diffusion``,
      ``noise_sub_bass_hz``, ``noise_floor_hz``, ``noise_floor_db`` —
      profile-level DSP parameters (perturbed in rows 1..n).
    - ``is_perturbed`` — boolean flag.
    - ``perturbation_idx`` — 0 for baseline, 1..n for perturbed.

Reproducibility:
    A master ``numpy.random.Generator`` (seeded by ``master_seed``) spawns
    unique child seeds for each :class:`GaussianNoiseInjector` instance.
    Given the same ``(master_seed, config, specifications)`` triple, the
    output DataFrame is bit-identical.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from engine.ml.deterministic_mapper import (
    DeterministicMapping,
    deterministic_map,
)
from engine.ml.gaussian_noise import GaussianNoiseInjector, PerturbationConfig
from engine.ml.regional_profiles import (
    RegionalProfile,
    RegionCode,
    SubRegion,
    load_profile,
)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackSpec:
    """One track/scene specification — input to the dataset generator.

    Mirrors the positional and keyword arguments of :func:`deterministic_map`
    so that a batch of specs can be iterated without unpacking.

    Attributes:
        bpm: Tempo in beats per minute. Must be positive.
        pitch_midi: Track key reference as a MIDI note number (A4 = 69).
        swing: Swing ratio in ``[0.0, 1.0]``, the literal ``"variable"``
            for per-step swing, or ``None`` to inherit from the profile.
        region: Regional profile identifier.
        effects: Signal-chain effect identifiers in chain order.
        sub_region: Optional sub-region discriminator.
    """

    bpm: float
    pitch_midi: float
    swing: float | Literal["variable"] | None
    region: RegionCode
    effects: tuple[str, ...]
    sub_region: SubRegion | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _flatten_mapping(
    mapping: DeterministicMapping,
) -> dict[str, float]:
    """Extract resonant-point frequencies into a flat ``freq_<source>`` dict.

    Args:
        mapping: Deterministic mapping to flatten.

    Returns:
        Dict with keys like ``freq_pitch_ref``, ``freq_mains_harmonic_2``,
        etc. Values are frequencies in Hz.
    """
    return {
        f"freq_{point.source}": point.frequency_hz
        for point in mapping.resonant_points
    }


def _flatten_profile_dsp(
    profile: RegionalProfile,
) -> dict[str, Any]:
    """Extract perturbable numeric DSP parameters from a profile.

    Non-numeric and categorical fields are excluded — they are not
    perturbed and would bloat the DataFrame with invariant columns.

    Args:
        profile: Regional profile (deterministic or perturbed).

    Returns:
        Dict with keys: ``swing_amount``, ``reverb_decay``,
        ``reverb_diffusion``, ``noise_sub_bass_hz``, ``noise_floor_hz``,
        ``noise_floor_db``. Missing fields receive ``None`` (→ ``NaN``
        in the DataFrame).
    """
    row: dict[str, Any] = {}

    # Swing
    row["swing_amount"] = (
        profile.swing.swing_amount
        if isinstance(profile.swing.swing_amount, float)
        else None
    )

    # Reverb
    if profile.reverb is not None:
        row["reverb_decay"] = profile.reverb.decay
        row["reverb_diffusion"] = profile.reverb.diffusion
    else:
        row["reverb_decay"] = None
        row["reverb_diffusion"] = None

    # Noise
    if profile.noise is not None:
        row["noise_sub_bass_hz"] = profile.noise.sub_bass_hz
        row["noise_floor_hz"] = profile.noise.noise_floor_hz
        row["noise_floor_db"] = profile.noise.noise_floor_db
    else:
        row["noise_sub_bass_hz"] = None
        row["noise_floor_hz"] = None
        row["noise_floor_db"] = None

    return row


def _build_row(
    spec: TrackSpec,
    mapping: DeterministicMapping,
    profile: RegionalProfile,
    *,
    is_perturbed: bool,
    perturbation_idx: int,
) -> dict[str, Any]:
    """Assemble a single flat dict representing one DataFrame row.

    Args:
        spec: Input track specification.
        mapping: Deterministic or perturbed mapping.
        profile: Deterministic or perturbed profile.
        is_perturbed: Whether this row is a perturbed variant.
        perturbation_idx: 0 for baseline, 1..n for perturbed.

    Returns:
        Flat dict ready for ``pd.DataFrame`` ingestion.
    """
    row: dict[str, Any] = {
        "bpm": spec.bpm,
        "pitch_midi": spec.pitch_midi,
        "swing": spec.swing if isinstance(spec.swing, float) else None,
        "region": spec.region,
        "sub_region": spec.sub_region,
        "tuning_hz": mapping.tuning_hz,
    }

    row.update(_flatten_mapping(mapping))
    row.update(_flatten_profile_dsp(profile))

    row["is_perturbed"] = is_perturbed
    row["perturbation_idx"] = perturbation_idx

    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SyntheticDatasetGenerator:
    """Generates synthetic labeled datasets for XGBoost training.

    Composes :func:`deterministic_map` (Layer 3) with
    :class:`GaussianNoiseInjector` (Layer 4) to produce a wide-format
    ``pandas.DataFrame`` of synthetic training rows.

    Each :class:`TrackSpec` produces ``1 + n_perturbations`` rows:
    one deterministic baseline and ``n_perturbations`` Gaussian-noised
    variants. The master RNG ensures full reproducibility.

    Args:
        config: Per-parameter sigma configuration for perturbation.
        n_perturbations: Number of perturbed variants per track spec.
            Must be non-negative. ``0`` produces only deterministic
            baselines (no noise injection).
        master_seed: Random seed for the master RNG that spawns child
            seeds for each :class:`GaussianNoiseInjector`. ``None``
            uses non-deterministic initialisation.

    Raises:
        ValueError: If ``n_perturbations`` is negative.
    """

    def __init__(
        self,
        config: PerturbationConfig,
        n_perturbations: int = 10,
        master_seed: int | None = None,
    ) -> None:
        if n_perturbations < 0:
            msg = f"n_perturbations must be non-negative, got {n_perturbations}"
            raise ValueError(msg)
        self._config = config
        self._n_perturbations = n_perturbations
        self._master_seed = master_seed
        self._rng = np.random.default_rng(master_seed)

    @property
    def config(self) -> PerturbationConfig:
        """Return the active perturbation configuration."""
        return self._config

    @property
    def n_perturbations(self) -> int:
        """Return the number of perturbed variants per track spec."""
        return self._n_perturbations

    @property
    def master_seed(self) -> int | None:
        """Return the master seed, or ``None`` for non-deterministic mode."""
        return self._master_seed

    def generate_rows(
        self,
        spec: TrackSpec,
        *,
        profile: RegionalProfile | None = None,
    ) -> list[dict[str, Any]]:
        """Generate deterministic baseline + perturbed rows for one spec.

        Args:
            spec: Track specification defining the scene parameters.
            profile: Optional pre-loaded profile. If ``None``, the
                profile is resolved via :func:`load_profile`.

        Returns:
            A list of ``1 + n_perturbations`` flat dicts. Row 0 is the
            deterministic baseline; rows 1..n are perturbed variants.
        """
        if profile is None:
            profile = load_profile(spec.region, sub_region=spec.sub_region)

        # --- Deterministic baseline (Layer 3) ---
        mapping = deterministic_map(
            bpm=spec.bpm,
            pitch_midi=spec.pitch_midi,
            swing=spec.swing,
            region=spec.region,
            effects=list(spec.effects),
            sub_region=spec.sub_region,
            profile=profile,
        )

        rows: list[dict[str, Any]] = [
            _build_row(
                spec,
                mapping,
                profile,
                is_perturbed=False,
                perturbation_idx=0,
            ),
        ]

        # --- Perturbed variants (Layer 4) ---
        for i in range(self._n_perturbations):
            child_seed = int(self._rng.integers(0, 2**63))
            injector = GaussianNoiseInjector(self._config, seed=child_seed)

            perturbed_profile = injector.perturb_profile(profile)
            perturbed_mapping = injector.perturb_mapping(mapping, profile)

            rows.append(
                _build_row(
                    spec,
                    perturbed_mapping,
                    perturbed_profile,
                    is_perturbed=True,
                    perturbation_idx=i + 1,
                ),
            )

        return rows

    def generate_dataset(
        self,
        specifications: Sequence[TrackSpec],
        *,
        profile: RegionalProfile | None = None,
    ) -> pd.DataFrame:
        """Generate a complete synthetic dataset from multiple track specs.

        Iterates over all specifications, calling :meth:`generate_rows`
        for each. The resulting rows are concatenated into a single
        wide-format DataFrame.

        Frequency columns that are absent for certain regions (e.g.
        ``freq_mains_ref_fundamental`` for UK profiles) receive ``NaN``.

        Args:
            specifications: Sequence of track specifications. An empty
                sequence produces an empty DataFrame.
            profile: Optional pre-loaded profile passed through to
                :meth:`generate_rows`. If ``None``, each spec resolves
                its own profile via :func:`load_profile`. Useful for
                batch generation across a single region and for tests
                that avoid spoke filesystem access.

        Returns:
            A ``pandas.DataFrame`` with ``len(specifications) *
            (1 + n_perturbations)`` rows. Columns are ordered:
            input fields → ``tuning_hz`` → ``freq_*`` → DSP params →
            metadata.
        """
        if not specifications:
            return pd.DataFrame()

        all_rows: list[dict[str, Any]] = []
        for spec in specifications:
            all_rows.extend(self.generate_rows(spec, profile=profile))

        df = pd.DataFrame(all_rows)

        # --- Column ordering: inputs → tuning → freq → DSP → metadata ---
        input_cols = ["bpm", "pitch_midi", "swing", "region", "sub_region"]
        tuning_cols = ["tuning_hz"]
        freq_cols = sorted(c for c in df.columns if c.startswith("freq_"))
        dsp_cols = [
            "swing_amount",
            "reverb_decay",
            "reverb_diffusion",
            "noise_sub_bass_hz",
            "noise_floor_hz",
            "noise_floor_db",
        ]
        meta_cols = ["is_perturbed", "perturbation_idx"]

        ordered = (
            input_cols
            + tuning_cols
            + freq_cols
            + [c for c in dsp_cols if c in df.columns]
            + meta_cols
        )
        # Include any unexpected columns at the end (defensive).
        remaining = [c for c in df.columns if c not in ordered]

        return df[ordered + remaining]
