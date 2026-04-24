"""
tests/test_infra_smoke.py

Infrastructure smoke tests for V2.0 — DO Spaces connectivity and DVC config.

These are integration tests requiring real credentials. Skipped in CI
unless DO_SPACES_KEY is set in the environment.

Run locally:
    pytest tests/test_infra_smoke.py -v

Run in CI:
    Requires DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET,
    DO_SPACES_ENDPOINT_URL secrets provisioned in GitHub Actions.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

SKIP_REASON = "DO_SPACES_KEY not set — skipping infrastructure smoke tests"
needs_spaces = pytest.mark.skipif(
    not os.environ.get("DO_SPACES_KEY"),
    reason=SKIP_REASON,
)


class TestDVCConfig:
    """Verify DVC repository configuration is valid."""

    def test_dvc_initialized(self) -> None:
        """DVC directory exists at repo root."""
        repo_root = Path(__file__).resolve().parent.parent
        assert (repo_root / ".dvc" / "config").is_file(), ".dvc/config not found"

    def test_dvc_remote_configured(self) -> None:
        """DVC config contains do-spaces remote with correct endpoint."""
        repo_root = Path(__file__).resolve().parent.parent
        config_text = (repo_root / ".dvc" / "config").read_text()
        assert "do-spaces" in config_text
        assert "s3://idm-generative-system/dvc" in config_text
        assert "ams3.digitaloceanspaces.com" in config_text


class TestDOSpacesConnectivity:
    """Verify round-trip connectivity to DO Spaces bucket."""

    @needs_spaces
    def test_bucket_reachable(self) -> None:
        """boto3 can list objects in the configured bucket."""
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get(
                "DO_SPACES_ENDPOINT_URL", "https://ams3.digitaloceanspaces.com"
            ),
            aws_access_key_id=os.environ["DO_SPACES_KEY"],
            aws_secret_access_key=os.environ["DO_SPACES_SECRET"],
            region_name="ams3",
        )
        bucket = os.environ.get("DO_SPACES_BUCKET", "idm-generative-system")
        response = s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200

    @needs_spaces
    def test_write_read_delete_roundtrip(self) -> None:
        """Write a test object, read it back, delete it."""
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=os.environ.get(
                "DO_SPACES_ENDPOINT_URL", "https://ams3.digitaloceanspaces.com"
            ),
            aws_access_key_id=os.environ["DO_SPACES_KEY"],
            aws_secret_access_key=os.environ["DO_SPACES_SECRET"],
            region_name="ams3",
        )
        bucket = os.environ.get("DO_SPACES_BUCKET", "idm-generative-system")
        test_key = "smoke-test/roundtrip.txt"
        test_body = b"IDM infra smoke test"

        try:
            s3.put_object(Bucket=bucket, Key=test_key, Body=test_body)
            obj = s3.get_object(Bucket=bucket, Key=test_key)
            assert obj["Body"].read() == test_body
        finally:
            s3.delete_object(Bucket=bucket, Key=test_key)


class TestEnvExample:
    """Verify .env.example documents all V2 variables."""

    def test_v2_vars_present(self) -> None:
        """All required V2 environment variables appear in .env.example."""
        repo_root = Path(__file__).resolve().parent.parent
        content = (repo_root / ".env.example").read_text()
        required = [
            "DO_SPACES_KEY",
            "DO_SPACES_SECRET",
            "DO_SPACES_BUCKET",
            "DO_SPACES_ENDPOINT_URL",
            "MLFLOW_TRACKING_URI",
            "MLFLOW_S3_ENDPOINT_URL",
        ]
        for var in required:
            assert var in content, f"{var} missing from .env.example"
