"""
tests/test_api.py

End-to-end test suite for the IDM Generative System FastAPI backend.

Uses FastAPI TestClient (ASGI in-process) — no subprocess, no live server.
This is the production convention for FastAPI testing.

Coverage:
    GET  /health    — liveness, version string
    GET  /effects   — schema completeness, canonical order
    POST /generate  — all generators, overrides, skip, bypass, error cases
    POST /process   — WAV upload, stereo→mono, bypass, error cases

Run:
    pytest tests/test_api.py -v
"""

from __future__ import annotations

import io
import json

import numpy as np
import soundfile as sf
import pytest
from fastapi.testclient import TestClient

from api.main import app, GENERATORS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Shared test client — single instance for the module."""
    return TestClient(app)


@pytest.fixture()
def mono_wav_bytes() -> bytes:
    """Generate a short mono WAV file in memory (1024 samples, 44100 Hz)."""
    signal = np.random.default_rng(42).uniform(-0.5, 0.5, 1024)
    buf = io.BytesIO()
    sf.write(buf, signal, 44100, subtype="PCM_24", format="WAV")
    buf.seek(0)
    return buf.read()


@pytest.fixture()
def stereo_wav_bytes() -> bytes:
    """Generate a short stereo WAV file in memory (1024 frames, 2 channels)."""
    rng = np.random.default_rng(99)
    signal = rng.uniform(-0.5, 0.5, (1024, 2))
    buf = io.BytesIO()
    sf.write(buf, signal, 44100, subtype="PCM_24", format="WAV")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealth:
    """GET /health — liveness check."""

    def test_health_status_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_body(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"


# ---------------------------------------------------------------------------
# GET /effects
# ---------------------------------------------------------------------------

EXPECTED_KEYS = [
    "noise_floor", "bitcrusher", "filter", "saturation", "reverb",
    "delay", "spatial", "glitch", "compressor", "vinyl",
]


class TestEffects:
    """GET /effects — self-documenting block schema."""

    def test_effects_status_200(self, client: TestClient) -> None:
        resp = client.get("/effects")
        assert resp.status_code == 200

    def test_effects_returns_10_blocks(self, client: TestClient) -> None:
        data = client.get("/effects").json()
        assert len(data) == 10

    def test_effects_canonical_order(self, client: TestClient) -> None:
        data = client.get("/effects").json()
        keys = [block["key"] for block in data]
        assert keys == EXPECTED_KEYS

    def test_effects_positions_sequential(self, client: TestClient) -> None:
        data = client.get("/effects").json()
        positions = [block["position"] for block in data]
        assert positions == list(range(10))

    def test_effects_block_schema_keys(self, client: TestClient) -> None:
        """Every block entry has the required schema fields."""
        data = client.get("/effects").json()
        required = {"position", "key", "class_name", "params", "docstring"}
        for block in data:
            assert required.issubset(block.keys()), (
                f"Block '{block.get('key')}' missing keys: "
                f"{required - block.keys()}"
            )

    def test_effects_params_have_type_and_default(self, client: TestClient) -> None:
        """Every parameter in every block has 'type' and 'default'."""
        data = client.get("/effects").json()
        for block in data:
            for pname, pinfo in block["params"].items():
                assert "type" in pinfo, (
                    f"{block['key']}.{pname} missing 'type'"
                )
                assert "default" in pinfo, (
                    f"{block['key']}.{pname} missing 'default'"
                )


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

class TestGenerate:
    """POST /generate — sample generation + chain processing."""

    @pytest.mark.parametrize("gen_name", list(GENERATORS.keys()))
    def test_generate_all_generators_default_params(
        self, client: TestClient, gen_name: str
    ) -> None:
        """Each generator produces a valid WAV with default params."""
        resp = client.post("/generate", json={"generator": gen_name})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"

        # Verify returned bytes are a valid WAV
        audio, sr = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert audio.ndim == 1, "Output should be mono"
        assert len(audio) > 0, "Output should not be empty"
        assert sr == 44100, f"Expected 44100 Hz, got {sr}"

    def test_generate_with_chain_overrides(self, client: TestClient) -> None:
        """Chain overrides are applied without error.

        Uses bitcrusher.bit_depth — known valid from /effects schema.
        Override params must match actual constructor signatures of effect
        classes; use GET /effects to discover valid param names.
        """
        # First, discover a valid override param dynamically
        effects_data = client.get("/effects").json()
        bitcrusher = next(b for b in effects_data if b["key"] == "bitcrusher")
        assert "bit_depth" in bitcrusher["params"], (
            "Expected 'bit_depth' in bitcrusher params — schema changed?"
        )

        resp = client.post("/generate", json={
            "generator": "glitch_click",
            "chain_overrides": {
                "bitcrusher": {"bit_depth": 8},
            },
        })
        assert resp.status_code == 200
        audio, _ = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert len(audio) > 0

    def test_generate_with_chain_skip(self, client: TestClient) -> None:
        """Skipping blocks reduces chain length, still produces valid output."""
        resp = client.post("/generate", json={
            "generator": "noise_burst",
            "chain_skip": ["reverb", "delay", "glitch"],
        })
        assert resp.status_code == 200
        audio, _ = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert len(audio) > 0

    def test_generate_bypass_chain(self, client: TestClient) -> None:
        """bypass_chain=true returns raw sample without effects processing."""
        resp = client.post("/generate", json={
            "generator": "glitch_click",
            "bypass_chain": True,
        })
        assert resp.status_code == 200
        audio, _ = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert len(audio) > 0

    def test_generate_invalid_generator_400(self, client: TestClient) -> None:
        """Unknown generator name returns 400."""
        resp = client.post("/generate", json={
            "generator": "nonexistent_gen",
        })
        assert resp.status_code == 400
        assert "nonexistent_gen" in resp.json()["detail"]

    def test_generate_invalid_params_400(self, client: TestClient) -> None:
        """Invalid generator kwargs return 400."""
        resp = client.post("/generate", json={
            "generator": "glitch_click",
            "generator_params": {"totally_bogus_param": 999},
        })
        assert resp.status_code == 400
        assert "Invalid generator params" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /process
# ---------------------------------------------------------------------------

class TestProcess:
    """POST /process — upload WAV, process through chain, return WAV."""

    def test_process_mono_wav(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """Upload mono WAV → processed WAV returned."""
        resp = client.post(
            "/process",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"

        audio, sr = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert audio.ndim == 1
        assert sr == 44100

    def test_process_bypass_chain_signal_unchanged(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """bypass_chain=true returns the uploaded audio (normalised) unchanged.

        Note: bypass_chain is passed as a query parameter rather than a form
        field. FastAPI bool parsing from multipart form strings can be
        unreliable across versions; query params are unambiguous.
        """
        # Request WITH chain processing (default)
        resp_processed = client.post(
            "/process",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
        )
        assert resp_processed.status_code == 200

        # Request WITHOUT chain processing (bypass via query param)
        resp_bypass = client.post(
            "/process?bypass_chain=true",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
        )
        assert resp_bypass.status_code == 200

        processed, _ = sf.read(io.BytesIO(resp_processed.content), dtype="float64")
        bypassed, _ = sf.read(io.BytesIO(resp_bypass.content), dtype="float64")

        # Both should be valid mono audio of same length
        assert processed.ndim == 1
        assert bypassed.ndim == 1
        assert len(processed) == len(bypassed)

        # Bypassed output should differ from processed output —
        # the 10-block chain modifies the signal significantly
        assert not np.allclose(processed, bypassed, atol=1e-3), (
            "Bypassed and processed signals are identical — bypass not working"
        )

        # Bypassed signal peak should be ≈1.0 (API normalises to [-1, 1])
        bypass_peak = np.max(np.abs(bypassed))
        assert bypass_peak == pytest.approx(1.0, abs=1e-3), (
            f"Bypassed peak={bypass_peak:.4f}, expected ≈1.0 (normalised)"
        )

    def test_process_stereo_summed_to_mono(
        self, client: TestClient, stereo_wav_bytes: bytes
    ) -> None:
        """Stereo upload is summed to mono, processed correctly."""
        resp = client.post(
            "/process",
            files={"file": ("stereo.wav", stereo_wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 200

        audio, _ = sf.read(io.BytesIO(resp.content), dtype="float64")
        assert audio.ndim == 1, "Output must be mono even for stereo input"

    def test_process_with_overrides(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """Chain overrides applied via JSON string in form field."""
        overrides = json.dumps({"bitcrusher": {"bit_depth": 6}})
        resp = client.post(
            "/process",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
            data={"chain_overrides": overrides},
        )
        assert resp.status_code == 200

    def test_process_with_skip(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """Chain skip applied via JSON string in form field."""
        skip = json.dumps(["reverb", "delay"])
        resp = client.post(
            "/process",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
            data={"chain_skip": skip},
        )
        assert resp.status_code == 200

    def test_process_invalid_overrides_json_400(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """Malformed chain_overrides JSON returns 400.

        Form field defaults in /process are strings with default values
        ("{}"/''[]"). Multipart form fields sent via TestClient do not
        reliably override these defaults. Query params do.
        """
        resp = client.post(
            "/process?chain_overrides=NOT_VALID_JSON",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 400
        assert "chain_overrides" in resp.json()["detail"].lower()

    def test_process_invalid_skip_json_400(
        self, client: TestClient, mono_wav_bytes: bytes
    ) -> None:
        """Malformed chain_skip JSON returns 400."""
        resp = client.post(
            "/process?chain_skip=NOT_VALID_JSON",
            files={"file": ("test.wav", mono_wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 400
        assert "chain_skip" in resp.json()["detail"].lower()
