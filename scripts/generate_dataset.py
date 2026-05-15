"""Generate synthetic training dataset via DVC pipeline.

CLI entry point for the ``generate`` stage in ``dvc.yaml``.
All parameters are read from ``params.yaml`` (DVC-tracked).
Actual generation logic lives in :mod:`engine.ml.dataset_generator`.

Usage:
    python scripts/generate_dataset.py          # uses params.yaml defaults
    dvc repro generate                           # via DVC pipeline
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Literal, cast, get_args

import numpy as np
import yaml  # type: ignore[import-untyped]

from engine.ml.dataset_generator import SyntheticDatasetGenerator, TrackSpec
from engine.ml.gaussian_noise import PerturbationConfig
from engine.ml.regional_profiles import RegionCode, SubRegion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGIONS: tuple[str, ...] = get_args(RegionCode)
_SUB_REGIONS: tuple[str, ...] = get_args(SubRegion)

# Representative effects chain identifiers for TrackSpec generation.
# Sampled in varying combinations to produce diverse effects_density.
_EFFECTS_POOL: tuple[str, ...] = (
    "reverb",
    "delay",
    "compressor",
    "distortion",
    "filter",
    "chorus",
    "flanger",
    "phaser",
    "bitcrusher",
    "granular",
)


# ---------------------------------------------------------------------------
# TrackSpec generation
# ---------------------------------------------------------------------------


def _generate_specs(
    rng: np.random.Generator,
    region: str,
    n_specs: int,
    *,
    bpm_min: float,
    bpm_max: float,
    pitch_midi_min: int,
    pitch_midi_max: int,
) -> list[TrackSpec]:
    """Generate randomised TrackSpecs for a single region.

    Args:
        rng: Seeded numpy random generator for reproducibility.
        region: Regional profile identifier.
        n_specs: Number of specs to generate.
        bpm_min: Minimum BPM (inclusive).
        bpm_max: Maximum BPM (inclusive).
        pitch_midi_min: Minimum MIDI note (inclusive).
        pitch_midi_max: Maximum MIDI note (inclusive).

    Returns:
        List of TrackSpec instances with diverse parameter combinations.
    """
    specs: list[TrackSpec] = []

    for _ in range(n_specs):
        bpm = float(rng.uniform(bpm_min, bpm_max))
        pitch_midi = float(rng.integers(pitch_midi_min, pitch_midi_max + 1))

        # Swing: 80% float in [0, 1], 10% "variable", 10% None
        swing_roll = rng.random()
        swing: float | Literal["variable"] | None
        if swing_roll < 0.8:
            swing = float(rng.uniform(0.0, 1.0))
        elif swing_roll < 0.9:
            swing = "variable"
        else:
            swing = None

        # Effects: random subset of 0–6 effects from pool
        n_effects = int(rng.integers(0, 7))
        effects_indices = rng.choice(len(_EFFECTS_POOL), size=n_effects, replace=False)
        effects = tuple(_EFFECTS_POOL[i] for i in sorted(effects_indices))

        # Sub-region: only for JAPAN_IDM
        sub_region = None
        if region == "JAPAN_IDM":
            sub_region = rng.choice(list(_SUB_REGIONS))

        specs.append(
            TrackSpec(
                bpm=bpm,
                pitch_midi=pitch_midi,
                swing=swing,
                region=cast(RegionCode, region),
                effects=effects,
                sub_region=sub_region,
            )
        )

    return specs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Load params, generate dataset, write to parquet."""
    params_path = Path("params.yaml")
    if not params_path.exists():
        logger.error("params.yaml not found in working directory")
        sys.exit(1)

    with params_path.open() as f:
        params = yaml.safe_load(f)

    gen_params = params["generate"]
    pert_params = gen_params["perturbation"]

    # --- Build PerturbationConfig from params ---
    config = PerturbationConfig(
        swing_sigma=pert_params["swing_sigma"],
        reverb_sigma=pert_params["reverb_sigma"],
        saturation_sigma=pert_params["saturation_sigma"],
        harmonic_sigma=pert_params["harmonic_sigma"],
        noise_sigma=pert_params["noise_sigma"],
        mapper_sigma=pert_params["mapper_sigma"],
    )

    n_perturbations: int = gen_params["n_perturbations"]
    master_seed: int = gen_params["master_seed"]
    specs_per_region: int = gen_params["specs_per_region"]
    output_path = Path(gen_params["output_path"])

    logger.info(
        "Config: %d regions × %d specs × (1 + %d perturbations) = %d expected rows",
        len(_REGIONS),
        specs_per_region,
        n_perturbations,
        len(_REGIONS) * specs_per_region * (1 + n_perturbations),
    )
    logger.info("Master seed: %d", master_seed)
    logger.info("Output: %s", output_path)

    # --- Generate TrackSpecs across all regions ---
    spec_rng = np.random.default_rng(master_seed)
    all_specs: list[TrackSpec] = []

    for region in _REGIONS:
        region_specs = _generate_specs(
            spec_rng,
            region,
            specs_per_region,
            bpm_min=gen_params["bpm_min"],
            bpm_max=gen_params["bpm_max"],
            pitch_midi_min=gen_params["pitch_midi_min"],
            pitch_midi_max=gen_params["pitch_midi_max"],
        )
        all_specs.extend(region_specs)
        logger.info("Region %s: %d specs generated", region, len(region_specs))

    # --- Generate dataset ---
    generator = SyntheticDatasetGenerator(
        config=config,
        n_perturbations=n_perturbations,
        master_seed=master_seed,
    )

    logger.info("Generating dataset from %d total specs...", len(all_specs))
    df = generator.generate_dataset(all_specs)
    logger.info("Dataset generated: %d rows × %d columns", len(df), len(df.columns))

    # --- Write to parquet ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, engine="pyarrow")
    logger.info("Written to %s (%.2f MB)", output_path, output_path.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
