"""Contract tests for scripts/deploy_api.sh, the deploy script on the droplet.

The deploy key may run this script and nothing else: its forced command hands the
client's command, through sudo, to the script as its only argument. The script
must therefore refuse anything but one lowercase 40-character commit SHA before it
runs a single command, and then deploy as the Deploy workflow did: pull the image
tagged with that commit, bring up the API service and wait for it, check health
and the running revision, and only then prune.

Refusals come first. Every run puts stand-ins for docker, curl and id first on the
PATH, and each stand-in logs its calls, so a refusal must leave the log empty. The
positive cases prove the stand-ins are reached and record what they receive: the
arguments, the IDM_API_TAG they see and their working directory. The script is
executed directly, as sudo executes it, so its shebang and executable bit are part
of the contract.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy_api.sh"

SHA = "123b854767095ba9a7cfdccb4a8cb3a78a171c55"
OTHER_SHA = "9dcb152074be8e4ce43dee28903125853b77a744"
CONTAINER = "c0ffee"
REVISION_FORMAT = '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
SOURCE_FILTER = (
    "label=org.opencontainers.image.source=https://github.com/coloursinvision/idm-generative-system"
)

Result = subprocess.CompletedProcess[str]

LOG_CALL = r"""#!/bin/bash
printf '%s | IDM_API_TAG=%s | PWD=%s\n' "${0##*/} $*" "${IDM_API_TAG-unset}" "$PWD" >> "$STUB_LOG"
"""

STAND_INS = {
    "docker": r"""case "$*" in
  "compose pull idm-api") exit "${STUB_PULL_EXIT:-0}" ;;
  "compose ps -q idm-api") echo c0ffee ;;
  "inspect --format "*) echo "$STUB_REVISION" ;;
esac
""",
    "curl": r"""[ "${STUB_HEALTH_EXIT:-0}" -eq 0 ] || exit "$STUB_HEALTH_EXIT"
echo '{"status":"ok"}'
""",
    "id": "",
}

REFUSED = {
    "no argument": [],
    "empty": [""],
    "39 characters": [SHA[:39]],
    "41 characters": [SHA + "0"],
    "upper case": [SHA.upper()],
    "not hexadecimal": [SHA[:39] + "g"],
    "trailing newline": [SHA + "\n"],
    "leading space": [" " + SHA],
    "trailing space": [SHA + " "],
    "semicolon": [SHA[:39] + ";"],
    "command substitution": ["$(id)"],
    "option": ["--help"],
    "two arguments": [SHA, "id"],
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A scratch tree: the stand-ins in bin/ and an empty compose directory."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STAND_INS.items():
        stand_in = bin_dir / name
        stand_in.write_text(LOG_CALL + body, encoding="utf-8")
        stand_in.chmod(0o755)
    (tmp_path / "compose").mkdir()
    return tmp_path


def run_deploy(*args: str, root: Path, **stub: str) -> Result:
    """Run the script directly, as sudo does: a fixed environment, the stand-ins first."""
    env = {
        "PATH": os.pathsep.join([str(root / "bin"), "/usr/bin", "/bin"]),
        "HOME": str(root),
        "LC_ALL": "C.UTF-8",
        "IDM_COMPOSE_DIR": str(root / "compose"),
        "STUB_LOG": str(root / "calls.log"),
        "STUB_REVISION": SHA,
        **stub,
    }
    return subprocess.run(  # noqa: S603
        [str(SCRIPT), *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def calls(root: Path) -> list[str]:
    """Every stand-in call, in order."""
    log = root / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def call(command: str, root: Path) -> str:
    """A logged call made from the compose directory with the commit exported as the tag."""
    return f"{command} | IDM_API_TAG={SHA} | PWD={root / 'compose'}"


@pytest.mark.parametrize("args", list(REFUSED.values()), ids=list(REFUSED))
def test_refuses_anything_but_one_commit_sha(root: Path, args: list[str]) -> None:
    result = run_deploy(*args, root=root)
    assert result.returncode == 2
    assert "refused" in result.stderr
    assert result.stdout == ""
    assert calls(root) == []


def test_deploys_the_commit_in_order(root: Path) -> None:
    result = run_deploy(SHA, root=root)
    assert result.returncode == 0, result.stderr
    assert calls(root) == [
        call("docker compose pull idm-api", root),
        call("docker compose up -d --wait --wait-timeout 180 idm-api", root),
        call("curl -sf http://localhost:8000/health", root),
        call("docker compose ps -q idm-api", root),
        call(f"docker inspect --format {REVISION_FORMAT} {CONTAINER}", root),
        call(f"docker image prune -af --filter {SOURCE_FILTER}", root),
    ]


def test_reports_the_expected_and_running_revision(root: Path) -> None:
    result = run_deploy(SHA, root=root)
    lines = result.stdout.splitlines()
    assert f"expected {SHA}, running {SHA}" in lines
    assert "=== Deploy complete ===" in lines


def test_failed_pull_stops_the_deploy(root: Path) -> None:
    result = run_deploy(SHA, root=root, STUB_PULL_EXIT="1")
    assert result.returncode != 0
    assert calls(root) == [call("docker compose pull idm-api", root)]


def test_failed_health_check_stops_before_pruning(root: Path) -> None:
    result = run_deploy(SHA, root=root, STUB_HEALTH_EXIT="22")
    assert result.returncode != 0
    assert not any("image prune" in line for line in calls(root))
    assert "=== Deploy complete ===" not in result.stdout


def test_revision_mismatch_stops_before_pruning(root: Path) -> None:
    result = run_deploy(SHA, root=root, STUB_REVISION=OTHER_SHA)
    assert result.returncode != 0
    assert f"expected {SHA}, running {OTHER_SHA}" in result.stdout.splitlines()
    assert not any("image prune" in line for line in calls(root))
