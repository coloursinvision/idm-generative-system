"""resonance_rules — Layer 2 Part 5.1 rule implementations.

Pipeline layer: 3
Consumes:       02-Knowledge/supporting/resonance/*.md (5 rule spokes)
Consumed by:    deterministic_mapper, regional_profiles (for cross-refs)
Status:         draft

Implements the five rule signatures from the resonance rule spokes. Four rules
are physically derived (BPM/Hz mapping, Schumann cavity modes, 12-TET tuning
arithmetic, regional mains-hum harmonics); the fifth (Solfeggio cutoff
seeding) is an aesthetic project convention and is explicitly marked as such.

The four physical rules are grouped at the top of this module. The single
aesthetic rule is at the bottom, visually separated by a divider and a
header comment recording the non-physical character of its values.

Spoke sources:
    BPM_TO_HZ.md              → bpm_to_hz + AudibleHarmonic
    SCHUMANN_RESONANCES.md    → schumann_mode + schumann_bpm_anchor
    TUNING_432_440.md         → midi_to_hz + hz_to_midi + tuning_difference_hz
    MAINS_HUM_REGIONAL.md     → mains_hum_profile + friends
    SOLFEGGIO_FILTER_SEEDING.md → solfeggio_cutoff_seed (AESTHETIC, not physical)

All functions are pure: no I/O, no hidden state, no module-level side effects
beyond constant-table definitions. Downstream layers (Gaussian noise injection,
dataset generation) may safely call any function at any time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Shared helpers (private)
# ---------------------------------------------------------------------------

_NOTE_NAMES: tuple[str, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)


def _hz_to_note_and_cents(
    frequency_hz: float,
    tuning_hz: float = 440.0,
) -> tuple[str, float]:
    """Resolve a frequency to its nearest 12-TET note name and signed cents.

    Args:
        frequency_hz: Positive frequency in Hz.
        tuning_hz: Reference frequency for A4.

    Returns:
        A two-tuple of ``(note_name, cents_deviation)`` where ``note_name``
        follows scientific pitch notation (e.g. ``"G1"``, ``"F#3"``) and
        ``cents_deviation`` is signed in ``[-50, +50]``.

    Raises:
        ValueError: If ``frequency_hz`` is not positive.
    """
    if frequency_hz <= 0.0:
        raise ValueError(f"frequency_hz must be positive, got {frequency_hz}")
    midi_exact = 69.0 + 12.0 * math.log2(frequency_hz / tuning_hz)
    midi_rounded = round(midi_exact)
    cents = (midi_exact - midi_rounded) * 100.0
    pitch_class = midi_rounded % 12
    octave = (midi_rounded // 12) - 1
    return f"{_NOTE_NAMES[pitch_class]}{octave}", cents


# ===========================================================================
# PHYSICAL RULES (1–4)
# ===========================================================================

# ---------------------------------------------------------------------------
# Rule 1 — BPM to audible harmonic mapping   [BPM_TO_HZ.md]
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudibleHarmonic:
    """An audible harmonic derived from a tempo by octave multiplication.

    Attributes:
        frequency_hz: Resulting frequency after beat-Hz * octave_multiplier.
        nearest_note: Nearest 12-TET note in scientific pitch notation.
        cents_deviation: Signed distance from the nearest note in cents,
            always within ``[-50, +50]``.
        harmonically_locked: ``True`` when ``|cents_deviation| <= 5``,
            indicating the harmonic sits effectively on the tuning grid.
    """

    frequency_hz: float
    nearest_note: str
    cents_deviation: float
    harmonically_locked: bool


def bpm_to_hz(
    bpm: float,
    octave_multiplier: Literal[1, 2, 4, 8, 16, 32, 64, 128, 256] = 64,
    tuning_hz: float = 440.0,
) -> AudibleHarmonic:
    """Map a tempo to its audible harmonic and identify the nearest pitch.

    The beat frequency ``bpm / 60`` is multiplied by ``octave_multiplier``
    (power of two) to shift into the audible range; the result is resolved
    to the nearest 12-TET note.

    Args:
        bpm: Tempo in beats per minute. Must be positive.
        octave_multiplier: Power-of-two factor that shifts the beat
            frequency into the audible range. ``64`` is the canonical choice
            for typical IDM tempos (80–180 BPM land in the C2–F3 octave).
        tuning_hz: Reference pitch for A4. Defaults to concert ``440.0``;
            ``432.0`` supports alternative-tuning research.

    Returns:
        An :class:`AudibleHarmonic` describing the resulting frequency,
        nearest note, signed cents deviation, and whether the harmonic is
        grid-locked (``|cents| <= 5``).

    Raises:
        ValueError: If ``bpm`` is not positive.

    Example:
        >>> h = bpm_to_hz(128.0, octave_multiplier=64)
        >>> round(h.frequency_hz, 2)
        136.53
    """
    if bpm <= 0.0:
        raise ValueError(f"bpm must be positive, got {bpm}")
    frequency_hz = (bpm / 60.0) * octave_multiplier
    note, cents = _hz_to_note_and_cents(frequency_hz, tuning_hz)
    return AudibleHarmonic(
        frequency_hz=frequency_hz,
        nearest_note=note,
        cents_deviation=cents,
        harmonically_locked=abs(cents) <= 5.0,
    )


# ---------------------------------------------------------------------------
# Rule 2 — Schumann resonances (Earth-ionosphere cavity)   [SCHUMANN_RESONANCES.md]
# ---------------------------------------------------------------------------

SCHUMANN_MODES_HZ: tuple[float, ...] = (7.83, 14.30, 20.80, 27.30, 33.80)
"""Canonical Schumann resonance mode frequencies (first five modes, Hz).

Values are the widely cited observational means; individual measurements
drift with ionospheric conditions and diurnal cycles.
"""


def schumann_mode(n: int = 1) -> float:
    """Return the frequency of the *n*-th Schumann resonance mode.

    Args:
        n: 1-indexed mode number in ``[1, len(SCHUMANN_MODES_HZ)]``.

    Returns:
        Frequency in Hz from :data:`SCHUMANN_MODES_HZ`.

    Raises:
        ValueError: If ``n`` is out of range.

    Example:
        >>> schumann_mode(1)
        7.83
    """
    if not 1 <= n <= len(SCHUMANN_MODES_HZ):
        raise ValueError(f"n must be in [1, {len(SCHUMANN_MODES_HZ)}], got {n}")
    return SCHUMANN_MODES_HZ[n - 1]


def schumann_bpm_anchor(
    mode: int = 1,
    subharmonic_divisor: Literal[1, 2, 4, 8, 16] = 4,
) -> float:
    """Convert a Schumann mode frequency to a musically usable BPM anchor.

    Computed as ``schumann_mode(mode) * 60 / subharmonic_divisor``. Mode 1
    (7.83 Hz) with divisor 4 yields ~117.45 BPM, a common anchor for tempo
    quantisation against the Earth-ionosphere fundamental.

    Args:
        mode: Schumann mode index, 1-indexed.
        subharmonic_divisor: Power-of-two divisor applied after the Hz→BPM
            conversion to drop the tempo into a musically useful range.

    Returns:
        Tempo in beats per minute.

    Example:
        >>> round(schumann_bpm_anchor(1, 4), 2)
        117.45
    """
    return (schumann_mode(mode) * 60.0) / subharmonic_divisor


# ---------------------------------------------------------------------------
# Rule 3 — 432 / 440 Hz tuning arithmetic   [TUNING_432_440.md]
# ---------------------------------------------------------------------------

# PEP 586 forbids float values inside ``Literal[...]``; mypy strict rejects
# ``Literal[432.0, 440.0]``. ``TuningReference`` is therefore typed as ``float``
# at the language level. The canonical values are ``432.0`` and ``440.0``;
# runtime validation is the caller's concern. This diverges from the raw spoke
# signature in ``TUNING_432_440.md`` §4 by necessity, not by design.
TuningReference = float


def midi_to_hz(midi_note: float, tuning_hz: TuningReference = 440.0) -> float:
    """Convert a MIDI note number to frequency in Hz under a given tuning.

    Args:
        midi_note: MIDI note number (A4 = 69). Accepts float for microtuning.
        tuning_hz: Reference frequency for A4.

    Returns:
        Frequency in Hz.

    Example:
        >>> midi_to_hz(69, 440.0)
        440.0
    """
    return tuning_hz * math.pow(2.0, (midi_note - 69.0) / 12.0)


def hz_to_midi(
    frequency_hz: float,
    tuning_hz: TuningReference = 440.0,
) -> float:
    """Convert a frequency in Hz to its (possibly fractional) MIDI note number.

    Args:
        frequency_hz: Positive frequency in Hz.
        tuning_hz: Reference frequency for A4.

    Returns:
        MIDI note number; fractional part expresses microtuning.

    Raises:
        ValueError: If ``frequency_hz`` is not positive.

    Example:
        >>> hz_to_midi(440.0, 440.0)
        69.0
    """
    if frequency_hz <= 0.0:
        raise ValueError(f"frequency_hz must be positive, got {frequency_hz}")
    return 69.0 + 12.0 * math.log2(frequency_hz / tuning_hz)


def hz_to_nearest_note(
    frequency_hz: float,
    tuning_hz: TuningReference = 440.0,
) -> str:
    """Resolve a frequency to its nearest 12-TET note in scientific pitch notation.

    Thin public wrapper around :func:`_hz_to_note_and_cents` that discards
    the cents component. Used by Layer 3 (deterministic mapper) and Layer 4
    (Gaussian noise injector) to label resonant points with human-readable
    note names.

    Args:
        frequency_hz: Positive frequency in Hz.
        tuning_hz: Reference frequency for A4.

    Returns:
        Note name string in scientific pitch notation (e.g. ``"G1"``,
        ``"F#3"``).

    Raises:
        ValueError: If ``frequency_hz`` is not positive.

    Example:
        >>> hz_to_nearest_note(440.0)
        'A4'
        >>> hz_to_nearest_note(50.0)
        'G1'
    """
    note, _ = _hz_to_note_and_cents(frequency_hz, tuning_hz)
    return note


def tuning_difference_hz(a: TuningReference, b: TuningReference) -> float:
    """Return the arithmetic difference ``a - b`` between two tuning references.

    Args:
        a: First tuning reference in Hz.
        b: Second tuning reference in Hz.

    Returns:
        ``a - b`` in Hz.

    Example:
        >>> tuning_difference_hz(440.0, 432.0)
        8.0
    """
    return a - b


# ---------------------------------------------------------------------------
# Rule 4 — Regional mains hum   [MAINS_HUM_REGIONAL.md]
# ---------------------------------------------------------------------------

GridRegion = Literal["UK", "JP_TOKYO", "US", "JP_OSAKA"]

GRID_HZ: dict[GridRegion, float] = {
    "UK": 50.0,
    "JP_TOKYO": 50.0,
    "US": 60.0,
    "JP_OSAKA": 60.0,
}
"""Fundamental frequency of each supported electrical grid region, in Hz."""


@dataclass(frozen=True)
class MainsHarmonic:
    """A single harmonic of regional mains hum.

    Attributes:
        index: 1-indexed harmonic number (``1`` is the fundamental).
        frequency_hz: Frequency of this harmonic in Hz.
        nearest_note: Nearest 12-TET note (scientific pitch notation).
        cents_deviation: Signed cents from the nearest note, in ``[-50, +50]``.
    """

    index: int
    frequency_hz: float
    nearest_note: str
    cents_deviation: float


@dataclass(frozen=True)
class RegionalNoiseFloor:
    """Complete mains-hum harmonic stack for a single electrical grid region.

    Attributes:
        region: Grid region identifier.
        fundamental_hz: Grid fundamental (50 Hz or 60 Hz).
        harmonics: Harmonics starting with the fundamental at ``harmonics[0]``.
        tonal_centre: Nearest note to the fundamental — the perceived pitch
            centre of the noise floor.
    """

    region: GridRegion
    fundamental_hz: float
    harmonics: tuple[MainsHarmonic, ...]
    tonal_centre: str


def mains_hum_profile(
    region: GridRegion,
    n_harmonics: int = 5,
    tuning_hz: float = 440.0,
) -> RegionalNoiseFloor:
    """Build the mains-hum harmonic stack for a given electrical grid region.

    UK and Tokyo share a 50 Hz fundamental (G-centred noise floor, ~35 cents
    sharp of G1); US and Osaka share a 60 Hz fundamental. 60 Hz sits nearly
    equidistant between A♯1 and B1; rounding resolves it to B1 at ~49 cents
    flat. The tonal centre is defined as the nearest-note label of the
    fundamental harmonic.

    Args:
        region: Electrical grid identifier.
        n_harmonics: Number of harmonics to emit, starting from the
            fundamental (inclusive). Must be ``>= 1``.
        tuning_hz: Reference pitch for A4, used when resolving nearest notes.

    Returns:
        A :class:`RegionalNoiseFloor` with the harmonic stack and the tonal
        centre (nearest note to the fundamental).

    Raises:
        ValueError: If ``n_harmonics < 1``.

    Example:
        >>> floor = mains_hum_profile("UK", n_harmonics=3)
        >>> floor.fundamental_hz
        50.0
        >>> len(floor.harmonics)
        3
    """
    if n_harmonics < 1:
        raise ValueError(f"n_harmonics must be >= 1, got {n_harmonics}")
    fundamental = GRID_HZ[region]
    harmonics: list[MainsHarmonic] = []
    for k in range(1, n_harmonics + 1):
        freq = fundamental * k
        note, cents = _hz_to_note_and_cents(freq, tuning_hz)
        harmonics.append(
            MainsHarmonic(
                index=k,
                frequency_hz=freq,
                nearest_note=note,
                cents_deviation=cents,
            )
        )
    return RegionalNoiseFloor(
        region=region,
        fundamental_hz=fundamental,
        harmonics=tuple(harmonics),
        tonal_centre=harmonics[0].nearest_note,
    )


# ===========================================================================
# AESTHETIC RULE (5) — NON-PHYSICAL PROJECT CONVENTION
# ===========================================================================
#
# The frequencies and profile mappings below are an EDITORIAL CONVENTION of
# the IDM Generative System project; they are NOT physically derived. Unlike
# the four rules above, Solfeggio seed values cannot be validated against
# measurement. They are recorded here because the project's editorial scope
# includes them; downstream consumers MUST treat them as stylistic anchors,
# not as ground truth.
#
# See also: SOLFEGGIO_FILTER_SEEDING.md spoke, parked research TODO-6
# (formal Solfeggio → filter cutoff mapping methodology).
# ===========================================================================

SOLFEGGIO_HZ: dict[str, float] = {
    "foundation": 174.0,
    "regeneration": 285.0,
    "liberation": 396.0,
    "transformation": 417.0,
    "harmonic": 528.0,
    "connection": 639.0,
    "expression": 741.0,
    "perception": 852.0,
    "crown": 963.0,
}
"""Canonical Solfeggio frequencies by project-assigned label.

Aesthetic convention, not physical. See the section header above.
"""

ProfileKey = Literal[
    "DETROIT_FIRST_WAVE",
    "DETROIT_UR",
    "DREXCIYA",
    "UK_IDM",
    "UK_BRAINDANCE",
    "JAPAN_IDM",
]

REGIONAL_SOLFEGGIO_SEED: dict[ProfileKey, float] = {
    "DETROIT_UR": 396.0,
    "JAPAN_IDM": 528.0,
    "UK_IDM": 741.0,
    "DREXCIYA": 852.0,
}
"""Solfeggio seed frequency assigned to each regional profile.

``DETROIT_FIRST_WAVE`` and ``UK_BRAINDANCE`` intentionally have no entry —
their spoke editorial stance is that their aesthetics are not Solfeggio-derived.
"""


def solfeggio_cutoff_seed(
    profile: ProfileKey,
    offset_cents: float = 0.0,
) -> float | None:
    """Aesthetic (NON-PHYSICAL) Solfeggio seed frequency for a regional profile.

    The Solfeggio mapping is an editorial project convention; it is NOT a
    physical derivation and MUST NOT be treated as ground truth. Downstream
    consumers should use the returned value as a stylistic anchor for filter
    cutoffs, not as a measured property of source material.

    ``DETROIT_FIRST_WAVE`` and ``UK_BRAINDANCE`` return ``None`` by design.

    Args:
        profile: Regional profile identifier.
        offset_cents: Signed detune applied to the seed frequency, in cents.
            ``0.0`` returns the canonical seed; non-zero offsets shift the
            seed exponentially (``seed * 2 ** (offset_cents / 1200)``).

    Returns:
        Seed frequency in Hz, detuned by ``offset_cents`` if non-zero, or
        ``None`` if the profile has no assigned Solfeggio seed.

    Example:
        >>> solfeggio_cutoff_seed("UK_IDM")
        741.0
        >>> solfeggio_cutoff_seed("DETROIT_FIRST_WAVE") is None
        True
    """
    seed = REGIONAL_SOLFEGGIO_SEED.get(profile)
    if seed is None:
        return None
    if offset_cents == 0.0:
        return seed
    return seed * math.pow(2.0, offset_cents / 1200.0)
