"""regional_profiles — Layer 2 profile spoke loader.

Pipeline layer: 3
Consumes:       02-Knowledge/supporting/profiles/*.md (6 spokes)
Consumed by:    deterministic_mapper, downstream dataset generation
Status:         draft

Parses each profile spoke's YAML frontmatter and the ``## 5. DSP specification``
YAML code block into a composed, frozen :class:`RegionalProfile` dataclass.
Values are NOT duplicated in this module; they are read from the spoke files
on first access.

Loading strategy:
    - Lazy: first call to :func:`load_profile` triggers parse.
    - Cached: :func:`functools.lru_cache` memoises per
      ``(region, sub_region, profiles_dir)`` tuple.
    - Fail-fast: :class:`SpokeParseError` on any I/O, frontmatter, YAML, or
      schema failure, with spoke path + underlying cause.

Parse pipeline:
    markdown file
      → python-frontmatter (YAML header + body)
      → regex-extract ``## 5. DSP specification`` fenced block
      → ``yaml.safe_load`` (raw dict)
      → Pydantic v2 ``_DSPSpecModel`` (runtime validation, ``extra="forbid"``)
      → composed frozen ``RegionalProfile`` dataclass

Japan Tokyo/Osaka split:
    ``load_profile("JAPAN_IDM", sub_region="OSAKA")`` swaps ``sub_bass_hz``
    and ``noise_floor_hz`` from 50 Hz (Tokyo default) to 60 Hz. No separate
    ``JAPAN_OSAKA_PROFILE.md`` spoke exists; the split is parameter-level
    per the bootstrap Gotcha.

Path resolution:
    Honours the ``IDM_VAULT_PATH`` environment variable. Falls back to
    assuming the Obsidian vault sits at ``../IDM_Obsidian`` relative to
    the repo root. Tests may override by passing ``profiles_dir=`` directly.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import frontmatter  # type: ignore[import-untyped]
import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from engine.ml.resonance_rules import ProfileKey

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# RegionCode is the canonical name inside regional_profiles; it aliases
# ProfileKey (defined once in resonance_rules) so the two modules cannot drift.
RegionCode = ProfileKey

SubRegion = Literal["TOKYO", "OSAKA"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGION_TO_FILENAME: dict[RegionCode, str] = {
    "DETROIT_FIRST_WAVE": "DETROIT_FIRST_WAVE_PROFILE.md",
    "DETROIT_UR": "DETROIT_UR_PROFILE.md",
    "DREXCIYA": "DREXCIYA_PROFILE.md",
    "UK_IDM": "UK_IDM_PROFILE.md",
    "UK_BRAINDANCE": "UK_BRAINDANCE_PROFILE.md",
    "JAPAN_IDM": "JAPAN_IDM_PROFILE.md",
}

# Match `## 5. DSP specification` section and its first fenced code block.
# Accepts optional `yaml` language tag on the fence. DOTALL lets `.*?`
# traverse newlines.
_DSP_SPEC_PATTERN: re.Pattern[str] = re.compile(
    r"##\s+5\.\s+DSP\s+specification\s*\n"
    r".*?"
    r"```(?:yaml)?\s*\n"
    r"(?P<yaml_block>.*?)"
    r"\n```",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SpokeParseError(Exception):
    """Raised when a profile spoke cannot be parsed into a RegionalProfile.

    Attributes:
        spoke_path: Path of the spoke file that failed.
        cause: Underlying exception, if one triggered the failure.
    """

    def __init__(
        self,
        spoke_path: Path,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        self.spoke_path = spoke_path
        self.cause = cause
        super().__init__(f"[{spoke_path.name}] {message}")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _default_profiles_dir() -> Path:
    """Resolve the spoke directory via env var or filesystem convention.

    Honours the ``IDM_VAULT_PATH`` environment variable. Falls back to
    assuming the Obsidian vault is a sibling directory ``IDM_Obsidian``
    adjacent to the repo root.

    Returns:
        Absolute path to ``<vault>/02-Knowledge/supporting/profiles``.
    """
    env = os.environ.get("IDM_VAULT_PATH")
    if env:
        return Path(env) / "02-Knowledge" / "supporting" / "profiles"
    # /<repo>/engine/ml/regional_profiles.py → repo root at parent[2]
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root.parent / "IDM_Obsidian" / "02-Knowledge" / "supporting" / "profiles"


# ---------------------------------------------------------------------------
# Pydantic validation layer (internal)
# ---------------------------------------------------------------------------


class _DSPSpecModel(BaseModel):
    """Pydantic model that validates one raw DSP spec dict from a spoke.

    This is an internal validation model, not part of the public API. The
    validated instance is converted by :func:`_model_to_profile` into the
    composed public :class:`RegionalProfile` dataclass.

    ``extra="forbid"`` is intentional: unknown fields must surface as a
    validation error at parse time so that spec drift between the spoke
    markdown and this model is caught early, not silently dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Universal fields (present in all 6 spokes) --------------------
    bpm_range: tuple[int, int] = Field(..., min_length=2, max_length=2)
    swing_type: str
    gate_behavior: str
    primary_synthesis: str
    saturation: str

    # --- Swing detail --------------------------------------------------
    swing_amount: float | Literal["variable"] | None = None
    swing_offset_ms: tuple[int, int] | None = None
    retrigger_range_ms: tuple[int, int] | None = None
    timing_resolution: int | None = None

    # --- Reverb --------------------------------------------------------
    reverb_profile: str | None = None
    reverb_bandwidth: int | None = None
    reverb_decay: int | None = None
    reverb_diffusion: float | None = None
    reverb_sample_rate: int | None = None

    # --- Saturation detail --------------------------------------------
    saturation_curve: str | None = None
    saturation_threshold: str | None = None
    dynamic_range: str | None = None

    # --- Harmonic content ---------------------------------------------
    harmonic_content: str | None = None
    chord_voicing: str | None = None
    pitch_ramp_semitones: int | None = None
    time_stretch_grain_hz: tuple[int, int] | None = None

    # --- Noise / bass --------------------------------------------------
    sub_bass_hz: int | None = Field(default=None, gt=0)
    sub_bass_level: str | None = None
    mid_range_cut: bool | None = None
    mid_range_boost_hz: int | None = None
    noise_floor_hz: int | None = None
    noise_floor_db: int | None = None
    vinyl_noise: bool | None = None

    # --- Spatial / filter / misc top-level ----------------------------
    stereo_width: str | None = None
    filter_type: str | None = None
    filter_key_tracking: float | None = None
    velocity_curves: str | None = None
    spatial_decorrelation: bool | None = None
    delay_modulation: bool | None = None
    vocal_presence: bool | None = None

    @field_validator("bpm_range", mode="after")
    @classmethod
    def _bpm_range_ordered(cls, v: tuple[int, int]) -> tuple[int, int]:
        """Assert BPM range is ordered (min < max) and positive."""
        lo, hi = v
        if lo <= 0:
            raise ValueError(f"bpm_range min must be positive, got {v}")
        if lo >= hi:
            raise ValueError(f"bpm_range must be strictly ordered (min < max), got {v}")
        return v


# ---------------------------------------------------------------------------
# Public frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SwingSpec:
    """Tempo, swing, and timing envelope parameters.

    Attributes:
        bpm_range: Canonical tempo window as ``(min, max)`` in BPM.
        swing_type: Named swing scheme (e.g. ``"mpc60_nonlinear"``,
            ``"deterministic"``, ``"inverse"``).
        gate_behavior: Named gate/retrigger convention.
        swing_amount: Swing ratio in ``[0.0, 1.0]``, or the literal string
            ``"variable"`` when swing is per-step rather than global,
            or ``None`` if unspecified.
        swing_offset_ms: Inverse-swing offset window (only UK_BRAINDANCE).
        retrigger_range_ms: Micro-retrigger window (only UK_BRAINDANCE).
        timing_resolution: PPQN timing resolution (only UK_IDM).
    """

    bpm_range: tuple[int, int]
    swing_type: str
    gate_behavior: str
    swing_amount: float | Literal["variable"] | None = None
    swing_offset_ms: tuple[int, int] | None = None
    retrigger_range_ms: tuple[int, int] | None = None
    timing_resolution: int | None = None


@dataclass(frozen=True)
class ReverbSpec:
    """Reverb profile and its tunable parameters.

    Attributes:
        profile: Named reverb character (e.g. ``"dry_short"``,
            ``"long_diffuse"``, ``"deep_lush"``).
        bandwidth: Upper frequency bound in Hz.
        decay: Decay time in milliseconds.
        diffusion: Diffusion coefficient in ``[0.0, 1.0]``.
        sample_rate: Effective sample-rate character (e.g. 31250 Hz for
            the Quadraverb aesthetic).
    """

    profile: str | None = None
    bandwidth: int | None = None
    decay: int | None = None
    diffusion: float | None = None
    sample_rate: int | None = None


@dataclass(frozen=True)
class SaturationSpec:
    """Saturation / non-linear distortion parameters.

    Attributes:
        saturation: Named saturation intensity (e.g. ``"moderate"``,
            ``"high"``, ``"low_to_moderate"``).
        curve: Named transfer curve (e.g. ``"asymmetric_tanh"``).
        threshold: Named limiter/threshold behaviour (e.g. ``"limiter"``).
        dynamic_range: Named dynamic-range character (e.g. ``"compressed"``).
    """

    saturation: str
    curve: str | None = None
    threshold: str | None = None
    dynamic_range: str | None = None


@dataclass(frozen=True)
class HarmonicContentSpec:
    """Source / synthesis and harmonic-content parameters.

    Attributes:
        primary_synthesis: Named synthesis technique (e.g. ``"fm"``,
            ``"analog_subtractive"``, ``"sampler_mangling"``).
        harmonic_content: Named harmonic character
            (e.g. ``"fm_inharmonic"``, ``"909_overdrive"``).
        chord_voicing: Named voicing convention (only DETROIT_FIRST_WAVE).
        pitch_ramp_semitones: Pitch ramp amount in semitones
            (only UK_BRAINDANCE).
        time_stretch_grain_hz: Time-stretch grain rate window
            (only UK_BRAINDANCE).
    """

    primary_synthesis: str
    harmonic_content: str | None = None
    chord_voicing: str | None = None
    pitch_ramp_semitones: int | None = None
    time_stretch_grain_hz: tuple[int, int] | None = None


@dataclass(frozen=True)
class NoiseSpec:
    """Sub-bass and noise-floor parameters.

    Attributes:
        sub_bass_hz: Sub-bass fundamental in Hz.
        sub_bass_level: Named sub-bass emphasis
            (e.g. ``"dominant"``, ``"controlled"``).
        mid_range_cut: Whether a mid-range cut is part of the aesthetic.
        mid_range_boost_hz: Mid-range boost centre frequency (Hz).
        noise_floor_hz: Mains-hum-driven noise floor fundamental in Hz.
            May differ from ``sub_bass_hz`` for Japan/US profiles.
        noise_floor_db: Noise floor level in dBFS.
        vinyl_noise: Whether vinyl surface noise is part of the aesthetic.
    """

    sub_bass_hz: int
    sub_bass_level: str | None = None
    mid_range_cut: bool | None = None
    mid_range_boost_hz: int | None = None
    noise_floor_hz: int | None = None
    noise_floor_db: int | None = None
    vinyl_noise: bool | None = None


@dataclass(frozen=True)
class RegionalProfile:
    """Complete DSP specification for one regional IDM profile.

    Sparse subgroups (``reverb``, ``noise``) are represented as ``None``
    when the spoke contains no fields belonging to that subgroup; this
    happens for UK_BRAINDANCE which specifies only swing/saturation/
    harmonic content.

    Attributes:
        region: Canonical region code.
        sub_region: Sub-region discriminator; currently only JAPAN_IDM
            uses this (Tokyo vs Osaka 50/60 Hz split).
        swing: Tempo and swing parameters (always present).
        saturation: Saturation parameters (always present).
        harmonic: Source/synthesis and harmonic content (always present).
        reverb: Reverb parameters, or ``None`` if the profile specifies no
            reverb fields.
        noise: Sub-bass and noise-floor parameters, or ``None`` if the
            profile specifies no noise/bass fields.
        stereo_width: Named stereo width category.
        filter_type: Explicit filter model name, if specified.
        filter_key_tracking: Keyboard tracking coefficient (0.0–1.0).
        velocity_curves: Named velocity curve type.
        spatial_decorrelation: Presence of spatial decorrelation.
        delay_modulation: Presence of delay modulation.
        vocal_presence: Whether vocals are an intentional sonic element.
    """

    region: RegionCode
    sub_region: SubRegion | None
    swing: SwingSpec
    saturation: SaturationSpec
    harmonic: HarmonicContentSpec
    reverb: ReverbSpec | None = None
    noise: NoiseSpec | None = None
    stereo_width: str | None = None
    filter_type: str | None = None
    filter_key_tracking: float | None = None
    velocity_curves: str | None = None
    spatial_decorrelation: bool | None = None
    delay_modulation: bool | None = None
    vocal_presence: bool | None = None


# ---------------------------------------------------------------------------
# Parsing pipeline (internal)
# ---------------------------------------------------------------------------


def _extract_dsp_yaml(markdown_body: str, spoke_path: Path) -> str:
    """Extract the raw YAML text from the ``## 5. DSP specification`` block.

    Args:
        markdown_body: Spoke content after frontmatter extraction.
        spoke_path: Path of the originating spoke (for error messages).

    Returns:
        The captured YAML text (without the enclosing ``` fences).

    Raises:
        SpokeParseError: If the section or its fenced code block is missing.
    """
    match = _DSP_SPEC_PATTERN.search(markdown_body)
    if match is None:
        raise SpokeParseError(
            spoke_path,
            "could not locate '## 5. DSP specification' section or its fenced code block",
        )
    return match.group("yaml_block")


def _parse_spoke_file(spoke_path: Path) -> _DSPSpecModel:
    """Parse a single spoke end-to-end into a validated :class:`_DSPSpecModel`.

    Args:
        spoke_path: Filesystem path of the spoke markdown file.

    Returns:
        A validated internal Pydantic model.

    Raises:
        SpokeParseError: On any I/O, frontmatter, YAML, or schema failure.
    """
    if not spoke_path.is_file():
        raise SpokeParseError(spoke_path, "spoke file not found")

    try:
        post = frontmatter.load(str(spoke_path))
    except Exception as exc:  # python-frontmatter wraps many underlying errors
        raise SpokeParseError(spoke_path, f"frontmatter parse failed: {exc}", exc) from exc

    yaml_block = _extract_dsp_yaml(post.content, spoke_path)

    try:
        raw_dict = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        raise SpokeParseError(spoke_path, f"DSP spec YAML parse failed: {exc}", exc) from exc

    if not isinstance(raw_dict, dict):
        raise SpokeParseError(
            spoke_path,
            f"DSP spec block must be a YAML mapping, got {type(raw_dict).__name__}",
        )

    # Spoke YAML nests DSP fields under a region-name key
    # (e.g. "DETROIT_FIRST_WAVE: { bpm_range: ... }").
    # Unwrap the single top-level key to get the flat field dict.
    if len(raw_dict) == 1:
        (wrapper_key,) = raw_dict
        inner = raw_dict[wrapper_key]
        if not isinstance(inner, dict):
            raise SpokeParseError(
                spoke_path,
                f"DSP spec region key '{wrapper_key}' must wrap a mapping, "
                f"got {type(inner).__name__}",
            )
        raw_dict = inner

    try:
        return _DSPSpecModel(**raw_dict)
    except ValidationError as exc:
        raise SpokeParseError(spoke_path, f"DSP spec validation failed: {exc}", exc) from exc


def _build_reverb(model: _DSPSpecModel) -> ReverbSpec | None:
    """Compose a :class:`ReverbSpec` or ``None`` if no reverb fields are set."""
    if (
        model.reverb_profile is None
        and model.reverb_bandwidth is None
        and model.reverb_decay is None
        and model.reverb_diffusion is None
        and model.reverb_sample_rate is None
    ):
        return None
    return ReverbSpec(
        profile=model.reverb_profile,
        bandwidth=model.reverb_bandwidth,
        decay=model.reverb_decay,
        diffusion=model.reverb_diffusion,
        sample_rate=model.reverb_sample_rate,
    )


def _build_noise(
    model: _DSPSpecModel,
    region: RegionCode,
    sub_region: SubRegion | None,
) -> NoiseSpec | None:
    """Compose a :class:`NoiseSpec` or ``None``; apply the Osaka override.

    For ``region == "JAPAN_IDM"`` and ``sub_region == "OSAKA"``, both
    ``sub_bass_hz`` and ``noise_floor_hz`` are forced to 60 Hz per the
    project convention (Tokyo defaults to 50 Hz in the spoke).
    """
    sub_bass_hz = model.sub_bass_hz
    noise_floor_hz = model.noise_floor_hz

    if region == "JAPAN_IDM" and sub_region == "OSAKA":
        if sub_bass_hz is not None:
            sub_bass_hz = 60
        if noise_floor_hz is not None:
            noise_floor_hz = 60

    if sub_bass_hz is None:
        # Without a sub_bass_hz the NoiseSpec has no anchor; absent-is-None.
        # (UK_BRAINDANCE is the only profile that hits this path.)
        return None

    return NoiseSpec(
        sub_bass_hz=sub_bass_hz,
        sub_bass_level=model.sub_bass_level,
        mid_range_cut=model.mid_range_cut,
        mid_range_boost_hz=model.mid_range_boost_hz,
        noise_floor_hz=noise_floor_hz,
        noise_floor_db=model.noise_floor_db,
        vinyl_noise=model.vinyl_noise,
    )


def _model_to_profile(
    model: _DSPSpecModel,
    region: RegionCode,
    sub_region: SubRegion | None,
) -> RegionalProfile:
    """Convert a validated Pydantic model into a frozen :class:`RegionalProfile`."""
    return RegionalProfile(
        region=region,
        sub_region=sub_region,
        swing=SwingSpec(
            bpm_range=model.bpm_range,
            swing_type=model.swing_type,
            gate_behavior=model.gate_behavior,
            swing_amount=model.swing_amount,
            swing_offset_ms=model.swing_offset_ms,
            retrigger_range_ms=model.retrigger_range_ms,
            timing_resolution=model.timing_resolution,
        ),
        saturation=SaturationSpec(
            saturation=model.saturation,
            curve=model.saturation_curve,
            threshold=model.saturation_threshold,
            dynamic_range=model.dynamic_range,
        ),
        harmonic=HarmonicContentSpec(
            primary_synthesis=model.primary_synthesis,
            harmonic_content=model.harmonic_content,
            chord_voicing=model.chord_voicing,
            pitch_ramp_semitones=model.pitch_ramp_semitones,
            time_stretch_grain_hz=model.time_stretch_grain_hz,
        ),
        reverb=_build_reverb(model),
        noise=_build_noise(model, region, sub_region),
        stereo_width=model.stereo_width,
        filter_type=model.filter_type,
        filter_key_tracking=model.filter_key_tracking,
        velocity_curves=model.velocity_curves,
        spatial_decorrelation=model.spatial_decorrelation,
        delay_modulation=model.delay_modulation,
        vocal_presence=model.vocal_presence,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@cache
def load_profile(
    region: RegionCode,
    sub_region: SubRegion | None = None,
    profiles_dir: Path | None = None,
) -> RegionalProfile:
    """Load a single regional profile from its spoke markdown file.

    Memoised per ``(region, sub_region, profiles_dir)``. Pass a distinct
    ``profiles_dir`` (e.g. in tests) to bypass the cache for a given
    directory.

    Args:
        region: Canonical region code.
        sub_region: Optional sub-region discriminator. Currently only
            ``"OSAKA"`` has a non-default effect — it swaps
            mains-frequency-driven fields on ``JAPAN_IDM`` from 50 Hz to
            60 Hz.
        profiles_dir: Override for the spoke directory. Defaults to the
            value resolved by :func:`_default_profiles_dir`, which honours
            the ``IDM_VAULT_PATH`` environment variable.

    Returns:
        A frozen :class:`RegionalProfile`.

    Raises:
        SpokeParseError: If the spoke file is missing, malformed, or fails
            schema validation.
        ValueError: If ``sub_region`` is supplied for a region that does
            not support sub-region discrimination.
    """
    if sub_region is not None and region != "JAPAN_IDM":
        raise ValueError(
            f"sub_region='{sub_region}' not applicable for region '{region}' "
            "(only JAPAN_IDM supports sub-region discrimination)"
        )

    base_dir = profiles_dir if profiles_dir is not None else _default_profiles_dir()
    spoke_path = base_dir / _REGION_TO_FILENAME[region]

    logger.debug("loading profile spoke: %s", spoke_path)
    model = _parse_spoke_file(spoke_path)
    return _model_to_profile(model, region, sub_region)


def all_profiles(
    profiles_dir: Path | None = None,
) -> dict[RegionCode, RegionalProfile]:
    """Load every available regional profile in canonical (default) form.

    For JAPAN_IDM only the Tokyo default is returned here; to obtain the
    Osaka variant, call ``load_profile("JAPAN_IDM", sub_region="OSAKA")``
    explicitly.

    Args:
        profiles_dir: Override for the spoke directory. Defaults to the
            value resolved by :func:`_default_profiles_dir`.

    Returns:
        Dict mapping each :data:`RegionCode` to its loaded
        :class:`RegionalProfile`.
    """
    return {
        region: load_profile(region, sub_region=None, profiles_dir=profiles_dir)
        for region in _REGION_TO_FILENAME
    }
