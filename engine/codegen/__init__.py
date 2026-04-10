"""
engine/codegen/__init__.py

Public API for the IDM Generative System code generation module.

Generates SuperCollider (.scd) and TidalCycles (Haskell DSL) code
from engine configurations. Pure string transforms — no audio
processing, no external dependencies.

Usage:
    # Quick generation with convenience functions
    from engine.codegen import generate_synthdef, generate_tidal

    result = generate_synthdef(
        generator="fm_blip",
        generator_params={"freq": 300, "mod_index": 2.0},
        effects={"reverb": {"decay_s": 3.0}},
        pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
    )
    print(result.code)

    # Full control via classes
    from engine.codegen import SuperColliderCodegen, CodegenInput, CodegenOptions

    sc = SuperColliderCodegen()
    result = sc.generate(CodegenInput(
        generator="fm_blip",
        options=CodegenOptions(mode=CodegenMode.LIVE),
    ))
"""

from __future__ import annotations

from typing import Any

from engine.codegen.base import (
    BaseCodegen,
    CodegenInput,
    CodegenMode,
    CodegenOptions,
    CodegenResult,
    CodegenTarget,
)
from engine.codegen.synthdef import SuperColliderCodegen
from engine.codegen.tidal import TidalCyclesCodegen


def generate_synthdef(
    generator: str,
    generator_params: dict[str, Any] | None = None,
    effects: dict[str, dict[str, Any]] | None = None,
    pattern: dict[str, Any] | None = None,
    mode: str = "studio",
    include_pattern: bool = True,
    bpm: float = 120.0,
    bus_offset: int = 16,
) -> CodegenResult:
    """Generate SuperCollider code from engine configuration.

    Convenience function wrapping SuperColliderCodegen.generate().

    Args:
        generator:        Generator name ('glitch_click', 'noise_burst', 'fm_blip').
        generator_params: Generator kwargs dict.
        effects:          Dict of block_key → effect kwargs dict.
        pattern:          Pattern config dict (type, pulses/probabilities, steps).
        mode:             'studio' (self-contained) or 'live' (hot-swap).
        include_pattern:  Generate Pbind/Pdef pattern code.
        bpm:              Beats per minute.
        bus_offset:       Starting private bus number.

    Returns:
        CodegenResult with SuperCollider code.
    """
    codegen_input = CodegenInput(
        generator=generator,
        generator_params=generator_params or {},
        effects=effects or {},
        pattern=pattern,
        options=CodegenOptions(
            mode=CodegenMode(mode),
            include_pattern=include_pattern,
            include_server_boot=(mode == "studio"),
            bus_offset=bus_offset,
            bpm=bpm,
        ),
    )
    return SuperColliderCodegen().generate(codegen_input)


def generate_tidal(
    generator: str,
    generator_params: dict[str, Any] | None = None,
    effects: dict[str, dict[str, Any]] | None = None,
    pattern: dict[str, Any] | None = None,
    mode: str = "studio",
    include_pattern: bool = True,
    bpm: float = 120.0,
) -> CodegenResult:
    """Generate TidalCycles code from engine configuration.

    Convenience function wrapping TidalCyclesCodegen.generate().

    Args:
        generator:        Generator name ('glitch_click', 'noise_burst', 'fm_blip').
        generator_params: Generator kwargs dict.
        effects:          Dict of block_key → effect kwargs dict.
        pattern:          Pattern config dict (type, pulses/probabilities, steps).
        mode:             'studio' (full setup) or 'live' (bare patterns).
        include_pattern:  Generate pattern code.
        bpm:              Beats per minute.

    Returns:
        CodegenResult with TidalCycles code.
    """
    codegen_input = CodegenInput(
        generator=generator,
        generator_params=generator_params or {},
        effects=effects or {},
        pattern=pattern,
        options=CodegenOptions(
            mode=CodegenMode(mode),
            include_pattern=include_pattern,
            bpm=bpm,
        ),
    )
    return TidalCyclesCodegen().generate(codegen_input)


__all__ = [
    # Convenience functions
    "generate_synthdef",
    "generate_tidal",
    # Classes
    "SuperColliderCodegen",
    "TidalCyclesCodegen",
    "BaseCodegen",
    # Data types
    "CodegenInput",
    "CodegenOptions",
    "CodegenResult",
    "CodegenTarget",
    "CodegenMode",
]
