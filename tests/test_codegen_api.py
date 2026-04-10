"""
tests/test_codegen_api.py

Integration test suite for the codegen API endpoints.

Uses FastAPI TestClient (ASGI in-process) — same convention as test_api.py.

Coverage:
    POST /synthdef  — valid requests, all generators, effects, modes, errors
    POST /tidal     — valid requests, all generators, effects, modes, errors
    Shared          — response schema validation, default behaviour

Run:
    pytest tests/test_codegen_api.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Shared test client — single instance for the module."""
    return TestClient(app)


def _post_synthdef(client: TestClient, **kwargs: Any) -> Any:
    """Helper: POST /synthdef with defaults."""
    payload: dict[str, Any] = {"generator": "fm_blip"}
    payload.update(kwargs)
    return client.post("/synthdef", json=payload)


def _post_tidal(client: TestClient, **kwargs: Any) -> Any:
    """Helper: POST /tidal with defaults."""
    payload: dict[str, Any] = {"generator": "fm_blip"}
    payload.update(kwargs)
    return client.post("/tidal", json=payload)


# =====================================================================
# POST /synthdef
# =====================================================================


class TestSynthdefEndpoint:
    """Integration tests for POST /synthdef."""

    def test_minimal_request_returns_200(self, client: TestClient) -> None:
        resp = _post_synthdef(client)
        assert resp.status_code == 200

    def test_response_schema(self, client: TestClient) -> None:
        """Response contains all required CodegenResponse fields."""
        resp = _post_synthdef(client)
        data = resp.json()
        assert "code" in data
        assert "target" in data
        assert "mode" in data
        assert "warnings" in data
        assert "unmapped_params" in data
        assert "metadata" in data
        assert "setup_notes" in data

    def test_target_is_supercollider(self, client: TestClient) -> None:
        data = _post_synthdef(client).json()
        assert data["target"] == "supercollider"

    def test_studio_mode_default(self, client: TestClient) -> None:
        data = _post_synthdef(client).json()
        assert data["mode"] == "studio"
        assert "s.waitForBoot" in data["code"]

    def test_live_mode(self, client: TestClient) -> None:
        data = _post_synthdef(client, mode="live").json()
        assert data["mode"] == "live"
        assert "s.waitForBoot" not in data["code"]

    def test_all_three_generators(self, client: TestClient) -> None:
        for gen in ("glitch_click", "noise_burst", "fm_blip"):
            resp = _post_synthdef(client, generator=gen)
            assert resp.status_code == 200
            assert f"idm_{gen}" in resp.json()["code"]

    def test_generator_params_applied(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            generator="fm_blip",
            generator_params={"freq": 880, "mod_index": 5.0},
        ).json()
        assert "880" in data["code"]
        assert "5.0" in data["code"]

    def test_effects_in_output(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            effects={"reverb": {"decay_s": 3.0}, "delay": {"feedback": 0.6}},
        ).json()
        assert "idm_fx_reverb" in data["code"]
        assert "idm_fx_delay" in data["code"]

    def test_effects_chain_order(self, client: TestClient) -> None:
        """Effects appear in canonical order regardless of request order."""
        data = _post_synthdef(
            client,
            effects={
                "compressor": {},
                "bitcrusher": {},
                "reverb": {},
            },
        ).json()
        code = data["code"]
        assert code.index("idm_fx_bitcrusher") < code.index("idm_fx_reverb")
        assert code.index("idm_fx_reverb") < code.index("idm_fx_compressor")

    def test_pattern_euclidean(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
        ).json()
        assert "Pseq(" in data["code"]

    def test_no_pattern(self, client: TestClient) -> None:
        data = _post_synthdef(client, include_pattern=False).json()
        assert "Pbind" not in data["code"]
        assert "Pdef" not in data["code"]

    def test_bpm_affects_output(self, client: TestClient) -> None:
        d1 = _post_synthdef(
            client,
            bpm=120,
            pattern={"type": "euclidean", "pulses": {"kick": 4}, "steps": 16},
        ).json()
        d2 = _post_synthdef(
            client,
            bpm=180,
            pattern={"type": "euclidean", "pulses": {"kick": 4}, "steps": 16},
        ).json()
        assert d1["code"] != d2["code"]

    def test_metadata_has_synthdef_names(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            effects={"reverb": {}},
        ).json()
        names = data["metadata"]["synthdef_names"]
        assert "\\idm_fm_blip" in names
        assert "\\idm_fx_reverb" in names

    def test_warnings_on_approximate_mappings(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            effects={"reverb": {"decay_s": 3.0}},
        ).json()
        assert len(data["warnings"]) > 0

    def test_unmapped_params_tracked(self, client: TestClient) -> None:
        data = _post_synthdef(
            client,
            effects={"delay": {"tape_age": "worn"}},
        ).json()
        assert "delay" in data["unmapped_params"]

    def test_setup_notes_present(self, client: TestClient) -> None:
        data = _post_synthdef(client).json()
        assert len(data["setup_notes"]) > 0

    def test_invalid_generator_returns_400(self, client: TestClient) -> None:
        resp = _post_synthdef(client, generator="nonexistent")
        assert resp.status_code == 400

    def test_invalid_effect_returns_400(self, client: TestClient) -> None:
        resp = _post_synthdef(client, effects={"phaser": {}})
        assert resp.status_code == 400

    def test_invalid_pattern_type_returns_400(self, client: TestClient) -> None:
        resp = _post_synthdef(client, pattern={"type": "markov"})
        assert resp.status_code == 400

    def test_all_ten_effects(self, client: TestClient) -> None:
        """All 10 effects active — no crash."""
        all_fx = {
            k: {}
            for k in [
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
            ]
        }
        resp = _post_synthdef(client, effects=all_fx)
        assert resp.status_code == 200
        assert len(resp.json()["metadata"]["effects_chain"]) == 10


# =====================================================================
# POST /tidal
# =====================================================================


class TestTidalEndpoint:
    """Integration tests for POST /tidal."""

    def test_minimal_request_returns_200(self, client: TestClient) -> None:
        resp = _post_tidal(client)
        assert resp.status_code == 200

    def test_response_schema(self, client: TestClient) -> None:
        data = _post_tidal(client).json()
        assert "code" in data
        assert "target" in data
        assert "mode" in data
        assert "warnings" in data
        assert "metadata" in data

    def test_target_is_tidalcycles(self, client: TestClient) -> None:
        data = _post_tidal(client).json()
        assert data["target"] == "tidalcycles"

    def test_studio_mode_has_setcps(self, client: TestClient) -> None:
        data = _post_tidal(client, mode="studio", bpm=135).json()
        assert "setcps" in data["code"]
        assert "135" in data["code"]

    def test_live_mode_no_setcps(self, client: TestClient) -> None:
        data = _post_tidal(client, mode="live").json()
        assert "setcps" not in data["code"]

    def test_all_three_generators(self, client: TestClient) -> None:
        for gen in ("glitch_click", "noise_burst", "fm_blip"):
            resp = _post_tidal(client, generator=gen)
            assert resp.status_code == 200

    def test_euclidean_pattern(self, client: TestClient) -> None:
        data = _post_tidal(
            client,
            pattern={"type": "euclidean", "pulses": {"kick": 5}, "steps": 16},
        ).json()
        assert "(5,16)" in data["code"]

    def test_multi_track_uses_stack(self, client: TestClient) -> None:
        data = _post_tidal(
            client,
            pattern={
                "type": "euclidean",
                "pulses": {"kick": 5, "snare": 3},
                "steps": 16,
            },
        ).json()
        assert "stack [" in data["code"]

    def test_density_pattern(self, client: TestClient) -> None:
        data = _post_tidal(
            client,
            pattern={"type": "density", "density": 0.4, "steps": 16},
        ).json()
        assert "degradeBy" in data["code"]

    def test_effects_as_tidal_syntax(self, client: TestClient) -> None:
        data = _post_tidal(
            client,
            effects={
                "reverb": {"mix": 0.3},
                "filter": {"cutoff_hz": 2000},
            },
        ).json()
        assert "# room" in data["code"]
        assert "# lpf" in data["code"]

    def test_filter_type_hp(self, client: TestClient) -> None:
        data = _post_tidal(
            client,
            effects={"filter": {"cutoff_hz": 800, "filter_type": "hp"}},
        ).json()
        assert "# hpf" in data["code"]

    def test_d1_in_output(self, client: TestClient) -> None:
        data = _post_tidal(client).json()
        assert "d1" in data["code"]

    def test_metadata_has_tidal_sound(self, client: TestClient) -> None:
        data = _post_tidal(client, generator="fm_blip").json()
        assert data["metadata"]["tidal_sound"] == "supermandolin"

    def test_metadata_has_bpm(self, client: TestClient) -> None:
        data = _post_tidal(client, bpm=140).json()
        assert data["metadata"]["bpm"] == 140.0

    def test_invalid_generator_returns_400(self, client: TestClient) -> None:
        resp = _post_tidal(client, generator="nonexistent")
        assert resp.status_code == 400

    def test_invalid_pattern_returns_400(self, client: TestClient) -> None:
        resp = _post_tidal(client, pattern={"type": "markov"})
        assert resp.status_code == 400

    def test_hush_in_studio(self, client: TestClient) -> None:
        data = _post_tidal(client, mode="studio").json()
        assert "hush" in data["code"]


# =====================================================================
# Cross-endpoint consistency
# =====================================================================


class TestCrossEndpoint:
    """Same input to both endpoints — consistent behaviour."""

    def test_same_input_different_targets(self, client: TestClient) -> None:
        payload = {
            "generator": "fm_blip",
            "generator_params": {"freq": 440},
            "effects": {"reverb": {"decay_s": 3.0}},
        }
        sc = client.post("/synthdef", json=payload).json()
        tc = client.post("/tidal", json=payload).json()
        assert sc["target"] == "supercollider"
        assert tc["target"] == "tidalcycles"
        assert sc["code"] != tc["code"]

    def test_both_endpoints_return_warnings_for_same_effect(self, client: TestClient) -> None:
        payload = {
            "generator": "fm_blip",
            "effects": {"reverb": {"decay_s": 3.0}},
        }
        sc = client.post("/synthdef", json=payload).json()
        tc = client.post("/tidal", json=payload).json()
        assert len(sc["warnings"]) > 0
        assert len(tc["warnings"]) > 0

    def test_empty_request_defaults_work(self, client: TestClient) -> None:
        """Both endpoints handle a fully default request."""
        sc = client.post("/synthdef", json={}).json()
        tc = client.post("/tidal", json={}).json()
        assert len(sc["code"]) > 50
        assert len(tc["code"]) > 50
