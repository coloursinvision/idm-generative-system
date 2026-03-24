"""
engine/effects/__init__.py

Public API for the IDM Generative System effects chain.

Exports all 10 effect blocks, the EffectChain pipeline, and a factory
function for building the canonical signal-chain order.

Canonical signal chain:
    INPUT → [1. NoiseFloor] → [2. Bitcrusher] → [3. ResonantFilter] →
    [4. Saturation] → [5. Reverb] → [6. TapeDelay] → [7. SpatialProcessor] →
    [8. GlitchEngine] → [9. Compressor] → [10. VinylMastering] → OUTPUT

Usage:
    # Import individual blocks
    from engine.effects import NoiseFloor, TapeDelay, GlitchEngine

    # Build the full canonical chain with defaults
    from engine.effects import build_chain
    chain = build_chain()
    output = chain(signal)

    # Build a partial chain (selected blocks only)
    from engine.effects import EffectChain, Bitcrusher, Reverb, Compressor
    chain = EffectChain([Bitcrusher(hardware_preset='sp1200'),
                         Reverb(reverb_type='plate'),
                         Compressor()])

    # Override specific block parameters in the canonical chain
    chain = build_chain(overrides={
        'glitch': {'stutter_density': 0.3, 'xor_mode': 'moderate'},
        'compressor': {'threshold_db': -24, 'ratio': 8},
        'vinyl': {'vinyl_condition': 'worn'},
    })
"""

from engine.effects.base import BaseEffect
from engine.effects.chain import EffectChain

# Block 1 — Analogue noise floor (Mackie CR-1604)
from engine.effects.noise_floor import NoiseFloor

# Block 2 — Bitcrusher (SP-1200, S950, RZ-1)
from engine.effects.bitcrusher import Bitcrusher

# Block 3 — Resonant filter (TB-303, SH-101)
from engine.effects.filter import ResonantFilter

# Block 4 — Saturation (Mackie bus, tape)
from engine.effects.saturation import Saturation

# Block 5 — Reverb (Alesis Quadraverb)
from engine.effects.reverb import Reverb

# Block 6 — Tape delay (Roland Space Echo RE-201)
from engine.effects.delay import TapeDelay

# Block 7 — Spatial processor (stereo field)
from engine.effects.spatial import SpatialProcessor

# Block 8 — Glitch engine (Braindance stutter, ASR-10, XOR)
from engine.effects.glitch import GlitchEngine

# Block 9 — Bus compressor (SSL, Neve, dbx)
from engine.effects.compressor import Compressor

# Block 10 — Vinyl mastering (RIAA, DAT, surface noise)
from engine.effects.vinyl import VinylMastering


# ---------------------------------------------------------------------------
# Canonical chain order — used by build_chain()
# ---------------------------------------------------------------------------

CANONICAL_ORDER: list[tuple[str, type]] = [
    ("noise_floor",  NoiseFloor),
    ("bitcrusher",   Bitcrusher),
    ("filter",       ResonantFilter),
    ("saturation",   Saturation),
    ("reverb",       Reverb),
    ("delay",        TapeDelay),
    ("spatial",      SpatialProcessor),
    ("glitch",       GlitchEngine),
    ("compressor",   Compressor),
    ("vinyl",        VinylMastering),
]


def build_chain(
    overrides: dict[str, dict] | None = None,
    skip: list[str] | None = None,
) -> EffectChain:
    """
    Build an EffectChain in canonical signal-chain order.

    Each block is instantiated with default parameters unless overridden.
    Blocks can be skipped entirely by name.

    Args:
        overrides: Dict mapping block key to kwargs dict.
                   Keys: 'noise_floor', 'bitcrusher', 'filter', 'saturation',
                   'reverb', 'delay', 'spatial', 'glitch', 'compressor', 'vinyl'.
                   Example: {'glitch': {'stutter_density': 0.4}}
        skip:      List of block keys to omit from the chain.
                   Example: ['noise_floor', 'spatial']

    Returns:
        Configured EffectChain with blocks in canonical order.

    Example:
        >>> # Full chain, default parameters
        >>> chain = build_chain()
        >>> output = chain(signal)

        >>> # Skip noise floor and spatial, heavy glitch
        >>> chain = build_chain(
        ...     overrides={'glitch': {'stutter_density': 0.4, 'xor_mode': 'heavy'}},
        ...     skip=['noise_floor', 'spatial'],
        ... )
    """
    overrides = overrides or {}
    skip_set = set(skip or [])

    effects: list[BaseEffect] = []
    for key, cls in CANONICAL_ORDER:
        if key in skip_set:
            continue
        kwargs = overrides.get(key, {})
        effects.append(cls(**kwargs))

    return EffectChain(effects)


__all__ = [
    # Base + chain
    "BaseEffect",
    "EffectChain",
    # Blocks 1–10
    "NoiseFloor",
    "Bitcrusher",
    "ResonantFilter",
    "Saturation",
    "Reverb",
    "TapeDelay",
    "SpatialProcessor",
    "GlitchEngine",
    "Compressor",
    "VinylMastering",
    # Factory
    "build_chain",
    "CANONICAL_ORDER",
]
