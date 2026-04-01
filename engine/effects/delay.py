"""
engine/effects/delay.py

Block 6 — Tape Delay (Roland Space Echo RE-201 Emulation).

Source:
    MASTER_DATASET Part 8 — Spatial Processing & Time-Based Effects
    Roland Space Echo (Tape Saturation)

Hardware references:
    - Roland Space Echo RE-201 (1974–1990): Three tape read heads, spring
      reverb, analog tape loop. Remained in production for 14 straight years.
      The defining tape echo for reggae/dub, IDM, and post-rock.

    - Basic Channel (Maurizio / Mark Ernestus): Heavy use of RE-201 in
      dub-techno delay chains — long feedback tails with tape saturation
      creating evolving, self-similar textures.

Historical context:
    The RE-201's sound character comes from several interacting physical
    mechanisms:

    Wow & Flutter:
        The tape motor and capstan/pinch roller introduce mechanical
        instability — slow pitch variations (wow) and faster irregular
        variations (flutter). Combined, they produce the characteristic
        "swimming" pitch instability of tape echo.

    Tape Head Saturation:
        The read/write heads saturate at high signal levels, introducing
        harmonic distortion (tanh) into the feedback path. This is what
        makes the RE-201 "warm" rather than clinical.

    Tape Age / HF Rolloff:
        Older tape loses high-frequency response due to oxide shedding
        and head wear. Three conditions modelled:
            new  → 14 kHz cutoff
            used → 8 kHz cutoff  (default — most period-accurate)
            worn → 4.5 kHz cutoff

    Self-Oscillation:
        At feedback > 0.95, the delay enters self-oscillation — the
        tail builds into a resonant drone. Used deliberately in dub
        and IDM for sustained textural effects.

Signal position: Reverb → [Block 6] → SpatialProcessor → ...
"""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal
from engine.effects.base import BaseEffect


# ---------------------------------------------------------------------------
# Tape age HF cutoff frequencies (Hz)
# ---------------------------------------------------------------------------

TAPE_AGE_CUTOFF: dict[str, int] = {
    "new":  14000,
    "used": 8000,
    "worn": 4500,
}


class TapeDelay(BaseEffect):
    """
    Roland Space Echo RE-201 tape delay emulation.

    Models the four key characteristics of the RE-201:
    wow & flutter pitch modulation, tape head saturation, HF rolloff
    dependent on tape condition, and self-oscillation at high feedback.

    Args:
        delay_ms:       Delay time in milliseconds [20–1200].
                        Default: 375.0 ms (RE-201 head 2 at mid rate).
        feedback:       Feedback amount [0.0–0.98].
                        Values above 0.95 approach self-oscillation.
                        Default: 0.45.
        tape_saturation: Read head saturation depth [0.0–1.0].
                        0.0 = clean digital delay.
                        1.0 = heavily saturated tape character.
                        Default: 0.4.
        wow_flutter_hz: Wow & flutter modulation rate in Hz [0.0–4.0].
                        Wow: slow motor instability (~0.5–1.5 Hz).
                        Flutter: faster capstan variation (~3–7 Hz).
                        Default: 0.8 Hz.
        wow_depth:      Pitch modulation depth [0.0–0.02].
                        Scales the LFO amplitude as a fraction of SR.
                        Default: 0.004 (subtle, period-accurate).
        tape_age:       Tape condition. Options: 'new', 'used', 'worn'.
                        Controls HF rolloff in the feedback path.
                        Default: 'used'.
        mix:            Dry/wet blend [0.0–1.0]. Default: 0.35.
        sr:             Sample rate in Hz. Default: 44100.

    Example:
        >>> td = TapeDelay(delay_ms=375, feedback=0.5, tape_age='used')
        >>> output = td(signal)

        >>> # Self-oscillation drone (dub-style)
        >>> td = TapeDelay(delay_ms=500, feedback=0.96, tape_saturation=0.7)

        >>> # Clean short slapback
        >>> td = TapeDelay(delay_ms=80, feedback=0.2, tape_age='new', mix=0.2)
    """

    def __init__(
        self,
        delay_ms: float = 375.0,
        feedback: float = 0.45,
        tape_saturation: float = 0.4,
        wow_flutter_hz: float = 0.8,
        wow_depth: float = 0.004,
        tape_age: str = "used",
        mix: float = 0.35,
        sr: int = 44100,
    ) -> None:
        if tape_age not in TAPE_AGE_CUTOFF:
            raise ValueError(
                f"Invalid tape_age '{tape_age}'. "
                f"Options: {sorted(TAPE_AGE_CUTOFF.keys())}"
            )

        self.delay_ms = delay_ms
        self.feedback = np.clip(feedback, 0.0, 0.98)
        self.tape_saturation = tape_saturation
        self.wow_flutter_hz = wow_flutter_hz
        self.wow_depth = wow_depth
        self.tape_age = tape_age
        self.mix = mix
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply tape delay to the input signal.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Tape-delayed audio array.
        """
        n = len(signal)
        dry = signal.copy()
        delay_samples = int(self.delay_ms * self.sr / 1000)

        # Wow & flutter: combined pitch modulation
        modulation = self._generate_wow_flutter(n)

        # Tape HF rolloff (age-dependent)
        sos_tape = self._build_tape_filter()

        # Delay buffer — extra headroom for modulation offset
        max_mod_offset = int(self.wow_depth * self.sr) + 1
        buf_len = delay_samples + max_mod_offset + n + 1
        buf = np.zeros(buf_len)
        buf[:n] = signal
        wet = np.zeros(n)

        for i in range(n):
            mod_offset = int(modulation[i] * self.sr)
            read_idx = int(
                np.clip(i + delay_samples + mod_offset, 0, buf_len - 1)
            )
            delayed_sample = buf[read_idx]

            # Tape head saturation in feedback path
            saturated = np.tanh(
                delayed_sample * (1.0 + self.tape_saturation * 3.0)
            )
            wet[i] = saturated

            write_idx = i + delay_samples
            if write_idx < buf_len:
                buf[write_idx] += saturated * self.feedback

        # Apply tape frequency response (HF rolloff)
        wet = scipy_signal.sosfilt(sos_tape, wet)

        return dry * (1.0 - self.mix) + wet * self.mix

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""
        pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_wow_flutter(self, n: int) -> np.ndarray:
        """
        Generate combined wow & flutter modulation signal.

        Wow: sine LFO at wow_flutter_hz — slow motor speed variation.
        Flutter: sine LFO at 7.3× wow rate — faster capstan/roller variation.
        The 7.3 ratio is inharmonic, preventing periodic beating artefacts.
        """
        t = np.arange(n) / self.sr
        wow = np.sin(2.0 * np.pi * self.wow_flutter_hz * t) * self.wow_depth
        flutter = (
            np.sin(2.0 * np.pi * (self.wow_flutter_hz * 7.3) * t)
            * self.wow_depth
            * 0.3
        )
        return wow + flutter

    def _build_tape_filter(self) -> np.ndarray:
        """
        Build low-pass SOS filter modelling tape HF rolloff.

        Cutoff frequency depends on tape_age:
            new  → 14 kHz (minimal oxide loss)
            used → 8 kHz  (moderate wear, period-accurate default)
            worn → 4.5 kHz (heavy head wear, thick/dark character)
        """
        cutoff_hz = TAPE_AGE_CUTOFF.get(self.tape_age, 8000)
        cutoff_norm = np.clip(cutoff_hz / (self.sr / 2.0), 0.001, 0.999)
        return scipy_signal.butter(2, cutoff_norm, btype="low", output="sos")
