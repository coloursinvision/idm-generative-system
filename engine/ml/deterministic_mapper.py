"""deterministic_mapper — canonical mapping from scene + track params to DSP targets.

Pipeline layer: 3
Consumes:       regional_profiles (RegionalProfile, RegionCode,
                    SubRegion, load_profile)
                resonance_rules (bpm_to_hz, midi_to_hz, hz_to_midi,
                    mains_hum_profile, solfeggio_cutoff_seed,
                    schumann_mode, schumann_bpm_anchor)
Consumed by:    Layer 4 dataset generator (gaussian_noise.py)
Status:         complete

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

Implementation completed in S5 (2026-04-25) per the 7-step plan defined
in the S3 stub docstring. See SESSION_2026-04-25_S5.md for decisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from engine.ml.regional_profiles import (
    RegionalProfile,
    RegionCode,
    SubRegion,
    load_profile,
)
from engine.ml.resonance_rules import (
    GridRegion,
    bpm_to_hz,
    hz_to_midi,
    mains_hum_profile,
    midi_to_hz,
    schumann_bpm_anchor,
    schumann_mode,
    solfeggio_cutoff_seed,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOTE_NAMES: tuple[str, ...] = (
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
)

_REGION_TO_GRID: dict[RegionCode, GridRegion] = {
    "DETROIT_FIRST_WAVE": "US",
    "DETROIT_UR": "US",
    "DREXCIYA": "US",
    "UK_IDM": "UK",
    "UK_BRAINDANCE": "UK",
    "JAPAN_IDM": "JP_TOKYO",
}
"""Map each regional profile to its physical electrical grid region.

Detroit scenes operate on the US 60 Hz grid. UK scenes on the 50 Hz grid.
Japan defaults to Tokyo (50 Hz); Osaka override (60 Hz) is handled at
runtime via ``sub_region``.
"""

_UK_GRID: GridRegion = "UK"
"""Reference grid for the dual-stack mains emission (D-S5-01).

UK_IDM is the conceptual baseline of the system. Non-UK regions receive
both a UK 50 Hz reference stack and their physical regional stack.
"""

_MAINS_N_HARMONICS: int = 5
"""Number of mains harmonics (inclusive of fundamental) emitted per stack."""

_SCHUMANN_BPM_TOLERANCE: float = 2.0
"""Maximum BPM deviation from the Schumann mode-1 anchor (~117.45 BPM)
that triggers emission of the ``schumann_bpm_anchor`` resonant point."""

_MIDI_MAX: float = 127.0
"""Upper bound of the standard MIDI note number range."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _nearest_note(frequency_hz: float, tuning_hz: float = 440.0) -> str:
    """Resolve a frequency to its nearest 12-TET note in scientific pitch notation.

    Args:
        frequency_hz: Positive frequency in Hz.
        tuning_hz: A4 reference frequency.

    Returns:
        Note name string (e.g. ``"G1"``, ``"F#3"``).
    """
    midi_exact = hz_to_midi(frequency_hz, tuning_hz)
    midi_rounded = round(midi_exact)
    pitch_class = midi_rounded % 12
    octave = (midi_rounded // 12) - 1
    return f"{_NOTE_NAMES[pitch_class]}{octave}"


def _select_tuning_hz(profile: RegionalProfile) -> float:
    """Select the A4 reference tuning for a given profile.

    Currently returns ``440.0`` for all profiles. Reserved for TODO-3
    (Aphex Twin 432 Hz alternative tuning practice) once that parked
    research item is resolved.

    Args:
        profile: Loaded regional profile.

    Returns:
        A4 reference frequency in Hz.
    """
    # TODO-3: When resolved, inspect profile for alternative tuning flag.
    _ = profile  # Consumed once TODO-3 activates.
    return 440.0


def _resolve_grid(region: RegionCode, sub_region: SubRegion | None) -> GridRegion:
    """Map a profile region + sub-region to its physical electrical grid.

    Args:
        region: Canonical region code.
        sub_region: Optional sub-region discriminator.

    Returns:
        Grid region identifier for :func:`mains_hum_profile`.
    """
    if region == "JAPAN_IDM" and sub_region == "OSAKA":
        return "JP_OSAKA"
    return _REGION_TO_GRID[region]


def _is_uk_region(region: RegionCode) -> bool:
    """Return ``True`` if the region's physical grid is UK 50 Hz."""
    return _REGION_TO_GRID[region] == _UK_GRID


def _build_mains_points(
    region: RegionCode,
    sub_region: SubRegion | None,
    tuning_hz: float,
) -> list[ResonantPoint]:
    """Build the mains-hum resonant points, applying the dual-stack rule (D-S5-01).

    For UK regions, emits a single stack (regional = reference).
    For non-UK regions, emits the UK 50 Hz reference stack first, then the
    physical regional stack.

    Args:
        region: Canonical region code.
        sub_region: Optional sub-region discriminator.
        tuning_hz: A4 reference for nearest-note resolution.

    Returns:
        List of mains-related :class:`ResonantPoint` entries.
    """
    points: list[ResonantPoint] = []
    regional_grid = _resolve_grid(region, sub_region)

    if _is_uk_region(region):
        # Single stack — UK is both reference and regional.
        mains = mains_hum_profile(
            regional_grid,
            n_harmonics=_MAINS_N_HARMONICS,
            tuning_hz=tuning_hz,
        )
        points.append(ResonantPoint(
            frequency_hz=mains.fundamental_hz,
            source="mains_fundamental",
            nearest_note=mains.harmonics[0].nearest_note,
        ))
        points.extend(
            ResonantPoint(
                frequency_hz=h.frequency_hz,
                source=f"mains_harmonic_{h.index}",
                nearest_note=h.nearest_note,
            )
            for h in mains.harmonics[1:]
        )
    else:
        # Dual stack — UK reference first, then regional.
        uk_mains = mains_hum_profile(
            _UK_GRID,
            n_harmonics=_MAINS_N_HARMONICS,
            tuning_hz=tuning_hz,
        )
        points.append(ResonantPoint(
            frequency_hz=uk_mains.fundamental_hz,
            source="mains_ref_fundamental",
            nearest_note=uk_mains.harmonics[0].nearest_note,
        ))
        points.extend(
            ResonantPoint(
                frequency_hz=h.frequency_hz,
                source=f"mains_ref_harmonic_{h.index}",
                nearest_note=h.nearest_note,
            )
            for h in uk_mains.harmonics[1:]
        )

        regional_mains = mains_hum_profile(
            regional_grid,
            n_harmonics=_MAINS_N_HARMONICS,
            tuning_hz=tuning_hz,
        )
        points.append(ResonantPoint(
            frequency_hz=regional_mains.fundamental_hz,
            source="mains_fundamental",
            nearest_note=regional_mains.harmonics[0].nearest_note,
        ))
        points.extend(
            ResonantPoint(
                frequency_hz=h.frequency_hz,
                source=f"mains_harmonic_{h.index}",
                nearest_note=h.nearest_note,
            )
            for h in regional_mains.harmonics[1:]
        )

    return points


def _apply_effects_filter(
    points: list[ResonantPoint],
    effects: Sequence[str],
) -> list[ResonantPoint]:
    """Remove resonant points invalidated by the signal-chain effects.

    Currently recognised effects:

    - ``"notch_mains"`` — removes all mains-derived points (both reference
      and regional stacks). Physically models a notch filter at the grid
      fundamental that eliminates hum from the signal path.

    Unrecognised effect identifiers are silently ignored (pass-through).
    Future sessions may extend recognition to additional effect types.

    Args:
        points: Current resonant point stack.
        effects: Signal-chain effect identifiers in chain order.

    Returns:
        Filtered copy of the point stack.
    """
    effects_set = frozenset(effects)

    if "notch_mains" in effects_set:
        points = [
            p for p in points
            if not (p.source.startswith("mains_") or p.source.startswith("mains_ref_"))
        ]

    return points


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResonantPoint:
    """One resonant frequency emitted by the mapper, with provenance.

    Attributes:
        frequency_hz: Resonant frequency in Hz.
        source: Machine-readable provenance tag identifying which rule
            emitted this point. Conventional values:

            - ``"pitch_ref"`` — scene pitch reference at ``tuning_hz``
            - ``"bpm_harmonic"`` — audible harmonic from :func:`bpm_to_hz`
            - ``"mains_fundamental"`` — regional grid fundamental (50 / 60 Hz)
            - ``"mains_harmonic_<k>"`` — ``k``-th regional mains harmonic
            - ``"mains_ref_fundamental"`` — UK 50 Hz reference fundamental (D-S5-01)
            - ``"mains_ref_harmonic_<k>"`` — ``k``-th UK reference harmonic (D-S5-01)
            - ``"solfeggio_seed"`` — aesthetic Solfeggio seed
            - ``"schumann_bpm_anchor"`` — BPM-anchor derived from Schumann mode 1
            - ``"sub_bass"`` — profile sub-bass fundamental

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
            always ``440.0``; ``432.0`` reserved for profiles whose spoke
            records alternative-tuning practice (TODO-3, parked).
        resonant_points: Ordered stack of resonant frequencies with
            per-point provenance. Ordering is deterministic for a given
            ``(bpm, pitch_midi, swing, region, sub_region, effects)``
            tuple: pitch_ref → bpm_harmonic → mains (ref then regional)
            → solfeggio_seed → schumann_bpm_anchor → sub_bass.
    """

    tuning_hz: float
    resonant_points: tuple[ResonantPoint, ...]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

    Implements the 7-step pipeline defined in the S3 stub docstring.

    Step 1: Resolve profile via :func:`load_profile` if not supplied.
    Step 2: Emit ``pitch_ref`` resonant point from ``pitch_midi`` + tuning.
    Step 3: Call :func:`bpm_to_hz` for the tempo's audible harmonic.
    Step 4: Build mains-hum stacks (dual-stack for non-UK regions per D-S5-01).
    Step 5: Call :func:`solfeggio_cutoff_seed` when the region has an aesthetic seed.
    Step 6: Anchor to :func:`schumann_bpm_anchor` when BPM is within tolerance.
    Step 7: Filter resonant stack based on signal-chain ``effects``.

    Args:
        bpm: Tempo in beats per minute. Must be positive.
        pitch_midi: Track key reference as a MIDI note number (A4 = 69).
            Fractional values accepted for microtuning.
        swing: Track swing ratio in ``[0.0, 1.0]``; the literal
            ``"variable"`` for per-step swing; or ``None`` to inherit
            the regional profile's swing specification. Consumed by
            Layer 4; not used in the deterministic mapping itself.
        region: Regional profile identifier.
        effects: Sequence of named effect identifiers in signal-chain
            order. See :func:`_apply_effects_filter` for recognised values.
        sub_region: Optional sub-region discriminator. Currently only
            ``"OSAKA"`` has effect (forces the Japan 60 Hz mains stack).
        profile: Optional pre-loaded :class:`RegionalProfile`. If
            ``None``, the mapper calls ``load_profile(region,
            sub_region)`` on demand.

    Returns:
        A :class:`DeterministicMapping` with the selected tuning
        reference and a tuple of :class:`ResonantPoint` entries.

    Raises:
        ValueError: If ``bpm`` is not positive or ``pitch_midi`` is
            outside the MIDI range ``[0, 127]``.
        SpokeParseError: If profile resolution requires spoke access
            and the spoke file is missing or malformed.
    """
    # --- Input validation ---------------------------------------------------
    if bpm <= 0.0:
        msg = f"bpm must be positive, got {bpm}"
        raise ValueError(msg)
    if not (0.0 <= pitch_midi <= _MIDI_MAX):
        msg = f"pitch_midi must be in [0, {_MIDI_MAX:.0f}], got {pitch_midi}"
        raise ValueError(msg)

    # swing is consumed by Layer 4 (GaussianNoiseInjector); the
    # deterministic mapper passes it through without transformation.
    _ = swing

    # --- Step 1: Resolve profile --------------------------------------------
    if profile is None:
        profile = load_profile(region, sub_region=sub_region)

    # --- Step 2: Tuning reference + pitch_ref -------------------------------
    tuning_hz = _select_tuning_hz(profile)
    pitch_hz = midi_to_hz(pitch_midi, tuning_hz)

    points: list[ResonantPoint] = [
        ResonantPoint(
            frequency_hz=pitch_hz,
            source="pitch_ref",
            nearest_note=_nearest_note(pitch_hz, tuning_hz),
        ),
    ]

    # --- Step 3: BPM audible harmonic ---------------------------------------
    bpm_harm = bpm_to_hz(bpm, tuning_hz=tuning_hz)
    points.append(ResonantPoint(
        frequency_hz=bpm_harm.frequency_hz,
        source="bpm_harmonic",
        nearest_note=bpm_harm.nearest_note,
    ))

    # --- Step 4: Mains-hum stacks (dual-stack for non-UK, D-S5-01) ----------
    points.extend(_build_mains_points(region, sub_region, tuning_hz))

    # --- Step 5: Solfeggio aesthetic seed -----------------------------------
    seed_hz = solfeggio_cutoff_seed(region)
    if seed_hz is not None:
        points.append(ResonantPoint(
            frequency_hz=seed_hz,
            source="solfeggio_seed",
            nearest_note=_nearest_note(seed_hz, tuning_hz),
        ))

    # --- Step 6: Schumann BPM anchor ---------------------------------------
    anchor_bpm = schumann_bpm_anchor(mode=1, subharmonic_divisor=4)
    if abs(bpm - anchor_bpm) <= _SCHUMANN_BPM_TOLERANCE:
        mode1_hz = schumann_mode(1)
        points.append(ResonantPoint(
            frequency_hz=mode1_hz,
            source="schumann_bpm_anchor",
            nearest_note=_nearest_note(mode1_hz, tuning_hz),
        ))

    # --- Step 6b: Sub-bass from profile -------------------------------------
    if profile.noise is not None:
        sub_hz = float(profile.noise.sub_bass_hz)
        points.append(ResonantPoint(
            frequency_hz=sub_hz,
            source="sub_bass",
            nearest_note=_nearest_note(sub_hz, tuning_hz),
        ))

    # --- Step 7: Effects-driven stack filtering -----------------------------
    points = _apply_effects_filter(points, effects)

    return DeterministicMapping(
        tuning_hz=tuning_hz,
        resonant_points=tuple(points),
    )
