#!/usr/bin/env bash
#
# run-with-env.sh — entrypoint wrapper that loads the full application
# environment (non-secret config + decrypted secrets) and execs a command.
#
# Combines:
#   - .env.shared          (committed, plaintext: URLs, bucket names, hosts)
#   - secrets/app.enc.yaml (committed, SOPS+age encrypted: API keys, tokens)
#
# After loading, exports DO_SPACES_KEY / DO_SPACES_SECRET also as
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for boto3 consumers (MLflow
# artifact uploads, DVC S3 remote against DigitalOcean Spaces). The
# semantic names stay authoritative in the SOPS file; the AWS_* names
# are runtime-only aliases injected here.
#
# Per DECISIONS D-CRF13-01: plaintext credentials must not live in shell
# rc files; SOPS+age is the canonical store and this wrapper is the
# canonical injector.
#
# Usage:
#   bash scripts/run-with-env.sh <command> [args...]
#
# Examples:
#   bash scripts/run-with-env.sh uvicorn api.main:app --reload
#   bash scripts/run-with-env.sh pytest tests/
#   bash scripts/run-with-env.sh python scripts/train_model.py
#
# Requires: bash 4+, sops 3.13+, age 1.3+, SOPS_AGE_KEY_FILE in env
#           pointing at a valid age key (see SOPS_AGE_RUNBOOK.md).

set -euo pipefail

# Resolve repository root from this script's location, regardless of CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SHARED_FILE="${REPO_ROOT}/.env.shared"
SECRETS_FILE="${REPO_ROOT}/secrets/app.enc.yaml"

# Pre-flight: required inputs exist and are readable.
if [[ ! -r "${SHARED_FILE}" ]]; then
    echo "[run-with-env] ERROR: missing or unreadable: ${SHARED_FILE}" >&2
    exit 2
fi
if [[ ! -r "${SECRETS_FILE}" ]]; then
    echo "[run-with-env] ERROR: missing or unreadable: ${SECRETS_FILE}" >&2
    exit 2
fi
if [[ -z "${SOPS_AGE_KEY_FILE:-}" ]]; then
    echo "[run-with-env] ERROR: SOPS_AGE_KEY_FILE not set. Add to ~/.zshrc:" >&2
    echo '  export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"' >&2
    exit 2
fi
if [[ ! -r "${SOPS_AGE_KEY_FILE}" ]]; then
    echo "[run-with-env] ERROR: age key not readable at ${SOPS_AGE_KEY_FILE}" >&2
    exit 2
fi

# Pre-flight: command to exec was actually provided.
if [[ "$#" -eq 0 ]]; then
    echo "[run-with-env] ERROR: no command supplied" >&2
    echo "Usage: bash scripts/run-with-env.sh <command> [args...]" >&2
    exit 2
fi

# Load non-secret config from .env.shared. allexport makes every KEY=VAL
# line export into the environment without needing an `export` prefix.
set -a
# shellcheck source=/dev/null
source "${SHARED_FILE}"
set +a

# Decrypt secrets to a tmp file (mode 600), source it, delete on exit.
# Tmp file rather than process substitution: sourcing from <(...) with
# `set -u` can race on file closure and miss lines, leading to silently
# unset secrets. The tmp-file pattern is deterministic.
TMP_SECRETS="$(mktemp)"
chmod 600 "${TMP_SECRETS}"
trap 'rm -f "${TMP_SECRETS}"' EXIT
sops --decrypt --output-type dotenv "${SECRETS_FILE}" > "${TMP_SECRETS}"
set -a
# shellcheck source=/dev/null
source "${TMP_SECRETS}"
set +a

# AWS_* aliases for boto3 (DigitalOcean Spaces is S3-compatible; MLflow
# and DVC both rely on the standard AWS env vars rather than the
# semantic DO_SPACES_* names).
export AWS_ACCESS_KEY_ID="${DO_SPACES_KEY}"
export AWS_SECRET_ACCESS_KEY="${DO_SPACES_SECRET}"

# Exec the provided command, replacing this shell — signals (Ctrl-C,
# SIGTERM) flow directly to the child without an intermediate bash.
exec "$@"
