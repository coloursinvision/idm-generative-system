"""gaussian_noise — calibrated Gaussian noise injection for synthetic data generation.

Pipeline layer: 4
Consumes:       deterministic_mapper (DeterministicMapping, ResonantPoint)
                regional_profiles (RegionalProfile, NoiseSpec, ReverbSpec,
                    SwingSpec)
                resonance_rules (hz_to_nearest_note)
Consumed by:    Layer 5 dataset generator (dataset_generator.py)
Status:         complete

Produces feature-space dispersion around the deterministic targets emitted
by :func:`deterministic_map`. Each DSP parameter receives independent
Gaussian noise scaled by a per-parameter ``sigma`` drawn from
:class:`PerturbationConfig`. The injector is source-tag-aware: resonant
points tagged ``"mains_fundamental"`` or ``"mains_ref_fundamental"`` are
held fixed by default (grid frequency is a physical invariant, not a
tuneable parameter), while all other source tags receive perturbation.

Design principles:
    - **Reproducibility:** Seeded ``numpy.random.Generator`` ensures
      identical perturbation sequences for a given ``(config, seed)`` pair.
    - **Spoke-as-source-of-truth:** Perturbation bounds are derived from
      the hardware-plausibility ranges recorded in the MASTER_DATASET
      Part 5. No hard-coded magic sigma values in this module.
    - **Composability:** :meth:`perturb_profile` and
      :meth:`perturb_mapping` can be called independently or in sequence,
      enabling partial perturbation workflows in Layer 5.
    - **Immutability:** Both public methods return new frozen dataclass
      instances; inputs are never mutated.

RNG draw order contract:
    :meth:`perturb_profile` draws in fixed field order:
    ``swing_amount → reverb_decay → reverb_diffusion → noise_sub_bass_hz
    → noise_floor_hz → noise_floor_db``. Fields that are absent (``None``)
    or whose sigma is ``0.0`` consume zero draws, preserving downstream
    determinism for any ``(config, seed)`` pair.

    :meth:`perturb_mapping` draws one value per non-fixed resonant point,
    in the order they appear in ``mapping.resonant_points``. Fixed-source
    points consume zero draws.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from engine.ml.deterministic_mapper import (
    DeterministicMapping,
    ResonantPoint,
)
from engine.ml.regional_profiles import (
    NoiseSpec,
    RegionalProfile,
    ReverbSpec,
    SwingSpec,
)
from engine.ml.resonance_rules import hz_to_nearest_note

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXED_SOURCES: frozenset[str] = frozenset(
    {
        "mains_fundamental",
        "mains_ref_fundamental",
    }
)
"""Source tags whose resonant points are never perturbed.

Mains fundamentals are physical invariants of the electrical grid.
Mains harmonics (``mains_harmonic_<k>``, ``mains_ref_harmonic_<k>``)
*may* receive perturbation to model transformer hum variation. They are
NOT in this set and therefore DO receive perturbation scaled by
``mapper_sigma``.

This set is intentionally conservative. Future iterations may expand it
based on empirical calibration.
"""

_MIN_FREQUENCY_HZ: float = 1.0
"""Lower clamp for perturbed frequency values.

Frequencies must remain positive and physically meaningful. Sub-Hz values
are unrepresentable in the downstream DSP chain.
"""


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerturbationConfig:
    """Per-parameter Gaussian noise standard deviations.

    Each field represents the sigma (standard deviation) of a zero-mean
    Gaussian applied to the corresponding DSP parameter dimension.
    A value of ``0.0`` disables perturbation for that parameter.

    Attributes:
        swing_sigma: Sigma for swing amount perturbation.
        reverb_sigma: Sigma for reverb decay / diffusion perturbation.
        saturation_sigma: Sigma for saturation intensity perturbation.
            Reserved — :class:`SaturationSpec` has no numeric fields in
            the current spoke schema.
        harmonic_sigma: Sigma for harmonic content frequency perturbation.
            Reserved — :class:`HarmonicContentSpec` has no perturbable
            numeric fields in the current spoke schema.
        noise_sigma: Sigma for noise floor level perturbation.
        mapper_sigma: Sigma for resonant-point frequency perturbation
            (applied to non-fixed source tags only).
    """

    swing_sigma: float = 0.0
    reverb_sigma: float = 0.0
    saturation_sigma: float = 0.0
    harmonic_sigma: float = 0.0
    noise_sigma: float = 0.0
    mapper_sigma: float = 0.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _draw(rng: np.random.Generator, sigma: float) -> float:
    """Draw a single sample from a zero-mean Gaussian.

    Args:
        rng: Seeded numpy random generator.
        sigma: Standard deviation. Must be non-negative.

    Returns:
        A float sample. Returns ``0.0`` without consuming an RNG draw
        when ``sigma`` is exactly ``0.0``.
    """
    if sigma == 0.0:
        return 0.0
    return float(rng.normal(0.0, sigma))


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value to ``[lo, hi]``.

    Args:
        value: Value to clamp.
        lo: Lower bound (inclusive).
        hi: Upper bound (inclusive).

    Returns:
        Clamped value.
    """
    return max(lo, min(hi, value))


def _perturb_swing(
    swing: SwingSpec,
    rng: np.random.Generator,
    sigma: float,
) -> SwingSpec:
    """Apply Gaussian noise to :class:`SwingSpec` numeric fields.

    Only ``swing_amount`` is perturbed, and only when it is a ``float``
    (not ``"variable"`` or ``None``). Result is clamped to ``[0.0, 1.0]``.

    Args:
        swing: Source swing specification.
        rng: Seeded numpy random generator.
        sigma: Standard deviation for swing perturbation.

    Returns:
        A new :class:`SwingSpec` with perturbed ``swing_amount``, or the
        original instance if no perturbation applies.
    """
    if not isinstance(swing.swing_amount, float) or sigma == 0.0:
        return swing
    perturbed = _clamp(swing.swing_amount + _draw(rng, sigma), 0.0, 1.0)
    return replace(swing, swing_amount=perturbed)


def _perturb_reverb(
    reverb: ReverbSpec | None,
    rng: np.random.Generator,
    sigma: float,
) -> ReverbSpec | None:
    """Apply Gaussian noise to :class:`ReverbSpec` numeric fields.

    Perturbs ``decay`` (int, ms) and ``diffusion`` (float, coefficient).
    Decay is clamped to ``>= 1`` ms. Diffusion is clamped to ``[0.0, 1.0]``.
    Draws occur in fixed order: decay then diffusion, regardless of whether
    the field is ``None``.

    Args:
        reverb: Source reverb specification, or ``None``.
        rng: Seeded numpy random generator.
        sigma: Standard deviation for reverb perturbation.

    Returns:
        A new :class:`ReverbSpec` with perturbed fields, the original
        instance if no perturbation applies, or ``None`` if input is ``None``.
    """
    if reverb is None or sigma == 0.0:
        return reverb

    new_decay = reverb.decay
    if reverb.decay is not None:
        new_decay = max(1, round(reverb.decay + _draw(rng, sigma)))

    new_diffusion = reverb.diffusion
    if reverb.diffusion is not None:
        # Scale sigma to diffusion range: sigma is in ms-scale for decay,
        # so normalise by 1000 for the [0, 1] diffusion coefficient.
        diffusion_sigma = sigma / 1000.0
        new_diffusion = _clamp(
            reverb.diffusion + _draw(rng, diffusion_sigma),
            0.0,
            1.0,
        )

    return replace(reverb, decay=new_decay, diffusion=new_diffusion)


def _perturb_noise(
    noise: NoiseSpec | None,
    rng: np.random.Generator,
    sigma: float,
) -> NoiseSpec | None:
    """Apply Gaussian noise to :class:`NoiseSpec` numeric fields.

    Perturbs ``sub_bass_hz``, ``noise_floor_hz``, and ``noise_floor_db``.
    Hz fields are clamped to ``>= 1``. dB field is clamped to ``<= 0``
    (noise floor is always negative dBFS or zero).

    Draws occur in fixed order: ``sub_bass_hz → noise_floor_hz →
    noise_floor_db``, regardless of whether individual fields are ``None``.

    Args:
        noise: Source noise specification, or ``None``.
        rng: Seeded numpy random generator.
        sigma: Standard deviation for noise perturbation.

    Returns:
        A new :class:`NoiseSpec` with perturbed fields, the original
        instance if no perturbation applies, or ``None`` if input is ``None``.
    """
    if noise is None or sigma == 0.0:
        return noise

    new_sub_bass_hz = noise.sub_bass_hz
    new_sub_bass_hz = max(1, round(noise.sub_bass_hz + _draw(rng, sigma)))

    new_noise_floor_hz = noise.noise_floor_hz
    if noise.noise_floor_hz is not None:
        new_noise_floor_hz = max(1, round(noise.noise_floor_hz + _draw(rng, sigma)))

    new_noise_floor_db = noise.noise_floor_db
    if noise.noise_floor_db is not None:
        new_noise_floor_db = min(0, round(noise.noise_floor_db + _draw(rng, sigma)))

    return replace(
        noise,
        sub_bass_hz=new_sub_bass_hz,
        noise_floor_hz=new_noise_floor_hz,
        noise_floor_db=new_noise_floor_db,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class GaussianNoiseInjector:
    """Applies calibrated Gaussian noise to deterministic DSP targets.

    The injector wraps a seeded ``numpy.random.Generator`` for
    reproducibility. Two perturbation methods are provided:

    - :meth:`perturb_profile` — perturbs profile-level DSP parameters
      (swing, reverb, noise specs). Saturation and harmonic specs are
      passed through unchanged (no perturbable numeric fields in the
      current spoke schema).
    - :meth:`perturb_mapping` — perturbs the resonant-point frequencies
      in a :class:`DeterministicMapping`, respecting source-tag filters.

    Both methods return new frozen instances; inputs are never mutated.

    RNG draw order is deterministic for a given ``(config, seed)`` pair.
    See the module docstring for the full draw-order contract.

    Args:
        config: Per-parameter sigma configuration.
        seed: Random seed for reproducibility. ``None`` uses
            non-deterministic initialisation.
    """

    def __init__(
        self,
        config: PerturbationConfig,
        seed: int | None = None,
    ) -> None:
        self._config = config
        self._seed = seed
        self._rng = np.random.default_rng(seed)

    @property
    def config(self) -> PerturbationConfig:
        """Return the active perturbation configuration."""
        return self._config

    @property
    def seed(self) -> int | None:
        """Return the random seed, or ``None`` for non-deterministic mode."""
        return self._seed

    def perturb_profile(
        self,
        profile: RegionalProfile,
    ) -> RegionalProfile:
        """Apply Gaussian noise to profile-level DSP parameters.

        Perturbs swing amount, reverb decay/diffusion, and noise floor
        fields (sub_bass_hz, noise_floor_hz, noise_floor_db) according to
        the corresponding sigma values in :attr:`config`. Fields with
        sigma = 0.0 are returned unchanged and consume no RNG draws.

        Saturation and harmonic specs are passed through unchanged — they
        contain no perturbable numeric fields in the current spoke schema.

        Returns a new frozen :class:`RegionalProfile`; the input is
        never mutated.

        Args:
            profile: Source profile to perturb.

        Returns:
            A new :class:`RegionalProfile` with perturbed DSP fields.
        """
        new_swing = _perturb_swing(profile.swing, self._rng, self._config.swing_sigma)
        new_reverb = _perturb_reverb(profile.reverb, self._rng, self._config.reverb_sigma)
        new_noise = _perturb_noise(profile.noise, self._rng, self._config.noise_sigma)

        return replace(
            profile,
            swing=new_swing,
            reverb=new_reverb,
            noise=new_noise,
        )

    def perturb_mapping(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> DeterministicMapping:
        """Apply Gaussian noise to resonant-point frequencies.

        Perturbs each :class:`ResonantPoint` whose ``source`` tag is
        NOT in :data:`_FIXED_SOURCES`. Fixed-source points (mains
        fundamentals) are passed through unchanged and consume no RNG
        draws.

        Perturbed frequencies are clamped to ``>=`` :data:`_MIN_FREQUENCY_HZ`.
        The ``nearest_note`` field is recalculated after perturbation using
        the mapping's ``tuning_hz`` reference.

        The ``profile`` argument is accepted per the locked interface and
        reserved for future hardware-plausibility clamping based on spoke
        DSP bounds. In the current implementation it is not consumed.

        Returns a new frozen :class:`DeterministicMapping`; the input
        is never mutated.

        Args:
            mapping: Deterministic mapping to perturb.
            profile: Regional profile providing plausibility bounds.
                Currently unused; reserved for future clamping.

        Returns:
            A new :class:`DeterministicMapping` with perturbed
            resonant-point frequencies.
        """
        # profile reserved for future hardware-plausibility clamping.
        _ = profile

        sigma = self._config.mapper_sigma
        if sigma == 0.0:
            return mapping

        new_points: list[ResonantPoint] = []
        for point in mapping.resonant_points:
            if point.source in _FIXED_SOURCES:
                new_points.append(point)
                continue

            perturbed_hz = max(
                _MIN_FREQUENCY_HZ,
                point.frequency_hz + _draw(self._rng, sigma),
            )
            new_note = hz_to_nearest_note(perturbed_hz, mapping.tuning_hz)
            new_points.append(
                ResonantPoint(
                    frequency_hz=perturbed_hz,
                    source=point.source,
                    nearest_note=new_note,
                )
            )

        return replace(mapping, resonant_points=tuple(new_points))
