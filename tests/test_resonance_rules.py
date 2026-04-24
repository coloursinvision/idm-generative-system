"""Unit tests for engine.ml.resonance_rules — Layer 2 Part 5.1 rule implementations.

Covers the 5 rule signatures (4 physical + 1 aesthetic):

    * bpm_to_hz + AudibleHarmonic
    * schumann_mode + schumann_bpm_anchor + SCHUMANN_MODES_HZ
    * midi_to_hz + hz_to_midi + tuning_difference_hz
    * mains_hum_profile + MainsHarmonic + RegionalNoiseFloor + GRID_HZ
    * solfeggio_cutoff_seed + SOLFEGGIO_HZ + REGIONAL_SOLFEGGIO_SEED  (aesthetic)

All concrete numerical assertions are derived from the rule definitions
and verified against the implementation's ground-truth output (see S3
session log). Where a computed value sits near a rounding boundary (e.g.
60 Hz between A♯1 and B1), the test documents the boundary inline.
"""

from __future__ import annotations

import math

import pytest

from engine.ml.resonance_rules import (
    GRID_HZ,
    REGIONAL_SOLFEGGIO_SEED,
    SCHUMANN_MODES_HZ,
    SOLFEGGIO_HZ,
    AudibleHarmonic,
    MainsHarmonic,
    RegionalNoiseFloor,
    bpm_to_hz,
    hz_to_midi,
    mains_hum_profile,
    midi_to_hz,
    schumann_bpm_anchor,
    schumann_mode,
    solfeggio_cutoff_seed,
    tuning_difference_hz,
)

# ===========================================================================
# Rule 1 — bpm_to_hz + AudibleHarmonic
# ===========================================================================


class TestBpmToHz:
    """Tests for :func:`bpm_to_hz` and its :class:`AudibleHarmonic` return."""

    def test_canonical_idm_tempo_unlocked(self) -> None:
        """128 BPM × 64 = 136.533 Hz, nearest C♯3 (unlocked, ~-26 cents)."""
        h = bpm_to_hz(128.0, octave_multiplier=64)
        assert h.frequency_hz == pytest.approx(128.0 * 64 / 60, abs=1e-9)
        assert h.nearest_note == "C#3"
        assert -30 < h.cents_deviation < -20
        assert h.harmonically_locked is False

    def test_engineered_locked_case(self) -> None:
        """103.125 BPM × 128 = exactly 220 Hz = A3 → locked at 0 cents."""
        h = bpm_to_hz(103.125, octave_multiplier=128)
        assert h.frequency_hz == pytest.approx(220.0, abs=1e-9)
        assert h.nearest_note == "A3"
        assert h.cents_deviation == pytest.approx(0.0, abs=1e-6)
        assert h.harmonically_locked is True

    def test_default_octave_multiplier_is_64(self) -> None:
        assert bpm_to_hz(120.0) == bpm_to_hz(120.0, octave_multiplier=64)

    def test_tuning_reference_shifts_cents_not_hz(self) -> None:
        """Changing tuning reference changes cents deviation, not frequency."""
        h440 = bpm_to_hz(128.0, octave_multiplier=64, tuning_hz=440.0)
        h432 = bpm_to_hz(128.0, octave_multiplier=64, tuning_hz=432.0)
        assert h440.frequency_hz == h432.frequency_hz
        assert h440.cents_deviation != h432.cents_deviation

    def test_locked_threshold_at_5_cents(self) -> None:
        """``harmonically_locked`` is True iff ``|cents_deviation| <= 5``."""
        # 103.125 BPM × 128 = exactly 220 Hz (A3, 0 cents) — locked
        assert bpm_to_hz(103.125, octave_multiplier=128).harmonically_locked is True
        # 128 BPM × 64 = 136.53 Hz (C#3, -26 cents) — not locked
        assert bpm_to_hz(128.0, octave_multiplier=64).harmonically_locked is False

    def test_zero_bpm_raises(self) -> None:
        with pytest.raises(ValueError, match="bpm must be positive"):
            bpm_to_hz(0.0)

    def test_negative_bpm_raises(self) -> None:
        with pytest.raises(ValueError, match="bpm must be positive"):
            bpm_to_hz(-128.0)

    @pytest.mark.parametrize("multiplier", [1, 2, 4, 8, 16, 32, 64, 128, 256])
    def test_all_allowed_octave_multipliers(self, multiplier: int) -> None:
        """Every documented multiplier yields a valid AudibleHarmonic."""
        h = bpm_to_hz(120.0, octave_multiplier=multiplier)  # type: ignore[arg-type]
        assert isinstance(h, AudibleHarmonic)
        assert h.frequency_hz == pytest.approx(120.0 * multiplier / 60, abs=1e-9)
        assert -50.0 <= h.cents_deviation <= 50.0
        assert h.nearest_note  # non-empty string


# ===========================================================================
# Rule 2 — Schumann
# ===========================================================================


class TestSchumann:
    """Tests for :func:`schumann_mode` and :func:`schumann_bpm_anchor`."""

    def test_modes_table_canonical(self) -> None:
        """:data:`SCHUMANN_MODES_HZ` is the canonical 5-element tuple."""
        assert SCHUMANN_MODES_HZ == (7.83, 14.30, 20.80, 27.30, 33.80)

    def test_mode_1_is_default(self) -> None:
        assert schumann_mode() == 7.83
        assert schumann_mode(1) == 7.83

    @pytest.mark.parametrize(
        "n, expected",
        [(1, 7.83), (2, 14.30), (3, 20.80), (4, 27.30), (5, 33.80)],
    )
    def test_all_5_modes(self, n: int, expected: float) -> None:
        assert schumann_mode(n) == expected

    @pytest.mark.parametrize("invalid_n", [0, -1, 6, 100])
    def test_out_of_range_raises(self, invalid_n: int) -> None:
        with pytest.raises(ValueError, match="n must be in"):
            schumann_mode(invalid_n)

    def test_bpm_anchor_canonical(self) -> None:
        """Mode 1 × 60 ÷ 4 = 117.45 BPM (canonical IDM tempo anchor)."""
        assert schumann_bpm_anchor(1, 4) == pytest.approx(117.45, abs=0.01)

    def test_bpm_anchor_defaults(self) -> None:
        """Defaults are ``mode=1``, ``subharmonic_divisor=4``."""
        assert schumann_bpm_anchor() == schumann_bpm_anchor(1, 4)

    @pytest.mark.parametrize("divisor", [1, 2, 4, 8, 16])
    def test_bpm_anchor_divisor_scaling(self, divisor: int) -> None:
        """BPM scales as ``mode_hz × 60 ÷ divisor``; halving doubles effect."""
        bpm = schumann_bpm_anchor(1, divisor)  # type: ignore[arg-type]
        assert bpm == pytest.approx(7.83 * 60 / divisor, abs=1e-6)


# ===========================================================================
# Rule 3 — 432 / 440 tuning arithmetic
# ===========================================================================


class TestTuningArithmetic:
    """Tests for :func:`midi_to_hz`, :func:`hz_to_midi`, :func:`tuning_difference_hz`."""

    def test_a4_at_440_is_440(self) -> None:
        assert midi_to_hz(69, 440.0) == pytest.approx(440.0, abs=1e-9)

    def test_a4_at_432_is_432(self) -> None:
        assert midi_to_hz(69, 432.0) == pytest.approx(432.0, abs=1e-9)

    def test_a3_at_440_is_220(self) -> None:
        """One octave below A4 at 440 Hz reference."""
        assert midi_to_hz(57, 440.0) == pytest.approx(220.0, abs=1e-9)

    def test_a5_at_440_is_880(self) -> None:
        """One octave above A4 at 440 Hz reference."""
        assert midi_to_hz(81, 440.0) == pytest.approx(880.0, abs=1e-9)

    def test_hz_to_midi_inverse_of_midi_to_hz(self) -> None:
        """Roundtrip property: ``hz_to_midi(midi_to_hz(n)) == n`` across MIDI range."""
        for midi in range(21, 109):  # A0 (21) through C8 (108)
            hz = midi_to_hz(float(midi), 440.0)
            back = hz_to_midi(hz, 440.0)
            assert back == pytest.approx(float(midi), abs=1e-9)

    def test_fractional_midi_for_microtuning(self) -> None:
        """Half-semitone MIDI (69.5) is 50 cents above A4."""
        hz = midi_to_hz(69.5, 440.0)
        expected = 440.0 * math.pow(2.0, 0.5 / 12.0)
        assert hz == pytest.approx(expected, abs=1e-9)

    def test_hz_to_midi_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="frequency_hz must be positive"):
            hz_to_midi(0.0)

    def test_hz_to_midi_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="frequency_hz must be positive"):
            hz_to_midi(-100.0)

    def test_tuning_difference_positive(self) -> None:
        assert tuning_difference_hz(440.0, 432.0) == 8.0

    def test_tuning_difference_negative(self) -> None:
        assert tuning_difference_hz(432.0, 440.0) == -8.0

    def test_tuning_difference_same_is_zero(self) -> None:
        assert tuning_difference_hz(440.0, 440.0) == 0.0


# ===========================================================================
# Rule 4 — Regional mains hum
# ===========================================================================


class TestMainsHum:
    """Tests for :func:`mains_hum_profile` and its :class:`RegionalNoiseFloor`."""

    def test_grid_hz_canonical_table(self) -> None:
        assert GRID_HZ == {
            "UK": 50.0,
            "JP_TOKYO": 50.0,
            "US": 60.0,
            "JP_OSAKA": 60.0,
        }

    @pytest.mark.parametrize(
        "region, expected_fundamental",
        [("UK", 50.0), ("JP_TOKYO", 50.0), ("US", 60.0), ("JP_OSAKA", 60.0)],
    )
    def test_fundamentals_per_region(self, region: str, expected_fundamental: float) -> None:
        floor = mains_hum_profile(region)  # type: ignore[arg-type]
        assert floor.fundamental_hz == expected_fundamental

    def test_uk_first_5_harmonics(self) -> None:
        """UK 50 Hz grid: first 5 harmonics are 50, 100, 150, 200, 250 Hz."""
        floor = mains_hum_profile("UK", n_harmonics=5)
        assert [h.frequency_hz for h in floor.harmonics] == [
            50.0,
            100.0,
            150.0,
            200.0,
            250.0,
        ]

    def test_harmonic_indices_are_1_based(self) -> None:
        floor = mains_hum_profile("US", n_harmonics=3)
        assert [h.index for h in floor.harmonics] == [1, 2, 3]

    def test_harmonic_contains_typed_entries(self) -> None:
        floor = mains_hum_profile("UK", n_harmonics=2)
        assert all(isinstance(h, MainsHarmonic) for h in floor.harmonics)

    def test_50hz_tonal_centre_is_g1(self) -> None:
        """50 Hz → G1 (~35 cents sharp), per the spoke's G-centred noise floor."""
        floor = mains_hum_profile("UK")
        assert floor.tonal_centre == "G1"
        assert floor.harmonics[0].nearest_note == "G1"
        assert floor.harmonics[0].cents_deviation == pytest.approx(35.0, abs=1.0)

    def test_60hz_tonal_centre_is_b1(self) -> None:
        """60 Hz → B1 (~-49 cents).

        60 Hz sits near-equidistant between A♯1 (50.7 cents below) and B1
        (49.4 cents below). The implementation's ``round()`` resolves to
        B1 by the ~1.3 cent advantage. If the :file:`MAINS_HUM_REGIONAL.md`
        spoke's §5 Examples explicitly records A♯1, this assertion must
        flip and the rounding policy in :func:`_hz_to_note_and_cents`
        must change accordingly — flag for DECISIONS review.
        """
        floor = mains_hum_profile("US")
        assert floor.tonal_centre == "B1"
        assert floor.harmonics[0].nearest_note == "B1"
        assert floor.harmonics[0].cents_deviation == pytest.approx(-49.0, abs=1.0)

    def test_tokyo_osaka_produce_different_centres(self) -> None:
        """Tokyo (50 Hz) and Osaka (60 Hz) have distinct tonal centres."""
        tokyo = mains_hum_profile("JP_TOKYO")
        osaka = mains_hum_profile("JP_OSAKA")
        assert tokyo.tonal_centre != osaka.tonal_centre
        assert tokyo.fundamental_hz == 50.0
        assert osaka.fundamental_hz == 60.0

    @pytest.mark.parametrize("n", [1, 3, 5, 10])
    def test_n_harmonics_respected(self, n: int) -> None:
        floor = mains_hum_profile("UK", n_harmonics=n)
        assert len(floor.harmonics) == n

    def test_zero_n_harmonics_raises(self) -> None:
        with pytest.raises(ValueError, match="n_harmonics must be >= 1"):
            mains_hum_profile("UK", n_harmonics=0)

    def test_negative_n_harmonics_raises(self) -> None:
        with pytest.raises(ValueError, match="n_harmonics must be >= 1"):
            mains_hum_profile("UK", n_harmonics=-1)

    def test_region_field_preserved_in_output(self) -> None:
        floor = mains_hum_profile("JP_OSAKA")
        assert floor.region == "JP_OSAKA"
        assert isinstance(floor, RegionalNoiseFloor)

    def test_tonal_centre_matches_first_harmonic_note(self) -> None:
        """``tonal_centre`` is defined as the nearest note of ``harmonics[0]``."""
        for region in ("UK", "JP_TOKYO", "US", "JP_OSAKA"):
            floor = mains_hum_profile(region)
            assert floor.tonal_centre == floor.harmonics[0].nearest_note


# ===========================================================================
# Rule 5 — Solfeggio (AESTHETIC / NON-PHYSICAL)
# ===========================================================================


class TestSolfeggio:
    """Tests for :func:`solfeggio_cutoff_seed` — aesthetic project convention."""

    def test_solfeggio_hz_table_has_all_9_labels(self) -> None:
        expected_labels = {
            "foundation",
            "regeneration",
            "liberation",
            "transformation",
            "harmonic",
            "connection",
            "expression",
            "perception",
            "crown",
        }
        assert set(SOLFEGGIO_HZ.keys()) == expected_labels

    def test_solfeggio_hz_canonical_values(self) -> None:
        assert SOLFEGGIO_HZ["foundation"] == 174.0
        assert SOLFEGGIO_HZ["liberation"] == 396.0
        assert SOLFEGGIO_HZ["harmonic"] == 528.0
        assert SOLFEGGIO_HZ["expression"] == 741.0
        assert SOLFEGGIO_HZ["perception"] == 852.0
        assert SOLFEGGIO_HZ["crown"] == 963.0

    def test_regional_seed_assignments_exactly_4_regions(self) -> None:
        """Only 4 of 6 profiles carry a Solfeggio seed by editorial choice."""
        assert REGIONAL_SOLFEGGIO_SEED == {
            "DETROIT_UR": 396.0,
            "JAPAN_IDM": 528.0,
            "UK_IDM": 741.0,
            "DREXCIYA": 852.0,
        }

    @pytest.mark.parametrize(
        "profile, expected_hz",
        [
            ("DETROIT_UR", 396.0),
            ("JAPAN_IDM", 528.0),
            ("UK_IDM", 741.0),
            ("DREXCIYA", 852.0),
        ],
    )
    def test_seeded_profiles_return_canonical_hz(self, profile: str, expected_hz: float) -> None:
        assert solfeggio_cutoff_seed(profile) == expected_hz  # type: ignore[arg-type]

    @pytest.mark.parametrize("profile", ["DETROIT_FIRST_WAVE", "UK_BRAINDANCE"])
    def test_unseeded_profiles_return_none(self, profile: str) -> None:
        """DETROIT_FIRST_WAVE and UK_BRAINDANCE are unassigned per spoke editorial."""
        assert solfeggio_cutoff_seed(profile) is None  # type: ignore[arg-type]

    def test_zero_offset_returns_canonical_unchanged(self) -> None:
        assert solfeggio_cutoff_seed("UK_IDM", offset_cents=0.0) == 741.0

    def test_positive_offset_raises_frequency(self) -> None:
        base = solfeggio_cutoff_seed("UK_IDM", offset_cents=0.0)
        shifted = solfeggio_cutoff_seed("UK_IDM", offset_cents=100.0)
        assert base is not None and shifted is not None
        assert shifted > base
        # 100 cents = one semitone = factor 2^(1/12)
        assert shifted == pytest.approx(base * math.pow(2.0, 1.0 / 12.0), abs=1e-9)

    def test_negative_offset_lowers_frequency(self) -> None:
        base = solfeggio_cutoff_seed("DREXCIYA", offset_cents=0.0)
        shifted = solfeggio_cutoff_seed("DREXCIYA", offset_cents=-100.0)
        assert base is not None and shifted is not None
        assert shifted < base

    def test_octave_offset_doubles_frequency(self) -> None:
        """+1200 cents = one octave = exact factor of 2."""
        base = solfeggio_cutoff_seed("JAPAN_IDM", offset_cents=0.0)
        octaved = solfeggio_cutoff_seed("JAPAN_IDM", offset_cents=1200.0)
        assert base is not None and octaved is not None
        assert octaved == pytest.approx(base * 2.0, abs=1e-9)

    def test_none_result_not_affected_by_offset(self) -> None:
        """Unseeded profiles return None regardless of ``offset_cents`` value."""
        assert solfeggio_cutoff_seed("DETROIT_FIRST_WAVE", offset_cents=0.0) is None
        assert solfeggio_cutoff_seed("DETROIT_FIRST_WAVE", offset_cents=50.0) is None
        assert solfeggio_cutoff_seed("UK_BRAINDANCE", offset_cents=-200.0) is None
