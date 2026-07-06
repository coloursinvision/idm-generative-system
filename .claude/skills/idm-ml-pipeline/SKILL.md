---
name: idm-ml-pipeline
description: >-
  ML pipeline discipline for the IDM Generative System: DVC stages, dataset
  generation, train/val/test split rules, MLflow registry over Tailscale, and the
  project's hard-won honest-metrics rules. Use when running or modifying dvc repro,
  scripts/generate_dataset.py, scripts/train_model.py, engine/ml/* (schema, mapper,
  profiles, resonance rules, training), interpreting RMSE metrics, touching the
  /tuning model, or answering why tuning_hz is not a regression target.
---

# IDM — ML pipeline

## Pipeline shape

Three DVC stages (`dvc.yaml`), parameterised solely by `params.yaml` (single
source of truth — never hardcode pipeline config in scripts):

```
generate  python scripts/generate_dataset.py  → data/synthetic/dataset.parquet
validate  python scripts/validate_schema.py   (pandera schema gate)
train     bash scripts/train_with_hash.sh     (captures dataset hash, trains, logs to MLflow)
```

- Dataset size: `specs_per_region × 6 regions × (1 + n_perturbations)` rows;
  current params give 150 × 6 × 11 = **9,900 rows**. `master_seed: 42` makes
  generation bit-identical for the same (seed, config, specs) triple.
- Run the full chain with `dvc repro`; never run `train` against a dataset whose
  `generate`/`validate` stages are stale. `scripts/preflight_dvc_repro.sh` is the
  pre-run checklist.
- **Execution hosts:** training runs on the Linux workstation (or a MacBook for
  CPU-sized runs). Training on the production droplet is forbidden.
- MLflow tracking + registry are reached over Tailscale; `MLFLOW_TRACKING_URI`
  and the S3-compatible artefact endpoint come from `.env.shared` via
  `./scripts/run-with-env.sh` (see the `idm-dev-environment` skill). Credentialed
  pipeline commands run through the wrapper.

## Data model (Layer 1→2→3)

- **Layer 2 spokes** in the vault (`02-Knowledge/supporting/profiles/` and
  `resonance/`) are the editorial source of regional DSP knowledge; they are
  consumed by `engine/ml/regional_profiles.py` (requires `IDM_VAULT_PATH`) and
  mirrored in `engine/ml/resonance_rules.py`.
- **Region vocabulary** (load-bearing, used across schema/mapper/API):
  `DETROIT_FIRST_WAVE`, `DETROIT_UR`, `DREXCIYA`, `JAPAN_IDM` (sub_region
  `TOKYO`/`OSAKA`), `UK_IDM`, `UK_BRAINDANCE`.
- `engine/ml/deterministic_mapper.py` maps a TrackSpec deterministically to DSP
  features; `gaussian_noise.py` produces the perturbed variants; feature/target
  framing lives in `dataset_schema.py` + `model_training.py`.

## Honest-metrics rules (each closed a real defect — do not regress)

1. **Group-aware split.** All rows from one `TrackSpec` share a `spec_id` and
   identical features. Train/val/test splits use
   `sklearn.model_selection.GroupShuffleSplit` keyed on `spec_id` so no spec
   straddles partitions. A plain row-wise split reintroduces spec-level leakage
   and produces flattering-but-fake RMSE. When this was fixed, RMSE *rose* —
   that rise was honesty, not regression.
2. **HPO never sees test.** Three-way split: Optuna optimises on the held-out
   **validation** set, the final model is refit on train+val, and test metrics
   are computed **once**. The metric HPO optimises is never the metric reported.
3. **`tuning_hz` is not a target.** It is a deterministic constant (A4 = 440.0)
   emitted in the dataset for schema completeness but excluded from both model
   inputs and targets (`dataset_schema.py` documents the exclusion; as a target
   it had zero variance and a meaningless rmse of 0.0). The regression targets
   are the 15 `freq_*` columns only, and `/tuning` echoes `tuning_hz: 440.0`
   verbatim. Making 432-vs-440 functional is known future work, not a bug.

Corollary: **never compare RMSE numbers across these methodology changes** —
older, lower numbers were measured under leakier protocols.

## Serving

- `/tuning` (FastAPI) loads the registered model once at startup via a fail-soft
  lifespan; registration is gated on mlflow importability (`_HAS_MLFLOW`). See
  the `idm-architecture` skill for the pattern.
- Do not hardcode registry state ("version N in Staging") in code, docs, or
  tests — it changes with every promotion. Query MLflow instead.
- Known migration debt: the code uses stage-based registry methods
  (`get_latest_versions(stages=...)`); MLflow is moving stages → aliases. Check
  current status before extending registry code.
- Local full `pytest` shows a block of mlflow-environment failures **by design**
  when no model is reachable locally; the CI Test Suite (installed with `[dev]`
  only) is the green gate. Investigate a *change* in the failure count, not its
  existence.

## Verification order for pipeline changes

1. `mypy engine api` (must stay clean),
2. unit tests of the touched `engine/ml` module (no wrapper needed if the module
   doesn't read credentials at import),
3. `./scripts/run-with-env.sh pytest tests/test_tuning_api.py` for serving paths,
4. `dvc repro` end-to-end only when the change affects pipeline outputs — then
   check `dvc status` is clean and metrics moved for the reason you expected.

Stop on first red. If a metrics change is surprising, treat it as a finding to
explain, never as noise to accept.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `06-MLOps/V2_ROADMAP.md`,
`06-MLOps/RUNBOOK_DVC_REPRO_BASELINE.md`, `00-Project/DECISIONS.md` (pipeline
decisions), `02-Knowledge/supporting/` spokes. Verified against `develop`
v0.10.1 (2026-07-05). Registry state and RMSE numbers are not encoded here —
read them from MLflow / `models/metrics.json` at time of use.*
