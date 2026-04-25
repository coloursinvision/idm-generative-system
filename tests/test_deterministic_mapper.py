"""Tests for engine.ml.deterministic_mapper.

Covers all 6 regional profiles via synthetic RegionalProfile injection
(``profile=`` parameter), input validation, source-tag provenance,
dual-stack mains emission (D-S5-01), Solfeggio seed presence/absence,
Schumann BPM anchor, sub-bass emission, and effects filtering.

No spoke filesystem access required — all profiles are constructed
in-memory.
"""

from __future__ import annotations

import pytest
from engine.ml.deterministic_mapper import (
    DeterministicMapping,
    ResonantPoint,
    deterministic_map,
)
from engine.ml.regional_profiles import (
    HarmonicContentSpec,
    NoiseSpec,
    RegionalProfile,
    ReverbSpec,
    SaturationSpec,
    SwingSpec,
)
from engine.ml.resonance_rules import (
    midi_to_hz,
    schumann_bpm_anchor,
)

# ---------------------------------------------------------------------------
# Fixtures — synthetic profiles
# ---------------------------------------------------------------------------

_SWING_DEFAULT = SwingSpec(
    bpm_range=(120, 150),
    swing_type="deterministic",
    gate_behavior="tight",
)

_SAT_DEFAULT = SaturationSpec(saturation="moderate")
_HARM_DEFAULT = HarmonicContentSpec(primary_synthesis="fm")
_REVERB_DEFAULT = ReverbSpec(profile="dry_short", bandwidth=8000)

_NOISE_50HZ = NoiseSpec(sub_bass_hz=50, noise_floor_hz=50)
_NOISE_60HZ = NoiseSpec(sub_bass_hz=60, noise_floor_hz=60)


def _make_profile(
    region: str,
    *,
    sub_region: str | None = None,
    noise: NoiseSpec | None = _NOISE_50HZ,
    reverb: ReverbSpec | None = _REVERB_DEFAULT,
) -> RegionalProfile:
    """Build a minimal synthetic RegionalProfile for testing."""
    return RegionalProfile(
        region=region,  # type: ignore[arg-type]
        sub_region=sub_region,  # type: ignore[arg-type]
        swing=_SWING_DEFAULT,
        saturation=_SAT_DEFAULT,
        harmonic=_HARM_DEFAULT,
        reverb=reverb,
        noise=noise,
    )


# Pre-built profiles for parametrized tests.
PROFILES: dict[str, RegionalProfile] = {
    "UK_IDM": _make_profile("UK_IDM"),
    "UK_BRAINDANCE": _make_profile("UK_BRAINDANCE", noise=None),
    "DETROIT_FIRST_WAVE": _make_profile(
        "DETROIT_FIRST_WAVE", noise=_NOISE_60HZ,
    ),
    "DETROIT_UR": _make_profile("DETROIT_UR", noise=_NOISE_60HZ),
    "DREXCIYA": _make_profile("DREXCIYA", noise=_NOISE_60HZ),
    "JAPAN_IDM": _make_profile("JAPAN_IDM"),
    "JAPAN_IDM_OSAKA": _make_profile(
        "JAPAN_IDM", sub_region="OSAKA", noise=_NOISE_60HZ,
    ),
}

# Standard test parameters.
_BPM = 128.0
_PITCH_MIDI = 69.0  # A4
_EFFECTS: list[str] = []


def _source_tags(mapping: DeterministicMapping) -> list[str]:
    """Extract source tags from a mapping's resonant points."""
    return [p.source for p in mapping.resonant_points]


def _sources_set(mapping: DeterministicMapping) -> set[str]:
    """Extract unique source tags as a set."""
    return {p.source for p in mapping.resonant_points}


def _points_by_source(
    mapping: DeterministicMapping,
    prefix: str,
) -> list[ResonantPoint]:
    """Filter resonant points whose source starts with prefix."""
    return [
        p for p in mapping.resonant_points
        if p.source.startswith(prefix)
    ]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Verify ValueError on invalid inputs."""

    def test_negative_bpm_raises(self) -> None:
        profile = PROFILES["UK_IDM"]
        with pytest.raises(ValueError, match="bpm must be positive"):
            deterministic_map(
                -1.0, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
                profile=profile,
            )

    def test_zero_bpm_raises(self) -> None:
        profile = PROFILES["UK_IDM"]
        with pytest.raises(ValueError, match="bpm must be positive"):
            deterministic_map(
                0.0, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
                profile=profile,
            )

    def test_pitch_midi_too_high_raises(self) -> None:
        profile = PROFILES["UK_IDM"]
        with pytest.raises(ValueError, match="pitch_midi"):
            deterministic_map(
                _BPM, 128.0, None, "UK_IDM", _EFFECTS,
                profile=profile,
            )

    def test_pitch_midi_negative_raises(self) -> None:
        profile = PROFILES["UK_IDM"]
        with pytest.raises(ValueError, match="pitch_midi"):
            deterministic_map(
                _BPM, -1.0, None, "UK_IDM", _EFFECTS,
                profile=profile,
            )

    def test_pitch_midi_boundary_zero_ok(self) -> None:
        profile = PROFILES["UK_IDM"]
        result = deterministic_map(
            _BPM, 0.0, None, "UK_IDM", _EFFECTS,
            profile=profile,
        )
        assert isinstance(result, DeterministicMapping)

    def test_pitch_midi_boundary_127_ok(self) -> None:
        profile = PROFILES["UK_IDM"]
        result = deterministic_map(
            _BPM, 127.0, None, "UK_IDM", _EFFECTS,
            profile=profile,
        )
        assert isinstance(result, DeterministicMapping)


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------


class TestReturnStructure:
    """Verify output shape and types."""

    def test_returns_deterministic_mapping(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert isinstance(result, DeterministicMapping)

    def test_tuning_hz_is_440(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert result.tuning_hz == 440.0

    def test_resonant_points_is_tuple(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert isinstance(result.resonant_points, tuple)

    def test_all_points_are_resonant_point(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert all(
            isinstance(p, ResonantPoint) for p in result.resonant_points
        )

    def test_all_points_have_positive_frequency(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert all(p.frequency_hz > 0 for p in result.resonant_points)

    def test_all_points_have_nonempty_source(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert all(p.source for p in result.resonant_points)


# ---------------------------------------------------------------------------
# Step 2 — pitch_ref
# ---------------------------------------------------------------------------


class TestPitchRef:
    """Step 2: pitch_ref resonant point from pitch_midi + tuning."""

    def test_pitch_ref_present(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "pitch_ref" in _sources_set(result)

    def test_pitch_ref_frequency_matches_midi_to_hz(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        pitch_pt = _points_by_source(result, "pitch_ref")[0]
        expected = midi_to_hz(_PITCH_MIDI, 440.0)
        assert pitch_pt.frequency_hz == pytest.approx(expected)

    def test_pitch_ref_a4_is_440(self) -> None:
        result = deterministic_map(
            _BPM, 69.0, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        pitch_pt = _points_by_source(result, "pitch_ref")[0]
        assert pitch_pt.frequency_hz == pytest.approx(440.0)
        assert pitch_pt.nearest_note == "A4"

    def test_pitch_ref_is_first_point(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert result.resonant_points[0].source == "pitch_ref"

    def test_fractional_midi_accepted(self) -> None:
        result = deterministic_map(
            _BPM, 69.5, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        pitch_pt = _points_by_source(result, "pitch_ref")[0]
        expected = midi_to_hz(69.5, 440.0)
        assert pitch_pt.frequency_hz == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Step 3 — bpm_harmonic
# ---------------------------------------------------------------------------


class TestBpmHarmonic:
    """Step 3: audible harmonic from BPM."""

    def test_bpm_harmonic_present(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "bpm_harmonic" in _sources_set(result)

    def test_bpm_harmonic_frequency(self) -> None:
        result = deterministic_map(
            128.0, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        bpm_pt = _points_by_source(result, "bpm_harmonic")[0]
        # 128 BPM / 60 * 64 = 136.533...
        assert bpm_pt.frequency_hz == pytest.approx(136.533, rel=1e-3)

    def test_bpm_harmonic_is_second_point(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert result.resonant_points[1].source == "bpm_harmonic"


# ---------------------------------------------------------------------------
# Step 4 — mains stack (D-S5-01 dual-stack)
# ---------------------------------------------------------------------------


class TestMainsStackUK:
    """Step 4: UK regions get a single mains stack (50 Hz)."""

    @pytest.mark.parametrize("region", ["UK_IDM", "UK_BRAINDANCE"])
    def test_uk_single_stack_no_ref_tags(self, region: str) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        ref_pts = _points_by_source(result, "mains_ref_")
        assert len(ref_pts) == 0

    @pytest.mark.parametrize("region", ["UK_IDM", "UK_BRAINDANCE"])
    def test_uk_fundamental_is_50hz(self, region: str) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        fund = _points_by_source(result, "mains_fundamental")[0]
        assert fund.frequency_hz == pytest.approx(50.0)

    def test_uk_5_mains_points(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        mains_pts = _points_by_source(result, "mains_")
        assert len(mains_pts) == 5

    def test_uk_harmonic_frequencies(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        mains_pts = _points_by_source(result, "mains_")
        freqs = [p.frequency_hz for p in mains_pts]
        expected = [50.0, 100.0, 150.0, 200.0, 250.0]
        for actual, exp in zip(freqs, expected, strict=False):
            assert actual == pytest.approx(exp)


class TestMainsStackNonUK:
    """Step 4: Non-UK regions get dual stack (UK ref + regional)."""

    @pytest.mark.parametrize(
        ("region", "expected_regional_hz"),
        [
            ("DETROIT_FIRST_WAVE", 60.0),
            ("DETROIT_UR", 60.0),
            ("DREXCIYA", 60.0),
        ],
    )
    def test_detroit_dual_stack_present(
        self,
        region: str,
        expected_regional_hz: float,
    ) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        ref_pts = _points_by_source(result, "mains_ref_")
        regional_pts = _points_by_source(result, "mains_fundamental")
        assert len(ref_pts) == 5
        assert len(regional_pts) == 1
        assert regional_pts[0].frequency_hz == pytest.approx(
            expected_regional_hz,
        )

    def test_detroit_ref_stack_is_50hz(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "DETROIT_UR", _EFFECTS,
            profile=PROFILES["DETROIT_UR"],
        )
        ref_fund = [
            p for p in result.resonant_points
            if p.source == "mains_ref_fundamental"
        ]
        assert len(ref_fund) == 1
        assert ref_fund[0].frequency_hz == pytest.approx(50.0)

    def test_detroit_total_mains_points_is_10(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "DETROIT_UR", _EFFECTS,
            profile=PROFILES["DETROIT_UR"],
        )
        all_mains = [
            p for p in result.resonant_points
            if p.source.startswith("mains_")
        ]
        assert len(all_mains) == 10


class TestMainsStackJapan:
    """Step 4: Japan Tokyo (50 Hz) and Osaka (60 Hz) dual stacks."""

    def test_japan_tokyo_regional_is_50hz(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "JAPAN_IDM", _EFFECTS,
            profile=PROFILES["JAPAN_IDM"],
        )
        regional_fund = [
            p for p in result.resonant_points
            if p.source == "mains_fundamental"
        ]
        assert regional_fund[0].frequency_hz == pytest.approx(50.0)

    def test_japan_osaka_regional_is_60hz(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "JAPAN_IDM", _EFFECTS,
            sub_region="OSAKA",
            profile=PROFILES["JAPAN_IDM_OSAKA"],
        )
        regional_fund = [
            p for p in result.resonant_points
            if p.source == "mains_fundamental"
        ]
        assert regional_fund[0].frequency_hz == pytest.approx(60.0)

    def test_japan_has_uk_ref_stack(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "JAPAN_IDM", _EFFECTS,
            profile=PROFILES["JAPAN_IDM"],
        )
        ref_pts = _points_by_source(result, "mains_ref_")
        assert len(ref_pts) == 5


# ---------------------------------------------------------------------------
# Step 5 — Solfeggio seed
# ---------------------------------------------------------------------------


class TestSolfeggioSeed:
    """Step 5: Solfeggio aesthetic seed presence by region."""

    @pytest.mark.parametrize(
        ("region", "expected_hz"),
        [
            ("DETROIT_UR", 396.0),
            ("JAPAN_IDM", 528.0),
            ("UK_IDM", 741.0),
            ("DREXCIYA", 852.0),
        ],
    )
    def test_solfeggio_seed_present(
        self,
        region: str,
        expected_hz: float,
    ) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        seed_pts = _points_by_source(result, "solfeggio_seed")
        assert len(seed_pts) == 1
        assert seed_pts[0].frequency_hz == pytest.approx(expected_hz)

    @pytest.mark.parametrize(
        "region",
        ["DETROIT_FIRST_WAVE", "UK_BRAINDANCE"],
    )
    def test_solfeggio_seed_absent(self, region: str) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        seed_pts = _points_by_source(result, "solfeggio_seed")
        assert len(seed_pts) == 0


# ---------------------------------------------------------------------------
# Step 6 — Schumann BPM anchor
# ---------------------------------------------------------------------------


class TestSchumannAnchor:
    """Step 6: Schumann mode-1 anchor emitted when BPM is within tolerance."""

    def test_anchor_present_at_117bpm(self) -> None:
        anchor = schumann_bpm_anchor(1, 4)  # ~117.45
        result = deterministic_map(
            anchor, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "schumann_bpm_anchor" in _sources_set(result)

    def test_anchor_present_within_tolerance(self) -> None:
        anchor = schumann_bpm_anchor(1, 4)
        result = deterministic_map(
            anchor + 1.5, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "schumann_bpm_anchor" in _sources_set(result)

    def test_anchor_absent_outside_tolerance(self) -> None:
        anchor = schumann_bpm_anchor(1, 4)
        result = deterministic_map(
            anchor + 5.0, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "schumann_bpm_anchor" not in _sources_set(result)

    def test_anchor_absent_at_128bpm(self) -> None:
        result = deterministic_map(
            128.0, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "schumann_bpm_anchor" not in _sources_set(result)

    def test_anchor_frequency_is_schumann_mode1(self) -> None:
        anchor = schumann_bpm_anchor(1, 4)
        result = deterministic_map(
            anchor, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        sch_pts = _points_by_source(result, "schumann_bpm_anchor")
        assert sch_pts[0].frequency_hz == pytest.approx(7.83)


# ---------------------------------------------------------------------------
# Step 6b — sub-bass
# ---------------------------------------------------------------------------


class TestSubBass:
    """Sub-bass resonant point from profile noise spec."""

    def test_sub_bass_present_when_noise_spec_exists(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert "sub_bass" in _sources_set(result)

    def test_sub_bass_frequency_matches_profile(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        sub_pts = _points_by_source(result, "sub_bass")
        assert sub_pts[0].frequency_hz == pytest.approx(50.0)

    def test_sub_bass_absent_when_no_noise_spec(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_BRAINDANCE", _EFFECTS,
            profile=PROFILES["UK_BRAINDANCE"],
        )
        assert "sub_bass" not in _sources_set(result)

    def test_detroit_sub_bass_is_60hz(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "DETROIT_UR", _EFFECTS,
            profile=PROFILES["DETROIT_UR"],
        )
        sub_pts = _points_by_source(result, "sub_bass")
        assert sub_pts[0].frequency_hz == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Step 7 — effects filtering
# ---------------------------------------------------------------------------


class TestEffectsFiltering:
    """Step 7: notch_mains removes all mains-derived points."""

    def test_notch_mains_removes_all_mains(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "DETROIT_UR",
            ["notch_mains"],
            profile=PROFILES["DETROIT_UR"],
        )
        mains_pts = [
            p for p in result.resonant_points
            if p.source.startswith("mains_")
        ]
        assert len(mains_pts) == 0

    def test_notch_mains_preserves_non_mains(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "DETROIT_UR",
            ["notch_mains"],
            profile=PROFILES["DETROIT_UR"],
        )
        assert "pitch_ref" in _sources_set(result)
        assert "bpm_harmonic" in _sources_set(result)
        assert "solfeggio_seed" in _sources_set(result)

    def test_empty_effects_no_filtering(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        mains_pts = _points_by_source(result, "mains_")
        assert len(mains_pts) == 5

    def test_unknown_effect_passes_through(self) -> None:
        result_with = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM",
            ["reverb", "delay", "compression"],
            profile=PROFILES["UK_IDM"],
        )
        result_without = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert len(result_with.resonant_points) == len(
            result_without.resonant_points,
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same inputs produce identical outputs."""

    def test_identical_calls_identical_result(self) -> None:
        args = (_BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS)
        kwargs = {"profile": PROFILES["UK_IDM"]}
        r1 = deterministic_map(*args, **kwargs)
        r2 = deterministic_map(*args, **kwargs)
        assert r1 == r2

    def test_ordering_stable(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        tags = _source_tags(result)
        assert tags[0] == "pitch_ref"
        assert tags[1] == "bpm_harmonic"
        assert tags[2] == "mains_fundamental"


# ---------------------------------------------------------------------------
# Swing pass-through
# ---------------------------------------------------------------------------


class TestSwingPassThrough:
    """Swing parameter does not affect the deterministic mapping."""

    @pytest.mark.parametrize(
        "swing",
        [None, 0.0, 0.5, 1.0, "variable"],
    )
    def test_swing_values_produce_same_mapping(
        self,
        swing: float | str | None,
    ) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, swing, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        baseline = deterministic_map(
            _BPM, _PITCH_MIDI, None, "UK_IDM", _EFFECTS,
            profile=PROFILES["UK_IDM"],
        )
        assert result == baseline


# ---------------------------------------------------------------------------
# All 6 regions — smoke tests
# ---------------------------------------------------------------------------


class TestAllRegionsSmoke:
    """Every region produces a valid mapping without errors."""

    @pytest.mark.parametrize(
        "region",
        [
            "UK_IDM",
            "UK_BRAINDANCE",
            "DETROIT_FIRST_WAVE",
            "DETROIT_UR",
            "DREXCIYA",
            "JAPAN_IDM",
        ],
    )
    def test_region_produces_valid_mapping(self, region: str) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, region, _EFFECTS,
            profile=PROFILES[region],
        )
        assert isinstance(result, DeterministicMapping)
        assert result.tuning_hz == 440.0
        assert len(result.resonant_points) >= 3
        assert "pitch_ref" in _sources_set(result)
        assert "bpm_harmonic" in _sources_set(result)

    def test_japan_osaka_produces_valid_mapping(self) -> None:
        result = deterministic_map(
            _BPM, _PITCH_MIDI, None, "JAPAN_IDM", _EFFECTS,
            sub_region="OSAKA",
            profile=PROFILES["JAPAN_IDM_OSAKA"],
        )
        assert isinstance(result, DeterministicMapping)
        assert "mains_fundamental" in _sources_set(result)
