"""gaussian_noise — calibrated Gaussian noise injection for synthetic data generation.

Pipeline layer: 4
Consumes:       deterministic_mapper (DeterministicMapping, ResonantPoint)
                regional_profiles (RegionalProfile)
Consumed by:    Layer 5 dataset generator (dataset_generator.py)
Status:         draft (signature scaffold only; implementation deferred to S6)

Produces feature-space dispersion around the deterministic targets emitted
by :func:`deterministic_map`. Each DSP parameter receives independent
Gaussian noise scaled by a per-parameter ``sigma`` drawn from
:class:`PerturbationConfig`. The injector is source-tag-aware: resonant
points tagged ``"mains_*"`` or ``"mains_ref_*"`` are held fixed by default
(grid frequency is a physical invariant, not a tuneable parameter), while
``"solfeggio_seed"`` and ``"bpm_harmonic"`` receive perturbation.

Design principles:
    - **Reproducibility:** Seeded ``numpy.random.Generator`` ensures
      identical perturbation sequences for a given ``(config, seed)`` pair.
    - **Spoke-as-source-of-truth:** Perturbation bounds are derived from
      the hardware-plausibility ranges recorded in the MASTER_DATASET
      Part 5. No hard-coded magic sigma values in this module.
    - **Composability:** :meth:`perturb_profile` and
      :meth:`perturb_mapping` can be called independently or in sequence,
      enabling partial perturbation workflows in Layer 5.

Open questions (resolvable at S6):
    - sigma calibration table: which Part 5 hardware-plausibility bounds map
      to each ``PerturbationConfig`` field. Default proposal: sigma = 10% of
      feature range, refined per feature.
    - Whether ``mapper_sigma`` perturbs ``tuning_hz`` or resonant-point
      frequencies or both.
    - Source-tag filter: which source tags are held fixed vs perturbed.
      Current assumption documented in ``_FIXED_SOURCES`` below.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.ml.deterministic_mapper import DeterministicMapping
from engine.ml.regional_profiles import RegionalProfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXED_SOURCES: frozenset[str] = frozenset({
    "mains_fundamental",
    "mains_ref_fundamental",
})
"""Source tags whose resonant points are never perturbed.

Mains fundamentals are physical invariants of the electrical grid.
Mains harmonics (``mains_harmonic_<k>``, ``mains_ref_harmonic_<k>``)
*may* receive perturbation in future iterations to model transformer
hum variation, but are excluded in the initial implementation.

This set is intentionally conservative. S6 implementation may expand
it based on empirical calibration.
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
        harmonic_sigma: Sigma for harmonic content frequency perturbation.
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
# Public API
# ---------------------------------------------------------------------------


class GaussianNoiseInjector:
    """Applies calibrated Gaussian noise to deterministic DSP targets.

    The injector wraps a seeded ``numpy.random.Generator`` for
    reproducibility. Two perturbation methods are provided:

    - :meth:`perturb_profile` — perturbs profile-level DSP parameters
      (swing, reverb, saturation, harmonic, noise specs).
    - :meth:`perturb_mapping` — perturbs the resonant-point frequencies
      in a :class:`DeterministicMapping`, respecting source-tag filters.

    Both methods return new frozen instances; inputs are never mutated.

    **Stub.** The interface is canonical as of S5 (2026-04-25). Full
    implementation lands in S6. Callers receive :class:`NotImplementedError`
    until then.

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
        # numpy.random.Generator will be initialised in S6 implementation.

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

        Perturbs swing amount, reverb decay/diffusion, saturation
        intensity, harmonic content parameters, and noise floor level
        according to the corresponding sigma values in :attr:`config`.
        Fields with sigma = 0.0 are returned unchanged.

        Returns a new frozen :class:`RegionalProfile`; the input is
        never mutated.

        Args:
            profile: Source profile to perturb.

        Returns:
            A new :class:`RegionalProfile` with perturbed DSP fields.

        Raises:
            NotImplementedError: Always, pending S6 implementation.
        """
        msg = (
            "GaussianNoiseInjector.perturb_profile: implementation "
            "deferred to session S6. Interface canonical as of S5."
        )
        raise NotImplementedError(msg)

    def perturb_mapping(
        self,
        mapping: DeterministicMapping,
        profile: RegionalProfile,
    ) -> DeterministicMapping:
        """Apply Gaussian noise to resonant-point frequencies.

        Perturbs each :class:`ResonantPoint` whose ``source`` tag is
        NOT in :data:`_FIXED_SOURCES`. The ``profile`` argument provides
        hardware-plausibility bounds for clamping perturbed values.

        Returns a new frozen :class:`DeterministicMapping`; the input
        is never mutated.

        Args:
            mapping: Deterministic mapping to perturb.
            profile: Regional profile providing plausibility bounds.

        Returns:
            A new :class:`DeterministicMapping` with perturbed
            resonant-point frequencies.

        Raises:
            NotImplementedError: Always, pending S6 implementation.
        """
        msg = (
            "GaussianNoiseInjector.perturb_mapping: implementation "
            "deferred to session S6. Interface canonical as of S5."
        )
        raise NotImplementedError(msg)
