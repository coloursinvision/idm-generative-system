#!/usr/bin/env bash
#
# train_with_hash.sh — DVC train stage entrypoint with dataset hash injection.
#
# Extracts the md5 hash of data/synthetic/dataset.parquet from dvc.lock
# (under the generate stage's outs), exports it as DVC_DATASET_HASH, and
# invokes the training script. engine.ml.model_training.train() reads the
# env var and logs it as an MLflow tag (TODO-S13-E — closes V2.3 endpoint
# `TuningResponse.dataset_dvc_hash` provenance gap).
#
# Standalone-runnable for testing:
#   bash scripts/train_with_hash.sh
#
# Invoked by dvc.yaml train stage cmd.

set -euo pipefail

DVC_DATASET_HASH=$(python -c "
import yaml
d = yaml.safe_load(open('dvc.lock'))
outs = d['stages']['generate']['outs']
print(next(o['md5'] for o in outs if o['path'] == 'data/synthetic/dataset.parquet'))
")
export DVC_DATASET_HASH

echo "[train_with_hash.sh] DVC_DATASET_HASH=${DVC_DATASET_HASH}"
exec python scripts/train_model.py
