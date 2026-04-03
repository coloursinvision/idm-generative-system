"""
tests/test_codegen.py

Comprehensive test suite for engine/codegen/ module.

Coverage:
    - Mapping completeness (zero silent parameter drops)
    - Value transforms (range correctness, edge cases, round-trip sanity)
    - Lookup helpers (generators, effects, Tidal params)
    - BaseCodegen input validation
    - SuperCollider output (structural assertions, parametric, mode switching)
    - TidalCycles output (structural assertions, parametric, mode switching)
    - CodegenResult contract (all fields populated)
    - Edge cases (empty effects, minimal input, all effects enabled)

Test count: 35 cases
"""

from __future__ import annotations

import re

import pytest

from engine.codegen import generate_synthdef, generate_tidal
from engine.codegen.base import (
    CodegenInput,
    CodegenMode,
    CodegenOptions,
    CodegenTarget,
)
from engine.codegen.mappings import (
    SC_EFFECTS,
    SC_GENERATORS,
    TIDAL_EFFECTS,
    get_all_sc_effect_keys,
    get_sc_effect,
    get_sc_effect_by_position,
    get_sc_generator,
    get_tidal_effect_params,
    get_tidal_unmapped,
    transform_param,
    validate_mapping_completeness,
)
from engine.codegen.synthdef import SuperColliderCodegen

# =====================================================================
# Section 1: Mapping completeness
# =====================================================================


class TestMappingCompleteness:
    """Every engine parameter must be mapped or explicitly unmapped."""

    def test_all_parameters_accounted_for(self) -> None:
        """Zero silent parameter drops across all 10 effect blocks."""
        missing = validate_mapping_completeness()
        assert missing == {}, (
            f"Unaccounted parameters found: {missing}. "
            "Every param must be in sc_params, unmapped_sc, "
            "tidal_params, or unmapped_tidal."
        )

    def test_all_ten_effects_have_sc_mappings(self) -> None:
        """All 10 canonical effect blocks have SC effect mappings."""
        expected_keys = {
            "noise_floor",
            "bitcrusher",
            "filter",
            "saturation",
            "reverb",
            "delay",
            "spatial",
            "glitch",
            "compressor",
            "vinyl",
        }
        assert set(SC_EFFECTS.keys()) == expected_keys

    def test_all_three_generators_have_sc_mappings(self) -> None:
        """All 3 generators have SC generator mappings."""
        expected = {"glitch_click", "noise_burst", "fm_blip"}
        assert set(SC_GENERATORS.keys()) == expected

    def test_chain_positions_are_unique_and_sequential(self) -> None:
        """Each effect block has a unique chain position from 1 to 10."""
        positions = [e.chain_position for e in SC_EFFECTS.values()]
        assert sorted(positions) == list(range(1, 11))

    def test_canonical_order_matches_chain_positions(self) -> None:
        """get_all_sc_effect_keys returns blocks in chain position order."""
        ordered = get_all_sc_effect_keys()
        positions = [SC_EFFECTS[k].chain_position for k in ordered]
        assert positions == sorted(positions)


# =====================================================================
# Section 2: Value transforms
# =====================================================================


class TestValueTransforms:
    """Parameter value transforms produce correct target-language values."""

    def test_ms_to_s(self) -> None:
        """Milliseconds → seconds conversion."""
        pm = SC_EFFECTS["delay"].sc_params["delay_ms"]
        assert transform_param(pm, 375.0) == pytest.approx(0.375)

    def test_db_to_linear(self) -> None:
        """dB → linear amplitude: -78 dB ≈ 0.000126."""
        pm = SC_EFFECTS["noise_floor"].sc_params["noise_floor_db"]
        result = transform_param(pm, -78.0)
        assert result == pytest.approx(0.000126, rel=0.01)

    def test_db_to_linear_zero_db(self) -> None:
        """0 dB → 1.0 linear."""
        pm = SC_EFFECTS["noise_floor"].sc_params["noise_floor_db"]
        assert transform_param(pm, 0.0) == pytest.approx(1.0)

    def test_resonance_to_rq_low(self) -> None:
        """Low resonance (0.0) → wide bandwidth (rq ≈ 1.0)."""
        pm = SC_EFFECTS["filter"].sc_params["resonance"]
        result = transform_param(pm, 0.0)
        assert result == pytest.approx(1.0)

    def test_resonance_to_rq_high(self) -> None:
        """High resonance (0.9) → narrow bandwidth (rq << 0.1)."""
        pm = SC_EFFECTS["filter"].sc_params["resonance"]
        result = transform_param(pm, 0.9)
        assert result < 0.05

    def test_ratio_to_slope_above(self) -> None:
        """Compression ratio 4:1 → slopeAbove 0.25."""
        pm = SC_EFFECTS["compressor"].sc_params["ratio"]
        assert transform_param(pm, 4.0) == pytest.approx(0.25)

    def test_ratio_to_slope_above_unity(self) -> None:
        """Ratio 1:1 → slopeAbove 1.0 (no compression)."""
        pm = SC_EFFECTS["compressor"].sc_params["ratio"]
        assert transform_param(pm, 1.0) == pytest.approx(1.0)

    def test_feedback_to_decaytime(self) -> None:
        """Feedback 0.45 → reasonable CombC decay time (> 1s)."""
        pm = SC_EFFECTS["delay"].sc_params["feedback"]
        result = transform_param(pm, 0.45)
        assert 1.0 < result < 20.0

    def test_sr_reduction_to_effective_rate(self) -> None:
        """SR reduction factor 2 → effective 22050 Hz."""
        pm = SC_EFFECTS["bitcrusher"].sc_params["sample_rate_reduction"]
        assert transform_param(pm, 2) == pytest.approx(22050.0)

    def test_pan_to_tidal(self) -> None:
        """Python pan [-1,1] → Tidal pan [0,1]."""
        pm = TIDAL_EFFECTS["spatial"]["pan"]
        assert transform_param(pm, -1.0) == pytest.approx(0.0)
        assert transform_param(pm, 0.0) == pytest.approx(0.5)
        assert transform_param(pm, 1.0) == pytest.approx(1.0)

    def test_crush_to_tidal(self) -> None:
        """Python bit_depth 12 → Tidal crush value (reasonable range)."""
        pm = TIDAL_EFFECTS["bitcrusher"]["bit_depth"]
        result = transform_param(pm, 12)
        assert 1.0 <= result <= 16.0

    def test_identity_transform_passthrough(self) -> None:
        """Params with transform=None pass values through unchanged."""
        pm = SC_EFFECTS["filter"].sc_params["cutoff_hz"]
        assert transform_param(pm, 2400.0) == 2400.0


# =====================================================================
# Section 3: Lookup helpers
# =====================================================================


class TestLookupHelpers:
    """Lookup functions return correct mappings or None."""

    def test_get_sc_generator_found(self) -> None:
        mapping = get_sc_generator("fm_blip")
        assert mapping is not None
        assert mapping.sc_name == "idm_fm_blip"

    def test_get_sc_generator_not_found(self) -> None:
        assert get_sc_generator("nonexistent") is None

    def test_get_sc_effect_found(self) -> None:
        mapping = get_sc_effect("reverb")
        assert mapping is not None
        assert mapping.chain_position == 5

    def test_get_sc_effect_by_position(self) -> None:
        mapping = get_sc_effect_by_position(6)
        assert mapping is not None
        assert mapping.block_key == "delay"

    def test_get_tidal_effect_params_with_mappings(self) -> None:
        params = get_tidal_effect_params("reverb")
        assert "mix" in params
        assert "decay_s" in params

    def test_get_tidal_effect_params_empty(self) -> None:
        """Effects with no Tidal equivalent return empty dict."""
        params = get_tidal_effect_params("noise_floor")
        assert params == {}

    def test_get_tidal_unmapped(self) -> None:
        unmapped = get_tidal_unmapped("compressor")
        assert "threshold_db" in unmapped
        assert len(unmapped) > 5  # compressor has many unmapped Tidal params


# =====================================================================
# Section 4: BaseCodegen validation
# =====================================================================


class TestBaseCodegenValidation:
    """Input validation catches invalid generators, effects, and patterns."""

    def _make_input(self, **kwargs) -> CodegenInput:
        defaults = {"generator": "fm_blip"}
        defaults.update(kwargs)
        return CodegenInput(**defaults)

    def test_valid_input_passes(self) -> None:
        sc = SuperColliderCodegen()
        errors = sc.validate(
            self._make_input(
                effects={"reverb": {"decay_s": 3.0}},
                pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
            )
        )
        assert errors == []

    def test_invalid_generator_rejected(self) -> None:
        sc = SuperColliderCodegen()
        errors = sc.validate(self._make_input(generator="unknown_gen"))
        assert len(errors) == 1
        assert "unknown_gen" in errors[0]

    def test_invalid_effect_key_rejected(self) -> None:
        sc = SuperColliderCodegen()
        errors = sc.validate(self._make_input(effects={"phaser": {}}))
        assert len(errors) == 1
        assert "phaser" in errors[0]

    def test_invalid_pattern_type_rejected(self) -> None:
        sc = SuperColliderCodegen()
        errors = sc.validate(self._make_input(pattern={"type": "markov"}))
        assert len(errors) == 1
        assert "markov" in errors[0]

    def test_generate_raises_on_invalid_input(self) -> None:
        sc = SuperColliderCodegen()
        with pytest.raises(ValueError, match="validation failed"):
            sc.generate(self._make_input(generator="bad"))


# =====================================================================
# Section 5: SuperCollider output
# =====================================================================


class TestSuperColliderOutput:
    """SC codegen produces valid, structurally correct output."""

    def test_studio_mode_has_server_boot(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            mode="studio",
        )
        assert "s.waitForBoot" in result.code

    def test_live_mode_no_server_boot(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            mode="live",
        )
        assert "s.waitForBoot" not in result.code

    def test_generator_synthdef_present(self) -> None:
        result = generate_synthdef(generator="fm_blip")
        assert "SynthDef(\\idm_fm_blip" in result.code

    def test_generator_params_in_output(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            generator_params={"freq": 660, "mod_index": 5.0},
        )
        assert "660" in result.code
        assert "5.0" in result.code

    def test_effect_synthdefs_in_chain_order(self) -> None:
        """Effects appear in canonical chain order in output."""
        result = generate_synthdef(
            generator="fm_blip",
            effects={
                "compressor": {},  # position 9
                "reverb": {},  # position 5
                "bitcrusher": {},  # position 2
            },
        )
        code = result.code
        pos_bc = code.index("idm_fx_bitcrusher")
        pos_rv = code.index("idm_fx_reverb")
        pos_cp = code.index("idm_fx_compressor")
        assert pos_bc < pos_rv < pos_cp

    def test_bus_routing_present(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            effects={"reverb": {}},
        )
        assert "~genBus" in result.code
        assert "~genGroup" in result.code
        assert "~fxGroup" in result.code
        assert "ReplaceOut" in result.code

    def test_group_ordering_correct(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            effects={"reverb": {}},
        )
        assert "Group.after(~genGroup)" in result.code

    def test_euclidean_pattern_in_pbind(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
            mode="studio",
        )
        assert "Pseq(" in result.code
        assert "\\instrument" in result.code

    def test_live_mode_uses_pdef(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
            mode="live",
        )
        assert "Pdef(" in result.code

    def test_tape_age_maps_to_lpf(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            effects={"delay": {"tape_age": "worn"}},
        )
        assert "4500" in result.code  # worn = 4500 Hz

    def test_no_effects_produces_generator_only(self) -> None:
        result = generate_synthdef(generator="glitch_click", effects={})
        assert "SynthDef(\\idm_glitch_click" in result.code
        assert "idm_fx_" not in result.code

    def test_all_three_generators(self) -> None:
        for gen in ("glitch_click", "noise_burst", "fm_blip"):
            result = generate_synthdef(generator=gen)
            assert result.code
            assert result.target == CodegenTarget.SUPERCOLLIDER

    def test_all_ten_effects_generate(self) -> None:
        """Each effect block can be individually generated without error."""
        for key in SC_EFFECTS:
            result = generate_synthdef(
                generator="fm_blip",
                effects={key: {}},
            )
            assert f"idm_fx_{key}" in result.code or "idm_fx" in result.code


# =====================================================================
# Section 6: TidalCycles output
# =====================================================================


class TestTidalCyclesOutput:
    """Tidal codegen produces valid, structurally correct output."""

    def test_studio_mode_has_setcps(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            mode="studio",
            bpm=135,
        )
        assert "setcps" in result.code
        assert "135" in result.code

    def test_live_mode_no_setcps(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            mode="live",
        )
        assert "setcps" not in result.code

    def test_euclidean_pattern_uses_native_syntax(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
        )
        assert "(5,16)" in result.code

    def test_multi_track_euclidean_uses_stack(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            pattern={
                "type": "euclidean",
                "pulses": {"kick": 5, "snare": 3},
                "steps": 16,
            },
        )
        assert "stack [" in result.code

    def test_density_pattern_uses_degrade_by(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            pattern={"type": "density", "density": 0.4, "steps": 16},
        )
        assert "degradeBy" in result.code
        assert "0.60" in result.code  # 1.0 - 0.4 = 0.6

    def test_effects_mapped_to_tidal_syntax(self) -> None:
        result = generate_tidal(
            generator="fm_blip",
            effects={
                "reverb": {"decay_s": 3.0, "mix": 0.3},
                "filter": {"cutoff_hz": 2000},
            },
        )
        assert "# room" in result.code
        assert "# sz" in result.code
        assert "# lpf" in result.code

    def test_filter_type_selects_correct_tidal_effect(self) -> None:
        """filter_type='hp' → # hpf, not # lpf."""
        result = generate_tidal(
            generator="fm_blip",
            effects={"filter": {"cutoff_hz": 800, "filter_type": "hp"}},
        )
        assert "# hpf" in result.code

    def test_d1_present_in_output(self) -> None:
        result = generate_tidal(generator="fm_blip")
        assert "d1" in result.code

    def test_live_mode_has_re_evaluate_comment(self) -> None:
        result = generate_tidal(generator="fm_blip", mode="live")
        assert "re-evaluate" in result.code.lower()

    def test_hush_in_studio_mode(self) -> None:
        result = generate_tidal(generator="fm_blip", mode="studio")
        assert "hush" in result.code


# =====================================================================
# Section 7: CodegenResult contract
# =====================================================================


class TestCodegenResult:
    """CodegenResult fields are consistently populated."""

    def test_sc_result_fields(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            effects={"reverb": {"reverb_type": "plate"}},
        )
        assert isinstance(result.code, str)
        assert len(result.code) > 100
        assert result.target == CodegenTarget.SUPERCOLLIDER
        assert result.mode == CodegenMode.STUDIO
        assert isinstance(result.warnings, list)
        assert isinstance(result.unmapped_params, dict)
        assert isinstance(result.metadata, dict)
        assert isinstance(result.setup_notes, list)
        assert "synthdef_names" in result.metadata

    def test_tidal_result_fields(self) -> None:
        result = generate_tidal(generator="fm_blip")
        assert result.target == CodegenTarget.TIDALCYCLES
        assert "tidal_sound" in result.metadata
        assert result.metadata["tidal_sound"] == "supermandolin"

    def test_warnings_include_approximate_mappings(self) -> None:
        """Approximate mappings generate user-visible warnings."""
        result = generate_synthdef(
            generator="fm_blip",
            effects={"reverb": {"decay_s": 3.0}},
        )
        decay_warnings = [w for w in result.warnings if "decay" in w.lower()]
        assert len(decay_warnings) > 0

    def test_unmapped_params_tracked(self) -> None:
        """User-provided params with no target equivalent are tracked."""
        result = generate_synthdef(
            generator="fm_blip",
            effects={"delay": {"tape_age": "worn"}},
        )
        assert "delay" in result.unmapped_params
        assert "tape_age" in result.unmapped_params["delay"]

    def test_setup_notes_differ_by_mode(self) -> None:
        studio = generate_synthdef(generator="fm_blip", mode="studio")
        live = generate_synthdef(generator="fm_blip", mode="live")
        assert studio.setup_notes != live.setup_notes

    def test_metadata_contains_synthdef_names(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            effects={"reverb": {}, "delay": {}},
        )
        names = result.metadata["synthdef_names"]
        assert "\\idm_fm_blip" in names
        assert "\\idm_fx_reverb" in names
        assert "\\idm_fx_delay" in names


# =====================================================================
# Section 8: CodegenOptions
# =====================================================================


class TestCodegenOptions:
    """Options correctly control generation behaviour."""

    def test_live_mode_auto_disables_server_boot(self) -> None:
        opts = CodegenOptions(mode=CodegenMode.LIVE, include_server_boot=True)
        assert opts.include_server_boot is False

    def test_studio_mode_preserves_server_boot(self) -> None:
        opts = CodegenOptions(mode=CodegenMode.STUDIO, include_server_boot=True)
        assert opts.include_server_boot is True

    def test_no_pattern_skips_pbind(self) -> None:
        result = generate_synthdef(
            generator="fm_blip",
            include_pattern=False,
        )
        assert "Pbind" not in result.code
        assert "Pdef" not in result.code

    def test_bpm_affects_dur(self) -> None:
        r1 = generate_synthdef(
            generator="fm_blip",
            pattern={"type": "euclidean", "pulses": {"kick": 4}, "steps": 16},
            bpm=120,
        )
        r2 = generate_synthdef(
            generator="fm_blip",
            pattern={"type": "euclidean", "pulses": {"kick": 4}, "steps": 16},
            bpm=180,
        )
        # Faster BPM → shorter dur value
        dur_pattern = re.compile(r"\\dur,\s*([\d.]+)")
        dur1 = float(dur_pattern.search(r1.code).group(1))
        dur2 = float(dur_pattern.search(r2.code).group(1))
        assert dur2 < dur1


# =====================================================================
# Section 9: Edge cases
# =====================================================================


class TestEdgeCases:
    """Boundary conditions and unusual inputs."""

    def test_empty_effects_dict(self) -> None:
        result = generate_synthdef(generator="fm_blip", effects={})
        assert result.code
        assert "idm_fx_" not in result.code

    def test_all_effects_enabled(self) -> None:
        """All 10 effects active simultaneously — no crashes."""
        all_effects = {key: {} for key in SC_EFFECTS}
        result = generate_synthdef(
            generator="fm_blip",
            effects=all_effects,
        )
        assert result.code
        assert len(result.metadata["effects_chain"]) == 10

    def test_no_pattern_provided(self) -> None:
        result = generate_synthdef(generator="fm_blip", pattern=None)
        assert result.code

    def test_tidal_no_pattern(self) -> None:
        result = generate_tidal(generator="fm_blip", pattern=None)
        assert "d1" in result.code

    def test_convenience_functions_match_class_output(self) -> None:
        """generate_synthdef() convenience function matches class-based usage."""
        # Convenience
        r1 = generate_synthdef(generator="fm_blip", effects={"reverb": {}})
        # Class-based
        sc = SuperColliderCodegen()
        r2 = sc.generate(
            CodegenInput(
                generator="fm_blip",
                effects={"reverb": {}},
            )
        )
        assert r1.code == r2.code

    def test_saturation_modes_generate_different_output(self) -> None:
        """Each saturation mode produces distinct SC code."""
        codes = set()
        for mode in ("asymmetric", "symmetric", "tanh", "wavefold"):
            result = generate_synthdef(
                generator="fm_blip",
                effects={"saturation": {"mode": mode}},
            )
            codes.add(result.code)
        assert len(codes) == 4  # all four are distinct

    def test_vinyl_conditions_affect_noise_params(self) -> None:
        """Different vinyl conditions produce different noise values."""
        codes = set()
        for cond in ("mint", "good", "worn", "trashed"):
            result = generate_synthdef(
                generator="fm_blip",
                effects={"vinyl": {"vinyl_condition": cond}},
            )
            codes.add(result.code)
        assert len(codes) == 4
