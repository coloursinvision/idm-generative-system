"""Tests for engine.ml.model_training — XGBoost training scaffold.

Covers:
    - Pipeline construction (single + multi-output).
    - Feature/target column extraction.
    - Data preparation (NaN imputation).
    - Training smoke test on synthetic data.
    - MLflow logging produces expected artifacts.
    - Optuna HPO smoke test (minimal trial count).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from engine.ml.model_training import (
    OptunaConfig,
    TrainingConfig,
    build_pipeline,
    build_preprocessor,
    extract_feature_target_columns,
    prepare_data,
    run_optuna_study,
    train,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_training_df(n_rows: int = 100) -> pd.DataFrame:
    """Build a minimal synthetic DataFrame for training tests.

    Produces a DataFrame with the same column structure as
    SyntheticDatasetGenerator output, but with random values.
    """
    rng = np.random.default_rng(42)
    regions = [
        "DETROIT_FIRST_WAVE",
        "DETROIT_UR",
        "DREXCIYA",
        "UK_IDM",
        "UK_BRAINDANCE",
        "JAPAN_IDM",
    ]

    region_choices = rng.choice(regions, size=n_rows)
    sub_regions: list[str | None] = [
        rng.choice(["TOKYO", "OSAKA"]) if r == "JAPAN_IDM" else None
        for r in region_choices
    ]

    return pd.DataFrame(
        {
            "bpm": rng.uniform(60, 200, n_rows),
            "pitch_midi": rng.uniform(36, 96, n_rows),
            "swing": [
                float(rng.uniform(0, 1)) if rng.random() > 0.1 else None
                for _ in range(n_rows)
            ],
            "region": region_choices.tolist(),
            "sub_region": sub_regions,
            "tuning_hz": rng.choice([432.0, 440.0], size=n_rows).tolist(),
            "freq_pitch_ref": rng.uniform(200, 600, n_rows),
            "freq_bpm_harmonic": rng.uniform(100, 400, n_rows),
            "freq_mains_fundamental": rng.uniform(45, 65, n_rows),
            "swing_amount": rng.uniform(0, 1, n_rows),
            "reverb_decay": rng.uniform(100, 2000, n_rows),
            "reverb_diffusion": rng.uniform(0, 1, n_rows),
            "noise_sub_bass_hz": rng.uniform(20, 80, n_rows),
            "noise_floor_hz": rng.uniform(50, 200, n_rows),
            "noise_floor_db": rng.uniform(-90, 0, n_rows),
            "is_perturbed": [i % 2 == 1 for i in range(n_rows)],
            "perturbation_idx": [i % 2 for i in range(n_rows)],
        }
    )


# ---------------------------------------------------------------------------
# Pipeline construction
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    """Pipeline construction produces valid scikit-learn Pipelines."""

    def test_single_target_pipeline(self) -> None:
        pipeline = build_pipeline(n_targets=1)
        assert hasattr(pipeline, "fit")
        assert hasattr(pipeline, "predict")
        assert "preprocessor" in pipeline.named_steps
        assert "regressor" in pipeline.named_steps

    def test_multi_target_pipeline(self) -> None:
        from sklearn.multioutput import MultiOutputRegressor

        pipeline = build_pipeline(n_targets=5)
        regressor = pipeline.named_steps["regressor"]
        assert isinstance(regressor, MultiOutputRegressor)

    def test_custom_xgboost_params(self) -> None:
        params = {"n_estimators": 200, "max_depth": 4}
        pipeline = build_pipeline(params, n_targets=1)
        regressor = pipeline.named_steps["regressor"]
        assert regressor.n_estimators == 200
        assert regressor.max_depth == 4

    def test_default_params_applied(self) -> None:
        pipeline = build_pipeline(n_targets=1)
        regressor = pipeline.named_steps["regressor"]
        assert regressor.n_estimators == 500
        assert regressor.max_depth == 6


class TestBuildPreprocessor:
    """Preprocessor handles categorical and numeric features."""

    def test_preprocessor_structure(self) -> None:
        preprocessor = build_preprocessor()
        transformer_names = [name for name, _, _ in preprocessor.transformers]
        assert "cat" in transformer_names
        assert "num" in transformer_names


# ---------------------------------------------------------------------------
# Feature / target extraction
# ---------------------------------------------------------------------------


class TestExtractColumns:
    """Feature and target column identification."""

    def test_feature_columns(self) -> None:
        df = _make_training_df(10)
        feature_cols, _ = extract_feature_target_columns(df)
        assert "bpm" in feature_cols
        assert "pitch_midi" in feature_cols
        assert "swing" in feature_cols
        assert "region" in feature_cols
        assert "sub_region" in feature_cols

    def test_target_columns(self) -> None:
        df = _make_training_df(10)
        _, target_cols = extract_feature_target_columns(df)
        assert "tuning_hz" in target_cols
        assert "freq_pitch_ref" in target_cols
        assert "freq_bpm_harmonic" in target_cols

    def test_metadata_excluded_from_targets(self) -> None:
        df = _make_training_df(10)
        _, target_cols = extract_feature_target_columns(df)
        assert "is_perturbed" not in target_cols
        assert "perturbation_idx" not in target_cols

    def test_missing_feature_column_raises(self) -> None:
        df = _make_training_df(10).drop(columns=["bpm"])
        with pytest.raises(ValueError, match="Missing feature columns"):
            extract_feature_target_columns(df)


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------


class TestPrepareData:
    """NaN imputation and feature/target matrix preparation."""

    def test_sub_region_nan_imputed(self) -> None:
        df = _make_training_df(20)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, _ = prepare_data(df, feature_cols, target_cols)
        assert not X["sub_region"].isna().any()
        assert "__NaN__" in X["sub_region"].values

    def test_swing_nan_imputed(self) -> None:
        df = _make_training_df(100)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, _ = prepare_data(df, feature_cols, target_cols)
        assert not X["swing"].isna().any()

    def test_target_nan_imputed(self) -> None:
        df = _make_training_df(10)
        # Inject NaN into a freq column.
        df.loc[0, "freq_pitch_ref"] = None
        feature_cols, target_cols = extract_feature_target_columns(df)
        _, y = prepare_data(df, feature_cols, target_cols)
        assert not y.isna().any().any()

    def test_output_shapes(self) -> None:
        df = _make_training_df(50)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, y = prepare_data(df, feature_cols, target_cols)
        assert len(X) == 50
        assert len(y) == 50
        assert X.shape[1] == len(feature_cols)
        assert y.shape[1] == len(target_cols)


# ---------------------------------------------------------------------------
# Training smoke test
# ---------------------------------------------------------------------------


class TestTrain:
    """Training pipeline runs end-to-end on synthetic data."""

    def test_train_smoke(self, tmp_path: Any) -> None:
        """Full training run with MLflow tracking to temp directory."""
        import mlflow

        mlflow.set_tracking_uri(f"file://{tmp_path}/mlruns")

        df = _make_training_df(200)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, y = prepare_data(df, feature_cols, target_cols)

        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        config = TrainingConfig(
            test_size=0.2,
            random_state=42,
            experiment_name="test-smoke",
            registry_name="TestModel",
            xgboost_params={"n_estimators": 10, "max_depth": 3},
        )

        pipeline, metrics = train(X_train, y_train, X_test, y_test, config)

        # Pipeline is fitted.
        assert hasattr(pipeline, "predict")
        predictions = pipeline.predict(X_test)
        assert predictions.shape[0] == len(X_test)

        # Metrics are populated.
        assert "rmse_mean" in metrics
        assert "r2_mean" in metrics
        assert metrics["rmse_mean"] >= 0.0

    def test_train_produces_mlflow_artifacts(self, tmp_path: Any) -> None:
        """MLflow run contains logged model artifact."""
        import mlflow

        tracking_uri = f"file://{tmp_path}/mlruns"
        mlflow.set_tracking_uri(tracking_uri)

        df = _make_training_df(100)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, y = prepare_data(df, feature_cols, target_cols)

        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        config = TrainingConfig(
            test_size=0.2,
            random_state=42,
            experiment_name="test-artifacts",
            registry_name="TestArtifactModel",
            xgboost_params={"n_estimators": 10, "max_depth": 3},
        )

        train(X_train, y_train, X_test, y_test, config)

        # Verify MLflow experiment exists.
        experiment = mlflow.get_experiment_by_name("test-artifacts")
        assert experiment is not None

        # Verify at least one run exists.
        runs = mlflow.search_runs(experiment_ids=[experiment.experiment_id])
        assert len(runs) >= 1

        # Verify metrics are logged.
        latest_run = runs.iloc[0]
        assert "metrics.rmse_mean" in latest_run.index
        assert "metrics.r2_mean" in latest_run.index


# ---------------------------------------------------------------------------
# Optuna HPO smoke test
# ---------------------------------------------------------------------------


class TestOptunaStudy:
    """Optuna hyperparameter optimisation smoke test."""

    def test_optuna_smoke(self, tmp_path: Any) -> None:
        """Run 3 Optuna trials and verify best pipeline is returned."""
        import mlflow

        mlflow.set_tracking_uri(f"file://{tmp_path}/mlruns")

        df = _make_training_df(200)
        feature_cols, target_cols = extract_feature_target_columns(df)
        X, y = prepare_data(df, feature_cols, target_cols)

        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        training_config = TrainingConfig(
            test_size=0.2,
            random_state=42,
            experiment_name="test-optuna",
            registry_name="TestOptunaModel",
        )

        optuna_config = OptunaConfig(
            n_trials=3,
            timeout_seconds=300,
            sampler_seed=42,
            xgboost_ranges={
                "n_estimators_min": 10,
                "n_estimators_max": 50,
                "max_depth_min": 2,
                "max_depth_max": 5,
                "learning_rate_min": 0.05,
                "learning_rate_max": 0.2,
                "subsample_min": 0.7,
                "subsample_max": 1.0,
                "colsample_bytree_min": 0.7,
                "colsample_bytree_max": 1.0,
                "min_child_weight_min": 1,
                "min_child_weight_max": 5,
                "reg_alpha_min": 0.0,
                "reg_alpha_max": 0.5,
                "reg_lambda_min": 0.0,
                "reg_lambda_max": 0.5,
            },
        )

        with patch("optuna.logging.set_verbosity"):
            best_pipeline, best_metrics, study = run_optuna_study(
                X_train,
                y_train,
                X_test,
                y_test,
                training_config,
                optuna_config,
            )

        # Study completed expected trials.
        assert len(study.trials) == 3

        # Best pipeline is fitted.
        predictions = best_pipeline.predict(X_test)
        assert predictions.shape[0] == len(X_test)

        # Best metrics are populated.
        assert "rmse_mean" in best_metrics
        assert best_metrics["rmse_mean"] >= 0.0
