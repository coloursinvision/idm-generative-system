"""
engine/effects/base.py

Abstract base class for all DSP effect blocks in the IDM Generative System.

All effects in the chain must inherit from BaseEffect and implement:
    - __call__(signal) → processed signal
    - reset()          → reset any internal state

This interface ensures:
    - Consistent API across all 10 effect blocks
    - Safe chaining via EffectChain (chain.py)
    - Easy extension without breaking existing code
    - Stateful effects (delay buffers, envelope followers) work correctly
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseEffect(ABC):
    """
    Abstract base class for all DSP effect blocks.

    Every effect block in the signal chain must inherit from this class
    and implement __call__ and reset.

    Subclasses may store state in __init__ (e.g. delay buffers, envelope
    followers). Call reset() to reinitialise that state between renders.

    Example:
        class MyEffect(BaseEffect):
            def __init__(self, gain: float = 1.0):
                self.gain = gain

            def __call__(self, signal: np.ndarray) -> np.ndarray:
                return signal * self.gain

            def reset(self) -> None:
                pass  # stateless — nothing to reset
    """

    @abstractmethod
    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Process an audio signal.

        Args:
            signal: Input audio as a float32/float64 numpy array,
                    normalised to [-1.0, 1.0].

        Returns:
            Processed audio array of the same dtype and shape.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """
        Reset any internal state (buffers, envelope followers, etc.).

        Called automatically by EffectChain before each new render.
        Stateless effects should implement this as a no-op (pass).
        """
        ...

    def __repr__(self) -> str:
        params = ", ".join(
            f"{k}={v!r}"
            for k, v in self.__dict__.items()
            if not k.startswith("_")
        )
        return f"{self.__class__.__name__}({params})"
