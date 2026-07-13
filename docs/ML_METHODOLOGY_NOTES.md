# ML Methodology Notes — Leakage-Safe Training Pipeline

Three methodology pitfalls that synthetic-dataset regression pipelines commonly
fall into, and the structural guard this project uses against each. These are
invariants of the training pipeline (`engine/ml/`), not historical notes: any
change to the split, the HPO loop, or the target framing should be re-checked
against this list.

## 1. Group-aware splitting — no spec-level leakage

The synthetic dataset expands each track spec into 1 base + N perturbed rows
that share a `spec_id` and identical features. A plain row-level train/test
split would place near-duplicates of the same spec on both sides of the
boundary and inflate reported accuracy. **Guard:** every split goes through
`sklearn.model_selection.GroupShuffleSplit` keyed on `spec_id`
(`engine/ml/model_training.py` — `split_by_group`,
`split_train_val_test_by_group`; wired with `groups=df["spec_id"]` in
`scripts/train_model.py`), so a spec lies wholly on one side of every
partition. When this guard was introduced, reported RMSE **rose** — that rise
was honesty, not regression.

## 2. HPO never sees the test set

Three-way group split. Optuna trials fit on **train** and are scored on
**validation**; the best configuration is refit on **train+val**; test metrics
are computed **once**, for the final report
(`engine/ml/model_training.py` — `run_optuna_study`). The quantity the
hyperparameter search optimises is never the quantity reported.

## 3. No zero-variance targets

`tuning_hz` is a deterministic A4 reference (440.0 by construction) — a chosen
convention, not a learnable quantity. As a regression target it had zero
variance and contributed a meaningless RMSE of 0.0 that diluted the mean
metric. It is excluded from both features and targets — the regression targets
are the `freq_*` columns only (`engine/ml/model_training.py`) — and stays in
the dataset for provenance; the `/tuning` endpoint echoes the constant.

## Verifying the claims

The pipeline's honesty properties are falsifiable by reproduction: `dvc repro`
with the pinned master seed regenerates the dataset bit-identically (content
hash unchanged) and retrains to a byte-identical `models/metrics.json` on the
same host. Corollary: RMSE values are **not comparable across the methodology
changes above** — numbers measured under leakier protocols are systematically
flattering.

*Last verified against `develop`: 2026-07-13.*
