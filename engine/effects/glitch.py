"""
engine/effects/glitch.py

Block 8 — Glitch Engine (Braindance Stutter · ASR-10 Loop Modulation · XOR Bit Mangle).

Source:
    MASTER_DATASET — Glitch & Micro-Edit Processing
    Autechre — Tri Repetae (1995), Chiastic Slide (1997)
    Aphex Twin — Richard D. James Album (1996), Windowlicker (1999)

Hardware references:
    - Ensoniq ASR-10 (1992): 16-bit sampler with loop point modulation
      capabilities unprecedented for the era. Assigning LFOs to loop
      start/end parameters created granular artefacts years before
      "granular synthesis" entered mainstream production vocabulary.
      The 31.25 kHz maximum sample rate and 16-bit converters contributed
      additional lo-fi character baked into every sound.
      Notable users: Autechre (Tri Repetae, Chiastic Slide), BoC.

    - Braindance aesthetic (Rephlex Records, ~1991–2004): Micro-edit
      stutter technique — repeating tiny buffer slices at rhythmic
      subdivisions to create machine-gun fills and "skipping CD"
      artefacts. The technique exploits the perceptual boundary between
      rhythm and timbre (~50 ms) — stutters shorter than this threshold
      fuse into pitched buzzes, longer ones remain rhythmic.
      Aphex Twin (Come to Daddy, Windowlicker), Squarepusher (Hard
      Normal Daddy), µ-Ziq (Lunatic Harness).

    - XOR bit manipulation: Digital-domain corruption technique. Applying
      bitwise XOR to raw PCM sample values produces harsh, inharmonic
      artefacts characteristic of data-bent audio. Related to Oval's
      CD-skipping technique (Systemisch, 1994) and the broader "glitch"
      movement centred on Mille Plateaux and 12k labels.

Historical context:
    The glitch aesthetic emerged from two parallel lineages:

    Hardware accidents:
        Oval's scratched CDs, Yasunao Tone's wounded CDs, Nicolas Collins'
        circuit bending — errors elevated to compositional material. The
        philosophical premise: digital systems reveal their most interesting
        behaviour at failure boundaries.

    Sampler abuse:
        Autechre and Squarepusher pushing the ASR-10 and Akai S-series
        beyond intended use — extreme loop point modulation, deliberate
        buffer underruns, bit-depth reduction during playback. The
        "Tri Repetae" album title itself references triple-repeat loop
        modulation on the ASR-10.

    Three algorithms modelled here represent the core glitch toolkit:
        Stutter  — temporal fragmentation (buffer repeat)
        Loop mod — positional displacement (read-pointer warping)
        Bit mangle — data-level corruption (bitwise operations)

    Processing order: stutter → loop modulation → XOR mangle.
    Each stage operates independently and can be bypassed by setting
    its intensity/density parameter to 0.

Signal position: SpatialProcessor → [Block 8] → Compressor → ...
"""

from __future__ import annotations

import numpy as np
from engine.effects.base import BaseEffect


# ---------------------------------------------------------------------------
# XOR mask patterns — each produces a distinct corruption character
# Values target int16 PCM range (−32768 to +32767)
# ---------------------------------------------------------------------------

XOR_MASKS: dict[str, int] = {
    "subtle":   0x000F,   # 4 LSBs — gentle noise-floor corruption
    "moderate": 0x00FF,   # 8 LSBs — audible digital artefacts
    "heavy":    0x0FFF,   # 12 LSBs — severe data corruption
    "destroy":  0x7FFF,   # 15 bits — near-total signal destruction
}


class GlitchEngine(BaseEffect):
    """
    Glitch processor combining three complementary corruption algorithms.

    Stage 1 — Braindance Stutter:
        Scans the signal and probabilistically replaces segments with
        micro-repeated slices, producing the "skipping CD" / machine-gun
        fill effect central to the Rephlex/Warp IDM aesthetic.

    Stage 2 — ASR-10 Loop Modulation:
        Warps the read pointer with an LFO, emulating the Ensoniq ASR-10's
        loop-start modulation. Creates granular scanning artefacts —
        pitch-shifted micro-windows that smear temporal detail.

    Stage 3 — XOR Bit Mangle:
        Applies bitwise XOR to raw PCM values with configurable mask
        depth. Produces inharmonic digital corruption from subtle
        noise-floor texture to full signal destruction.

    Each stage is independently bypassable: set its density/depth
    parameter to 0 to skip processing.

    Args:
        stutter_density:     Probability of stutter per scan window [0.0–1.0].
                             0.0 = no stutter (bypass stage 1).
                             0.15 = sparse, rhythmically interesting fills.
                             1.0 = every segment stuttered (extreme).
                             Default: 0.15.
        stutter_min_ms:      Minimum stutter slice length in ms [1.0–100.0].
                             Slices below ~50 ms fuse into pitched buzzes.
                             Default: 5.0 ms.
        stutter_max_ms:      Maximum stutter slice length in ms [5.0–500.0].
                             Default: 60.0 ms.
        stutter_max_repeats: Maximum repetitions per stutter event [2–32].
                             Higher values produce longer "freeze" zones.
                             Default: 8.
        loop_mod_hz:         Loop modulation LFO rate in Hz [0.1–20.0].
                             Sub-1 Hz = slow granular drift.
                             5–20 Hz = aggressive pitch-warping.
                             Default: 2.0 Hz.
        loop_mod_depth:      Loop modulation intensity [0.0–1.0].
                             0.0 = no modulation (bypass stage 2).
                             Scales the LFO amplitude relative to
                             loop_window_ms. Default: 0.3.
        loop_window_ms:      Maximum read-pointer offset in ms [5.0–200.0].
                             Larger windows = more dramatic displacement.
                             Default: 40.0 ms.
        xor_mode:            Bit corruption depth preset.
                             Options: 'subtle', 'moderate', 'heavy', 'destroy'.
                             Default: 'subtle'.
        xor_density:         Probability of XOR per sample [0.0–1.0].
                             0.0 = no corruption (bypass stage 3).
                             Default: 0.1.
        mix:                 Dry/wet blend [0.0–1.0]. Default: 0.5.
        seed:                RNG seed for reproducible glitch patterns.
                             None = non-deterministic. Default: None.
        sr:                  Sample rate in Hz. Default: 44100.

    Example:
        >>> # Subtle IDM micro-edits (Autechre — Tri Repetae style)
        >>> ge = GlitchEngine(stutter_density=0.1, loop_mod_depth=0.2)
        >>> output = ge(signal)

        >>> # Aggressive braindance stutter (Squarepusher — Hard Normal Daddy)
        >>> ge = GlitchEngine(stutter_density=0.4, stutter_max_repeats=16,
        ...                   xor_mode='moderate', xor_density=0.05)

        >>> # Pure data corruption (Oval — Systemisch)
        >>> ge = GlitchEngine(stutter_density=0.0, loop_mod_depth=0.0,
        ...                   xor_mode='heavy', xor_density=0.3, mix=0.7)

        >>> # Reproducible pattern for A/B testing
        >>> ge = GlitchEngine(seed=42)
    """

    def __init__(
        self,
        # --- Stage 1: Braindance stutter ---
        stutter_density: float = 0.15,
        stutter_min_ms: float = 5.0,
        stutter_max_ms: float = 60.0,
        stutter_max_repeats: int = 8,
        # --- Stage 2: ASR-10 loop modulation ---
        loop_mod_hz: float = 2.0,
        loop_mod_depth: float = 0.3,
        loop_window_ms: float = 40.0,
        # --- Stage 3: XOR bit mangle ---
        xor_mode: str = "subtle",
        xor_density: float = 0.1,
        # --- Global ---
        mix: float = 0.5,
        seed: int | None = None,
        sr: int = 44100,
    ) -> None:
        self.stutter_density = np.clip(stutter_density, 0.0, 1.0)
        self.stutter_min_ms = max(stutter_min_ms, 1.0)
        self.stutter_max_ms = max(stutter_max_ms, self.stutter_min_ms + 1.0)
        self.stutter_max_repeats = max(int(stutter_max_repeats), 2)
        self.loop_mod_hz = np.clip(loop_mod_hz, 0.1, 20.0)
        self.loop_mod_depth = np.clip(loop_mod_depth, 0.0, 1.0)
        self.loop_window_ms = max(loop_window_ms, 1.0)
        self.xor_mode = xor_mode
        self.xor_density = np.clip(xor_density, 0.0, 1.0)
        self.mix = np.clip(mix, 0.0, 1.0)
        self.seed = seed
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply glitch processing to the input signal.

        Processing order: stutter → loop modulation → XOR mangle.
        Each stage is skipped when its intensity parameter is 0.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Glitch-processed audio array.
        """
        if len(signal) < 2:
            return signal

        dry = signal.copy()
        rng = np.random.default_rng(self.seed)

        wet = signal.copy()

        # Stage 1 — Braindance stutter
        if self.stutter_density > 0.0:
            wet = self._apply_stutter(wet, rng)

        # Stage 2 — ASR-10 loop modulation
        if self.loop_mod_depth > 0.0:
            wet = self._apply_loop_modulation(wet)

        # Stage 3 — XOR bit mangle
        if self.xor_density > 0.0:
            wet = self._apply_xor_mangle(wet, rng)

        return dry * (1.0 - self.mix) + wet * self.mix

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""
        pass

    # ------------------------------------------------------------------
    # Stage 1 — Braindance stutter
    # ------------------------------------------------------------------

    def _apply_stutter(
        self, signal: np.ndarray, rng: np.random.Generator
    ) -> np.ndarray:
        """
        Probabilistic micro-repeat stutter.

        Scans the signal with a variable-length window. At each position,
        a random draw against stutter_density decides whether to trigger
        a stutter event. When triggered, a slice of random length (within
        min/max bounds) is extracted and tiled to fill the stutter zone.

        The non-triggered advance step is also randomised to prevent
        mechanical regularity in the stutter pattern.
        """
        n = len(signal)
        output = signal.copy()

        min_samp = max(int(self.stutter_min_ms * self.sr / 1000), 1)
        max_samp = max(int(self.stutter_max_ms * self.sr / 1000), min_samp + 1)

        pos = 0
        while pos < n - min_samp:
            if rng.random() < self.stutter_density:
                # --- Stutter event ---
                slice_len = int(rng.integers(min_samp, max_samp))
                slice_len = min(slice_len, n - pos)

                num_repeats = int(rng.integers(2, self.stutter_max_repeats + 1))

                # Extract grain and tile into output
                grain = output[pos : pos + slice_len].copy()
                total_len = min(slice_len * num_repeats, n - pos)

                write_pos = pos
                end_pos = pos + total_len
                while write_pos < end_pos:
                    chunk = min(slice_len, end_pos - write_pos)
                    output[write_pos : write_pos + chunk] = grain[:chunk]
                    write_pos += chunk

                pos = end_pos
            else:
                # --- No stutter: advance by random step ---
                step = int(rng.integers(min_samp, max_samp))
                pos += step

        return output

    # ------------------------------------------------------------------
    # Stage 2 — ASR-10 loop modulation
    # ------------------------------------------------------------------

    def _apply_loop_modulation(self, signal: np.ndarray) -> np.ndarray:
        """
        Read-pointer warping via LFO, emulating ASR-10 loop-start modulation.

        A sine LFO modulates the read position offset. When the offset
        changes, the output "scans" through nearby signal content,
        producing granular pitch/time artefacts.

        Uses vectorised linear interpolation — no per-sample loop.
        """
        n = len(signal)
        max_offset_samp = int(self.loop_window_ms * self.sr / 1000)

        # LFO: sine + inharmonic secondary (ratio 3.17 avoids periodic beating)
        t = np.arange(n, dtype=np.float64) / self.sr
        lfo_primary = np.sin(2.0 * np.pi * self.loop_mod_hz * t)
        lfo_secondary = np.sin(2.0 * np.pi * self.loop_mod_hz * 3.17 * t) * 0.25
        lfo = lfo_primary + lfo_secondary

        # Modulated read indices
        offsets = lfo * self.loop_mod_depth * max_offset_samp
        read_indices = np.arange(n, dtype=np.float64) + offsets
        read_indices = np.clip(read_indices, 0.0, n - 1.0)

        # Vectorised linear interpolation
        idx_floor = np.floor(read_indices).astype(np.intp)
        idx_ceil = np.minimum(idx_floor + 1, n - 1)
        frac = read_indices - idx_floor

        return signal[idx_floor] * (1.0 - frac) + signal[idx_ceil] * frac

    # ------------------------------------------------------------------
    # Stage 3 — XOR bit mangle
    # ------------------------------------------------------------------

    def _apply_xor_mangle(
        self, signal: np.ndarray, rng: np.random.Generator
    ) -> np.ndarray:
        """
        Bitwise XOR corruption on raw PCM values.

        Converts the float signal to int16 representation, applies an XOR
        mask at randomly selected sample positions (controlled by
        xor_density), then converts back to float.

        The mask depth determines corruption severity — from subtle
        noise-floor texture (4 LSBs) to near-total destruction (15 bits).
        """
        n = len(signal)
        mask = XOR_MASKS.get(self.xor_mode, XOR_MASKS["subtle"])

        # Float → int16 (clamp to prevent overflow at ±1.0 boundary)
        clamped = np.clip(signal, -1.0, 1.0)
        int_signal = (clamped * 32767.0).astype(np.int16)

        # Probabilistic application mask
        apply_where = rng.random(n) < self.xor_density

        # Apply XOR at selected positions
        int_signal[apply_where] ^= np.int16(mask)

        # int16 → float, normalised back to [-1.0, 1.0]
        return int_signal.astype(np.float64) / 32767.0
