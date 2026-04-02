"""
engine/effects/vinyl.py

Block 10 — Vinyl Mastering (Pre-Emphasis EQ · DAT Brick-Wall · RIAA Curve).

Source:
    MASTER_DATASET — Mastering & Final Output Processing
    Vinyl pre-emphasis, DAT brick-wall 16 kHz ceiling

Hardware references:
    - RIAA pre-emphasis / de-emphasis curve (1954 standard): The Recording
      Industry Association of America equalisation standard defines the
      frequency response applied during vinyl cutting and playback. During
      cutting, bass is attenuated and treble is boosted (pre-emphasis) to
      fit the physical constraints of the groove. On playback, the inverse
      curve (de-emphasis) is applied, restoring flat response while reducing
      surface noise in the treble range. The three time constants:
          τ₁ = 3180 µs (50.05 Hz turnover)
          τ₂ = 318 µs  (500.5 Hz turnover)
          τ₃ = 75 µs   (2122 Hz turnover)

    - Sony PCM-1600 / PCM-1630 (1979–1990): Early digital mastering
      processors that recorded 16-bit PCM audio onto U-matic videotape.
      The PCM-1630 was the standard CD pre-mastering format throughout
      the 1980s. Anti-aliasing at 44.1 kHz with steep brick-wall filters
      introduced pre-ringing artefacts on transients — a characteristic
      of early digital that became part of the IDM aesthetic.

    - Sony DTC-1000ES DAT recorder (1987): First consumer DAT deck.
      44.1/48 kHz sampling, 16-bit. The anti-aliasing filters imposed
      a hard ceiling — typically rolling off steeply above 20 kHz at
      48 kHz mode, or ~16 kHz in the long-play 32 kHz mode. Many early
      IDM productions were bounced through DAT as the final master
      medium, imprinting this bandwidth limitation.

    - Technics SL-1200 (1972–present): The reference turntable. Surface
      noise character depends on vinyl condition — new pressings exhibit
      minimal noise, while worn records develop crackle, pop, and
      continuous hiss from groove degradation.

Historical context:
    The "vinyl mastering" sound in IDM represents a deliberate aesthetic
    choice — applying the coloration of analogue mastering chains to
    digital productions. Three distinct mechanisms combine:

    RIAA EQ coloration:
        Even when applied and inverted correctly, the RIAA curve
        introduces phase shift across the spectrum. Imperfect playback
        alignment (common on consumer turntables) leaves residual EQ
        coloration — typically a slight bass boost and treble roll-off
        that contributes to the "warm vinyl" character.

    Bandwidth limitation:
        DAT's brick-wall filter at 16–20 kHz removes ultrasonic content
        and introduces Gibbs phenomenon (pre-ringing) on sharp transients.
        This bandwidth ceiling is audibly different from gentle analogue
        roll-off — it's abrupt and phase-distorting. Combined with the
        RIAA treble attenuation, it creates a dense, enclosed high-end.

    Surface texture:
        Vinyl surface noise (hiss, crackle) adds a continuous noise bed
        that psychoacoustically "fills in" gaps between sparse elements.
        In IDM, this texture is often deliberately emphasised — it unifies
        disparate timbres under a shared physical medium identity.

    Processing order: RIAA pre-emphasis → DAT brick-wall → surface
    noise addition → final peak limiter.

Signal position: Compressor → [Block 10] → OUTPUT
"""

from __future__ import annotations

import numpy as np
from scipy import signal as scipy_signal

from engine.effects.base import BaseEffect

# ---------------------------------------------------------------------------
# RIAA time constants (seconds) — 1954 standard
# ---------------------------------------------------------------------------

RIAA_TAU: dict[str, float] = {
    "tau1": 3180e-6,  # 50.05 Hz  — bass shelf
    "tau2": 318e-6,  # 500.5 Hz  — midrange turnover
    "tau3": 75e-6,  # 2122 Hz   — treble boost/cut
}


# ---------------------------------------------------------------------------
# Vinyl condition presets — noise floor and crackle characteristics
# ---------------------------------------------------------------------------

VINYL_CONDITION: dict[str, dict[str, float]] = {
    "mint": {
        "hiss_level": 0.0003,  # barely audible surface noise
        "crackle_rate": 0.0001,  # rare pops
        "crackle_level": 0.005,
    },
    "good": {
        "hiss_level": 0.0008,  # light continuous hiss
        "crackle_rate": 0.0005,  # occasional pops
        "crackle_level": 0.015,
    },
    "worn": {
        "hiss_level": 0.002,  # prominent surface noise
        "crackle_rate": 0.002,  # frequent crackle
        "crackle_level": 0.04,
    },
    "trashed": {
        "hiss_level": 0.005,  # heavy noise floor
        "crackle_rate": 0.008,  # dense crackle texture
        "crackle_level": 0.08,
    },
}


# ---------------------------------------------------------------------------
# DAT bandwidth ceiling presets (Hz)
# ---------------------------------------------------------------------------

DAT_BANDWIDTH: dict[str, int] = {
    "dat_lp": 16000,  # DAT long-play 32 kHz mode — 16 kHz ceiling
    "dat_sp": 20000,  # DAT standard-play 48 kHz mode — 20 kHz ceiling
    "cd": 22050,  # CD 44.1 kHz — Nyquist limit
    "none": 0,  # bypass bandwidth limiting
}


class VinylMastering(BaseEffect):
    """
    Vinyl mastering emulation — final output processor.

    Applies analogue mastering chain coloration to the output signal:
    RIAA equalisation, DAT bandwidth limiting, vinyl surface texture,
    and a final peak limiter to prevent digital overs.

    Args:
        riaa_intensity:     RIAA curve application depth [0.0–1.0].
                            0.0 = bypass RIAA processing.
                            0.3 = subtle vinyl coloration (default).
                            1.0 = full pre-emphasis curve.
                            Default: 0.3.
        dat_mode:           DAT bandwidth ceiling preset.
                            Options: 'dat_lp' (16 kHz), 'dat_sp' (20 kHz),
                            'cd' (22.05 kHz), 'none' (bypass).
                            Default: 'dat_lp'.
        dat_filter_order:   Brick-wall filter steepness [2–12].
                            Higher order = steeper roll-off, more pre-ring.
                            8 = period-accurate Sony PCM-1630 character.
                            Default: 8.
        vinyl_condition:    Surface noise character preset.
                            Options: 'mint', 'good', 'worn', 'trashed'.
                            Default: 'good'.
        noise_mix:          Surface noise blend [0.0–1.0].
                            0.0 = no surface noise.
                            Default: 0.15.
        limiter_ceiling_db: Final peak limiter ceiling in dBFS [-6.0–0.0].
                            Prevents digital overs after processing.
                            Default: -0.3 dB.
        mix:                Dry/wet blend [0.0–1.0]. Default: 1.0.
        seed:               RNG seed for reproducible noise textures.
                            None = non-deterministic. Default: None.
        sr:                 Sample rate in Hz. Default: 44100.

    Example:
        >>> # Standard IDM vinyl mastering
        >>> vm = VinylMastering(riaa_intensity=0.3, dat_mode="dat_lp")
        >>> output = vm(signal)

        >>> # Heavy vinyl character (worn record through DAT)
        >>> vm = VinylMastering(
        ...     riaa_intensity=0.6, vinyl_condition="worn", noise_mix=0.3, dat_mode="dat_lp"
        ... )

        >>> # Clean digital master (bypass vinyl, DAT ceiling only)
        >>> vm = VinylMastering(riaa_intensity=0.0, noise_mix=0.0, dat_mode="dat_sp")

        >>> # Maximum degradation (trashed vinyl aesthetic)
        >>> vm = VinylMastering(
        ...     riaa_intensity=0.8, vinyl_condition="trashed", noise_mix=0.5, dat_mode="dat_lp"
        ... )
    """

    def __init__(
        self,
        riaa_intensity: float = 0.3,
        dat_mode: str = "dat_lp",
        dat_filter_order: int = 8,
        vinyl_condition: str = "good",
        noise_mix: float = 0.15,
        limiter_ceiling_db: float = -0.3,
        mix: float = 1.0,
        seed: int | None = None,
        sr: int = 44100,
    ) -> None:
        if dat_mode not in DAT_BANDWIDTH:
            raise ValueError(
                f"Invalid dat_mode '{dat_mode}'. Options: {sorted(DAT_BANDWIDTH.keys())}"
            )
        if vinyl_condition not in VINYL_CONDITION:
            raise ValueError(
                f"Invalid vinyl_condition '{vinyl_condition}'. "
                f"Options: {sorted(VINYL_CONDITION.keys())}"
            )

        self.riaa_intensity = np.clip(riaa_intensity, 0.0, 1.0)
        self.dat_mode = dat_mode
        self.dat_filter_order = np.clip(int(dat_filter_order), 2, 12)
        self.vinyl_condition = vinyl_condition
        self.noise_mix = np.clip(noise_mix, 0.0, 1.0)
        self.limiter_ceiling_db = np.clip(limiter_ceiling_db, -6.0, 0.0)
        self.mix = np.clip(mix, 0.0, 1.0)
        self.seed = seed
        self.sr = sr

    def __call__(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply vinyl mastering chain to the input signal.

        Processing order: RIAA pre-emphasis → DAT brick-wall →
        surface noise → peak limiter.

        Args:
            signal: Input audio array, normalised to [-1.0, 1.0].

        Returns:
            Vinyl-mastered audio array.
        """
        if len(signal) < 2:
            return signal

        dry = signal.copy()
        rng = np.random.default_rng(self.seed)

        wet = signal.copy()

        # Stage 1 — RIAA pre-emphasis EQ
        if self.riaa_intensity > 0.0:
            wet = self._apply_riaa(wet)

        # Stage 2 — DAT brick-wall bandwidth ceiling
        if self.dat_mode != "none":
            wet = self._apply_dat_ceiling(wet)

        # Stage 3 — Vinyl surface noise
        if self.noise_mix > 0.0:
            wet = self._apply_surface_noise(wet, rng)

        # Stage 4 — Final peak limiter
        wet = self._apply_limiter(wet)

        return dry * (1.0 - self.mix) + wet * self.mix

    def reset(self) -> None:
        """Stateless effect — nothing to reset."""

    # ------------------------------------------------------------------
    # Stage 1 — RIAA pre-emphasis
    # ------------------------------------------------------------------

    def _apply_riaa(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply RIAA pre-emphasis curve scaled by riaa_intensity.

        The RIAA curve is implemented as a combination of shelving filters
        derived from the three standard time constants. The intensity
        parameter cross-fades between flat response and full RIAA
        application, allowing subtle vinyl coloration without committing
        to the full curve.

        At intensity=1.0, the curve matches the cutting-head pre-emphasis:
            - Bass attenuation below 50 Hz (τ₁ = 3180 µs)
            - Flat midrange plateau (τ₂ = 318 µs)
            - Treble boost above 2122 Hz (τ₃ = 75 µs)
        """
        # Derive RIAA corner frequencies from time constants
        f1 = 1.0 / (2.0 * np.pi * RIAA_TAU["tau1"])  # ~50.05 Hz
        f3 = 1.0 / (2.0 * np.pi * RIAA_TAU["tau3"])  # ~2122 Hz
        nyquist = self.sr / 2.0

        # Bass shelf — attenuate below f1 (RIAA bass roll-off)
        f1_norm = np.clip(f1 / nyquist, 0.001, 0.999)
        sos_bass = scipy_signal.butter(1, f1_norm, btype="high", output="sos")

        # Treble shelf — boost above f3 (RIAA treble pre-emphasis)
        f3_norm = np.clip(f3 / nyquist, 0.001, 0.999)
        sos_treble = scipy_signal.butter(1, f3_norm, btype="high", output="sos")

        # Apply RIAA filters
        riaa_signal = scipy_signal.sosfilt(sos_bass, signal)
        treble_boost = scipy_signal.sosfilt(sos_treble, signal)

        # Blend treble boost into the bass-shaped signal
        # Scale: riaa_intensity controls the depth of EQ coloration
        intensity = float(self.riaa_intensity)
        processed = riaa_signal + treble_boost * intensity * 0.3

        # Cross-fade between dry and RIAA-processed
        return signal * (1.0 - intensity) + processed * intensity

    # ------------------------------------------------------------------
    # Stage 2 — DAT brick-wall filter
    # ------------------------------------------------------------------

    def _apply_dat_ceiling(self, signal: np.ndarray) -> np.ndarray:
        """
        Apply steep low-pass filter emulating DAT anti-aliasing.

        The Sony PCM-1630 and consumer DAT decks used high-order
        anti-aliasing filters that imposed a hard bandwidth ceiling.
        The steep roll-off introduces Gibbs phenomenon (pre-ringing)
        on transients — audibly different from gentle analogue roll-off.

        Filter order controls steepness:
            Order 2  — gentle roll-off (minimal pre-ring)
            Order 8  — period-accurate Sony PCM character (default)
            Order 12 — aggressive brick-wall (maximum pre-ring)
        """
        ceiling_hz = DAT_BANDWIDTH.get(self.dat_mode, 0)
        if ceiling_hz <= 0:
            return signal

        nyquist = self.sr / 2.0
        cutoff_norm = np.clip(ceiling_hz / nyquist, 0.001, 0.999)

        sos = scipy_signal.butter(
            int(self.dat_filter_order),
            cutoff_norm,
            btype="low",
            output="sos",
        )
        return scipy_signal.sosfilt(sos, signal)

    # ------------------------------------------------------------------
    # Stage 3 — Vinyl surface noise
    # ------------------------------------------------------------------

    def _apply_surface_noise(self, signal: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """
        Add vinyl surface noise — continuous hiss and sporadic crackle.

        Hiss: band-limited Gaussian noise shaped to match the spectral
        profile of vinyl surface noise (emphasis in the 1–6 kHz range,
        roll-off below 500 Hz and above 10 kHz).

        Crackle: sparse, high-amplitude impulses with fast exponential
        decay (~0.5 ms), emulating dust and groove damage artefacts.
        Crackle timing is stochastic (Poisson-like distribution).
        """
        n = len(signal)
        condition = VINYL_CONDITION.get(self.vinyl_condition, VINYL_CONDITION["good"])

        noise = np.zeros(n)

        # --- Continuous hiss ---
        hiss_level = condition["hiss_level"]
        if hiss_level > 0.0:
            raw_hiss = rng.standard_normal(n) * hiss_level

            # Shape hiss spectrum: bandpass 800 Hz – 8 kHz
            nyquist = self.sr / 2.0
            low_norm = np.clip(800.0 / nyquist, 0.001, 0.999)
            high_norm = np.clip(8000.0 / nyquist, 0.001, 0.999)

            if low_norm < high_norm:
                sos_hiss = scipy_signal.butter(2, [low_norm, high_norm], btype="band", output="sos")
                raw_hiss = scipy_signal.sosfilt(sos_hiss, raw_hiss)

            noise += raw_hiss

        # --- Sporadic crackle ---
        crackle_rate = condition["crackle_rate"]
        crackle_level = condition["crackle_level"]

        if crackle_rate > 0.0 and crackle_level > 0.0:
            # Poisson-distributed crackle events
            crackle_mask = rng.random(n) < crackle_rate
            crackle_positions = np.where(crackle_mask)[0]

            # Each crackle: short impulse with exponential decay (~0.5 ms)
            decay_samples = max(int(0.0005 * self.sr), 1)

            for pos in crackle_positions:
                polarity = rng.choice([-1.0, 1.0])
                amplitude = crackle_level * (0.5 + 0.5 * rng.random())
                end = min(pos + decay_samples, n)
                length = end - pos

                decay_env = np.exp(-np.arange(length, dtype=np.float64) / (decay_samples * 0.2))
                noise[pos:end] += polarity * amplitude * decay_env

        # Mix noise into signal
        return signal + noise * self.noise_mix

    # ------------------------------------------------------------------
    # Stage 4 — Final peak limiter
    # ------------------------------------------------------------------

    def _apply_limiter(self, signal: np.ndarray) -> np.ndarray:
        """
        Transparent peak limiter — prevents digital overs.

        Uses soft clipping (tanh) scaled to the ceiling level. The tanh
        curve provides graceful saturation rather than hard clipping,
        preserving transient shape while enforcing the ceiling.

        This is the absolute last stage before output — nothing should
        follow it in the signal chain.
        """
        ceiling_linear = float(np.power(10.0, self.limiter_ceiling_db / 20.0))

        # Scale signal so ceiling maps to tanh(1.0) ≈ 0.7616
        # Then rescale output to actual ceiling level
        peak = np.max(np.abs(signal))
        if peak <= ceiling_linear:
            return signal

        # Normalise to ceiling, soft-clip, restore level
        scaled = signal / peak
        clipped = np.tanh(scaled * 1.5) * ceiling_linear
        return clipped
