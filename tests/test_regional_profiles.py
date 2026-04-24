"""Unit tests for engine.ml.regional_profiles — profile spoke loader.

Covers the full parse pipeline end-to-end:

    markdown file
      → python-frontmatter (YAML header + body)
      → regex-extract ``## 5. DSP specification`` fenced block
      → ``yaml.safe_load`` (raw dict)
      → Pydantic v2 ``_DSPSpecModel`` (validation, ``extra="forbid"``)
      → composed frozen ``RegionalProfile`` dataclass

Strategy
--------
All tests run against **synthetic spoke fixtures** (YAML strings matching
the bootstrap §7.1 embedded inputs, written to ``tmp_path``). This keeps
the suite CI-friendly and independent of the Obsidian vault at
``02-Knowledge/supporting/profiles/``.

A separate integration test (marked ``integration``, skipped when the
vault is unreachable) exercises the real on-disk spokes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.ml.regional_profiles import (
    HarmonicContentSpec,
    NoiseSpec,
    RegionalProfile,
    ReverbSpec,
    SaturationSpec,
    SpokeParseError,
    SwingSpec,
    all_profiles,
    load_profile,
)

# ===========================================================================
# Synthetic spoke YAML bodies — verbatim from bootstrap §7.1 embedded input
# ===========================================================================


DETROIT_FIRST_WAVE_YAML = """\
bpm_range: [118, 132]
swing_type: "mpc60_nonlinear"
swing_amount: 0.54
gate_behavior: "standard_retrigger"
sub_bass_hz: 60
reverb_profile: "dry_short"
reverb_bandwidth: 16000
saturation: "moderate"
harmonic_content: "fm_inharmonic"
noise_floor_hz: 60
noise_floor_db: -75
stereo_width: "narrow"
primary_synthesis: "fm"
chord_voicing: "minor_9th_parallel"
filter_type: null
"""

DETROIT_UR_YAML = """\
bpm_range: [128, 145]
swing_type: "deterministic"
swing_amount: 0.50
gate_behavior: "no_variation"
sub_bass_hz: 60
reverb_profile: "dry_to_moderate"
saturation: "high"
saturation_curve: "asymmetric_tanh"
dynamic_range: "compressed"
harmonic_content: "909_overdrive"
noise_floor_hz: 60
noise_floor_db: -75
stereo_width: "narrow_to_moderate"
primary_synthesis: "analog_subtractive"
vocal_presence: false
"""

DREXCIYA_YAML = """\
bpm_range: [120, 140]
swing_type: "minimal_electro"
swing_amount: 0.50
gate_behavior: "sharp_808"
sub_bass_hz: 35
sub_bass_level: "dominant"
mid_range_cut: true
reverb_profile: "long_diffuse"
reverb_decay: 3000
delay_modulation: true
saturation: "low"
harmonic_content: "808_analog + cz_phase_distortion"
noise_floor_hz: 60
stereo_width: "wide"
spatial_decorrelation: true
primary_synthesis: "analog_drum_machine + phase_distortion"
"""

UK_IDM_YAML = """\
bpm_range: [110, 145]
swing_type: "euclidean_asymmetric"
swing_amount: "variable"
gate_behavior: "complex_envelope"
sub_bass_hz: 50
reverb_profile: "deep_lush"
reverb_bandwidth: 11000
reverb_diffusion: 0.85
reverb_sample_rate: 31250
saturation: "moderate_desk"
harmonic_content: "phase_distortion + fm + wavetable"
noise_floor_hz: 50
noise_floor_db: -75
stereo_width: "wide"
timing_resolution: 192
primary_synthesis: "mixed"
vinyl_noise: true
"""

UK_BRAINDANCE_YAML = """\
bpm_range: [140, 200]
swing_type: "inverse"
swing_offset_ms: [-4, -8]
gate_behavior: "micro_retrigger"
retrigger_range_ms: [10, 35]
pitch_ramp_semitones: 12
time_stretch_grain_hz: [40, 100]
saturation: "low_to_moderate"
primary_synthesis: "sampler_mangling"
"""

JAPAN_IDM_YAML = """\
bpm_range: [120, 140]
swing_type: "micro_jitter"
swing_amount: 0.51
gate_behavior: "precise_envelope"
sub_bass_hz: 50
sub_bass_level: "controlled"
mid_range_boost_hz: 3500
reverb_profile: "clean_deep_wide"
reverb_bandwidth: 18000
saturation: "soft_knee"
saturation_threshold: "limiter"
harmonic_content: "fm_pcm_layered"
noise_floor_hz: 50
noise_floor_db: -85
stereo_width: "wide_surgical"
filter_type: "18db_sallen_key"
filter_key_tracking: 1.0
velocity_curves: "nonlinear"
primary_synthesis: "fm_pcm_hybrid"
"""

_SYNTHETIC_SPOKES: dict[str, str] = {
    "DETROIT_FIRST_WAVE_PROFILE.md": DETROIT_FIRST_WAVE_YAML,
    "DETROIT_UR_PROFILE.md": DETROIT_UR_YAML,
    "DREXCIYA_PROFILE.md": DREXCIYA_YAML,
    "UK_IDM_PROFILE.md": UK_IDM_YAML,
    "UK_BRAINDANCE_PROFILE.md": UK_BRAINDANCE_YAML,
    "JAPAN_IDM_PROFILE.md": JAPAN_IDM_YAML,
}


# ===========================================================================
# Fixture helpers
# ===========================================================================


def _build_spoke_markdown(yaml_body: str) -> str:
    """Wrap a DSP spec YAML body in a full spoke markdown document.

    The surrounding scaffolding — YAML frontmatter, introductory sections,
    trailing sections — mirrors the real-vault spoke layout so the parser
    exercises the same regex path it does in production.
    """
    return (
        "---\n"
        "document_type: regional_profile\n"
        'status: "complete"\n'
        'version: "1.0"\n'
        "---\n"
        "\n"
        "# Synthetic spoke (test fixture)\n"
        "\n"
        "## 1. Overview\n"
        "\n"
        "Placeholder.\n"
        "\n"
        "## 5. DSP specification\n"
        "\n"
        "```yaml\n"
        f"{yaml_body}"
        "```\n"
        "\n"
        "## 6. References\n"
        "\n"
        "None.\n"
    )


@pytest.fixture
def synthetic_profiles_dir(tmp_path: Path) -> Path:
    """Write all 6 synthetic spoke files to ``tmp_path`` and return it.

    The returned directory is unique per test (pytest ``tmp_path`` is
    function-scoped), so ``load_profile``'s ``@lru_cache`` key
    ``(region, sub_region, profiles_dir)`` never collides between tests.
    """
    for filename, yaml_body in _SYNTHETIC_SPOKES.items():
        (tmp_path / filename).write_text(_build_spoke_markdown(yaml_body))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_load_profile_cache() -> None:
    """Clear the ``load_profile`` lru_cache before each test.

    Not strictly required given ``tmp_path`` uniqueness, but cheap
    insurance against cross-test cache pollution if a test passes a
    non-unique path (e.g. env-var integration test).
    """
    load_profile.cache_clear()


# ===========================================================================
# Parsing — all 6 profiles produce correct RegionalProfile values
# ===========================================================================


class TestProfileParsing:
    """Each of the 6 spokes parses into the expected RegionalProfile."""

    def test_detroit_first_wave(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile("DETROIT_FIRST_WAVE", profiles_dir=synthetic_profiles_dir)
        assert isinstance(p, RegionalProfile)
        assert p.region == "DETROIT_FIRST_WAVE"
        assert p.sub_region is None
        # Swing
        assert p.swing.bpm_range == (118, 132)
        assert p.swing.swing_type == "mpc60_nonlinear"
        assert p.swing.swing_amount == 0.54
        assert p.swing.gate_behavior == "standard_retrigger"
        # Reverb
        assert p.reverb is not None
        assert p.reverb.profile == "dry_short"
        assert p.reverb.bandwidth == 16000
        # Saturation
        assert p.saturation.saturation == "moderate"
        # Harmonic
        assert p.harmonic.primary_synthesis == "fm"
        assert p.harmonic.harmonic_content == "fm_inharmonic"
        assert p.harmonic.chord_voicing == "minor_9th_parallel"
        # Noise
        assert p.noise is not None
        assert p.noise.sub_bass_hz == 60
        assert p.noise.noise_floor_hz == 60
        assert p.noise.noise_floor_db == -75
        # Top-level
        assert p.stereo_width == "narrow"
        assert p.filter_type is None

    def test_detroit_ur(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile("DETROIT_UR", profiles_dir=synthetic_profiles_dir)
        assert p.swing.bpm_range == (128, 145)
        assert p.swing.swing_type == "deterministic"
        assert p.swing.swing_amount == 0.50
        assert p.saturation.saturation == "high"
        assert p.saturation.curve == "asymmetric_tanh"
        assert p.saturation.dynamic_range == "compressed"
        assert p.harmonic.primary_synthesis == "analog_subtractive"
        assert p.harmonic.harmonic_content == "909_overdrive"
        assert p.vocal_presence is False

    def test_drexciya(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile("DREXCIYA", profiles_dir=synthetic_profiles_dir)
        assert p.swing.bpm_range == (120, 140)
        assert p.noise is not None
        assert p.noise.sub_bass_hz == 35  # distinctive 35 Hz sub
        assert p.noise.sub_bass_level == "dominant"
        assert p.noise.mid_range_cut is True
        assert p.reverb is not None
        assert p.reverb.profile == "long_diffuse"
        assert p.reverb.decay == 3000
        assert p.spatial_decorrelation is True
        assert p.delay_modulation is True

    def test_uk_idm(self, synthetic_profiles_dir: Path) -> None:
        """UK_IDM's ``swing_amount`` is the literal string ``"variable"``."""
        p = load_profile("UK_IDM", profiles_dir=synthetic_profiles_dir)
        assert p.swing.swing_amount == "variable"
        assert p.swing.timing_resolution == 192
        assert p.reverb is not None
        assert p.reverb.bandwidth == 11000
        assert p.reverb.diffusion == 0.85
        assert p.reverb.sample_rate == 31250
        assert p.noise is not None
        assert p.noise.vinyl_noise is True

    def test_uk_braindance(self, synthetic_profiles_dir: Path) -> None:
        """UK_BRAINDANCE's sparse spec carries only swing/saturation/harmonic."""
        p = load_profile("UK_BRAINDANCE", profiles_dir=synthetic_profiles_dir)
        assert p.swing.bpm_range == (140, 200)
        assert p.swing.swing_type == "inverse"
        assert p.swing.swing_offset_ms == (-4, -8)
        assert p.swing.retrigger_range_ms == (10, 35)
        assert p.saturation.saturation == "low_to_moderate"
        assert p.harmonic.primary_synthesis == "sampler_mangling"
        assert p.harmonic.pitch_ramp_semitones == 12
        assert p.harmonic.time_stretch_grain_hz == (40, 100)

    def test_japan_idm_defaults_to_tokyo(self, synthetic_profiles_dir: Path) -> None:
        """``sub_region=None`` returns the Tokyo default (50 Hz)."""
        p = load_profile("JAPAN_IDM", profiles_dir=synthetic_profiles_dir)
        assert p.sub_region is None
        assert p.noise is not None
        assert p.noise.sub_bass_hz == 50
        assert p.noise.noise_floor_hz == 50
        assert p.noise.mid_range_boost_hz == 3500
        assert p.filter_type == "18db_sallen_key"
        assert p.filter_key_tracking == 1.0
        assert p.velocity_curves == "nonlinear"


# ===========================================================================
# Optional subgroups — None when the spoke has no fields for that group
# ===========================================================================


class TestOptionalSubgroups:
    """Sparse profiles produce ``None`` for reverb and noise subgroups."""

    def test_uk_braindance_has_no_reverb(self, synthetic_profiles_dir: Path) -> None:
        """UK_BRAINDANCE has zero reverb fields → ``reverb is None``."""
        p = load_profile("UK_BRAINDANCE", profiles_dir=synthetic_profiles_dir)
        assert p.reverb is None

    def test_uk_braindance_has_no_noise(self, synthetic_profiles_dir: Path) -> None:
        """UK_BRAINDANCE has no sub_bass_hz → ``noise is None``."""
        p = load_profile("UK_BRAINDANCE", profiles_dir=synthetic_profiles_dir)
        assert p.noise is None

    def test_uk_braindance_has_no_stereo_width(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile("UK_BRAINDANCE", profiles_dir=synthetic_profiles_dir)
        assert p.stereo_width is None

    def test_composed_types_preserved(self, synthetic_profiles_dir: Path) -> None:
        """Non-None subgroups are the right concrete types."""
        p = load_profile("DETROIT_FIRST_WAVE", profiles_dir=synthetic_profiles_dir)
        assert isinstance(p.swing, SwingSpec)
        assert isinstance(p.saturation, SaturationSpec)
        assert isinstance(p.harmonic, HarmonicContentSpec)
        assert isinstance(p.reverb, ReverbSpec)
        assert isinstance(p.noise, NoiseSpec)

    def test_all_profiles_have_required_subgroups(self, synthetic_profiles_dir: Path) -> None:
        """All 6 profiles carry swing/saturation/harmonic (the universal three)."""
        for region in _SYNTHETIC_SPOKES:
            region_code = region.removesuffix("_PROFILE.md")
            p = load_profile(region_code, profiles_dir=synthetic_profiles_dir)
            assert isinstance(p.swing, SwingSpec)
            assert isinstance(p.saturation, SaturationSpec)
            assert isinstance(p.harmonic, HarmonicContentSpec)


# ===========================================================================
# Japan Tokyo / Osaka parameter-level split
# ===========================================================================


class TestJapanTokyoOsaka:
    """Japan's 50 Hz (Tokyo default) vs 60 Hz (Osaka override)."""

    def test_tokyo_default_uses_50hz(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile(
            "JAPAN_IDM",
            sub_region="TOKYO",
            profiles_dir=synthetic_profiles_dir,
        )
        assert p.sub_region == "TOKYO"
        assert p.noise is not None
        assert p.noise.sub_bass_hz == 50
        assert p.noise.noise_floor_hz == 50

    def test_osaka_forces_60hz(self, synthetic_profiles_dir: Path) -> None:
        p = load_profile(
            "JAPAN_IDM",
            sub_region="OSAKA",
            profiles_dir=synthetic_profiles_dir,
        )
        assert p.sub_region == "OSAKA"
        assert p.noise is not None
        assert p.noise.sub_bass_hz == 60
        assert p.noise.noise_floor_hz == 60

    def test_osaka_preserves_non_mains_fields(self, synthetic_profiles_dir: Path) -> None:
        """Osaka override touches only sub_bass_hz + noise_floor_hz."""
        tokyo = load_profile(
            "JAPAN_IDM",
            sub_region="TOKYO",
            profiles_dir=synthetic_profiles_dir,
        )
        osaka = load_profile(
            "JAPAN_IDM",
            sub_region="OSAKA",
            profiles_dir=synthetic_profiles_dir,
        )
        # Everything except Noise's 50/60 Hz fields must match.
        assert tokyo.swing == osaka.swing
        assert tokyo.saturation == osaka.saturation
        assert tokyo.harmonic == osaka.harmonic
        assert tokyo.reverb == osaka.reverb
        assert tokyo.filter_type == osaka.filter_type
        assert tokyo.velocity_curves == osaka.velocity_curves
        # And Noise differs only on the two swapped fields.
        assert tokyo.noise is not None and osaka.noise is not None
        assert tokyo.noise.sub_bass_level == osaka.noise.sub_bass_level
        assert tokyo.noise.noise_floor_db == osaka.noise.noise_floor_db
        assert tokyo.noise.mid_range_boost_hz == osaka.noise.mid_range_boost_hz

    def test_sub_region_on_non_japan_raises(self, synthetic_profiles_dir: Path) -> None:
        """``sub_region`` is only valid for JAPAN_IDM."""
        with pytest.raises(ValueError, match="not applicable"):
            load_profile(
                "DETROIT_UR",
                sub_region="OSAKA",
                profiles_dir=synthetic_profiles_dir,
            )

    def test_sub_region_none_for_non_japan_ok(self, synthetic_profiles_dir: Path) -> None:
        """Omitting ``sub_region`` is fine for any region."""
        load_profile("DETROIT_UR", profiles_dir=synthetic_profiles_dir)


# ===========================================================================
# all_profiles()
# ===========================================================================


class TestAllProfiles:
    """Batch loader."""

    def test_returns_all_6_regions(self, synthetic_profiles_dir: Path) -> None:
        profiles = all_profiles(profiles_dir=synthetic_profiles_dir)
        assert set(profiles.keys()) == {
            "DETROIT_FIRST_WAVE",
            "DETROIT_UR",
            "DREXCIYA",
            "UK_IDM",
            "UK_BRAINDANCE",
            "JAPAN_IDM",
        }

    def test_returns_tokyo_default_for_japan(self, synthetic_profiles_dir: Path) -> None:
        """``all_profiles()`` returns JAPAN_IDM with ``sub_region=None`` (Tokyo)."""
        profiles = all_profiles(profiles_dir=synthetic_profiles_dir)
        japan = profiles["JAPAN_IDM"]
        assert japan.sub_region is None
        assert japan.noise is not None
        assert japan.noise.sub_bass_hz == 50  # Tokyo default

    def test_every_value_is_regional_profile(self, synthetic_profiles_dir: Path) -> None:
        profiles = all_profiles(profiles_dir=synthetic_profiles_dir)
        assert all(isinstance(p, RegionalProfile) for p in profiles.values())


# ===========================================================================
# Error paths
# ===========================================================================


class TestErrorPaths:
    """Every parse-pipeline failure surfaces as a SpokeParseError or ValueError."""

    def test_missing_spoke_file(self, tmp_path: Path) -> None:
        """Empty directory → missing file error."""
        with pytest.raises(SpokeParseError, match="spoke file not found"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_missing_dsp_section(self, tmp_path: Path) -> None:
        """Spoke without ``## 5. DSP specification`` → SpokeParseError."""
        (tmp_path / "DETROIT_UR_PROFILE.md").write_text(
            "---\ndocument_type: regional_profile\n---\n\n# no dsp section here\n"
        )
        with pytest.raises(SpokeParseError, match="could not locate"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_malformed_yaml_in_dsp_block(self, tmp_path: Path) -> None:
        """Invalid YAML inside the fenced block → SpokeParseError wrapping YAMLError."""
        bad_yaml = "bpm_range: [118, 132\nswing_type: broken\n"  # unclosed bracket
        (tmp_path / "DETROIT_UR_PROFILE.md").write_text(_build_spoke_markdown(bad_yaml))
        with pytest.raises(SpokeParseError, match="DSP spec YAML parse failed"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        """``extra="forbid"`` catches unknown DSP fields."""
        yaml_with_extra = DETROIT_UR_YAML + 'unknown_field: "shouldfail"\n'
        (tmp_path / "DETROIT_UR_PROFILE.md").write_text(_build_spoke_markdown(yaml_with_extra))
        with pytest.raises(SpokeParseError, match="validation failed"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_unordered_bpm_range_rejected(self, tmp_path: Path) -> None:
        """``bpm_range`` must be strictly ordered (min < max)."""
        bad_yaml = DETROIT_UR_YAML.replace("bpm_range: [128, 145]", "bpm_range: [145, 128]")
        (tmp_path / "DETROIT_UR_PROFILE.md").write_text(_build_spoke_markdown(bad_yaml))
        with pytest.raises(SpokeParseError, match="validation failed"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_non_mapping_dsp_block_rejected(self, tmp_path: Path) -> None:
        """A YAML list (not mapping) in the DSP block is a hard error."""
        list_yaml = "- just_a_list_element\n- another\n"
        (tmp_path / "DETROIT_UR_PROFILE.md").write_text(_build_spoke_markdown(list_yaml))
        with pytest.raises(SpokeParseError, match="must be a YAML mapping"):
            load_profile("DETROIT_UR", profiles_dir=tmp_path)

    def test_spoke_parse_error_carries_file_context(self, tmp_path: Path) -> None:
        """The exception message includes the spoke filename for debuggability."""
        bad_yaml = "bpm_range: [118\n"  # broken
        (tmp_path / "DREXCIYA_PROFILE.md").write_text(_build_spoke_markdown(bad_yaml))
        with pytest.raises(SpokeParseError) as excinfo:
            load_profile("DREXCIYA", profiles_dir=tmp_path)
        assert "DREXCIYA_PROFILE.md" in str(excinfo.value)
        assert excinfo.value.spoke_path.name == "DREXCIYA_PROFILE.md"
        assert excinfo.value.cause is not None


# ===========================================================================
# Caching — @lru_cache behaviour
# ===========================================================================


class TestCaching:
    """``@lru_cache`` memoises ``load_profile`` per (region, sub_region, profiles_dir)."""

    def test_same_args_return_same_object(self, synthetic_profiles_dir: Path) -> None:
        """Two calls with identical args return the same cached instance."""
        p1 = load_profile("UK_IDM", profiles_dir=synthetic_profiles_dir)
        p2 = load_profile("UK_IDM", profiles_dir=synthetic_profiles_dir)
        assert p1 is p2

    def test_different_sub_region_is_not_cached_together(
        self, synthetic_profiles_dir: Path
    ) -> None:
        """Tokyo and Osaka must not share a cache slot."""
        tokyo = load_profile(
            "JAPAN_IDM",
            sub_region="TOKYO",
            profiles_dir=synthetic_profiles_dir,
        )
        osaka = load_profile(
            "JAPAN_IDM",
            sub_region="OSAKA",
            profiles_dir=synthetic_profiles_dir,
        )
        assert tokyo is not osaka
        assert tokyo.noise is not None and osaka.noise is not None
        assert tokyo.noise.sub_bass_hz != osaka.noise.sub_bass_hz

    def test_cache_clear_invalidates(self, synthetic_profiles_dir: Path) -> None:
        """``cache_clear()`` forces re-parse on the next call."""
        p1 = load_profile("UK_IDM", profiles_dir=synthetic_profiles_dir)
        load_profile.cache_clear()
        p2 = load_profile("UK_IDM", profiles_dir=synthetic_profiles_dir)
        # Different object identity (re-parsed) but equal by value
        assert p1 is not p2
        assert p1 == p2


# ===========================================================================
# Integration — real vault (skipped when unreachable)
# ===========================================================================


def _real_vault_profiles_dir() -> Path | None:
    """Locate the real vault profile dir if accessible.

    Honours ``IDM_VAULT_PATH``; otherwise tries the default
    ``../IDM_Obsidian`` sibling directory. Returns ``None`` when neither
    resolves to an existing directory — the integration test skips in
    that case.
    """
    env = os.environ.get("IDM_VAULT_PATH")
    if env:
        candidate = Path(env) / "02-Knowledge" / "supporting" / "profiles"
        return candidate if candidate.is_dir() else None
    # Fallback matching engine/ml/regional_profiles.py::_default_profiles_dir
    here = Path(__file__).resolve()
    candidate = (
        here.parent.parent.parent / "IDM_Obsidian" / "02-Knowledge" / "supporting" / "profiles"
    )
    return candidate if candidate.is_dir() else None


@pytest.mark.integration
@pytest.mark.skipif(
    _real_vault_profiles_dir() is None,
    reason="Obsidian vault not reachable; set IDM_VAULT_PATH or place vault as ../IDM_Obsidian",
)
class TestRealVaultIntegration:
    """Smoke test against the real on-disk spokes. Skipped in CI by default."""

    def test_all_6_real_spokes_parse(self) -> None:
        """Every real spoke parses without raising."""
        profiles = all_profiles()
        assert len(profiles) == 6

    def test_real_japan_tokyo_osaka_split(self) -> None:
        """Real JAPAN_IDM spoke produces 50 Hz default and 60 Hz for Osaka."""
        tokyo = load_profile("JAPAN_IDM", sub_region="TOKYO")
        osaka = load_profile("JAPAN_IDM", sub_region="OSAKA")
        assert tokyo.noise is not None and osaka.noise is not None
        assert tokyo.noise.sub_bass_hz == 50
        assert osaka.noise.sub_bass_hz == 60
