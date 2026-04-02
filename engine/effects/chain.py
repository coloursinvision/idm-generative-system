"""
engine/effects/chain.py

EffectChain — sequential DSP pipeline for the IDM Generative System.

Connects all 10 effect blocks in the correct signal-chain order:

    INPUT → [1. NoiseFloor] → [2. Bitcrusher] → [3. ResonantFilter] →
    [4. Saturation] → [5. Reverb] → [6. TapeDelay] → [7. SpatialProcessor] →
    [8. GlitchEngine] → [9. Compressor] → [10. VinylMastering] → OUTPUT

Usage:
    from engine.effects.chain import EffectChain
    from engine.effects.noise_floor import NoiseFloor
    from engine.effects.bitcrusher import Bitcrusher

    chain = EffectChain([
        NoiseFloor(noise_type='hum_uk'),
        Bitcrusher(hardware_preset='sp1200'),
    ])

    output = chain(signal)

Effects can be added, removed or reordered at runtime. The chain resets
all internal state before each render to prevent bleed between patterns.
"""

from __future__ import annotations

import numpy as np

from engine.effects.base import BaseEffect


class EffectChain:
    """
    Sequential DSP effects pipeline.

    Processes a signal through a list of BaseEffect instances in order.
    Resets all effect state before each render.

    Args:
        effects: Ordered list of BaseEffect instances.
                 Pass an empty list to create an identity (bypass) chain.

    Example:
        >>> chain = EffectChain([NoiseFloor(), Bitcrusher(bit_depth=12)])
        >>> output = chain(signal)

        # Bypass all effects
        >>> chain.bypass = True
        >>> output = chain(signal)  # returns signal unchanged

        # Insert effect at position
        >>> chain.insert(1, ResonantFilter())

        # Remove effect by index
        >>> chain.remove(0)
    """

    def __init__(self, effects: list[BaseEffect] | None = None) -> None:
        self.effects: list[BaseEffect] = effects or []
        self.bypass: bool = False

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Process signal through the full effects chain.

        Resets all effect state before processing to ensure clean renders.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Processed audio array.
        """
        if self.bypass or not self.effects:
            return signal

        self.reset()

        output = signal.copy()
        for effect in self.effects:
            output = effect(output)

        return output

    def reset(self) -> None:
        """Reset internal state of all effects in the chain."""
        for effect in self.effects:
            effect.reset()

    def append(self, effect: BaseEffect) -> None:
        """Append an effect to the end of the chain."""
        self.effects.append(effect)

    def insert(self, index: int, effect: BaseEffect) -> None:
        """Insert an effect at the given position in the chain."""
        self.effects.insert(index, effect)

    def remove(self, index: int) -> BaseEffect:
        """
        Remove and return the effect at the given index.

        Args:
            index: Position in the chain.

        Returns:
            The removed BaseEffect instance.
        """
        return self.effects.pop(index)

    def __len__(self) -> int:
        return len(self.effects)

    def __repr__(self) -> str:
        chain_str = "\n  ".join(
            f"[{i}] {effect!r}" for i, effect in enumerate(self.effects)
        )
        return f"EffectChain(\n  {chain_str}\n)"
