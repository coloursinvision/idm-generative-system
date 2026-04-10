"""
engine/codegen/synthdef.py

SuperCollider code generator for the IDM Generative System.

Generates complete, runnable .scd files from engine configurations.
Output follows idiomatic SC patterns:

    - Composable SynthDefs (one per generator, one per active effect)
    - Private bus routing with ReplaceOut for in-place effect processing
    - Group-based execution ordering (genGroup → fxGroup)
    - Pbind (studio) or Pdef (live) pattern output
    - s.waitForBoot wrapper (studio) or bare code (live)

Usage:
    from engine.codegen.synthdef import SuperColliderCodegen
    from engine.codegen.base import CodegenInput, CodegenOptions

    sc = SuperColliderCodegen()
    result = sc.generate(CodegenInput(
        generator="fm_blip",
        generator_params={"freq": 300, "mod_index": 2.0},
        effects={"reverb": {"decay_s": 3.0}, "delay": {"feedback": 0.6}},
        pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
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
    DAT_MODE_SC_CUTOFF,
    SC_EFFECTS,
    SC_GENERATORS,
    TAPE_AGE_SC_CUTOFF,
    VINYL_CONDITION_SC,
    EffectBlockMapping,
    GeneratorMapping,
    transform_param,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INDENT = "    "  # 4-space indent for SC code
_HEADER_SEPARATOR = "// " + "=" * 67


# ---------------------------------------------------------------------------
# SuperCollider code generator
# ---------------------------------------------------------------------------


class SuperColliderCodegen(BaseCodegen):
    """Generate SuperCollider (.scd) code from engine configurations.

    Produces composable SynthDefs with bus routing, group ordering,
    and optional Pbind/Pdef pattern code. Supports studio and live modes.
    """

    def generate(self, codegen_input: CodegenInput) -> CodegenResult:
        """Generate a complete SuperCollider script.

        Args:
            codegen_input: Validated CodegenInput instance.

        Returns:
            CodegenResult with SC code, warnings, metadata, and setup notes.

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
        gen_code = self._build_generator_code(codegen_input, warnings)
        fx_code, fx_names = self._build_effects_code(codegen_input, warnings, unmapped)
        bus_code, bus_meta = self._build_bus_allocation(codegen_input, fx_names)
        instantiation = self._build_instantiation(codegen_input, fx_names, bus_meta)
        pattern_code = self._build_pattern_code(codegen_input, bus_meta)
        cleanup = self._build_cleanup()

        # --- Assemble ---
        sections = [header, gen_code, fx_code, bus_code, instantiation]
        if pattern_code:
            sections.append(pattern_code)
        sections.append(cleanup)

        inner_code = "\n\n".join(s for s in sections if s)

        if opts.include_server_boot:
            code = self._wrap_server_boot(inner_code) if opts.include_server_boot else inner_code
        else:
            code = inner_code

        # --- Metadata ---
        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        synthdef_names = [f"\\{gen_mapping.sc_name}" if gen_mapping else "\\unknown"]
        synthdef_names.extend(f"\\{name}" for name in fx_names)

        metadata: dict[str, Any] = {
            "synthdef_names": synthdef_names,
            "bus_allocation": bus_meta,
            "effects_chain": fx_names,
            "mode": opts.mode.value,
        }

        setup_notes = self._build_setup_notes(opts)

        return CodegenResult(
            code=code,
            target=CodegenTarget.SUPERCOLLIDER,
            mode=opts.mode,
            warnings=warnings,
            unmapped_params=unmapped,
            metadata=metadata,
            setup_notes=setup_notes,
        )

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self, codegen_input: CodegenInput) -> str:
        gen_name = codegen_input.generator
        mode = codegen_input.options.mode.value
        fx_keys = sorted(codegen_input.effects.keys())
        fx_list = ", ".join(fx_keys) if fx_keys else "none"

        return (
            f"{_HEADER_SEPARATOR}\n"
            f"// IDM Generative System — SuperCollider Output\n"
            f"// Generator: {gen_name}\n"
            f"// Effects:   {fx_list}\n"
            f"// Mode:      {mode}\n"
            f"{_HEADER_SEPARATOR}"
        )

    # ------------------------------------------------------------------
    # Generator SynthDef
    # ------------------------------------------------------------------

    def _build_generator_code(
        self,
        codegen_input: CodegenInput,
        warnings: list[str],
    ) -> str:
        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        if gen_mapping is None:
            warnings.append(f"No SC mapping for generator '{codegen_input.generator}'")
            return ""

        params = codegen_input.generator_params
        sc_args = self._resolve_generator_args(gen_mapping, params, warnings)

        if codegen_input.generator == "glitch_click":
            return self._synthdef_glitch_click(gen_mapping.sc_name, sc_args)
        if codegen_input.generator == "noise_burst":
            return self._synthdef_noise_burst(gen_mapping.sc_name, sc_args)
        if codegen_input.generator == "fm_blip":
            return self._synthdef_fm_blip(gen_mapping.sc_name, sc_args)

        warnings.append(f"No SynthDef template for '{codegen_input.generator}'")
        return ""

    def _resolve_generator_args(
        self,
        mapping: GeneratorMapping,
        params: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        """Resolve Python generator params to SC arg values."""
        sc_args: dict[str, Any] = {}
        for py_name, pm in mapping.params.items():
            if py_name in params:
                sc_args[pm.target_name] = transform_param(pm, params[py_name])
            else:
                sc_args[pm.target_name] = pm.default
            if pm.approximate and py_name in params:
                warnings.append(f"Generator.{py_name}: {pm.description}")
        return sc_args

    def _synthdef_glitch_click(self, name: str, args: dict[str, Any]) -> str:
        sustain = args.get("sustain", 0.2)
        decay_rate = args.get("decay_rate", 0.25)
        return (
            f"// --- Generator: Percussive glitch click ---\n"
            f"// Band-limited noise with exponential decay (Braindance micro-percussion)\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, sustain={sustain}, decay_rate={decay_rate}, amp=0.5, gate=1|\n"
            f"{_INDENT}var noise = WhiteNoise.ar;\n"
            f"{_INDENT}var env = EnvGen.kr(\n"
            f"{_INDENT}{_INDENT}Env.perc(0.001, decay_rate),\n"
            f"{_INDENT}{_INDENT}gate, doneAction: 2\n"
            f"{_INDENT});\n"
            f"{_INDENT}var sig = noise * env * amp;\n"
            f"{_INDENT}Out.ar(out, sig);\n"
            f"}}).add;"
        )

    def _synthdef_noise_burst(self, name: str, args: dict[str, Any]) -> str:
        sustain = args.get("sustain", 0.5)
        lpf_mix = args.get("lpf_mix", 0.3)
        decay_rate = args.get("decay_rate", 0.333)
        return (
            f"// --- Generator: Filtered noise burst ---\n"
            f"// White/filtered noise blend with exponential decay\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, sustain={sustain}, lpf_mix={lpf_mix}, "
            f"decay_rate={decay_rate}, amp=0.5, gate=1|\n"
            f"{_INDENT}var white = WhiteNoise.ar;\n"
            f"{_INDENT}var filtered = LPF.ar(white, 800);\n"
            f"{_INDENT}var blended = (white * (1 - lpf_mix)) + (filtered * lpf_mix);\n"
            f"{_INDENT}var env = EnvGen.kr(\n"
            f"{_INDENT}{_INDENT}Env.perc(0.001, decay_rate),\n"
            f"{_INDENT}{_INDENT}gate, doneAction: 2\n"
            f"{_INDENT});\n"
            f"{_INDENT}var sig = blended * env * amp;\n"
            f"{_INDENT}Out.ar(out, sig);\n"
            f"}}).add;"
        )

    def _synthdef_fm_blip(self, name: str, args: dict[str, Any]) -> str:
        freq = args.get("freq", 300.0)
        mod_freq = args.get("mod_freq", 80.0)
        mod_index = args.get("mod_index", 2.0)
        sustain = args.get("sustain", 0.5)
        decay_rate = args.get("decay_rate", 0.333)
        return (
            f"// --- Generator: FM synthesis blip ---\n"
            f"// Single operator pair (modulator -> carrier), DX100/TX81Z heritage\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, freq={freq}, mod_freq={mod_freq}, "
            f"mod_index={mod_index},\n"
            f"{_INDENT} sustain={sustain}, decay_rate={decay_rate}, amp=0.5, gate=1|\n"
            f"{_INDENT}var mod = SinOsc.ar(mod_freq) * mod_index * freq;\n"
            f"{_INDENT}var carrier = SinOsc.ar(freq + mod);\n"
            f"{_INDENT}var env = EnvGen.kr(\n"
            f"{_INDENT}{_INDENT}Env.perc(0.01, decay_rate),\n"
            f"{_INDENT}{_INDENT}gate, doneAction: 2\n"
            f"{_INDENT});\n"
            f"{_INDENT}var sig = carrier * env * amp;\n"
            f"{_INDENT}Out.ar(out, sig);\n"
            f"}}).add;"
        )

    # ------------------------------------------------------------------
    # Effect SynthDefs
    # ------------------------------------------------------------------

    def _build_effects_code(
        self,
        codegen_input: CodegenInput,
        warnings: list[str],
        unmapped: dict[str, list[str]],
    ) -> tuple[str, list[str]]:
        """Build effect SynthDefs in canonical chain order.

        Returns:
            Tuple of (combined effect code string, ordered list of effect SynthDef names).
        """
        from engine.codegen.mappings import get_all_sc_effect_keys

        ordered_keys = get_all_sc_effect_keys()
        sections: list[str] = []
        fx_names: list[str] = []

        for key in ordered_keys:
            if key not in codegen_input.effects:
                continue

            effect_mapping = SC_EFFECTS.get(key)
            if effect_mapping is None:
                warnings.append(f"No SC mapping for effect '{key}'")
                continue

            user_params = codegen_input.effects[key]
            sc_args = self._resolve_effect_args(effect_mapping, user_params, warnings)

            # Track unmapped params
            if effect_mapping.unmapped_sc:
                relevant_unmapped = [p for p in effect_mapping.unmapped_sc if p in user_params]
                if relevant_unmapped:
                    unmapped[key] = relevant_unmapped
                    for p in relevant_unmapped:
                        note = effect_mapping.unmapped_sc[p]
                        warnings.append(f"{effect_mapping.python_class}.{p}: {note}")

            # Generate the SynthDef using the appropriate template
            code = self._generate_effect_synthdef(key, effect_mapping, sc_args, user_params)
            if code:
                sections.append(code)
                fx_names.append(effect_mapping.sc_name)

        combined = "\n\n".join(sections) if sections else ""
        if combined:
            combined = (
                f"// --- Effect chain SynthDefs ---\n"
                f"// Signal flow: generator -> {' -> '.join(fx_names)} -> output\n\n" + combined
            )
        return combined, fx_names

    def _resolve_effect_args(
        self,
        mapping: EffectBlockMapping,
        user_params: dict[str, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        """Resolve Python effect params to SC arg values."""
        sc_args: dict[str, Any] = {}
        for py_name, pm in mapping.sc_params.items():
            if py_name in user_params:
                sc_args[pm.target_name] = transform_param(pm, user_params[py_name])
            else:
                sc_args[pm.target_name] = pm.default
            if pm.approximate and py_name in user_params:
                warnings.append(f"{mapping.python_class}.{py_name}: {pm.description}")
        return sc_args

    def _generate_effect_synthdef(
        self,
        key: str,
        mapping: EffectBlockMapping,
        sc_args: dict[str, Any],
        user_params: dict[str, Any],
    ) -> str:
        """Dispatch to the appropriate effect SynthDef template."""
        dispatch: dict[str, Any] = {
            "noise_floor": self._fx_noise_floor,
            "bitcrusher": self._fx_bitcrusher,
            "filter": self._fx_filter,
            "saturation": self._fx_saturation,
            "reverb": self._fx_reverb,
            "delay": self._fx_delay,
            "spatial": self._fx_spatial,
            "glitch": self._fx_glitch,
            "compressor": self._fx_compressor,
            "vinyl": self._fx_vinyl,
        }
        builder = dispatch.get(key)
        if builder is None:
            return ""
        return str(builder(mapping.sc_name, sc_args, user_params))

    # --- Block 1: Noise Floor ---

    def _fx_noise_floor(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        noise_amp = _fmt(args.get("noise_amp", 0.000126))
        hum_freq = _fmt(args.get("hum_freq", 50.0))
        crosstalk_amp = _fmt(args.get("crosstalk_amp", 0.000562))
        noise_type = user_params.get("noise_type", "pink")
        noise_ugen = "PinkNoise" if noise_type in ("pink", "hum_uk", "hum_us") else "WhiteNoise"
        has_hum = noise_type in ("hum_uk", "hum_us")

        lines = [
            "// Block 1: Noise floor (Mackie CR-1604 bus emulation)",
            f"SynthDef(\\{name}, {{",
            f"{_INDENT}|out=0, noise_amp={noise_amp}, hum_freq={hum_freq}, "
            f"crosstalk_amp={crosstalk_amp}|",
            f"{_INDENT}var sig = In.ar(out, 1);",
            f"{_INDENT}var noise = {noise_ugen}.ar(noise_amp);",
        ]
        if has_hum:
            lines.append(f"{_INDENT}var hum = SinOsc.ar(hum_freq, 0, noise_amp * 0.3);")
            lines.append(f"{_INDENT}noise = noise + hum;")
        lines.extend(
            [
                f"{_INDENT}var crosstalk = DelayN.ar(sig, 0.01, 64/44100) * crosstalk_amp;",
                f"{_INDENT}ReplaceOut.ar(out, sig + noise + crosstalk);",
                "}).add;",
            ]
        )
        return "\n".join(lines)

    # --- Block 2: Bitcrusher ---

    def _fx_bitcrusher(self, name: str, args: dict[str, Any], _user_params: dict[str, Any]) -> str:
        bits = _fmt(args.get("bits", 12.0))
        downsamp = _fmt(args.get("downsamp_rate", 44100.0))
        return (
            f"// Block 2: Bitcrusher (lo-fi DAC emulation)\n"
            f"// Manual quantisation — no sc3-plugins dependency\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, bits={bits}, downsamp_rate={downsamp}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}// Sample rate reduction via sample-and-hold\n"
            f"{_INDENT}sig = Latch.ar(sig, Impulse.ar(downsamp_rate));\n"
            f"{_INDENT}// Bit depth reduction via quantisation\n"
            f"{_INDENT}var step = 0.5.pow(bits);\n"
            f"{_INDENT}sig = (sig / step).round * step;\n"
            f"{_INDENT}ReplaceOut.ar(out, sig);\n"
            f"}}).add;"
        )

    # --- Block 3: Resonant Filter ---

    def _fx_filter(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        freq = _fmt(args.get("freq", 1200.0))
        rq = _fmt(args.get("rq", 0.5))
        accent = args.get("accent", 0.0)
        env_mod = _fmt(args.get("env_mod", 0.5))
        filter_type = user_params.get("filter_type", "lp")

        ugen_map = {"lp": "RLPF", "hp": "RHPF", "bp": "BPF"}
        ugen = ugen_map.get(filter_type, "RLPF")
        poles = user_params.get("poles", 4)

        lines = [
            f"// Block 3: Resonant filter ({ugen}, {poles}-pole)",
        ]

        # Determine if we need accent processing
        has_accent = accent > 0.0

        lines.extend(
            [
                f"SynthDef(\\{name}, {{",
                f"{_INDENT}|out=0, freq={freq}, rq={rq}, env_mod={env_mod}, accent={_fmt(accent)}|",
                f"{_INDENT}var sig = In.ar(out, 1);",
                f"{_INDENT}// Envelope follower for filter modulation",
                f"{_INDENT}var env = EnvFollow.kr(sig) * env_mod * freq;",
                f"{_INDENT}var cutoff = (freq + env).clip(20, 18000);",
            ]
        )

        # Cascade filters for higher pole counts
        if poles <= 2:
            lines.append(f"{_INDENT}sig = {ugen}.ar(sig, cutoff, rq);")
        elif poles == 3:
            lines.extend(
                [
                    f"{_INDENT}// 3-pole (TB-303 style): 2-pole + 1-pole cascade",
                    f"{_INDENT}sig = {ugen}.ar(sig, cutoff, rq);",
                    f"{_INDENT}sig = LPF.ar(sig, cutoff);",
                ]
            )
        else:
            lines.extend(
                [
                    f"{_INDENT}// 4-pole (SH-101 style): cascaded 2-pole sections",
                    f"{_INDENT}sig = {ugen}.ar(sig, cutoff, rq);",
                    f"{_INDENT}sig = {ugen}.ar(sig, cutoff, rq);",
                ]
            )

        if has_accent:
            lines.extend(
                [
                    f"{_INDENT}// TB-303 accent: tanh VCA saturation",
                    f"{_INDENT}var drive = 1.0 + ({_fmt(accent)} * 2.0);",
                    f"{_INDENT}sig = (sig * drive).tanh / drive.tanh;",
                ]
            )

        lines.extend(
            [
                f"{_INDENT}ReplaceOut.ar(out, sig);",
                "}).add;",
            ]
        )
        return "\n".join(lines)

    # --- Block 4: Saturation ---

    def _fx_saturation(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        drive = _fmt(args.get("drive", 1.5))
        mix = _fmt(args.get("mix", 0.8))
        out_gain = _fmt(args.get("out_gain", 1.0))
        mode = user_params.get("mode", "asymmetric")

        # Generate the saturation expression based on mode
        if mode == "symmetric":
            sat_expr = f"(sig * {drive}).tanh"
            mode_comment = "symmetric tanh (transistor-style odd harmonics)"
        elif mode == "tanh":
            sat_expr = f"(sig * {drive}).tanh / {drive}.tanh"
            mode_comment = "normalised tanh (unity gain)"
        elif mode == "wavefold":
            sat_expr = f"(sig * {drive}).fold(-1, 1).tanh"
            mode_comment = "wavefolding (complex overtone structures)"
        else:  # asymmetric (default)
            sat_expr = (
                f"Select.ar((sig > 0).asInteger, [\n"
                f"{_INDENT}{_INDENT}sig / (1 - (sig * {drive} * 0.5)).max(0.001),  "
                f"// negative: rational soft-clip\n"
                f"{_INDENT}{_INDENT}(sig * {drive}).tanh  "
                f"// positive: tanh soft-clip\n"
                f"{_INDENT}])"
            )
            mode_comment = "asymmetric (MASTER_DATASET Part 5 — even-order harmonics)"

        return (
            f"// Block 4: Saturation — {mode_comment}\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, drive={drive}, mix={mix}, out_gain={out_gain}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}var dry = sig;\n"
            f"{_INDENT}var wet = {sat_expr};\n"
            f"{_INDENT}wet = wet - wet.mean;  // DC offset removal\n"
            f"{_INDENT}sig = (dry * (1 - mix)) + (wet * mix) * out_gain;\n"
            f"{_INDENT}ReplaceOut.ar(out, sig);\n"
            f"}}).add;"
        )

    # --- Block 5: Reverb ---

    def _fx_reverb(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        room = _fmt(args.get("room", 0.25))
        mix = _fmt(args.get("mix", 0.25))
        damp = _fmt(args.get("damp", 0.6))
        predelay = _fmt(args.get("predelay", 0.015))
        reverb_type = user_params.get("reverb_type", "plate")

        return (
            f"// Block 5: Reverb (FreeVerb — Quadraverb '{reverb_type}' approximation)\n"
            f"// NOTE: reverb_type='{reverb_type}' — FreeVerb has no type param;\n"
            f"//       decay/room mapped from Python config. For faithful Schroeder\n"
            f"//       architecture, use a custom comb+allpass implementation.\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, room={room}, mix={mix}, damp={damp}, predelay={predelay}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}var dry = sig;\n"
            f"{_INDENT}// Pre-delay\n"
            f"{_INDENT}var delayed = DelayN.ar(sig, 0.1, predelay);\n"
            f"{_INDENT}var wet = FreeVerb.ar(delayed, mix: 1.0, room: room, damp: damp);\n"
            f"{_INDENT}sig = (dry * (1 - mix)) + (wet * mix);\n"
            f"{_INDENT}ReplaceOut.ar(out, sig);\n"
            f"}}).add;"
        )

    # --- Block 6: Tape Delay ---

    def _fx_delay(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        delaytime = _fmt(args.get("delaytime", 0.375))
        decaytime = _fmt(args.get("decaytime", 3.0))
        sat_drive = _fmt(args.get("sat_drive", 2.2))
        mod_freq = _fmt(args.get("mod_freq", 0.8))
        mod_depth = _fmt(args.get("mod_depth", 0.004))
        mix = _fmt(args.get("mix", 0.35))
        tape_age = user_params.get("tape_age", "used")
        tape_lpf = _fmt(TAPE_AGE_SC_CUTOFF.get(tape_age, 8000.0))

        return (
            f"// Block 6: Tape delay (Roland Space Echo RE-201)\n"
            f"// Tape age: '{tape_age}' -> LPF at {tape_lpf} Hz\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, delaytime={delaytime}, decaytime={decaytime},\n"
            f"{_INDENT} sat_drive={sat_drive}, mod_freq={mod_freq}, mod_depth={mod_depth},\n"
            f"{_INDENT} mix={mix}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}var dry = sig;\n"
            f"{_INDENT}// Wow & flutter: combined pitch modulation\n"
            f"{_INDENT}var wow = SinOsc.kr(mod_freq) * mod_depth;\n"
            f"{_INDENT}var flutter = SinOsc.kr(mod_freq * 7.3) * (mod_depth * 0.3);\n"
            f"{_INDENT}var mod_delay = delaytime + wow + flutter;\n"
            f"{_INDENT}// Delay with feedback + tape saturation in feedback path\n"
            f"{_INDENT}var wet = CombC.ar(sig, 1.2, mod_delay, decaytime);\n"
            f"{_INDENT}wet = (wet * sat_drive).tanh / sat_drive.tanh;  // tape head saturation\n"
            f"{_INDENT}wet = LPF.ar(wet, {tape_lpf});  // tape age HF rolloff\n"
            f"{_INDENT}sig = (dry * (1 - mix)) + (wet * mix);\n"
            f"{_INDENT}ReplaceOut.ar(out, sig);\n"
            f"}}).add;"
        )

    # --- Block 7: Spatial ---

    def _fx_spatial(self, name: str, args: dict[str, Any], _user_params: dict[str, Any]) -> str:
        spread = _fmt(args.get("spread", 0.5))
        mono_freq = _fmt(args.get("mono_freq", 200.0))
        pos = _fmt(args.get("pos", 0.0))
        decorr = _fmt(args.get("decorr", 0.0))

        return (
            f"// Block 7: Spatial (stereo width + bass mono enforcement)\n"
            f"// MASTER_DATASET Part 15: kick & bass strictly mono below {mono_freq} Hz\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, spread={spread}, mono_freq={mono_freq}, "
            f"pos={pos}, decorr={decorr}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}// Bass mono enforcement\n"
            f"{_INDENT}var bass = LPF.ar(sig, mono_freq);\n"
            f"{_INDENT}var high = HPF.ar(sig, mono_freq);\n"
            f"{_INDENT}// Stereo spread on highs only\n"
            f"{_INDENT}var stereo = Pan2.ar(high, pos) * spread;\n"
            f"{_INDENT}// Haas decorrelation on right channel\n"
            f"{_INDENT}var left = stereo[0] + bass;\n"
            f"{_INDENT}var right = DelayN.ar(stereo[1], 0.025, decorr) + bass;\n"
            f"{_INDENT}ReplaceOut.ar(out, [left, right]);\n"
            f"}}).add;"
        )

    # --- Block 8: Glitch Engine ---

    def _fx_glitch(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        stutter_prob = _fmt(args.get("stutter_prob", 0.15))
        grain_min = _fmt(args.get("grain_min", 0.005))
        grain_max = _fmt(args.get("grain_max", 0.06))
        loop_rate = _fmt(args.get("loop_rate", 2.0))
        loop_depth = _fmt(args.get("loop_depth", 0.3))
        mix = _fmt(args.get("mix", 0.5))
        xor_mode = user_params.get("xor_mode", "subtle")
        xor_density = user_params.get("xor_density", 0.1)

        lines = [
            "// Block 8: Glitch engine (stutter + ASR-10 loop mod)",
        ]
        if xor_mode != "subtle" or xor_density > 0:
            lines.append(
                f"// NOTE: xor_mode='{xor_mode}', xor_density={xor_density}"
                f" — approximated via bit manipulation"
            )

        lines.extend(
            [
                f"SynthDef(\\{name}, {{",
                f"{_INDENT}|out=0, stutter_prob={stutter_prob}, grain_min={grain_min},",
                f"{_INDENT} grain_max={grain_max}, loop_rate={loop_rate}, "
                f"loop_depth={loop_depth}, mix={mix}|",
                f"{_INDENT}var sig = In.ar(out, 1);",
                f"{_INDENT}var dry = sig;",
                f"{_INDENT}var bufLen = grain_max * SampleRate.ir;",
                f"{_INDENT}var localBuf = LocalBuf(bufLen);",
                f"{_INDENT}var phase = Phasor.ar(0, 1, 0, bufLen);",
                f"{_INDENT}// Write signal into local buffer",
                f"{_INDENT}BufWr.ar(sig, localBuf, phase);",
                f"{_INDENT}// Stutter: re-read from random earlier position",
                f"{_INDENT}var stutterTrig = Dust.kr(stutter_prob * 20);",
                f"{_INDENT}var grainDur = TRand.kr(grain_min, grain_max, stutterTrig);",
                f"{_INDENT}var readPos = phase - (grainDur * SampleRate.ir);",
                f"{_INDENT}var stutter = BufRd.ar(1, localBuf, readPos.wrap(0, bufLen));",
                f"{_INDENT}// ASR-10 loop modulation: LFO warps read position",
                f"{_INDENT}var loopMod = SinOsc.kr(loop_rate) * (loop_depth * bufLen);",
                f"{_INDENT}var modulated = BufRd.ar(1, localBuf, (phase + loopMod).wrap(0, bufLen));",
                f"{_INDENT}// Blend stutter + loop mod",
                f"{_INDENT}var wet = Select.ar(stutterTrig > 0, [modulated, stutter]);",
                f"{_INDENT}sig = (dry * (1 - mix)) + (wet * mix);",
                f"{_INDENT}ReplaceOut.ar(out, sig);",
                "}).add;",
            ]
        )
        return "\n".join(lines)

    # --- Block 9: Compressor ---

    def _fx_compressor(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        thresh = _fmt(args.get("thresh", 0.126))
        slope_above = _fmt(args.get("slopeAbove", 0.25))
        attack = _fmt(args.get("attackTime", 0.01))
        release = _fmt(args.get("releaseTime", 0.1))
        sc_hpf = _fmt(args.get("sc_hpf_freq", 80.0))
        mix = _fmt(args.get("mix", 1.0))
        auto_release = user_params.get("auto_release", True)
        makeup_db = user_params.get("makeup_db", 0.0)
        auto_makeup = user_params.get("auto_makeup", True)

        # Calculate makeup gain
        if auto_makeup:
            threshold_db = user_params.get("threshold_db", -18.0)
            ratio = user_params.get("ratio", 4.0)
            makeup_est = -threshold_db * (1.0 - 1.0 / max(ratio, 1.0)) * 0.5
            makeup_linear = 10.0 ** (makeup_est / 20.0)
        else:
            makeup_linear = 10.0 ** (makeup_db / 20.0)

        lines = [
            "// Block 9: Bus compressor (SSL/Neve/dbx dynamics)",
        ]
        if auto_release:
            lines.append("// auto_release=True: dual Compander (fast+slow) models SSL 4000G")

        lines.extend(
            [
                f"SynthDef(\\{name}, {{",
                f"{_INDENT}|out=0, thresh={thresh}, slopeAbove={slope_above},",
                f"{_INDENT} attackTime={attack}, releaseTime={release},",
                f"{_INDENT} sc_hpf_freq={sc_hpf}, mix={mix}|",
                f"{_INDENT}var sig = In.ar(out, 1);",
                f"{_INDENT}var dry = sig;",
                f"{_INDENT}// Sidechain HPF — prevents sub-bass from driving gain reduction",
                f"{_INDENT}var sidechain = HPF.ar(sig, sc_hpf_freq);",
            ]
        )

        if auto_release:
            lines.extend(
                [
                    f"{_INDENT}// Dual-detector auto-release (SSL 4000G model)",
                    f"{_INDENT}var fast = Compander.ar(sig, sidechain,",
                    f"{_INDENT}{_INDENT}thresh: thresh, slopeAbove: slopeAbove,",
                    f"{_INDENT}{_INDENT}attackTime: attackTime, releaseTime: 0.05);",
                    f"{_INDENT}var slow = Compander.ar(sig, sidechain,",
                    f"{_INDENT}{_INDENT}thresh: thresh, slopeAbove: slopeAbove,",
                    f"{_INDENT}{_INDENT}attackTime: attackTime, releaseTime: 0.6);",
                    f"{_INDENT}var wet = min(fast, slow);",
                ]
            )
        else:
            lines.extend(
                [
                    f"{_INDENT}var wet = Compander.ar(sig, sidechain,",
                    f"{_INDENT}{_INDENT}thresh: thresh, slopeAbove: slopeAbove,",
                    f"{_INDENT}{_INDENT}attackTime: attackTime, releaseTime: releaseTime);",
                ]
            )

        lines.extend(
            [
                f"{_INDENT}// Makeup gain",
                f"{_INDENT}wet = wet * {_fmt(makeup_linear)};",
                f"{_INDENT}// Soft clip safety",
                f"{_INDENT}wet = wet.tanh;",
                f"{_INDENT}sig = (dry * (1 - mix)) + (wet * mix);",
                f"{_INDENT}ReplaceOut.ar(out, sig);",
                "}).add;",
            ]
        )
        return "\n".join(lines)

    # --- Block 10: Vinyl Mastering ---

    def _fx_vinyl(self, name: str, args: dict[str, Any], user_params: dict[str, Any]) -> str:
        riaa_mix = _fmt(args.get("riaa_mix", 0.3))
        noise_amp = _fmt(args.get("noise_amp", 0.15))
        ceiling = _fmt(args.get("ceiling", 0.966))
        dat_mode = user_params.get("dat_mode", "dat_lp")
        dat_cutoff = _fmt(DAT_MODE_SC_CUTOFF.get(dat_mode, 16000.0))
        vinyl_cond = user_params.get("vinyl_condition", "good")
        vc = VINYL_CONDITION_SC.get(vinyl_cond, VINYL_CONDITION_SC["good"])

        return (
            f"// Block 10: Vinyl mastering (RIAA + DAT + surface noise + limiter)\n"
            f"// DAT mode: '{dat_mode}' -> {dat_cutoff} Hz ceiling\n"
            f"// Vinyl condition: '{vinyl_cond}'\n"
            f"SynthDef(\\{name}, {{\n"
            f"{_INDENT}|out=0, riaa_mix={riaa_mix}, noise_amp={noise_amp}, "
            f"ceiling={ceiling}|\n"
            f"{_INDENT}var sig = In.ar(out, 1);\n"
            f"{_INDENT}var dry = sig;\n"
            f"{_INDENT}// RIAA pre-emphasis approximation (shelving EQ)\n"
            f"{_INDENT}var riaa = BHiShelf.ar(\n"
            f"{_INDENT}{_INDENT}BLowShelf.ar(sig, 50, 1.0, riaa_mix * 3),\n"
            f"{_INDENT}{_INDENT}2122, 1.0, riaa_mix * -4\n"
            f"{_INDENT});\n"
            f"{_INDENT}sig = (dry * (1 - riaa_mix)) + (riaa * riaa_mix);\n"
            f"{_INDENT}// DAT brick-wall ceiling\n"
            f"{_INDENT}sig = LPF.ar(sig, {dat_cutoff});\n"
            f"{_INDENT}// Vinyl surface noise\n"
            f"{_INDENT}var hiss = PinkNoise.ar({_fmt(vc['hiss_amp'])});\n"
            f"{_INDENT}var crackle = Dust.ar({_fmt(vc['crackle_density'])}) "
            f"* {_fmt(vc['crackle_amp'])};\n"
            f"{_INDENT}sig = sig + ((hiss + crackle) * noise_amp);\n"
            f"{_INDENT}// Peak limiter (tanh soft-clip at ceiling)\n"
            f"{_INDENT}sig = (sig / ceiling).tanh * ceiling;\n"
            f"{_INDENT}ReplaceOut.ar(out, sig);\n"
            f"}}).add;"
        )

    # ------------------------------------------------------------------
    # Bus allocation & instantiation
    # ------------------------------------------------------------------

    def _build_bus_allocation(
        self,
        codegen_input: CodegenInput,
        fx_names: list[str],
    ) -> tuple[str, dict[str, Any]]:
        """Generate bus allocation code.

        Returns:
            Tuple of (code string, metadata dict with bus info).
        """
        offset = codegen_input.options.bus_offset
        meta: dict[str, Any] = {"gen_bus": offset}

        lines = [
            "// --- Bus allocation & routing ---",
            "~genBus = Bus.audio(s, 1);",
            "",
            "// Execution order groups",
            "~genGroup = Group.new(s);",
            "~fxGroup = Group.after(~genGroup);",
        ]

        return "\n".join(lines), meta

    def _build_instantiation(
        self,
        codegen_input: CodegenInput,
        fx_names: list[str],
        bus_meta: dict[str, Any],
    ) -> str:
        """Generate Synth instantiation code for effects chain."""
        if not fx_names:
            return ""

        lines = [
            "// --- Instantiate effect chain ---",
            "// Effects process in canonical order on ~genBus (ReplaceOut)",
        ]
        for fx_name in fx_names:
            lines.append(f"Synth(\\{fx_name}, [\\out, ~genBus], ~fxGroup, \\addToTail);")

        lines.extend(
            [
                "",
                "// Route processed signal to hardware output",
                "{Out.ar(0, In.ar(~genBus, 1))}.play(~fxGroup, addAction: \\addToTail);",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Pattern
    # ------------------------------------------------------------------

    def _build_pattern_code(
        self,
        codegen_input: CodegenInput,
        bus_meta: dict[str, Any],
    ) -> str:
        opts = codegen_input.options
        if not opts.include_pattern or codegen_input.pattern is None:
            return ""

        gen_mapping = SC_GENERATORS.get(codegen_input.generator)
        if gen_mapping is None:
            return ""

        pattern = codegen_input.pattern
        ptype = pattern.get("type", "euclidean")
        steps = pattern.get("steps", 16)
        bpm = opts.bpm

        # Build the step sequence
        step_seq = self._generate_step_sequence(pattern)
        dur_val = _fmt(60.0 / bpm / 4.0)  # sixteenth note at given BPM

        # Resolve generator args for pattern defaults
        gen_params = codegen_input.generator_params
        sc_args = self._resolve_generator_args(gen_mapping, gen_params, [])

        # Build param lines for Pbind
        param_lines: list[str] = []
        for sc_name, value in sc_args.items():
            if sc_name == "sustain":
                continue  # handled by dur
            param_lines.append(f"{_INDENT}\\{sc_name}, {_fmt(value)},")

        is_live = opts.mode == CodegenMode.LIVE
        pattern_name = "\\idm_pattern"

        if is_live:
            # Live mode: Pdef for hot-swapping
            lines = [
                "// --- Pattern (Pdef — re-evaluate to update live) ---",
                f"Pdef({pattern_name},",
                f"{_INDENT}Pbind(",
                f"{_INDENT}{_INDENT}\\instrument, \\{gen_mapping.sc_name},",
                f"{_INDENT}{_INDENT}\\out, ~genBus,",
                f"{_INDENT}{_INDENT}\\group, ~genGroup,",
                f"{_INDENT}{_INDENT}\\dur, {dur_val},",
                f"{_INDENT}{_INDENT}\\amp, Pseq({step_seq}, inf) * 0.5,",
            ]
            for pl in param_lines:
                lines.append(f"{_INDENT}{_INDENT}{pl.strip()}")
            lines.extend(
                [
                    f"{_INDENT})",
                    ").play;",
                ]
            )
        else:
            # Studio mode: Pbind
            lines = [
                f"// --- Pattern ({ptype}, {steps} steps, {bpm} BPM) ---",
                "~pattern = Pbind(",
                f"{_INDENT}\\instrument, \\{gen_mapping.sc_name},",
                f"{_INDENT}\\out, ~genBus,",
                f"{_INDENT}\\group, ~genGroup,",
                f"{_INDENT}\\dur, {dur_val},",
                f"{_INDENT}\\amp, Pseq({step_seq}, inf) * 0.5,",
            ]
            for pl in param_lines:
                lines.append(f"{_INDENT}{pl.strip()}")
            lines.extend(
                [
                    ");",
                    "~pattern.play;",
                ]
            )

        return "\n".join(lines)

    def _generate_step_sequence(self, pattern: dict[str, Any]) -> str:
        """Convert pattern config to SC Pseq array literal."""
        ptype = pattern.get("type", "euclidean")
        steps = pattern.get("steps", 16)

        if ptype == "euclidean":
            pulses = pattern.get("pulses", {})
            # Use the first track's pulse count, or default
            first_track = next(iter(pulses.values()), 5) if pulses else 5
            seq = self._bjorklund(first_track, steps)
            return f"[{', '.join(str(s) for s in seq)}]"

        if ptype == "density":
            density = pattern.get("density", 0.3)
            # Generate a deterministic pattern at given density
            seq = [1 if (i * 0.618) % 1.0 < density else 0 for i in range(steps)]
            return f"[{', '.join(str(s) for s in seq)}]"

        # Probabilistic: use Pwrand
        probs = pattern.get("probabilities", {})
        first_prob = next(iter(probs.values()), 0.3) if probs else 0.3
        return f"[{', '.join(str(s) for s in self._bjorklund(int(first_prob * steps), steps))}]"

    @staticmethod
    def _bjorklund(k: int, n: int) -> list[int]:
        """Euclidean rhythm generation (Bjorklund algorithm)."""
        if k <= 0:
            return [0] * n
        if k >= n:
            return [1] * n

        pattern: list[int] = []
        counts: list[int] = []
        remainders: list[int] = []

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
        i = pattern.index(1) if 1 in pattern else 0
        return pattern[i:] + pattern[:i]

    # ------------------------------------------------------------------
    # Wrappers & helpers
    # ------------------------------------------------------------------

    def _build_cleanup(self) -> str:
        return "// --- Cleanup (evaluate to stop) ---\n// CmdPeriod.run;"

    def _wrap_server_boot(self, inner_code: str) -> str:
        """Wrap code in s.waitForBoot for studio mode."""
        indented = "\n".join(
            f"{_INDENT}{line}" if line.strip() else "" for line in inner_code.split("\n")
        )
        return f"(\ns.waitForBoot {{\n{indented}\n}};\n)"

    def _build_setup_notes(self, opts: CodegenOptions) -> list[str]:
        notes = [
            "Requires SuperCollider 3.12+ with default server config",
        ]
        if opts.mode == CodegenMode.STUDIO:
            notes.extend(
                [
                    "Evaluate the entire file (Cmd+Enter on the outer parentheses)",
                    "Server boots automatically — wait for 'server ready' post message",
                    "Use CmdPeriod (Cmd+.) to stop all sound",
                ]
            )
        else:
            notes.extend(
                [
                    "Assumes server is already booted (s.boot)",
                    "Evaluate SynthDef blocks first, then bus/group, then pattern",
                    "Re-evaluate Pdef blocks to update pattern in real-time",
                ]
            )
        return notes


# ---------------------------------------------------------------------------
# Formatting helper
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    """Format a numeric value for SC code output.

    Ensures floats have decimal points and reasonable precision.
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e6:
            return f"{value:.1f}"
        return f"{value:.6g}"
    if isinstance(value, int):
        return str(value)
    return str(value)
