"""
engine/effects/bitcrusher.py

Block 2 — Bitcrusher (Lo-Fi / DAC Emulation).

Source:
    MASTER_DATASET Part 1.1 — Rhythmic Foundations (Drum Machines & Samplers)

Hardware references:
    - E-mu SP-1200     : 12-bit / 26.04 kHz — resonant SSM2044 filter artefacts
                         during pitch-shifting; distinct lo-fi resonance.
    - Akai S950        : 12-bit / variable SR — unique variable-bandwidth LPF;
                         key to "crunchy" drums.
    - Casio RZ-1       : 8-bit / 20 kHz — no anti-aliasing; extreme gritty
                         textures on user samples.
    - Roland TR-909    : 6-bit cymbals (custom Roland DAC) — heavy aliasing,
                         crunchy hi-hats; the defining cymbal sound of techno.

Historical context:
    The SP-1200 and S950 represent two distinct flavours of 12-bit grit.
    The SP-1200 (26.04 kHz sample rate) produces resonant artefacts during
    pitch-shifting via its SSM2044 filter. The S950 applies its unique
    variable-bandwidth LPF, giving a different, warmer character at the same
    bit depth. The RZ-1 has no anti-aliasing filter whatsoever — resulting in
    the most extreme lo-fi texture of the era.

Signal position: NoiseFloor → [Block 2] → ResonantFilter → ...
"""

from __future__ import annotations

import numpy as np
from engine.effects.base import BaseEffect


# ---------------------------------------------------------------------------
# Hardware presets
# ---------------------------------------------------------------------------

HARDWARE_PRESETS: dict[str, dict] = {
    "sp1200": {
        "bit_depth": 12,
        "target_sr": 26040,
        "description": "E-mu SP-1200 — 12-bit / 26.04 kHz, SSM2044 resonance",
    },
    "s950": {
        "bit_depth": 12,
        "target_sr": None,   # variable SR — no downsampling applied
        "description": "Akai S950 — 12-bit, variable-bandwidth LPF character",
    },
    "rz1": {
        "bit_depth": 8,
        "target_sr": 20000,
        "description": "Casio RZ-1 — 8-bit / 20 kHz, no anti-aliasing filter",
    },
    "909_cymbal": {
        "bit_depth": 6,
        "target_sr": None,
        "description": "Roland TR-909 cymbals — 6-bit custom DAC, heavy aliasing",
    },
}


class Bitcrusher(BaseEffect):
    """
    DAC emulation via bit depth and sample rate reduction.

    Reduces the resolution of the signal to emulate the characteristic
    lo-fi artefacts of classic hardware samplers and drum machines.
    Hardware presets override individual parameters when set.

    Args:
        bit_depth:            Target bit depth [4–24]. Default: 12.
        sample_rate_reduction: Downsampling factor [1–16]. 1 = no reduction.
                              Default: 1.
        dither:               Apply triangular dither before quantisation.
                              Reduces harsh quantisation distortion at low
                              bit depths. Default: True.
        mode:                 Quantisation algorithm.
                                'round'    — nearest neighbour (default)
                                'truncate' — floor toward zero
                                'floor'    — always round down
        hardware_preset:      Apply a hardware preset. Options:
                                'sp1200', 's950', 'rz1', '909_cymbal', None.
                              Overrides bit_depth and sample_rate_reduction.
                              Default: None.
        sr:                   Sample rate in Hz. Default: 44100.

    Example:
        >>> bc = Bitcrusher(hardware_preset='sp1200')
        >>> output = bc(signal)

        >>> bc = Bitcrusher(bit_depth=8, dither=False)
        >>> output = bc(signal)
    """

    def __init__(
        self,
        bit_depth: int = 12,
        sample_rate_reduction: int = 1,
        dither: bool = True,
        mode: str = "round",
        hardware_preset: str | None = None,
        sr: int = 44100,
    ) -> None:
        self.sr = sr
        self.dither = dither
        self.mode = mode
        self.hardware_preset = hardware_preset

        # Apply hardware preset if specified
        if hardware_preset is not None and hardware_preset in HARDWARE_PRESETS:
            preset = HARDWARE_PRESETS[hardware_preset]
            self.bit_depth = preset["bit_depth"]
            target_sr = preset["target_sr"]
            self.sample_rate_reduction = (
                max(1, int(sr / target_sr)) if target_sr else 1
            )
        else:
            self.bit_depth = bit_depth
            self.sample_rate_reduction = sample_rate_reduction

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply bit depth and sample rate reduction to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Bit-crushed audio array.
        """
        x = signal.copy()

        # --- Sample rate reduction (downsampling via sample-and-hold) ---
        if self.sample_rate_reduction > 1:
            x = np.repeat(
                x[:: self.sample_rate_reduction],
                self.sample_rate_reduction,
            )[: len(signal)]

        # --- Bit depth reduction ---
        levels = 2 ** self.bit_depth
        half_levels = levels / 2.0

        if self.dither:
            # Triangular probability density dither (TPDF)
            # Reduces quantisation distortion without adding correlated noise
            tpdf = (
                np.random.rand(len(x)) - np.random.rand(len(x))
            ) / levels
            x = x + tpdf

        if self.mode == "round":
            crushed = np.round(x * half_levels) / half_levels
        elif self.mode == "truncate":
            crushed = np.trunc(x * half_levels) / half_levels
        elif self.mode == "floor":
            crushed = np.floor(x * half_levels) / half_levels
        else:
            crushed = x

        return np.clip(crushed, -1.0, 1.0)

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""
        pass
