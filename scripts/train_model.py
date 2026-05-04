"""Train XGBoost tuning estimator via DVC pipeline.

CLI entry point for the ``train`` stage in ``dvc.yaml``.
All parameters are read from ``params.yaml`` (DVC-tracked).
Actual training logic lives in :mod:`engine.ml.model_training`.

Usage:
    python scripts/train_model.py                # standalone
    dvc repro train                               # via DVC pipeline

Outputs:
    models/tuning_estimator/    — MLflow model artifact (DVC-tracked)
    models/metrics.json         — per-target RMSE + aggregate (DVC metric)
    models/feature_importance.json — feature importance (DVC plot)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import yaml  # type: ignore[import-untyped]
from sklearn.model_selection import train_test_split

from engine.ml.dataset_schema import DATASET_SCHEMA
from engine.ml.model_training import (
    OptunaConfig,
    TrainingConfig,
    extract_feature_target_columns,
    prepare_data,
    run_optuna_study,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATASET_PATH = Path("data/synthetic/dataset.parquet")
_MODEL_DIR = Path("models/tuning_estimator")
_METRICS_PATH = Path("models/metrics.json")
_IMPORTANCE_PATH = Path("models/feature_importance.json")


# ---------------------------------------------------------------------------
# Feature importance extraction
# ---------------------------------------------------------------------------


def _extract_feature_importance(
    pipeline: object,
    feature_names: list[str],
) -> dict[str, float]:
    """Extract feature importance from a fitted pipeline.

    Handles both single-output XGBRegressor and MultiOutputRegressor
    wrapping. For multi-output, importance is averaged across estimators.

    Args:
        pipeline: Fitted scikit-learn Pipeline.
        feature_names: Preprocessed feature names.

    Returns:
        Dict mapping feature name to importance score.
    """
    from sklearn.multioutput import MultiOutputRegressor
    from sklearn.pipeline import Pipeline

    if not isinstance(pipeline, Pipeline):
        return {}

    regressor = pipeline.named_steps.get("regressor")
    if regressor is None:
        return {}

    if isinstance(regressor, MultiOutputRegressor):
        # Average importance across sub-estimators.
        importances = np.mean(
            [est.feature_importances_ for est in regressor.estimators_],
            axis=0,
        )
    elif hasattr(regressor, "feature_importances_"):
        importances = regressor.feature_importances_
    else:
        return {}

    # Map to feature names. Preprocessor may change count via encoding.
    if len(importances) != len(feature_names):
        # Fallback: use numeric indices.
        feature_names = [f"feature_{i}" for i in range(len(importances))]

    return {
        name: float(imp)
        for name, imp in zip(feature_names, importances, strict=False)
    }


def _get_preprocessed_feature_names(pipeline: object) -> list[str]:
    """Extract feature names after preprocessing.

    Args:
        pipeline: Fitted scikit-learn Pipeline.

    Returns:
        List of feature names post-transformation.
    """
    from sklearn.pipeline import Pipeline

    if not isinstance(pipeline, Pipeline):
        return []

    preprocessor = pipeline.named_steps.get("preprocessor")
    if preprocessor is None:
        return []

    try:
        return list(preprocessor.get_feature_names_out())
    except AttributeError:
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Load params, train model, export artifacts."""
    params_path = Path("params.yaml")
    if not params_path.exists():
        logger.error("params.yaml not found in working directory")
        sys.exit(1)

    with params_path.open() as f:
        params = yaml.safe_load(f)

    train_params = params["train"]

    # --- Load and validate dataset ---
    if not _DATASET_PATH.exists():
        logger.error("Dataset not found: %s", _DATASET_PATH)
        sys.exit(1)

    logger.info("Loading dataset from %s", _DATASET_PATH)
    df = pd.read_parquet(_DATASET_PATH, engine="pyarrow")
    logger.info("Loaded: %d rows × %d columns", len(df), len(df.columns))

    # Schema validation gate.
    DATASET_SCHEMA.validate(df)
    logger.info("Schema validation passed")

    # --- Extract features and targets ---
    feature_cols, target_cols = extract_feature_target_columns(df)
    X, y = prepare_data(df, feature_cols, target_cols)  # noqa: N806
    logger.info(
        "Features: %d columns, Targets: %d columns",
        len(feature_cols),
        len(target_cols),
    )

    # --- Train/test split (stratified by region) ---
    X_train, X_test, y_train, y_test = train_test_split(  # noqa: N806
        X,
        y,
        test_size=train_params["test_size"],
        random_state=train_params["random_state"],
        stratify=X["region"],
    )
    logger.info("Train: %d rows, Test: %d rows", len(X_train), len(X_test))

    # --- Configure ---
    optuna_params = train_params["optuna"]
    xgboost_ranges = train_params["xgboost"]

    training_config = TrainingConfig(
        test_size=train_params["test_size"],
        random_state=train_params["random_state"],
        experiment_name=train_params["experiment_name"],
        registry_name=train_params["registry_name"],
    )

    optuna_config = OptunaConfig(
        n_trials=optuna_params["n_trials"],
        timeout_seconds=optuna_params["timeout_seconds"],
        sampler_seed=optuna_params["sampler_seed"],
        xgboost_ranges=xgboost_ranges,
    )

    # --- Train with Optuna HPO ---
    best_pipeline, best_metrics, study = run_optuna_study(
        X_train,
        y_train,
        X_test,
        y_test,
        training_config,
        optuna_config,
    )

    # --- Export model artifact for DVC ---
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    mlflow.sklearn.save_model(best_pipeline, str(_MODEL_DIR))
    logger.info("Model artifact saved to %s", _MODEL_DIR)

    # --- Export metrics (DVC metric) ---
    _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    metrics_report = {
        **best_metrics,
        "best_trial_number": study.best_trial.number,
        "best_trial_params": study.best_trial.params,
        "n_trials_completed": len(study.trials),
    }
    with _METRICS_PATH.open("w") as f:
        json.dump(metrics_report, f, indent=2)
    logger.info("Metrics written to %s", _METRICS_PATH)

    # --- Export feature importance (DVC plot) ---
    feature_names = _get_preprocessed_feature_names(best_pipeline)
    importance = _extract_feature_importance(best_pipeline, feature_names)
    if importance:
        importance_sorted = dict(
            sorted(importance.items(), key=lambda x: x[1], reverse=True)
        )
        with _IMPORTANCE_PATH.open("w") as f:
            json.dump(importance_sorted, f, indent=2)
        logger.info("Feature importance written to %s", _IMPORTANCE_PATH)
    else:
        logger.warning("Could not extract feature importance")


if __name__ == "__main__":
    main()
