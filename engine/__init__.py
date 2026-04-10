"""
engine/__init__.py

IDM Generative System — core engine package.

Modules:
    generator       — Euclidean rhythms, Markov evolution, pattern mutation
    sample_maker    — Algorithmic sample generators (glitch, noise, FM)
    effects         — DSP effects chain (10 blocks, hardware-sourced)

Primary entry points:
    build_chain()       — build the canonical 10-block signal chain
    CANONICAL_ORDER     — ordered list of (key, class) tuples defining the chain

Block classes are available via the effects subpackage:
    from engine.effects import NoiseFloor, Bitcrusher, GlitchEngine, ...
"""

import engine.effects as effects
from engine.effects import CANONICAL_ORDER, build_chain
from engine.generator import (
    DEFAULT_PROBABILITIES,
    DEFAULT_STEPS,
    DEFAULT_TRACKS,
    euclidean_rhythm,
    generate_euclidean_pattern,
    generate_pattern,
    generate_pattern_density,
    markov_evolve,
    mutate_pattern,
    plot_pattern,
)
from engine.sample_maker import (
    SAMPLE_RATE,
    batch_export,
    fm_blip,
    glitch_click,
    noise_burst,
    normalize,
    save_sample,
)

__all__ = [
    # generator
    "euclidean_rhythm",
    "generate_pattern",
    "generate_pattern_density",
    "generate_euclidean_pattern",
    "mutate_pattern",
    "markov_evolve",
    "plot_pattern",
    "DEFAULT_TRACKS",
    "DEFAULT_STEPS",
    "DEFAULT_PROBABILITIES",
    # sample_maker
    "glitch_click",
    "noise_burst",
    "fm_blip",
    "normalize",
    "save_sample",
    "batch_export",
    "SAMPLE_RATE",
    # effects — primary entry points
    "build_chain",
    "CANONICAL_ORDER",
    "effects",
]
