---
name: idm-dev-environment
description: >-
  Machine setup, conda environment, Node baseline, and the SOPS+age secrets flow for
  the IDM Generative System (~/dev/IDM_Generative_System_app). Use when booting the
  backend or frontend, running credentialed tests, diagnosing "OPENAI_API_KEY not set"
  or SOPS/age decryption errors, provisioning a new machine, adding or rotating a
  secret, fixing npm/conda/Node toolchain issues, or resolving IDM_VAULT_PATH /
  profile-loading failures in engine/ml.
---

# IDM — development environment

## Machines and roles

| Role | Notes |
|---|---|
| Primary Linux workstation | dev + ML training host; conda via Miniconda, Node via nvm |
| Secondary macOS machines | same wrapper + conda flow; ML training stays on the workstation |
| Production droplet | serving only — **training on the droplet is forbidden** (resource + reproducibility rule) |

(Deliberately roles-only: hardware inventory does not belong in a public repo.)

## Python environment

- conda env **`idm`**, `python=3.11` (pins in `environment.yml`; numpy `>=1.26.0`).
- Bootstrap: `conda activate idm && pip install -e ".[dev,ml,monitoring]"`.
- CI installs `[dev]` only — code importable without `[ml]` extras must stay that way
  (see the `_HAS_ML_EXTRAS` pattern in the `idm-architecture` skill).
- `mypy engine api` must pass for every commit touching those trees.

## Node / frontend toolchain

- Local baseline: **Node 22 LTS via nvm** (verify with `node -v`).
- Known drift, do not "fix" casually: the e2e workflow pins Node 24, `ci.yml` does
  not pin Node at all. Consequence: `package-lock.json` can shrink or churn when
  `npm install` runs under a different Node/npm than CI used.
- **Lockfile discipline:** never commit `package-lock.json` changes produced by a
  routine `npm install`; commit lockfile diffs only when a dependency change is
  intentional.

## Secrets: three tiers (decision rule first)

> "If this value leaked to a public repo right now, would I rotate it at the
> provider?" Yes → tier 2 (encrypted). No → tier 3 (plaintext).

1. **Root of trust** — the age private key. Per-machine, outside Git, located only
   via the `SOPS_AGE_KEY_FILE` env pointer. Its location, backup, and rotation
   procedure are deliberately NOT documented here or anywhere in this repo — they
   live in the private vault (`03-Code/SECRETS_ARCHITECTURE_2026-05-29.md`).
2. **Encrypted secrets** — `secrets/app.enc.yaml` (committed, SOPS-encrypted).
   Six values: `OPENAI_API_KEY`, `QDRANT_API_KEY`, `DO_SPACES_KEY`,
   `DO_SPACES_SECRET`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
3. **Shared non-secrets** — `.env.shared` (committed plaintext). Six values:
   `QDRANT_URL`, `DO_SPACES_BUCKET`, `DO_SPACES_ENDPOINT_URL`,
   `MLFLOW_TRACKING_URI`, `MLFLOW_S3_ENDPOINT_URL`, `LANGFUSE_HOST`.

Shell init (`~/.zshrc`) exports exactly two project pointers and nothing else
credential-related: `SOPS_AGE_KEY_FILE` (key location) and `IDM_VAULT_PATH`
(vault location — a path, not a credential). Adding any real secret to shell
init is forbidden; it reverses the 2026-05-29 migration.

## The wrapper — canonical credential path

Every process needing credentials runs through `./scripts/run-with-env.sh <cmd>`:

1. `set -a; source .env.shared` (plaintext non-secrets),
2. SOPS-decrypts `secrets/app.enc.yaml` to a mode-600 `mktemp` file
   (mktemp + `trap` cleanup, chosen over process substitution so the decrypted
   content has a controlled lifetime and is removed on ANY exit),
3. sources it, exports boto3 aliases (`AWS_ACCESS_KEY_ID=$DO_SPACES_KEY`,
   `AWS_SECRET_ACCESS_KEY=$DO_SPACES_SECRET`),
4. `exec`s the command.

```bash
./scripts/run-with-env.sh uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
./scripts/run-with-env.sh pytest tests/test_api.py
```

- A bare `uvicorn` / `pytest tests/test_api.py` failing with
  `OSError: OPENAI_API_KEY not set` is **by design** — it enforces the canonical
  path. Do not bypass the wrapper; do not export the key manually to "fix" it.
- If the wrapper itself fails with that error, diagnose at the wrapper, not the
  consumer. The cause is one of: `SOPS_AGE_KEY_FILE` unset, pointing at the wrong
  path, or a corrupt key file.
- `scripts/run-with-env.sh` and `.sops.yaml` are operator-frozen files: do not
  edit them (not even comments) without an explicit operator decision.
- Tests that never touch credentials (pure-function suites like
  `tests/test_regional_profiles.py`) run WITHOUT the wrapper.

## SOPS operations

```bash
sops secrets/app.enc.yaml                                           # edit decrypted in $EDITOR
sops --decrypt --extract '["openai_api_key"]' secrets/app.enc.yaml  # read one value
sops updatekeys secrets/app.enc.yaml                                # re-encrypt after recipient change
```

Adding a machine or rotating the age key: follow the private vault procedure —
never improvise it, and never place the key in Git, cloud storage, `/tmp`,
email, or any sync folder, even briefly.

## IDM_VAULT_PATH is effectively mandatory

`engine/ml/regional_profiles.py` resolves the profile-spoke directory from
`IDM_VAULT_PATH`. Its built-in fallback points at a sibling directory named
`IDM_Obsidian` next to the repo root, which does not exist on current machines
(the vault lives at `~/Obsidian/IDM_Vault`). Consequences:

- ML code paths that load regional profiles fail without `IDM_VAULT_PATH` set.
- Tests avoid this by passing `profiles_dir=` explicitly.
- Treat a missing/wrong `IDM_VAULT_PATH` as the first suspect for
  profile-loading errors; do not patch the fallback as a drive-by (known,
  registered infra debt — fixing it is its own ticket).

## Clean sub-shell smoke test (canonical "works outside my shell" check)

```bash
env -i \
  HOME="$HOME" \
  PATH="/usr/bin:/bin:/usr/local/bin:$HOME/miniconda3/envs/idm/bin" \
  SOPS_AGE_KEY_FILE="$SOPS_AGE_KEY_FILE" \
  bash -c 'cd ~/dev/IDM_Generative_System_app && \
           ./scripts/run-with-env.sh pytest tests/test_api.py --collect-only'
```

Success = tests collected. Failure on a fresh machine = provisioning incomplete.
The same `env -i` technique doubles as a **negative smoke test**: to prove a file
no longer exports secrets, assert the variables are `(unset)` in a clean shell —
"I remember removing it" is not verification.

## Forbidden environment patterns

- **No file-sync clouds** (Dropbox, iCloud, OneDrive, Drive, Syncthing) anywhere
  near the working tree or the vault. If `npm install` fails with
  `TAR_ENTRY_ERROR` or `ENOENT`, suspect a re-introduced sync watcher —
  diagnose, don't work around.
- No application secrets in shell init (pointers only, see above).
- No wrapper bypass for credentialed processes.
- Working tree stays at `~/dev/IDM_Generative_System_app`; vault at
  `~/Obsidian/IDM_Vault` (synced via its own Git repo, operator-driven — the
  vault is read-only for Claude Code).

---
*Sources (vault `~/Obsidian/IDM_Vault`): `03-Code/SECRETS_ARCHITECTURE_2026-05-29.md`,
`03-Code/TESTING_METHODOLOGY.md` §6–§8, `06-MLOps/RUNBOOK_DVC_REPRO_BASELINE.md`.
Verified against `develop` v0.10.1 and the live workstation (2026-07-05).
Key locations and backup names are intentionally absent; see the private vault.*
