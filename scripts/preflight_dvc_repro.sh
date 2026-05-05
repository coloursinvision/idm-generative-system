#!/usr/bin/env bash
#
# preflight_dvc_repro.sh — pre-flight checks for RUNBOOK_DVC_REPRO_BASELINE.md
#
# Verifies nine pre-conditions required before running `dvc repro` on the
# IDM Generative System V2 ML pipeline (Layer 6). Designed to be invoked
# from the repository root on a Tailscale-connected workstation host
# (Linux: /home/tomboro/Dropbox/IDM_Generative_System/IDM_Generative_System_app
#  macOS: ~/Dropbox/IDM_Generative_System/IDM_Generative_System_app).
#
# Per DECISIONS D-S8-01: training execution host is the workstation
# (preferred — has GPU) or MacBook (acceptable — CPU-only, longer wall time).
# The droplet hosts the MLflow tracking server only and is reached via
# the Tailscale-restricted vhost https://mlflow.idm.coloursinvision.ai.
#
# Each check prints exactly one outcome line:
#   [PASS]  <check>     condition satisfied
#   [WARN]  <check>     informational; does not block
#   [FAIL]  <check>     condition unsatisfied; runbook must not proceed
#
# Exit code:
#   0  — all checks PASS (WARN allowed)
#   1  — one or more FAIL
#   2  — invalid invocation or environment (missing deps, wrong cwd)
#
# Usage:
#   bash scripts/preflight_dvc_repro.sh
#   bash scripts/preflight_dvc_repro.sh --help
#
# Requires: bash 4+, git, python3, curl, dvc, df, awk

set -uo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

readonly SCRIPT_NAME="preflight_dvc_repro.sh"
readonly EXPECTED_BRANCH="develop"
readonly MIN_FREE_GB=10
readonly DEFAULT_MLFLOW_URI="https://mlflow.idm.coloursinvision.ai"
readonly REPO_ROOT_MARKER="dvc.yaml"

# Color output (suppressed if NO_COLOR is set or stdout is not a tty)
if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
    readonly COL_GREEN=$'\033[0;32m'
    readonly COL_YELLOW=$'\033[0;33m'
    readonly COL_RED=$'\033[0;31m'
    readonly COL_BOLD=$'\033[1m'
    readonly COL_RESET=$'\033[0m'
else
    readonly COL_GREEN=""
    readonly COL_YELLOW=""
    readonly COL_RED=""
    readonly COL_BOLD=""
    readonly COL_RESET=""
fi

# ---------------------------------------------------------------------------
# Outcome counters and reporting
# ---------------------------------------------------------------------------

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() {
    printf "%s[PASS]%s  %-32s %s\n" "${COL_GREEN}" "${COL_RESET}" "$1" "${2:-}"
    PASS_COUNT=$((PASS_COUNT + 1))
}

warn() {
    printf "%s[WARN]%s  %-32s %s\n" "${COL_YELLOW}" "${COL_RESET}" "$1" "${2:-}"
    WARN_COUNT=$((WARN_COUNT + 1))
}

fail() {
    printf "%s[FAIL]%s  %-32s %s\n" "${COL_RED}" "${COL_RESET}" "$1" "${2:-}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
${SCRIPT_NAME} — pre-flight checks for DVC repro baseline (Layer 6)

Usage:
  bash scripts/${SCRIPT_NAME}            run all nine checks
  bash scripts/${SCRIPT_NAME} --help     show this message

Checks:
  1. on branch '${EXPECTED_BRANCH}' and working tree clean
  2. local '${EXPECTED_BRANCH}' not behind origin/${EXPECTED_BRANCH}
  3. [ml] extras importable (pandera, xgboost, mlflow, optuna)
  4. DVC remote configured
  5. MLflow tracking server healthy at \$MLFLOW_TRACKING_URI
  6. >= ${MIN_FREE_GB} GB free on filesystem holding repo root
  7. dvc.yaml is parseable and 'dvc status' returns without error
  8. MLFLOW_TRACKING_URI environment variable is set
  9. Tailscale daemon active (workstation/macOS path to droplet vhost)

Exit codes:
  0  all PASS (WARN allowed)
  1  one or more FAIL
  2  invalid invocation or missing dependencies
EOF
}

# ---------------------------------------------------------------------------
# Environment validation (exits with 2 on failure)
# ---------------------------------------------------------------------------

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "%s[ABORT]%s missing required command: %s\n" \
            "${COL_RED}" "${COL_RESET}" "$1" >&2
        exit 2
    fi
}

ensure_repo_root() {
    if [[ ! -f "${REPO_ROOT_MARKER}" ]]; then
        printf "%s[ABORT]%s expected to run from repository root containing %s\n" \
            "${COL_RED}" "${COL_RESET}" "${REPO_ROOT_MARKER}" >&2
        printf "        current directory: %s\n" "$(pwd)" >&2
        exit 2
    fi
}

# ---------------------------------------------------------------------------
# Individual checks (each is independent and non-fatal)
# ---------------------------------------------------------------------------

check_01_branch_and_clean() {
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "<detached>")
    if [[ "${branch}" != "${EXPECTED_BRANCH}" ]]; then
        fail "01-branch-clean" "on '${branch}', expected '${EXPECTED_BRANCH}'"
        return
    fi

    local dirty
    dirty=$(git status --porcelain)
    if [[ -n "${dirty}" ]]; then
        fail "01-branch-clean" "working tree dirty (${dirty##*$'\n'} ...)"
        return
    fi

    pass "01-branch-clean" "on '${branch}', tree clean"
}

check_02_not_behind_origin() {
    if ! git fetch -q origin "${EXPECTED_BRANCH}" 2>/dev/null; then
        warn "02-sync-origin" "git fetch failed; cannot compare to origin"
        return
    fi

    local behind ahead
    behind=$(git rev-list --count "HEAD..origin/${EXPECTED_BRANCH}" 2>/dev/null || echo "?")
    ahead=$(git rev-list --count "origin/${EXPECTED_BRANCH}..HEAD" 2>/dev/null || echo "?")

    if [[ "${behind}" == "?" || "${ahead}" == "?" ]]; then
        warn "02-sync-origin" "rev-list failed; ref state indeterminate"
        return
    fi

    if (( behind > 0 )); then
        fail "02-sync-origin" "local is ${behind} behind origin/${EXPECTED_BRANCH}"
        return
    fi

    if (( ahead > 0 )); then
        warn "02-sync-origin" "local is ${ahead} ahead of origin (unpushed work)"
        return
    fi

    pass "02-sync-origin" "in sync with origin/${EXPECTED_BRANCH}"
}

check_03_ml_extras() {
    local err
    if err=$(python3 -c "import pandera, xgboost, mlflow, optuna" 2>&1); then
        local versions
        versions=$(python3 -c "
import pandera, xgboost, mlflow, optuna
print(f'pandera={pandera.__version__} xgboost={xgboost.__version__} mlflow={mlflow.__version__} optuna={optuna.__version__}')
" 2>/dev/null || echo "")
        pass "03-ml-extras" "${versions}"
    else
        fail "03-ml-extras" "import failed: ${err##*$'\n'}"
    fi
}

check_04_dvc_remote() {
    local remotes
    remotes=$(dvc remote list 2>/dev/null || true)
    if [[ -z "${remotes}" ]]; then
        fail "04-dvc-remote" "no DVC remote configured (dvc remote list empty)"
        return
    fi
    local first_remote
    first_remote=$(printf "%s" "${remotes}" | head -n1 | awk '{print $1}')
    pass "04-dvc-remote" "${first_remote} (and possibly more)"
}

check_05_mlflow_health() {
    local uri="${MLFLOW_TRACKING_URI:-${DEFAULT_MLFLOW_URI}}"
    local code
    code=$(curl -fsS -o /dev/null -w "%{http_code}" --max-time 5 "${uri}/health" 2>/dev/null || echo "000")
    if [[ "${code}" == "200" ]]; then
        pass "05-mlflow-health" "${uri}/health -> 200"
    else
        fail "05-mlflow-health" "${uri}/health -> ${code} (Tailscale up? vhost reachable?)"
    fi
}

check_06_disk_space() {
    # macOS df does not support -BG; use POSIX df -k and convert.
    local free_kb free_gb
    free_kb=$(df -k . 2>/dev/null | awk 'NR==2 {print $4}')
    if [[ -z "${free_kb}" || ! "${free_kb}" =~ ^[0-9]+$ ]]; then
        warn "06-disk-space" "could not parse df output"
        return
    fi
    free_gb=$(( free_kb / 1024 / 1024 ))
    if (( free_gb < MIN_FREE_GB )); then
        fail "06-disk-space" "only ${free_gb}G free, need >= ${MIN_FREE_GB}G"
        return
    fi
    pass "06-disk-space" "${free_gb}G free (threshold ${MIN_FREE_GB}G)"
}

check_07_dvc_status() {
    if ! dvc status >/dev/null 2>&1; then
        local err
        err=$(dvc status 2>&1 || true)
        fail "07-dvc-status" "dvc status errored: ${err##*$'\n'}"
        return
    fi

    # Capture the human-readable output for the operator to scan; this check
    # itself does NOT fail on stage drift (drift is expected before first run).
    local pipeline_status
    pipeline_status=$(dvc status 2>&1 || true)
    if grep -qiE "up to date" <<<"${pipeline_status}"; then
        pass "07-dvc-status" "pipeline up to date (no stages need re-run)"
    else
        warn "07-dvc-status" "stages need re-run — expected on first run; review output below"
        printf "        %s\n" "${pipeline_status//$'\n'/$'\n        '}"
    fi
}

check_08_mlflow_tracking_uri() {
    if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
        fail "08-tracking-uri" "MLFLOW_TRACKING_URI not exported (expected: ${DEFAULT_MLFLOW_URI})"
        return
    fi
    pass "08-tracking-uri" "${MLFLOW_TRACKING_URI}"
}

check_09_tailscale_active() {
    # Tailscale presence is workstation/macOS-specific. The droplet itself
    # also runs tailscaled but does not need this check (loopback MLflow
    # access works without Tailscale on the droplet). On a non-Tailscale
    # node, the MLflow vhost is unreachable by IP allowlist policy
    # (DECISIONS 2026-04-10).
    if ! command -v tailscale >/dev/null 2>&1; then
        warn "09-tailscale" "tailscale CLI not installed; check 05 covers reachability"
        return
    fi

    local status
    status=$(tailscale status --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('BackendState', 'Unknown'))
except Exception:
    print('Unparseable')
" 2>/dev/null || echo "Error")

    case "${status}" in
        Running)
            pass "09-tailscale" "BackendState=Running"
            ;;
        Stopped|NeedsLogin|NoState)
            fail "09-tailscale" "BackendState=${status} (run 'tailscale up')"
            ;;
        *)
            warn "09-tailscale" "BackendState=${status}"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    case "${1:-}" in
        -h|--help)
            usage
            exit 0
            ;;
        "")
            ;;
        *)
            printf "unknown argument: %s\n" "$1" >&2
            usage >&2
            exit 2
            ;;
    esac

    require_command git
    require_command python3
    require_command curl
    require_command dvc
    require_command df
    require_command awk
    ensure_repo_root

    printf "%spreflight: DVC repro baseline (Layer 6)%s\n" "${COL_BOLD}" "${COL_RESET}"
    printf "  cwd:    %s\n" "$(pwd)"
    printf "  user:   %s@%s\n" "$(whoami)" "$(hostname -s)"
    printf "  date:   %s\n" "$(date +%Y-%m-%dT%H:%M:%S%z)"
    printf "\n"

    check_01_branch_and_clean
    check_02_not_behind_origin
    check_03_ml_extras
    check_04_dvc_remote
    check_05_mlflow_health
    check_06_disk_space
    check_07_dvc_status
    check_08_mlflow_tracking_uri
    check_09_tailscale_active

    printf "\n"
    printf "%ssummary:%s pass=%d  warn=%d  fail=%d\n" \
        "${COL_BOLD}" "${COL_RESET}" "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

    if (( FAIL_COUNT > 0 )); then
        printf "%sresult: FAIL — do not proceed with dvc repro%s\n" \
            "${COL_RED}" "${COL_RESET}"
        exit 1
    fi

    printf "%sresult: OK — proceed to runbook Step 1%s\n" \
        "${COL_GREEN}" "${COL_RESET}"
    exit 0
}

main "$@"
