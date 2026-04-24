"""deterministic_mapper — canonical mapping from scene + track parameters to DSP targets.

Pipeline layer: 3
Consumes:       regional_profiles (RegionalProfile, RegionCode, SubRegion)
                resonance_rules (imports deferred to S4 implementation)
Consumed by:    Layer 4 dataset generator
Status:         draft (signature stub only; full implementation deferred to S4)

Contract (stated by Tom):
    f(bpm, pitch, swing, genre, effects) → (tuning_hz, resonant_points)

Signature expansions from the stated spec, each justified below:

1. ``pitch`` → ``pitch_midi: float``
   Unambiguous numeric encoding. Integrates directly with
   ``hz_to_midi`` / ``midi_to_hz`` from :mod:`engine.ml.resonance_rules`
   without needing a note-name parser. Fractional values accepted for
   microtuning.

2. ``genre`` → ``region: RegionCode``
   Precise Layer 2 type alias, prevents genre/region confusion at call
   sites. Literal-constrained so mypy strict catches typos.

3. Added kw-only ``sub_region: SubRegion | None``
   Required to express the JAPAN_IDM Tokyo/Osaka 50/60 Hz split.
   Omitting this would make the mapper incapable of emitting a
   60 Hz-anchored resonant stack for Osaka scenes. Kw-only to keep the
   positional signature aligned with the stated 5-arg spec.

4. Added kw-only ``profile: RegionalProfile | None``
   Caller ergonomics: batch pipelines can hydrate one
   :class:`RegionalProfile` via :func:`load_profile` and reuse it across
   many mapper calls without re-hitting the lru_cache. Tests can inject
   synthetic profiles without touching the filesystem.

5. Return ``(float, Sequence[float])`` → :class:`DeterministicMapping`
   Structured output with typed ``resonant_points: tuple[ResonantPoint,
   ...]``. Each :class:`ResonantPoint` carries a ``source`` provenance
   tag (e.g. ``"mains_harmonic_3"``, ``"solfeggio_seed"``) so downstream
   consumers can attribute a frequency to the rule that emitted it.
   Provenance is essential for Layer 6 XGBoost training-label audit and
   for Layer 4 Gaussian noise injection to selectively perturb points
   by source.

Full implementation is deferred to S4 per bootstrap §6.9. This module
provides the canonical signature and the output dataclasses only; the
function body raises :class:`NotImplementedError` with an explicit
reference to the S4 handoff.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from engine.ml.regional_profiles import RegionalProfile, RegionCode, SubRegion


@dataclass(frozen=True)
class ResonantPoint:
    """One resonant frequency emitted by the mapper, with provenance.

    Attributes:
        frequency_hz: Resonant frequency in Hz.
        source: Machine-readable provenance tag identifying which rule
            emitted this point. Conventional values (final list defined
            in S4):

            - ``"bpm_harmonic"`` — from :func:`bpm_to_hz`
            - ``"mains_fundamental"`` — grid fundamental (50 / 60 Hz)
            - ``"mains_harmonic_<k>"`` — ``k``-th mains harmonic
            - ``"solfeggio_seed"`` — aesthetic Solfeggio seed
            - ``"schumann_mode_<n>"`` — Schumann cavity mode ``n``
            - ``"schumann_bpm_anchor"`` — BPM-anchor derived from mode 1
            - ``"sub_bass"`` — profile's sub-bass fundamental
            - ``"pitch_ref"`` — scene pitch reference (A4 at ``tuning_hz``)

            The tag enables Layer 4 Gaussian-noise perturbation to be
            source-aware (e.g. leave ``mains_*`` fixed while perturbing
            ``solfeggio_seed``) and Layer 6 feature attribution.
        nearest_note: Nearest 12-TET note in scientific pitch notation
            (e.g. ``"G1"``, ``"F#3"``) when a pitch label is resolvable;
            ``None`` otherwise.
    """

    frequency_hz: float
    source: str
    nearest_note: str | None = None


@dataclass(frozen=True)
class DeterministicMapping:
    """Output of :func:`deterministic_map`: tuning reference + resonant stack.

    Attributes:
        tuning_hz: A4 reference frequency selected by the mapper. Almost
            always ``440.0``; ``432.0`` emitted for profiles whose spoke
            records alternative-tuning practice (the UK_IDM +
            Aphex-Twin-era TODO-3 is the candidate case once resolved).
        resonant_points: Ordered stack of resonant frequencies with
            per-point provenance. Ordering is implementation-defined but
            stable for a given ``(bpm, pitch_midi, swing, region,
            sub_region, effects)`` tuple.
    """

    tuning_hz: float
    resonant_points: tuple[ResonantPoint, ...]


def deterministic_map(
    bpm: float,
    pitch_midi: float,
    swing: float | Literal["variable"] | None,
    region: RegionCode,
    effects: Sequence[str],
    *,
    sub_region: SubRegion | None = None,
    profile: RegionalProfile | None = None,
) -> DeterministicMapping:
    """Map a scene + track specification to DSP targets (tuning + resonant stack).

    **Stub.** The signature is canonical as of S3 (2026-04-23). Full
    implementation lands in S4 per bootstrap §6.9. Callers will receive
    :class:`NotImplementedError` until then.

    Planned S4 behaviour (high-level):
        1. Resolve ``profile`` via :func:`load_profile` if not supplied.
        2. Emit ``pitch_ref`` resonant point from ``pitch_midi`` and the
           mapper-selected ``tuning_hz``.
        3. Call :func:`bpm_to_hz` for the tempo's audible harmonic.
        4. Call :func:`mains_hum_profile` for the regional mains stack.
        5. Call :func:`solfeggio_cutoff_seed` when the region has an
           aesthetic seed (``DETROIT_UR``, ``JAPAN_IDM``, ``UK_IDM``,
           ``DREXCIYA``).
        6. Optionally anchor to :func:`schumann_bpm_anchor` when ``bpm``
           is within a tolerance of the mode 1 anchor.
        7. Inspect ``effects`` to adjust or filter the resonant stack
           (e.g. notch filter entries remove near-neighbour mains
           harmonics).

    Args:
        bpm: Tempo in beats per minute. Must be positive.
        pitch_midi: Track key reference as a MIDI note number (A4 = 69).
            Fractional values accepted for microtuning.
        swing: Track swing ratio in ``[0.0, 1.0]``; the literal
            ``"variable"`` for per-step swing; or ``None`` to inherit
            the regional profile's swing specification.
        region: Regional profile identifier.
        effects: Sequence of named effect identifiers in signal-chain
            order. Free-form strings for now; S4 may promote this to a
            structured effect-config sequence.
        sub_region: Optional sub-region discriminator. Currently only
            ``"OSAKA"`` has effect (forces the Japan 60 Hz mains stack).
        profile: Optional pre-loaded :class:`RegionalProfile`. If
            ``None``, the mapper calls ``load_profile(region,
            sub_region)`` on demand. Supplying a profile avoids the
            ``lru_cache`` round-trip in tight loops and allows test
            injection of synthetic profiles.

    Returns:
        A :class:`DeterministicMapping` with the selected tuning
        reference and a tuple of :class:`ResonantPoint` entries.

    Raises:
        NotImplementedError: Always, pending S4 implementation.
        ValueError: (Future.) Will be raised by the S4 body on invalid
            ``bpm`` (not positive), ``pitch_midi`` (out of MIDI range),
            or mismatched ``sub_region`` + ``region`` combinations.
    """
    raise NotImplementedError(
        "deterministic_map: full implementation deferred to session S4 "
        "(bootstrap §6.9). The signature and output dataclasses are "
        "canonical as of S3 (2026-04-23)."
    )
