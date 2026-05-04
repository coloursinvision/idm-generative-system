"""model_training — XGBoost training pipeline with Optuna HPO and MLflow tracking.

Pipeline layer: 6
Consumes:       dataset_generator (pd.DataFrame — validated by dataset_schema)
                dataset_schema (DATASET_SCHEMA — validation gate)
Consumed by:    scripts/train_model.py (DVC pipeline entry point)
                V2.3 model serving (/tuning endpoint)
Status:         complete

Implements the supervised ML training workflow for the tuning estimation
model. The pipeline:

    1. Loads and validates a synthetic dataset (parquet).
    2. Splits into train/test sets (stratified by region).
    3. Preprocesses features via scikit-learn ``Pipeline``
       (``OrdinalEncoder`` for categoricals, ``StandardScaler`` for
       numerics).
    4. Wraps ``XGBRegressor`` in ``MultiOutputRegressor`` for
       multi-target regression (``tuning_hz`` + ``freq_*`` columns).
    5. Optimises hyperparameters via Optuna (TPE sampler,
       ``MedianPruner``).
    6. Logs params, metrics, and model artifacts to MLflow.

Design principles:
    - **Spoke-derived feature sets:** Categorical encoder categories
      are extracted from ``RegionCode`` / ``SubRegion`` type aliases.
    - **Reproducibility:** All random state is seeded and logged.
    - **MLflow-first:** Every training run is an MLflow run. The best
      Optuna trial is registered in the MLflow Model Registry.
    - **Composability:** :func:`build_pipeline`, :func:`train`,
      :func:`run_optuna_study` are independently callable for testing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, get_args

import mlflow
import numpy as np
import optuna
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler
from xgboost import XGBRegressor

from engine.ml.regional_profiles import RegionCode, SubRegion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_REGIONS: list[str] = list(get_args(RegionCode))
_VALID_SUB_REGIONS: list[str] = list(get_args(SubRegion))

# Input feature columns consumed by the model.
_CATEGORICAL_FEATURES: list[str] = ["region", "sub_region"]
_NUMERIC_FEATURES: list[str] = [
    "bpm",
    "pitch_midi",
    "swing",
]

# Columns excluded from features (metadata, targets, or identifiers).
_EXCLUDE_COLUMNS: set[str] = {"is_perturbed", "perturbation_idx"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrainingConfig:
    """Configuration for a single training run.

    Attributes:
        test_size: Fraction of data reserved for testing.
        random_state: Seed for train/test split and XGBoost.
        experiment_name: MLflow experiment name.
        registry_name: MLflow Model Registry name.
        xgboost_params: XGBoost hyperparameters (passed to XGBRegressor).
    """

    test_size: float = 0.2
    random_state: int = 42
    experiment_name: str = "tuning-estimator"
    registry_name: str = "TuningEstimator"
    xgboost_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptunaConfig:
    """Configuration for Optuna hyperparameter optimisation.

    Attributes:
        n_trials: Maximum number of Optuna trials.
        timeout_seconds: Wall-clock timeout for the study.
        sampler_seed: Seed for the TPE sampler.
        xgboost_ranges: Search space bounds for XGBoost hyperparameters.
            Keys follow the pattern ``<param>_min`` / ``<param>_max``.
    """

    n_trials: int = 50
    timeout_seconds: int = 1800
    sampler_seed: int = 42
    xgboost_ranges: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Feature / target extraction
# ---------------------------------------------------------------------------


def extract_feature_target_columns(
    df: pd.DataFrame,
) -> tuple[list[str], list[str]]:
    """Identify feature and target columns from a validated DataFrame.

    Feature columns: ``bpm``, ``pitch_midi``, ``swing``, ``region``,
    ``sub_region`` (input specification columns).

    Target columns: ``tuning_hz`` + all ``freq_*`` columns (model
    prediction targets).

    Columns in :data:`_EXCLUDE_COLUMNS` (metadata) are excluded from
    both sets.

    Args:
        df: Validated synthetic training DataFrame.

    Returns:
        Tuple of (feature_column_names, target_column_names).
    """
    feature_cols = _CATEGORICAL_FEATURES + _NUMERIC_FEATURES
    target_cols = ["tuning_hz", *sorted(
        c for c in df.columns if c.startswith("freq_")
    )]

    # Validate presence.
    missing_features = [c for c in feature_cols if c not in df.columns]
    if missing_features:
        msg = f"Missing feature columns: {missing_features}"
        raise ValueError(msg)

    missing_targets = [c for c in target_cols if c not in df.columns]
    if missing_targets:
        msg = f"Missing target columns: {missing_targets}"
        raise ValueError(msg)

    return feature_cols, target_cols


# ---------------------------------------------------------------------------
# Pipeline construction
# ---------------------------------------------------------------------------


def build_preprocessor() -> ColumnTransformer:
    """Build the scikit-learn preprocessing ColumnTransformer.

    Categorical features (``region``, ``sub_region``) are ordinal-encoded
    with spoke-derived categories. Numeric features (``bpm``,
    ``pitch_midi``, ``swing``) are standard-scaled.

    Returns:
        Fitted-ready ColumnTransformer.
    """
    categorical_transformer = OrdinalEncoder(
        categories=[
            _VALID_REGIONS,
            [*_VALID_SUB_REGIONS, "__NaN__"],
        ],
        handle_unknown="use_encoded_value",
        unknown_value=-1,
    )

    numeric_transformer = StandardScaler()

    return ColumnTransformer(
        transformers=[
            ("cat", categorical_transformer, _CATEGORICAL_FEATURES),
            ("num", numeric_transformer, _NUMERIC_FEATURES),
        ],
        remainder="drop",
    )


def build_pipeline(
    xgboost_params: dict[str, Any] | None = None,
    *,
    random_state: int = 42,
    n_targets: int = 1,
) -> Pipeline:
    """Build the full scikit-learn Pipeline: preprocessor + XGBoost.

    The pipeline wraps ``XGBRegressor`` in ``MultiOutputRegressor``
    when ``n_targets > 1`` for multi-output regression.

    Args:
        xgboost_params: XGBoost hyperparameters. Defaults applied if
            ``None``.
        random_state: Random seed for XGBoost.
        n_targets: Number of target columns. Determines whether
            ``MultiOutputRegressor`` wrapping is applied.

    Returns:
        Unfitted scikit-learn Pipeline.
    """
    params: dict[str, Any] = {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "random_state": random_state,
        "n_jobs": -1,
        "verbosity": 0,
    }
    if xgboost_params:
        params.update(xgboost_params)

    base_estimator = XGBRegressor(**params)

    regressor: XGBRegressor | MultiOutputRegressor = (
        MultiOutputRegressor(base_estimator) if n_targets > 1 else base_estimator
    )

    return Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("regressor", regressor),
        ]
    )


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


def prepare_data(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_cols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prepare feature matrix and target matrix from raw DataFrame.

    Handles NaN imputation for features and targets:
    - ``sub_region`` NaN → ``"__NaN__"`` sentinel (OrdinalEncoder
      compatible).
    - ``swing`` NaN → 0.5 (neutral midpoint).
    - Target NaN (absent ``freq_*`` columns) → 0.0 (absent resonant
      point carries no frequency contribution).

    Args:
        df: Validated synthetic training DataFrame.
        feature_cols: Feature column names.
        target_cols: Target column names.

    Returns:
        Tuple of (X, y) DataFrames ready for pipeline consumption.
    """
    X = df[feature_cols].copy()  # noqa: N806
    y = df[target_cols].copy()

    # Feature NaN handling.
    X["sub_region"] = X["sub_region"].fillna("__NaN__")
    X["swing"] = X["swing"].fillna(0.5)

    # Target NaN handling (absent freq columns).
    y = y.fillna(0.0)

    return X, y


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(
    X_train: pd.DataFrame,  # noqa: N803
    y_train: pd.DataFrame,
    X_test: pd.DataFrame,  # noqa: N803
    y_test: pd.DataFrame,
    config: TrainingConfig,
) -> tuple[Pipeline, dict[str, float]]:
    """Train a single XGBoost pipeline and log to MLflow.

    Fits the pipeline on training data, evaluates on test data, and
    logs parameters, metrics, and the model artifact to MLflow.

    Args:
        X_train: Training feature matrix.
        y_train: Training target matrix.
        X_test: Test feature matrix.
        y_test: Test target matrix.
        config: Training configuration.

    Returns:
        Tuple of (fitted pipeline, metrics dict).
    """
    n_targets = y_train.shape[1]
    pipeline = build_pipeline(
        config.xgboost_params,
        random_state=config.random_state,
        n_targets=n_targets,
    )

    mlflow.set_experiment(config.experiment_name)

    with mlflow.start_run() as run:
        logger.info("MLflow run: %s", run.info.run_id)

        # --- Fit ---
        pipeline.fit(X_train, y_train)

        # --- Evaluate ---
        y_pred = pipeline.predict(X_test)
        if isinstance(y_pred, np.ndarray) and y_pred.ndim == 1:
            y_pred = y_pred.reshape(-1, 1)

        y_test_arr = y_test.values
        metrics: dict[str, float] = {}

        # Per-target RMSE.
        for i, col in enumerate(y_test.columns):
            rmse = float(
                np.sqrt(np.mean((y_test_arr[:, i] - y_pred[:, i]) ** 2))
            )
            metrics[f"rmse_{col}"] = rmse

        # Aggregate RMSE (mean across targets).
        metrics["rmse_mean"] = float(np.mean(list(metrics.values())))

        # R² score.
        from sklearn.metrics import r2_score

        metrics["r2_mean"] = float(
            r2_score(y_test_arr, y_pred, multioutput="uniform_average")
        )

        # --- Log to MLflow ---
        mlflow.log_params(
            {
                "test_size": config.test_size,
                "random_state": config.random_state,
                "n_targets": n_targets,
                "n_train_rows": len(X_train),
                "n_test_rows": len(X_test),
                "target_columns": ",".join(y_test.columns),
                **{
                    f"xgb_{k}": v
                    for k, v in (config.xgboost_params or {}).items()
                },
            }
        )
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(
            pipeline,
            artifact_path="model",
            registered_model_name=config.registry_name,
        )

        logger.info("Metrics: %s", metrics)

    return pipeline, metrics


# ---------------------------------------------------------------------------
# Optuna HPO
# ---------------------------------------------------------------------------


def run_optuna_study(
    X_train: pd.DataFrame,  # noqa: N803
    y_train: pd.DataFrame,
    X_test: pd.DataFrame,  # noqa: N803
    y_test: pd.DataFrame,
    training_config: TrainingConfig,
    optuna_config: OptunaConfig,
) -> tuple[Pipeline, dict[str, float], optuna.Study]:
    """Run Optuna hyperparameter optimisation and return best pipeline.

    Each trial suggests XGBoost hyperparameters within the ranges
    defined in ``optuna_config.xgboost_ranges``, trains a pipeline,
    and evaluates on the test set. The best trial's hyperparameters
    are used for a final training run logged to MLflow.

    Args:
        X_train: Training feature matrix.
        y_train: Training target matrix.
        X_test: Test feature matrix.
        y_test: Test target matrix.
        training_config: Base training configuration.
        optuna_config: Optuna study configuration.

    Returns:
        Tuple of (best pipeline, best metrics, Optuna study).
    """
    ranges = optuna_config.xgboost_ranges
    n_targets = y_train.shape[1]

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int(
                "n_estimators",
                ranges.get("n_estimators_min", 100),
                ranges.get("n_estimators_max", 1000),
            ),
            "max_depth": trial.suggest_int(
                "max_depth",
                ranges.get("max_depth_min", 3),
                ranges.get("max_depth_max", 10),
            ),
            "learning_rate": trial.suggest_float(
                "learning_rate",
                ranges.get("learning_rate_min", 0.01),
                ranges.get("learning_rate_max", 0.3),
                log=True,
            ),
            "subsample": trial.suggest_float(
                "subsample",
                ranges.get("subsample_min", 0.6),
                ranges.get("subsample_max", 1.0),
            ),
            "colsample_bytree": trial.suggest_float(
                "colsample_bytree",
                ranges.get("colsample_bytree_min", 0.6),
                ranges.get("colsample_bytree_max", 1.0),
            ),
            "min_child_weight": trial.suggest_int(
                "min_child_weight",
                ranges.get("min_child_weight_min", 1),
                ranges.get("min_child_weight_max", 10),
            ),
            "reg_alpha": trial.suggest_float(
                "reg_alpha",
                ranges.get("reg_alpha_min", 0.0),
                ranges.get("reg_alpha_max", 1.0),
            ),
            "reg_lambda": trial.suggest_float(
                "reg_lambda",
                ranges.get("reg_lambda_min", 0.0),
                ranges.get("reg_lambda_max", 1.0),
            ),
        }

        pipeline = build_pipeline(
            params,
            random_state=training_config.random_state,
            n_targets=n_targets,
        )
        pipeline.fit(X_train, y_train)

        y_pred = pipeline.predict(X_test)
        if isinstance(y_pred, np.ndarray) and y_pred.ndim == 1:
            y_pred = y_pred.reshape(-1, 1)

        # Minimise mean RMSE across all targets.
        rmse_per_target = np.sqrt(
            np.mean((y_test.values - y_pred) ** 2, axis=0)
        )
        return float(np.mean(rmse_per_target))

    # --- Run study ---
    sampler = optuna.samplers.TPESampler(seed=optuna_config.sampler_seed)
    pruner = optuna.pruners.MedianPruner()
    study = optuna.create_study(
        direction="minimize",
        sampler=sampler,
        pruner=pruner,
        study_name=f"{training_config.experiment_name}-hpo",
    )

    logger.info(
        "Starting Optuna study: %d trials, %ds timeout",
        optuna_config.n_trials,
        optuna_config.timeout_seconds,
    )
    study.optimize(
        objective,
        n_trials=optuna_config.n_trials,
        timeout=optuna_config.timeout_seconds,
    )

    logger.info(
        "Best trial: #%d, RMSE=%.6f, params=%s",
        study.best_trial.number,
        study.best_trial.value,
        study.best_trial.params,
    )

    # --- Final training with best params ---
    best_config = TrainingConfig(
        test_size=training_config.test_size,
        random_state=training_config.random_state,
        experiment_name=training_config.experiment_name,
        registry_name=training_config.registry_name,
        xgboost_params=study.best_trial.params,
    )
    best_pipeline, best_metrics = train(
        X_train, y_train, X_test, y_test, best_config
    )

    return best_pipeline, best_metrics, study
