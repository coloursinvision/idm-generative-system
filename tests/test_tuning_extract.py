"""test_tuning_extract — integration tests for V2.4 /tuning/extract endpoint.

Pipeline layer:  6 — V2.4 Frontend LLM extraction boundary
Targets:         api.main.tuning_extract handler + V2.4 Pydantic models
                 + RAGPipeline.extract_tuning_request mock contract
Spec reference:  V2_ROADMAP.md §V2.4 (sealed v3.0)

Architectural conventions:
    - F.1: module-scoped TestClient fixture (mirrors test_tuning_api.py D-S13-09).
    - F.2: synchronous TestClient (match V1 test convention).
    - F.3: GPT-4o calls fully mocked via monkeypatch on rag.extract_tuning_request.
           No real OpenAI traffic in unit tests — pinned to mock return values.

Test environment requirements:
    - api.main must import — same [ml] + OPENAI_API_KEY env-var requirements
      as test_tuning_api.py (RAGPipeline check at construction time).
    - No live OpenAI / Qdrant traffic.

Run:
    pytest tests/test_tuning_extract.py -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest

# Match the lazy-import / [ml] gating of test_tuning_api.py: api.main pulls in
# the conditional mlflow block at import time even though /tuning/extract
# itself does NOT depend on mlflow. The transitive import surface is the
# constraint here, not the endpoint's runtime dependencies.
pytest.importorskip("pandera")

os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-tests-only")

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Module fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Import the FastAPI app once per module."""
    from api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Any:
    """Module-scoped TestClient — lifespan runs once per file."""
    with TestClient(app) as c:
        yield c


def _valid_extracted() -> dict[str, Any]:
    """Baseline valid extraction payload — UK_IDM, no sub_region."""
    return {
        "bpm": 130.0,
        "pitch_midi": 69.0,
        "swing_pct": 55.0,
        "region": "UK_IDM",
        "sub_region": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """End-to-end /tuning/extract with mocked GPT-4o."""

    def test_happy_path_uk_idm(self, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid extraction round-trips through Pydantic + handler."""
        from api import main as api_main

        monkeypatch.setattr(
            api_main.rag,
            "extract_tuning_request",
            lambda text: _valid_extracted(),
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "130 BPM UK IDM track in A4 with moderate swing"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["extracted"]["bpm"] == 130.0
        assert body["extracted"]["region"] == "UK_IDM"
        assert body["extracted"]["sub_region"] is None
        assert body["model_version"] == api_main.rag.model

    def test_happy_path_japan_idm_tokyo(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JAPAN_IDM + TOKYO cross-field passes."""
        from api import main as api_main

        payload = _valid_extracted()
        payload["region"] = "JAPAN_IDM"
        payload["sub_region"] = "TOKYO"

        monkeypatch.setattr(
            api_main.rag,
            "extract_tuning_request",
            lambda text: payload,
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "Japanese IDM at 130 BPM in Tokyo"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["extracted"]["region"] == "JAPAN_IDM"
        assert body["extracted"]["sub_region"] == "TOKYO"


class TestInputValidation:
    """TuningExtractRequest field-level validation."""

    def test_empty_text_rejected(self, client: Any) -> None:
        response = client.post("/tuning/extract", json={"text": ""})
        assert response.status_code == 422

    def test_text_too_long_rejected(self, client: Any) -> None:
        # max_length=2000 per TuningExtractRequest
        response = client.post("/tuning/extract", json={"text": "x" * 2001})
        assert response.status_code == 422

    def test_unknown_field_rejected(self, client: Any) -> None:
        """extra='forbid' on TuningExtractRequest."""
        response = client.post(
            "/tuning/extract",
            json={"text": "valid description", "unknown_field": "x"},
        )
        assert response.status_code == 422


class TestExtractionFailures:
    """Handler-level error paths when extract_tuning_request raises."""

    def test_parser_validation_error_returns_422(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ValueError from parser surfaces as HTTP 422."""
        from api import main as api_main

        def raise_value_error(text: str) -> dict[str, Any]:
            raise ValueError("bpm out of range [60, 240]: 999")

        monkeypatch.setattr(
            api_main.rag, "extract_tuning_request", raise_value_error
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "absurdly fast track at 999 BPM"},
        )
        assert response.status_code == 422
        assert "Extraction validation failed" in response.json()["detail"]

    def test_upstream_openai_error_returns_502(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-ValueError exception from extract returns HTTP 502."""
        from api import main as api_main

        def raise_upstream(text: str) -> dict[str, Any]:
            raise RuntimeError("OpenAI service unreachable")

        monkeypatch.setattr(
            api_main.rag, "extract_tuning_request", raise_upstream
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "any description"},
        )
        assert response.status_code == 502
        assert "Upstream extraction service error" in response.json()["detail"]

    def test_pydantic_revalidation_catches_bad_payload(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defence-in-depth: parser passes but Pydantic rejects."""
        from api import main as api_main

        # Bad payload: passes parser-level type checks but fails cross-field
        # rule. The parser SHOULD catch this; if a future regression slips it
        # through, Pydantic re-validation must surface it as 422.
        bad = _valid_extracted()
        bad["region"] = "JAPAN_IDM"
        bad["sub_region"] = None  # invalid combo

        monkeypatch.setattr(
            api_main.rag, "extract_tuning_request", lambda text: bad
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "japan idm without sub_region"},
        )
        assert response.status_code == 422


class TestResponseShape:
    """TuningExtractResponse field integrity."""

    def test_response_has_required_fields(
        self, client: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from api import main as api_main

        monkeypatch.setattr(
            api_main.rag,
            "extract_tuning_request",
            lambda text: _valid_extracted(),
        )

        response = client.post(
            "/tuning/extract",
            json={"text": "valid description"},
        )
        assert response.status_code == 200
        body = response.json()

        # Top-level keys
        assert set(body.keys()) == {"extracted", "model_version"}

        # Extracted sub-object keys (matches TuningRequest contract)
        assert set(body["extracted"].keys()) == {
            "bpm",
            "pitch_midi",
            "swing_pct",
            "region",
            "sub_region",
        }
