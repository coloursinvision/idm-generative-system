"""
engine/__init__.py

IDM Generative System — core engine package.

Modules:
    generator       — Euclidean rhythms, Markov evolution, pattern mutation
    sample_maker    — Algorithmic sample generators (glitch, noise, FM)
    effects         — DSP effects chain (10 blocks, hardware-sourced)
"""

from engine.generator import (
    euclidean_rhythm,
    generate_pattern,
    generate_pattern_density,
    generate_euclidean_pattern,
    mutate_pattern,
    markov_evolve,
    plot_pattern,
    DEFAULT_TRACKS,
    DEFAULT_STEPS,
    DEFAULT_PROBABILITIES,
)

from engine.sample_maker import (
    glitch_click,
    noise_burst,
    fm_blip,
    normalize,
    save_sample,
    batch_export,
    SAMPLE_RATE,
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
]
