"""test_tuning_api — integration tests for V2.3 /tuning endpoint.

Pipeline layer:  6 — V2.3 Model Serving boundary
Targets:         api.main.tuning handler + lifespan + V2 Pydantic models
Spec reference:  V2_ROADMAP.md §V2.3 (sealed v3.0)
Decisions:       D-S7-02/03/04 (feature schema), D-S3-05 (sub_region rule),
                 D-S7-01 (lazy ml imports — these tests require [ml] extras)

Architectural conventions (S13 Sub-stage F mikro-decisions):
    - F.1: module-scoped TestClient fixture — lifespan + model load runs
      once per file (real Langfuse + real MLflow Registry connection).
    - F.2: synchronous TestClient (match V1 test convention).
    - F.3: fail-soft 503 paths exercised via monkeypatch on
      app.state.tuning_model / app.state.tuning_model_metadata, with
      pytest's automatic restore semantics.

Test environment requirements:
    - [ml] extras installed (mlflow, pandera, sklearn, xgboost, optuna)
    - [monitoring] extras installed (langfuse) — fail-open in handler means
      tests still pass without it, but Langfuse-specific tests are skipped
    - LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST env vars
    - MLFLOW_TRACKING_URI + AWS credentials for model registry access
    - OPENAI_API_KEY (any value — only used by V1 RAGPipeline at import)
    - Active Production version of TuningEstimator in MLflow Registry

Run:
    pytest tests/test_tuning_api.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

# These tests require [ml] extras because they import api.main which
# transitively imports engine.ml.dataset_schema (pandera) and triggers
# the conditional mlflow import block.
pytest.importorskip("mlflow")
pytest.importorskip("pandera")
pytest.importorskip("xgboost")

# OPENAI_API_KEY must be set for api.main to import (V1 RAGPipeline checks
# at construction). Any non-empty value works for these tests — no actual
# OpenAI calls are made.
os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-tests-only")

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Module fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Import the FastAPI app once per test module.

    Importing api.main triggers the conditional mlflow / langfuse import
    blocks. The actual lifespan (model download from MLflow Registry) runs
    later when TestClient is instantiated.
    """
    from api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Any:
    """Module-scoped TestClient — lifespan runs once per file.

    Yields the active TestClient. On context exit (after all tests in this
    file), lifespan shutdown runs and Langfuse flush is called. This
    minimises the ~3-5 second MLflow model download cost to a single
    occurrence per pytest run.
    """
    with TestClient(app) as c:
        yield c


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    """Construct a baseline valid TuningRequest payload, with field overrides.

    The baseline is a UK_IDM request known to pass all validations and
    return HTTP 200 (verified empirically in S13 Sub-stage D integration
    smoke tests).
    """
    base = {
        "bpm": 130.0,
        "pitch_midi": 69.0,
        "swing_pct": 55.0,
        "region": "UK_IDM",
        "sub_region": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Pydantic field-level validation — boundary cases
# ---------------------------------------------------------------------------


class TestPydanticFieldValidation:
    """Field-level constraints from TuningRequest Pydantic model."""

    @pytest.mark.parametrize(
        ("bpm", "expected_status"),
        [
            (59.9, 422),  # below ge=60.0
            (60.0, 200),  # lower boundary inclusive
            (240.0, 200),  # upper boundary inclusive
            (240.1, 422),  # above le=240.0
        ],
    )
    def test_bpm_range(self, client: Any, bpm: float, expected_status: int) -> None:
        """bpm must be in [60.0, 240.0]; boundaries inclusive."""
        r = client.post("/tuning", json=_valid_payload(bpm=bpm))
        assert r.status_code == expected_status

    @pytest.mark.parametrize(
        ("pitch_midi", "expected_status"),
        [
            (-0.1, 422),  # below ge=0.0
            (0.0, 200),  # lower boundary inclusive
            (127.0, 200),  # upper boundary inclusive
            (127.1, 422),  # above le=127.0
        ],
    )
    def test_pitch_midi_range(self, client: Any, pitch_midi: float, expected_status: int) -> None:
        """pitch_midi must be in [0.0, 127.0]; boundaries inclusive."""
        r = client.post("/tuning", json=_valid_payload(pitch_midi=pitch_midi))
        assert r.status_code == expected_status

    @pytest.mark.parametrize(
        ("swing_pct", "expected_status"),
        [
            (-0.1, 422),  # below ge=0.0
            (0.0, 200),  # lower boundary inclusive (no swing)
            (100.0, 200),  # upper boundary inclusive (max swing)
            (100.1, 422),  # above le=100.0
        ],
    )
    def test_swing_pct_range(self, client: Any, swing_pct: float, expected_status: int) -> None:
        """swing_pct must be in [0.0, 100.0]; boundaries inclusive.

        Internal scale is [0.0, 1.0] after boundary conversion in handler
        per D-S7-04; this test verifies the external API constraint.
        """
        r = client.post("/tuning", json=_valid_payload(swing_pct=swing_pct))
        assert r.status_code == expected_status

    def test_region_invalid_literal_rejected(self, client: Any) -> None:
        """region must match RegionCode Literal; arbitrary strings → 422."""
        r = client.post("/tuning", json=_valid_payload(region="MARS_TECHNO"))
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Cross-field rule: sub_region ↔ JAPAN_IDM (D-S3-05)
# ---------------------------------------------------------------------------


class TestCrossFieldRule:
    """TuningRequest @model_validator enforces sub_region scope rule."""

    def test_japan_idm_requires_sub_region(self, client: Any) -> None:
        """region == 'JAPAN_IDM' without sub_region → 422."""
        r = client.post(
            "/tuning",
            json=_valid_payload(region="JAPAN_IDM", sub_region=None),
        )
        assert r.status_code == 422
        # Pydantic v2 error body should mention the rule.
        assert "sub_region" in r.text.lower()

    def test_non_japan_forbids_sub_region(self, client: Any) -> None:
        """region != 'JAPAN_IDM' with sub_region set → 422."""
        r = client.post(
            "/tuning",
            json=_valid_payload(region="UK_IDM", sub_region="TOKYO"),
        )
        assert r.status_code == 422
        assert "sub_region" in r.text.lower()

    def test_japan_idm_with_sub_region_passes(self, client: Any) -> None:
        """region == 'JAPAN_IDM' with sub_region set → 200 (happy path)."""
        r = client.post(
            "/tuning",
            json=_valid_payload(region="JAPAN_IDM", sub_region="TOKYO"),
        )
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Happy path: each of the 6 RegionCode values returns 200
# ---------------------------------------------------------------------------


class TestHappyPathAllRegions:
    """One end-to-end happy-path request per region.

    Variable resonant_points cardinality per region is expected (per
    V2_ROADMAP §V2.1 invariant #3); the test asserts cardinality > 0 only,
    not a specific count — exact counts are an emergent property of the
    trained model and Layer 2 spokes.
    """

    @pytest.mark.parametrize(
        ("region", "sub_region"),
        [
            ("DETROIT_FIRST_WAVE", None),
            ("DETROIT_UR", None),
            ("DREXCIYA", None),
            ("UK_IDM", None),
            ("UK_BRAINDANCE", None),
            ("JAPAN_IDM", "OSAKA"),
        ],
    )
    def test_region_returns_200_with_resonants(
        self, client: Any, region: str, sub_region: str | None
    ) -> None:
        """Each region produces a valid TuningResponse with resonant_points."""
        r = client.post(
            "/tuning",
            json=_valid_payload(region=region, sub_region=sub_region),
        )
        assert r.status_code == 200
        body = r.json()
        # tuning_hz is discrete 432/440 per D-S5-01; defensive range check.
        assert body["tuning_hz"] > 0.0
        # At least one resonant point per region (none has zero spoke targets).
        assert len(body["resonant_points"]) > 0
        # Provenance fields populated by lifespan metadata.
        assert body["model_version"]
        assert body["dataset_dvc_hash"]
        assert body["inference_latency_ms"] >= 0.0


# ---------------------------------------------------------------------------
# Response shape integrity
# ---------------------------------------------------------------------------


class TestResponseShape:
    """TuningResponse shape, ordering, and field-level invariants."""

    def test_resonant_points_sorted_by_confidence_desc_then_hz_asc(self, client: Any) -> None:
        """resonant_points sorted by (-confidence, hz). With placeholder
        confidence=1.0 for all points (TODO-S13-F), ordering collapses to
        hz ascending. Test verifies the secondary sort key.
        """
        r = client.post("/tuning", json=_valid_payload())
        assert r.status_code == 200
        points = r.json()["resonant_points"]
        assert len(points) >= 2, "need at least 2 points to verify ordering"
        # With uniform confidence=1.0, points sorted by hz ascending.
        hz_values = [p["hz"] for p in points]
        assert hz_values == sorted(hz_values), (
            f"resonant_points should be hz-ascending, got {hz_values}"
        )

    def test_resonant_point_fields_complete(self, client: Any) -> None:
        """Every ResonantPoint has hz > 1.0, non-empty label, confidence in [0,1]."""
        r = client.post("/tuning", json=_valid_payload())
        assert r.status_code == 200
        for p in r.json()["resonant_points"]:
            assert p["hz"] >= 1.0, f"hz must be >= _RESONANT_POINT_MIN_HZ (1.0), got {p['hz']}"
            assert isinstance(p["label"], str)
            assert len(p["label"]) > 0
            assert not p["label"].startswith("freq_"), "label should have 'freq_' prefix stripped"
            assert 0.0 <= p["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Fail-soft 503 paths (D-S13 Sub-stage C decision β)
# ---------------------------------------------------------------------------


class TestFailSoft:
    """Lifespan fail-soft → handler returns 503 (not 500 or 200)."""

    def test_no_model_returns_503(self, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """app.state.tuning_model = None → /tuning returns 503.

        Simulates the lifespan fail-soft outcome (mlflow load failure,
        network blip, no Production version in registry).
        """
        monkeypatch.setattr(client.app.state, "tuning_model", None)
        r = client.post("/tuning", json=_valid_payload())
        assert r.status_code == 503
        assert "unavailable" in r.text.lower() or "lifespan" in r.text.lower()

    def test_no_target_columns_returns_503(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty target_columns in metadata → /tuning returns 503.

        Simulates the case where MLflow run params don't contain
        'target_columns' (e.g. model trained before train() was
        instrumented to log it).
        """
        original_meta = client.app.state.tuning_model_metadata
        broken_meta = dict(original_meta)
        broken_meta["target_columns"] = []
        monkeypatch.setattr(client.app.state, "tuning_model_metadata", broken_meta)
        r = client.post("/tuning", json=_valid_payload())
        assert r.status_code == 503
        assert "target_columns" in r.text


# ---------------------------------------------------------------------------
# Pydantic extra="forbid" (Gotcha #11)
# ---------------------------------------------------------------------------


class TestExtraFieldsRejected:
    """TuningRequest model_config = ConfigDict(extra='forbid')."""

    def test_unknown_field_rejected(self, client: Any) -> None:
        """Extra field in payload → 422 (not silent acceptance)."""
        payload = _valid_payload()
        payload["effects_density"] = 0.5  # dropped per D-S7-03
        r = client.post("/tuning", json=payload)
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Latency + metadata provenance integrity
# ---------------------------------------------------------------------------


class TestLatencyAndMetadata:
    """inference_latency_ms semantics + model_version provenance."""

    def test_latency_and_provenance_present(self, client: Any) -> None:
        """inference_latency_ms is positive; model_version matches loaded model."""
        r = client.post("/tuning", json=_valid_payload())
        assert r.status_code == 200
        body = r.json()

        # Latency: real predict() call always takes >0ms on CPU.
        assert body["inference_latency_ms"] > 0.0
        assert body["inference_latency_ms"] < 5000.0, (
            "predict latency > 5s suggests model regression — investigate"
        )

        # Provenance: model_version is the MLflow run_id of loaded model.
        expected_version = client.app.state.tuning_model_metadata["model_version"]
        assert body["model_version"] == expected_version

        # Provenance: dataset_dvc_hash either real hash or "unknown" placeholder
        # (per TODO-S13-E — S12 v1 baseline predates training-side tag).
        assert (
            body["dataset_dvc_hash"] in ({"unknown"} | {expected_version})
            or len(body["dataset_dvc_hash"]) > 0
        )


# ---------------------------------------------------------------------------
# Langfuse fail-open: trace breaks → request still succeeds
# ---------------------------------------------------------------------------


class TestLangfuseFailOpen:
    """Langfuse SDK errors MUST NOT block /tuning business path."""

    def test_langfuse_client_error_does_not_break_request(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if start_observation raises, request returns 200.

        Simulates a runtime Langfuse SDK failure (network blip,
        rate-limit, schema mismatch). The handler's defense-in-depth
        try/except wrappers must catch and continue.

        Skipped if Langfuse client unavailable in test env (then fail-open
        is trivially satisfied: trace_span = None branch).
        """
        if client.app.state.langfuse_client is None:
            pytest.skip("Langfuse client not available in test env")

        # Replace start_observation with a sabotage that raises.
        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("simulated Langfuse SDK failure")

        monkeypatch.setattr(
            client.app.state.langfuse_client,
            "start_observation",
            _raise,
        )

        r = client.post("/tuning", json=_valid_payload())
        # Request must succeed despite trace failure.
        assert r.status_code == 200
        body = r.json()
        assert body["tuning_hz"] > 0.0
        assert len(body["resonant_points"]) > 0
