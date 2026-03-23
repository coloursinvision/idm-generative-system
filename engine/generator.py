"""
engine/generator.py

Rhythmic pattern generator for the IDM Generative System.
Extracted and refactored from: notebooks/idm_project_01.ipynb

Algorithms:
    - Euclidean rhythms (Bjorklund algorithm)
    - Probabilistic pattern generation
    - Density-controlled generation
    - Markov chain evolution
    - Probabilistic mutation
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TRACKS: List[str] = ["kick", "snare", "hat", "glitch"]
DEFAULT_STEPS: int = 16

DEFAULT_PROBABILITIES: Dict[str, float] = {
    "kick": 0.25,
    "snare": 0.15,
    "hat": 0.60,
    "glitch": 0.08,
}


# ---------------------------------------------------------------------------
# Euclidean rhythm
# ---------------------------------------------------------------------------

def euclidean_rhythm(k: int, n: int) -> List[int]:
    """
    Generate a Euclidean rhythm (Bjorklund algorithm).

    Distributes k pulses as evenly as possible across n steps.
    The standard reference for rhythmic patterns used in IDM and world music.

    Args:
        k: Number of pulses (hits).
        n: Total number of steps.

    Returns:
        List of ints (0 or 1) of length n.

    Examples:
        >>> euclidean_rhythm(5, 16)  # classic IDM kick pattern
        [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0]
        >>> euclidean_rhythm(3, 8)   # standard clave
        [1, 0, 0, 1, 0, 0, 1, 0]
    """
    if k <= 0:
        return [0] * n
    if k >= n:
        return [1] * n

    pattern: List[int] = []
    counts: List[int] = []
    remainders: List[int] = []

    divisor = n - k
    remainders.append(k)
    level = 0

    while True:
        counts.append(divisor // remainders[level])
        remainders.append(divisor % remainders[level])
        divisor = remainders[level]
        level += 1
        if remainders[level] <= 1:
            break

    counts.append(divisor)

    def build(lvl: int) -> None:
        if lvl == -1:
            pattern.append(0)
        elif lvl == -2:
            pattern.append(1)
        else:
            for _ in range(counts[lvl]):
                build(lvl - 1)
            if remainders[lvl] != 0:
                build(lvl - 2)

    build(level)

    # Rotate so pattern starts on a pulse
    i = pattern.index(1)
    return pattern[i:] + pattern[:i]


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------

def generate_pattern(
    steps: int,
    probabilities: Dict[str, float],
) -> pd.DataFrame:
    """
    Generate a rhythmic pattern using per-track trigger probabilities.

    Args:
        steps: Number of steps (e.g. 16 for a standard bar).
        probabilities: Dict mapping track name → trigger probability [0, 1].

    Returns:
        pd.DataFrame with tracks as rows and steps as columns (int 0/1).
    """
    tracks = list(probabilities.keys())
    data = [
        (np.random.rand(steps) < probabilities[track]).astype(int)
        for track in tracks
    ]
    return pd.DataFrame(data, index=tracks, columns=range(steps))


def generate_pattern_density(
    steps: int,
    tracks: Optional[List[str]] = None,
    density: float = 0.3,
) -> pd.DataFrame:
    """
    Generate a rhythmic pattern with uniform density across all tracks.

    Args:
        steps: Number of steps.
        tracks: List of track names. Defaults to DEFAULT_TRACKS.
        density: Trigger probability per step [0, 1].

    Returns:
        pd.DataFrame with tracks as rows and steps as columns (int 0/1).
    """
    if tracks is None:
        tracks = DEFAULT_TRACKS

    mat = (np.random.rand(len(tracks), steps) < density).astype(int)
    return pd.DataFrame(mat, index=tracks, columns=range(steps))


def generate_euclidean_pattern(
    pulses: Optional[Dict[str, int]] = None,
    steps: int = DEFAULT_STEPS,
) -> pd.DataFrame:
    """
    Build a multi-track pattern from Euclidean rhythms.

    Args:
        pulses: Dict mapping track name → number of pulses.
                Defaults to a preset IDM-style distribution.
        steps: Total number of steps per track.

    Returns:
        pd.DataFrame with tracks as rows and steps as columns (int 0/1).
    """
    if pulses is None:
        pulses = {
            "kick": 5,
            "snare": 3,
            "hat": 11,
            "glitch": 2,
        }

    data = {
        track: euclidean_rhythm(k, steps)
        for track, k in pulses.items()
    }
    return pd.DataFrame(data).T.rename(
        columns={i: i for i in range(steps)}
    )


# ---------------------------------------------------------------------------
# Pattern evolution
# ---------------------------------------------------------------------------

def mutate_pattern(
    pattern: pd.DataFrame,
    mutation_rate: float = 0.1,
) -> pd.DataFrame:
    """
    Probabilistic mutation: randomly flip steps (bitwise XOR with a mask).

    Each step has `mutation_rate` probability of being toggled (0→1 or 1→0).
    Core operator for evolutionary pattern selection in the generator.

    Args:
        pattern: pd.DataFrame (tracks × steps, int 0/1).
        mutation_rate: Probability of flipping each step [0, 1].

    Returns:
        Mutated copy of the pattern.
    """
    mutated = pattern.copy()
    for track in pattern.index:
        row = mutated.loc[track].astype(int).values
        mask = (np.random.rand(len(row)) < mutation_rate).astype(int)
        mutated.loc[track] = row ^ mask
    return mutated


def markov_evolve(
    pattern: pd.DataFrame,
    influence: float = 0.3,
) -> pd.DataFrame:
    """
    Markov chain evolution: each step has `influence` probability of
    inheriting the value of the previous step.

    Introduces temporal coherence and "runs" into the pattern — characteristic
    of IDM sequencing where rhythms develop organic momentum over time.

    Args:
        pattern: pd.DataFrame (tracks × steps, int 0/1).
        influence: Markov carry-over probability [0, 1].

    Returns:
        Evolved copy of the pattern.
    """
    evolved = pattern.copy()
    for track in pattern.index:
        row = evolved.loc[track].astype(int).values
        for i in range(1, len(row)):
            if np.random.rand() < influence:
                row[i] = row[i - 1]
        evolved.loc[track] = row
    return evolved


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def plot_pattern(
    df: pd.DataFrame,
    title: str = "Rhythm Matrix",
) -> None:
    """
    Render a rhythm matrix as a heatmap.

    Args:
        df: pd.DataFrame (tracks × steps, int 0/1).
        title: Plot title.
    """
    plt.figure(figsize=(10, 3))
    plt.imshow(df, aspect="auto", interpolation="nearest")
    plt.yticks(range(len(df)), df.index)
    plt.xticks(range(len(df.columns)))
    plt.xlabel("Step")
    plt.title(title)
    plt.colorbar(label="Trigger")
    plt.tight_layout()
    plt.show()
