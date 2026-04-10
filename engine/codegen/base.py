"""
engine/codegen/base.py

Abstract base class for code generators and shared result types.

All codegen targets (SuperCollider, TidalCycles, future targets) must
inherit from BaseCodegen and implement the generate() method.

Architecture:
    - BaseCodegen defines the contract: validate input → generate code → return result
    - CodegenResult is the structured response returned to API consumers
    - CodegenOptions controls target-specific generation behaviour
    - Pure string transforms — no audio processing, no I/O, no external deps
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CodegenTarget(StrEnum):
    """Supported code generation targets."""

    SUPERCOLLIDER = "supercollider"
    TIDALCYCLES = "tidalcycles"


class CodegenMode(StrEnum):
    """Generation mode — controls output structure and boilerplate.

    STUDIO:
        Self-contained script. Includes server boot, cleanup, full
        comments. User copies into IDE and evaluates entire file.

    LIVE:
        Optimised for hot-swapping. Minimal boilerplate, assumes
        server is already running. Uses Pdef/Ndef (SC) or standard
        d1/d2 (Tidal) for live re-evaluation.
    """

    STUDIO = "studio"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodegenOptions:
    """Per-request generation options.

    Attributes:
        mode:                 Generation mode (studio / live).
        include_pattern:      Generate pattern code (Pbind / Tidal pattern).
        include_server_boot:  Include s.boot / s.waitForBoot in SC output.
                              Auto-set to False when mode is LIVE.
        bus_offset:           Starting private bus number for SC bus allocation.
        bpm:                  Beats per minute — used for Tidal cycle timing
                              and SC TempoClock.
    """

    mode: CodegenMode = CodegenMode.STUDIO
    include_pattern: bool = True
    include_server_boot: bool = True
    bus_offset: int = 16
    bpm: float = 120.0

    def __post_init__(self) -> None:
        # Live mode never includes server boot
        if self.mode == CodegenMode.LIVE and self.include_server_boot:
            object.__setattr__(self, "include_server_boot", False)


@dataclass(frozen=True, slots=True)
class CodegenResult:
    """Structured result returned by all codegen targets.

    Attributes:
        code:             Generated source code string.
        target:           Which language was generated (supercollider / tidalcycles).
        mode:             Generation mode used (studio / live).
        warnings:         List of mapping approximation warnings.
        unmapped_params:  Dict of block_key → list of param names with no
                          target equivalent (documented, not dropped).
        metadata:         Target-specific metadata (e.g. SynthDef names,
                          bus allocation, Tidal orbit assignments).
        setup_notes:      User-facing setup instructions for the generated code.
    """

    code: str
    target: CodegenTarget
    mode: CodegenMode
    warnings: list[str] = field(default_factory=list)
    unmapped_params: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    setup_notes: list[str] = field(default_factory=list)


@dataclass
class CodegenInput:
    """Validated input for code generation.

    Constructed from the API request body. All values are Python-native
    (not yet transformed to target language).

    Attributes:
        generator:        Generator name ('glitch_click', 'noise_burst', 'fm_blip').
        generator_params: Dict of generator kwargs (e.g. {'freq': 300}).
        effects:          Dict of block_key → effect kwargs dict.
                          Only blocks present in this dict are included in output.
                          Example: {'reverb': {'decay_s': 3.0}, 'delay': {'feedback': 0.6}}
        pattern:          Pattern configuration dict.
                          Required keys: 'type' (euclidean/probabilistic/density).
                          Optional keys depend on type:
                            euclidean: 'pulses' (dict), 'steps' (int)
                            probabilistic: 'probabilities' (dict), 'steps' (int)
                            density: 'density' (float), 'steps' (int), 'tracks' (list)
        options:          Generation options.
    """

    generator: str
    generator_params: dict[str, Any] = field(default_factory=dict)
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    pattern: dict[str, Any] | None = None
    options: CodegenOptions = field(default_factory=CodegenOptions)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseCodegen(ABC):
    """Abstract base class for code generation targets.

    Subclasses must implement:
        - generate(input) → CodegenResult
        - _build_generator_code(input) → str
        - _build_effects_code(input) → str
        - _build_pattern_code(input) → str

    The base class provides:
        - Input validation (validate)
        - Warning collection helpers
        - Consistent error handling
    """

    # Known generator names (must match sample_maker.py)
    VALID_GENERATORS: frozenset[str] = frozenset(
        {
            "glitch_click",
            "noise_burst",
            "fm_blip",
        }
    )

    # Known effect block keys (must match effects/__init__.py CANONICAL_ORDER)
    VALID_EFFECTS: frozenset[str] = frozenset(
        {
            "noise_floor",
            "bitcrusher",
            "filter",
            "saturation",
            "reverb",
            "delay",
            "spatial",
            "glitch",
            "compressor",
            "vinyl",
        }
    )

    # Known pattern types (must match generator.py algorithms)
    VALID_PATTERN_TYPES: frozenset[str] = frozenset(
        {
            "euclidean",
            "probabilistic",
            "density",
        }
    )

    def validate(self, codegen_input: CodegenInput) -> list[str]:
        """Validate codegen input and return a list of error messages.

        Returns:
            Empty list if input is valid. List of error strings otherwise.
        """
        errors: list[str] = []

        # Generator validation
        if codegen_input.generator not in self.VALID_GENERATORS:
            errors.append(
                f"Unknown generator '{codegen_input.generator}'. "
                f"Valid: {sorted(self.VALID_GENERATORS)}"
            )

        # Effects validation
        for block_key in codegen_input.effects:
            if block_key not in self.VALID_EFFECTS:
                errors.append(
                    f"Unknown effect block '{block_key}'. Valid: {sorted(self.VALID_EFFECTS)}"
                )

        # Pattern validation
        if codegen_input.pattern is not None:
            ptype = codegen_input.pattern.get("type")
            if ptype not in self.VALID_PATTERN_TYPES:
                errors.append(
                    f"Unknown pattern type '{ptype}'. Valid: {sorted(self.VALID_PATTERN_TYPES)}"
                )

        return errors

    @abstractmethod
    def generate(self, codegen_input: CodegenInput) -> CodegenResult:
        """Generate code from validated input.

        Args:
            codegen_input: Validated CodegenInput instance.

        Returns:
            CodegenResult with generated code, warnings, and metadata.

        Raises:
            ValueError: If input validation fails.
        """
        ...
