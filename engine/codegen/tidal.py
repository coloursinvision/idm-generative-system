"""
engine/codegen/tidal.py

TidalCycles code generator for the IDM Generative System.

Generates structurally valid Haskell DSL code for TidalCycles, including:

    - Pattern translation (Euclidean → e(k,n), probabilistic → ?, density)
    - Effect mapping (reverb, delay, filter, bitcrusher, saturation, pan)
    - Multi-track stack for multi-voice patterns
    - Studio mode (full setup with setcps, hush) or live mode (bare d1/d2)

Usage:
    from engine.codegen.tidal import TidalCyclesCodegen
    from engine.codegen.base import CodegenInput

    tc = TidalCyclesCodegen()
    result = tc.generate(CodegenInput(
        generator="fm_blip",
        generator_params={"freq": 300},
        effects={"reverb": {"decay_s": 3.0}, "delay": {"feedback": 0.6}},
        pattern={"type": "euclidean", "pulses": {"kick": 5, "snare": 3}, "steps": 16},
    ))
    print(result.code)
"""

from __future__ import annotations

from typing import Any

from engine.codegen.base import (
    BaseCodegen,
    CodegenInput,
    CodegenMode,
    CodegenOptions,
    CodegenResult,
    CodegenTarget,
)
from engine.codegen.mappings import (
    SC_GENERATORS,
    get_tidal_effect_params,
    get_tidal_unmapped,
    transform_param,
)

# ---------------------------------------------------------------------------
# TidalCycles code generator
# ---------------------------------------------------------------------------


class TidalCyclesCodegen(BaseCodegen):
    """Generate TidalCycles Haskell DSL code from engine configurations.

    Produces ready-to-evaluate Tidal patterns with effect chains,
    supporting both studio (full setup) and live (bare patterns) modes.
    """

    def generate(self, codegen_input: CodegenInput) -> CodegenResult:
        """Generate a complete TidalCycles script.

        Args:
            codegen_input: Validated CodegenInput instance.

        Returns:
            CodegenResult with Tidal code, warnings, metadata, and setup notes.

        Raises:
            ValueError: If input validation fails.
        """
        errors = self.validate(codegen_input)
        if errors:
            raise ValueError(f"Codegen input validation failed: {'; '.join(errors)}")

        warnings: list[str] = []
        unmapped: dict[str, list[str]] = {}
        opts = codegen_input.options

        # --- Build sections ---
        header = self._build_header(codegen_input)
        setup = self._build_setup(opts) if opts.mode == CodegenMode.STUDIO else ""
        pattern_code = self._build_pattern_code(codegen_input, warnings, unmapped)
        effects_code = self._build_effects_code(codegen_input, warnings, unmapped)
        cleanup = self._build_cleanup(opts)

        # --- Assemble complete code ---
        full_pattern = self._assemble_pattern_with_effects(
            codegen_input, pattern_code, effects_code, opts
        )

        sections = [header]
        if setup:
            sections.append(setup)
        sections.append(full_pattern)
        if cleanup:
            sections.append(cleanup)

        code = "\n\n".join(s for s in sections if s)

        # --- Metadata ---
        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        tidal_sound = gen_mapping.tidal_name if gen_mapping else "unknown"

        metadata: dict[str, Any] = {
            "tidal_sound": tidal_sound,
            "orbits": self._get_orbit_assignments(codegen_input),
            "mode": opts.mode.value,
            "bpm": opts.bpm,
        }

        setup_notes = self._build_setup_notes(opts)

        return CodegenResult(
            code=code,
            target=CodegenTarget.TIDALCYCLES,
            mode=opts.mode,
            warnings=warnings,
            unmapped_params=unmapped,
            metadata=metadata,
            setup_notes=setup_notes,
        )

    # ------------------------------------------------------------------
    # Header & setup
    # ------------------------------------------------------------------

    def _build_header(self, codegen_input: CodegenInput) -> str:
        gen_name = codegen_input.generator
        mode = codegen_input.options.mode.value
        fx_keys = sorted(codegen_input.effects.keys())
        fx_list = ", ".join(fx_keys) if fx_keys else "none"

        return (
            f"-- ===================================================================\n"
            f"-- IDM Generative System — TidalCycles Output\n"
            f"-- Generator: {gen_name}\n"
            f"-- Effects:   {fx_list}\n"
            f"-- Mode:      {mode}\n"
            f"-- ==================================================================="
        )

    def _build_setup(self, opts: CodegenOptions) -> str:
        return (
            f"-- Setup: tempo and configuration\n"
            f"-- Evaluate this block first\n"
            f"setcps ({opts.bpm}/120/2)"
        )

    # ------------------------------------------------------------------
    # Generator code (Tidal sound selection)
    # ------------------------------------------------------------------

    def _build_generator_code(self, codegen_input: CodegenInput) -> str:
        """Build Tidal sound string for the generator.

        Not used directly — incorporated into pattern building.
        Returns the sound name string.
        """
        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        if gen_mapping is None:
            return "unknown"
        return gen_mapping.tidal_name

    # ------------------------------------------------------------------
    # Pattern code
    # ------------------------------------------------------------------

    def _build_pattern_code(
        self,
        codegen_input: CodegenInput,
        warnings: list[str],
        unmapped: dict[str, list[str]],
    ) -> str:
        """Build the Tidal pattern string (without effects).

        Returns the pattern expression as a string.
        """
        if codegen_input.pattern is None:
            # No pattern — single trigger
            gen_mapping = SC_GENERATORS.get(codegen_input.generator)
            sound = gen_mapping.tidal_name if gen_mapping else "unknown"
            return f's "{sound}"'

        pattern = codegen_input.pattern
        ptype = pattern.get("type", "euclidean")
        steps = pattern.get("steps", 16)

        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        sound = gen_mapping.tidal_name if gen_mapping else "unknown"

        if ptype == "euclidean":
            return self._build_euclidean_pattern(sound, pattern, steps)
        if ptype == "probabilistic":
            return self._build_probabilistic_pattern(sound, pattern, steps)
        if ptype == "density":
            return self._build_density_pattern(sound, pattern, steps)

        warnings.append(f"Unknown pattern type '{ptype}' — using simple trigger")
        return f's "{sound}"'

    def _build_euclidean_pattern(self, sound: str, pattern: dict[str, Any], steps: int) -> str:
        """Build Euclidean pattern using Tidal's native e() syntax.

        Multi-track patterns (multiple pulse counts) use stack [].
        Single-track patterns use inline e() notation.
        """
        pulses = pattern.get("pulses", {})

        if not pulses:
            return f's "{sound}({5},{steps})"'

        if len(pulses) == 1:
            track_name, k = next(iter(pulses.items()))
            return f's "{sound}({k},{steps})"'

        # Multi-track: stack
        lines = ["stack ["]
        entries = list(pulses.items())
        for i, (track_name, k) in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            comment = f"  -- {track_name}"
            lines.append(f'  s "{sound}({k},{steps})"{comma}{comment}')
        lines.append("  ]")
        return "\n".join(lines)

    def _build_probabilistic_pattern(self, sound: str, pattern: dict[str, Any], steps: int) -> str:
        """Build probabilistic pattern using Tidal's ? operator.

        Each step has a probability of triggering, expressed via
        degradeBy in Tidal.
        """
        probs = pattern.get("probabilities", {})
        if not probs:
            return f's "{sound}*{steps}" |?| 0.3'

        if len(probs) == 1:
            track_name, prob = next(iter(probs.items()))
            return f'degradeBy {1.0 - prob:.2f} $ s "{sound}*{steps}"'

        # Multi-track with different probabilities
        lines = ["stack ["]
        entries = list(probs.items())
        for i, (track_name, prob) in enumerate(entries):
            comma = "," if i < len(entries) - 1 else ""
            comment = f"  -- {track_name} (p={prob})"
            lines.append(f'  degradeBy {1.0 - prob:.2f} $ s "{sound}*{steps}"{comma}{comment}')
        lines.append("  ]")
        return "\n".join(lines)

    def _build_density_pattern(self, sound: str, pattern: dict[str, Any], steps: int) -> str:
        """Build density-controlled pattern.

        Uses degradeBy (1-density) on a regular grid.
        """
        density = pattern.get("density", 0.3)
        degrade = 1.0 - density
        return f'degradeBy {degrade:.2f} $ s "{sound}*{steps}"'

    # ------------------------------------------------------------------
    # Effects code
    # ------------------------------------------------------------------

    def _build_effects_code(
        self,
        codegen_input: CodegenInput,
        warnings: list[str],
        unmapped: dict[str, list[str]],
    ) -> list[str]:
        """Build Tidal effect expressions.

        Returns a list of effect strings (e.g. '# room 0.25', '# lpf 1200').
        """
        effect_strs: list[str] = []

        # Process effects in canonical chain order
        from engine.codegen.mappings import get_all_sc_effect_keys

        ordered_keys = get_all_sc_effect_keys()

        for key in ordered_keys:
            if key not in codegen_input.effects:
                continue

            user_params = codegen_input.effects[key]
            tidal_params = get_tidal_effect_params(key)
            tidal_unmapped = get_tidal_unmapped(key)

            # Handle filter_type → correct Tidal effect name
            if key == "filter":
                filter_type = user_params.get("filter_type", "lp")
                tidal_filter_names = {"lp": "lpf", "hp": "hpf", "bp": "bpf"}
                # Override the target name based on filter_type
                if "cutoff_hz" in tidal_params:
                    from engine.codegen.mappings import ParamMapping

                    correct_name = tidal_filter_names.get(filter_type, "lpf")
                    tidal_params = dict(tidal_params)  # copy
                    orig = tidal_params["cutoff_hz"]
                    tidal_params["cutoff_hz"] = ParamMapping(
                        target_name=correct_name,
                        transform=orig.transform,
                        default=orig.default,
                        description=orig.description,
                        approximate=orig.approximate,
                    )

            # Map each parameter
            for py_name, pm in tidal_params.items():
                if py_name in user_params:
                    value = transform_param(pm, user_params[py_name])
                else:
                    value = pm.default

                effect_strs.append(f"# {pm.target_name} {_tidal_fmt(value)}")

                if pm.approximate and py_name in user_params:
                    warnings.append(f"Tidal.{key}.{py_name}: {pm.description}")

            # Track unmapped params that the user actually provided
            if tidal_unmapped:
                relevant = [p for p in tidal_unmapped if p in user_params]
                if relevant:
                    if key not in unmapped:
                        unmapped[key] = []
                    unmapped[key].extend(relevant)
                    for p in relevant:
                        note = tidal_unmapped[p]
                        warnings.append(f"Tidal.{key}.{p}: {note}")

        # Add generator-specific Tidal params
        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        if gen_mapping and gen_mapping.tidal_params:
            gen_params = codegen_input.generator_params
            for py_name, pm in gen_mapping.tidal_params.items():
                if py_name in gen_params:
                    value = transform_param(pm, gen_params[py_name])
                    effect_strs.append(f"# {pm.target_name} {_tidal_fmt(value)}")

        return effect_strs

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def _assemble_pattern_with_effects(
        self,
        codegen_input: CodegenInput,
        pattern_code: str,
        effects: list[str],
        opts: CodegenOptions,
    ) -> str:
        """Assemble the full Tidal expression: d1 $ pattern # effects."""
        is_live = opts.mode == CodegenMode.LIVE
        is_multiline = "\n" in pattern_code

        # Determine orbit (d1, d2, etc.)
        orbit = "d1"

        if is_live:
            prefix = f"-- Evaluate to play (re-evaluate to update live)\n{orbit}"
        else:
            prefix = f"-- Pattern\n{orbit}"

        if is_multiline:
            # Multi-track pattern — effects apply to the whole stack
            indent_pattern = _indent_block(pattern_code, "  ")
            if effects:
                fx_str = "\n  ".join(effects)
                return f"{prefix}\n  $ {indent_pattern}\n  {fx_str}"
            return f"{prefix}\n  $ {indent_pattern}"

        # Single-line pattern
        if effects:
            fx_str = "\n  ".join(effects)
            return f"{prefix}\n  $ {pattern_code}\n  {fx_str}"

        return f"{prefix} $ {pattern_code}"

    # ------------------------------------------------------------------
    # Cleanup & notes
    # ------------------------------------------------------------------

    def _build_cleanup(self, opts: CodegenOptions) -> str:
        if opts.mode == CodegenMode.STUDIO:
            return "-- Cleanup: evaluate to stop all sound\n-- hush"
        return ""

    def _build_setup_notes(self, opts: CodegenOptions) -> list[str]:
        notes = [
            "Requires TidalCycles 1.9+ with SuperDirt",
            "SuperCollider must be running with SuperDirt.start",
        ]
        if opts.mode == CodegenMode.STUDIO:
            notes.extend(
                [
                    "Evaluate the setcps line first to set tempo",
                    "Then evaluate the d1 block to start playback",
                    "Evaluate 'hush' to stop all sound",
                ]
            )
        else:
            notes.extend(
                [
                    "Assumes SuperDirt is already running",
                    "Evaluate d1 block to start — re-evaluate to update live",
                    "Use 'hush' or 'd1 silence' to stop",
                ]
            )
        return notes

    def _get_orbit_assignments(self, codegen_input: CodegenInput) -> dict[str, int]:
        """Return orbit assignments for multi-track patterns."""
        if codegen_input.pattern is None:
            return {"d1": 0}

        pulses = codegen_input.pattern.get("pulses", {})
        probs = codegen_input.pattern.get("probabilities", {})
        tracks = list(pulses.keys() or probs.keys() or ["main"])

        return {f"d{i + 1}": i for i, _ in enumerate(tracks)}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _tidal_fmt(value: Any) -> str:
    """Format a value for Tidal code output."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e6:
            return f"{value:.1f}"
        return f"{value:.4g}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def _indent_block(text: str, indent: str) -> str:
    """Indent a multiline string, preserving first line."""
    lines = text.split("\n")
    if len(lines) <= 1:
        return text
    return lines[0] + "\n" + "\n".join(indent + line for line in lines[1:])
