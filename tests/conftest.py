"""Fixtures shared by the modules that start the application.

tests/test_tuning_api.py and tests/test_tuning_extract.py run the application
lifespan, which loads models:/TuningEstimator/Production from the MLflow registry.
tuning_registry gives them a registry of their own: a SQLite store in a temporary
directory, built once per session around one model that
engine.ml.model_training.train trains and registers and that is then promoted to
Production, so no test reaches an MLflow server. MLflow and the training module are
imported inside the fixtures: without the [ml] extra those modules skip at import,
and nothing here loads what is missing.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

_MODEL_NAME = "TuningEstimator"
# Every region of the request schema; JAPAN_IDM takes a sub-region.
_REGIONS = (
    ("DETROIT_FIRST_WAVE", None),
    ("DETROIT_UR", None),
    ("DREXCIYA", None),
    ("UK_IDM", None),
    ("UK_BRAINDANCE", None),
    ("JAPAN_IDM", "TOKYO"),
    ("JAPAN_IDM", "OSAKA"),
)
_ROWS = 140


@dataclass(frozen=True)
class TuningRegistry:
    """The tracking URI of the test registry and the run of its Production version."""

    uri: str
    run_id: str


def _training_frame() -> pd.DataFrame:
    """Synthetic rows in the shape of the training data, with three freq_* targets."""
    rng = np.random.default_rng(7)
    regions = [_REGIONS[row % len(_REGIONS)] for row in range(_ROWS)]
    return pd.DataFrame(
        {
            "bpm": rng.uniform(60.0, 240.0, _ROWS),
            "pitch_midi": rng.uniform(0.0, 127.0, _ROWS),
            "swing": rng.uniform(0.0, 1.0, _ROWS),
            "region": [region for region, _ in regions],
            "sub_region": [sub_region for _, sub_region in regions],
            "freq_pitch_ref": rng.uniform(200.0, 600.0, _ROWS),
            "freq_bpm_harmonic": rng.uniform(100.0, 400.0, _ROWS),
            "freq_mains_fundamental": rng.uniform(45.0, 65.0, _ROWS),
        }
    )


@pytest.fixture(scope="session")
def tuning_registry_store(tmp_path_factory: pytest.TempPathFactory) -> TuningRegistry:
    """Build the test registry once per session.

    The tracking URI goes through the environment and the working directory moves to
    the store, where MLflow keeps artifacts by default; both are restored when the
    build ends. Training starts only after both URIs are seen to name the store, so a
    URI set earlier in the process never receives the model.
    """
    import mlflow
    from mlflow.tracking import MlflowClient

    from engine.ml.model_training import (
        TrainingConfig,
        extract_feature_target_columns,
        prepare_data,
        train,
    )

    path = tmp_path_factory.mktemp("tuning-registry")
    uri = f"sqlite:///{path}/mlflow.db"
    frame = _training_frame()
    X, y = prepare_data(frame, *extract_feature_target_columns(frame))
    split = _ROWS * 4 // 5
    config = TrainingConfig(
        experiment_name="tuning-registry",
        registry_name=_MODEL_NAME,
        xgboost_params={"n_estimators": 10, "max_depth": 3},
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLFLOW_TRACKING_URI", uri)
        mp.delenv("MLFLOW_REGISTRY_URI", raising=False)
        mp.chdir(path)
        assert mlflow.get_tracking_uri() == uri, "a tracking URI was set before the build"
        assert mlflow.get_registry_uri() == uri, "a registry URI was set before the build"
        train(X.iloc[:split], y.iloc[:split], X.iloc[split:], y.iloc[split:], config)
        client = MlflowClient()
        (version,) = client.search_model_versions(f"name='{_MODEL_NAME}'")
        client.transition_model_version_stage(_MODEL_NAME, version.version, "Production")
    return TuningRegistry(uri=uri, run_id=version.run_id)


@pytest.fixture(scope="module")
def tuning_registry(tuning_registry_store: TuningRegistry) -> Iterator[TuningRegistry]:
    """Point MLflow at the test registry for one module, restored when it ends.

    A tracking URI that still names the store when a module starts was left by an
    earlier module, which fails here rather than going unnoticed.
    """
    assert os.environ.get("MLFLOW_TRACKING_URI") != tuning_registry_store.uri, (
        "the test registry leaked from an earlier module"
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MLFLOW_TRACKING_URI", tuning_registry_store.uri)
        mp.delenv("MLFLOW_REGISTRY_URI", raising=False)
        yield tuning_registry_store
