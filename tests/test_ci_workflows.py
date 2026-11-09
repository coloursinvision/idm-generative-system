"""Contract tests for the conditions in the CI and Deploy workflows.

A manual start of CI exists for a push to main that GitHub left unprocessed, when no run
exists to re-run. On main it must build, push and deploy like a push. Anywhere else it must
not publish, and nothing a pull request or a fork starts may reach the registry or the
droplet.

The test job runs the suite with the development extra and again with the ML extra as well,
which the ML test modules need. Its two sets, their conditions and the step that fails on an
MLflow store left in the checkout are pinned here too.

The conditions are read from the workflow files and evaluated over truth tables, so the
tests judge what GitHub would decide rather than how a condition is spelled. The evaluator
covers the part of the expression syntax these conditions use: contexts, string literals,
==, &&, || and parentheses. Anything else raises, so a new construct fails loudly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "bash"

MAIN = "refs/heads/main"
DEVELOP = "refs/heads/develop"
HOTFIX = "refs/heads/hotfix/urgent"
TAG_MAIN = "refs/tags/main"
MERGE_REF = "refs/pull/1/merge"
OWN = "coloursinvision/idm-generative-system"
FORK = "someone/idm-generative-system"
SAVE_CACHE = "type=gha,mode=max,ignore-error=true"

TOKEN = re.compile(r"\s*('[^']*'|&&|\|\||==|\(|\)|[A-Za-z_][A-Za-z0-9_.]*)")
OPERATORS = {"&&": "and", "||": "or", "==": "==", "(": "(", ")": ")"}

Context = dict[str, Any]


def evaluate(expression: str, github: Context, matrix: Context | None = None) -> Any:
    """The value GitHub would give a condition, with its short-circuit semantics."""
    text = expression.strip().removeprefix("${{").removesuffix("}}").strip()
    contexts = {"github": github, "matrix": matrix}

    def context(path: str) -> Any:
        head, *rest = path.split(".")
        value: Any = contexts.get(head)
        if value is None:
            raise KeyError(path)
        for key in rest:
            value = value[key]
        return value

    parts: list[str] = []
    position = 0
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"unsupported expression: {text[position:]}")
        token = match.group(1)
        position = match.end()
        if token in OPERATORS:
            parts.append(OPERATORS[token])
        elif token.startswith("'"):
            parts.append(token)
        else:
            parts.append(f"context({token!r})")
    return eval(" ".join(parts), {"__builtins__": {}, "context": context})  # noqa: S307


def load(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """The on: section; PyYAML reads the key on as the boolean true."""
    return workflow[True]


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in job["steps"] if item.get("name") == name)


def ci(event: str, ref: str) -> Context:
    return {"event_name": event, "ref": ref}


def deploy(conclusion: str, event: str, head_repository: str) -> Context:
    run = {
        "conclusion": conclusion,
        "event": event,
        "head_repository": {"full_name": head_repository},
    }
    return {"repository": OWN, "event": {"workflow_run": run}}


CI = load("ci.yml")
DEPLOY = load("deploy.yml")
DOCKER = CI["jobs"]["docker"]
BUILD = step(DOCKER, "Build (and push on main)")
DEPLOY_JOB = DEPLOY["jobs"]["deploy"]

LOGIN = step(DOCKER, "Log in to GHCR")["if"]
PUSH = BUILD["with"]["push"]

TEST_JOB = CI["jobs"]["test"]
DEV_SET = {"name": "Test Suite", "extras": "dev", "cache": "pip-test"}
ML_SET = {"name": "ML Test Suite", "extras": "dev,ml", "cache": "pip-ml"}

PUBLISHING = [
    ("push", DEVELOP, False),
    ("pull_request", MERGE_REF, False),
    ("workflow_dispatch", DEVELOP, False),
    ("workflow_dispatch", TAG_MAIN, False),
    ("push", MAIN, True),
    ("workflow_dispatch", MAIN, True),
]


class TestTriggers:
    """Who can start a run, and what the deploy follows."""

    def test_manual_start_takes_no_inputs(self) -> None:
        """No input can reach a condition or a shell; the run builds the tip of its ref."""
        on = triggers(CI)
        assert "workflow_dispatch" in on, on
        assert not (on["workflow_dispatch"] or {}).get("inputs"), on["workflow_dispatch"]

    def test_automatic_triggers_stay(self) -> None:
        on = triggers(CI)
        assert on["push"] == {"branches": ["develop", "main", "hotfix/**"]}
        assert on["pull_request"] == {"branches": ["develop", "main"]}

    def test_deploy_follows_ci_on_main(self) -> None:
        assert triggers(DEPLOY) == {
            "workflow_run": {
                "workflows": ["CI"],
                "types": ["completed"],
                "branches": ["main"],
            }
        }

    def test_deploy_runs_the_commit_ci_built(self) -> None:
        env = step(DEPLOY_JOB, "Deploy via SSH")["env"]
        assert env["COMMIT"] == "${{ github.event.workflow_run.head_sha }}"


class TestDockerJob:
    """The image is built for pushes to the two long-lived branches, pull requests and main."""

    @pytest.mark.parametrize(
        ("event", "ref", "expected"),
        [
            ("push", HOTFIX, False),
            ("workflow_dispatch", DEVELOP, False),
            ("workflow_dispatch", HOTFIX, False),
            ("workflow_dispatch", TAG_MAIN, False),
            ("push", DEVELOP, True),
            ("push", MAIN, True),
            ("pull_request", MERGE_REF, True),
            ("workflow_dispatch", MAIN, True),
        ],
    )
    def test_runs_for(self, event: str, ref: str, expected: bool) -> None:
        assert bool(evaluate(DOCKER["if"], ci(event, ref))) is expected

    @pytest.mark.parametrize(("event", "ref", "expected"), PUBLISHING)
    def test_logs_in_to_the_registry_for(self, event: str, ref: str, expected: bool) -> None:
        assert bool(evaluate(LOGIN, ci(event, ref))) is expected

    @pytest.mark.parametrize(("event", "ref", "expected"), PUBLISHING)
    def test_pushes_the_image_for(self, event: str, ref: str, expected: bool) -> None:
        assert bool(evaluate(PUSH, ci(event, ref))) is expected

    @pytest.mark.parametrize(
        ("event", "ref", "expected"),
        [
            ("pull_request", MERGE_REF, ""),
            ("workflow_dispatch", MAIN, ""),
            ("push", DEVELOP, SAVE_CACHE),
            ("push", MAIN, SAVE_CACHE),
        ],
    )
    def test_saves_the_cache_for(self, event: str, ref: str, expected: str) -> None:
        assert evaluate(BUILD["with"]["cache-to"], ci(event, ref)) == expected

    def test_every_run_reads_the_cache(self) -> None:
        assert BUILD["with"]["cache-from"] == "type=gha"


class TestDeployJob:
    """Only a successful push or manual start in this repository reaches the droplet."""

    @pytest.mark.parametrize(
        ("conclusion", "event", "head_repository", "expected"),
        [
            ("failure", "push", OWN, False),
            ("failure", "workflow_dispatch", OWN, False),
            ("cancelled", "workflow_dispatch", OWN, False),
            ("success", "pull_request", OWN, False),
            ("success", "pull_request", FORK, False),
            ("success", "push", FORK, False),
            ("success", "workflow_dispatch", FORK, False),
            ("success", "schedule", OWN, False),
            ("success", "push", OWN, True),
            ("success", "workflow_dispatch", OWN, True),
        ],
    )
    def test_runs_for(
        self, conclusion: str, event: str, head_repository: str, expected: bool
    ) -> None:
        context = deploy(conclusion, event, head_repository)
        assert bool(evaluate(DEPLOY_JOB["if"], context)) is expected


class TestDependencySets:
    """The suite runs with the development extra, then again with the ML extra as well."""

    def test_runs_two_dependency_sets(self) -> None:
        """Test Suite keeps its name as a required context, and ML Test Suite joins it."""
        assert TEST_JOB["name"] == "${{ matrix.name }}"
        assert TEST_JOB["strategy"]["matrix"] == {"include": [DEV_SET, ML_SET]}

    def test_one_set_failing_does_not_cancel_the_other(self) -> None:
        """GitHub cancels the rest of a matrix on a failure unless fail-fast is off."""
        assert TEST_JOB["strategy"]["fail-fast"] is False

    def test_installs_the_extras_of_its_set(self) -> None:
        install = step(TEST_JOB, "Install dependencies")
        assert install["env"] == {"EXTRAS": "${{ matrix.extras }}"}
        assert 'pip install ".[${EXTRAS}]"' in install["run"]

    def test_each_set_keeps_its_own_pip_cache(self) -> None:
        """A shared key would restore the development wheels and never save the ML ones."""
        cache = step(TEST_JOB, "Cache pip")["with"]
        assert cache["key"] == "${{ matrix.cache }}-${{ hashFiles('pyproject.toml') }}"
        assert cache["restore-keys"] == "${{ matrix.cache }}-"

    def test_checks_the_ml_extra_before_the_tests(self) -> None:
        """Without the extra the four ML modules skip, and the set would pass having run none."""
        names = [item.get("name") for item in TEST_JOB["steps"]]
        assert names.index("Check the ML extra") < names.index("Run tests")
        check = step(TEST_JOB, "Check the ML extra")
        assert "import mlflow, optuna, pandas, pandera, sklearn, xgboost" in check["run"]
        assert evaluate(check["if"], {}, ML_SET) is True
        assert evaluate(check["if"], {}, DEV_SET) is False

    def test_runs_the_tests_as_before(self) -> None:
        """Both sets run the command and the stub keys the job had before the matrix."""
        tests = step(TEST_JOB, "Run tests")
        assert tests["env"] == {
            "OPENAI_API_KEY": "sk-test-000000000000000000000000000000000000000000000000",
            "QDRANT_URL": "http://localhost:6333",
            "QDRANT_API_KEY": "test-key",
        }
        command = (
            "pytest --tb=short --strict-markers -q --cov=engine --cov=api --cov=knowledge"
            " --cov-report=term-missing --cov-report=xml:coverage.xml"
        )
        assert tests["run"].replace("\\", " ").split() == command.split()

    @pytest.mark.parametrize(
        ("ref", "test_set", "expected"),
        [
            (DEVELOP, DEV_SET, True),
            (DEVELOP, ML_SET, False),
            (MAIN, DEV_SET, False),
        ],
        ids=["develop-dev", "develop-ml", "main-dev"],
    )
    def test_uploads_coverage_from_one_set(
        self, ref: str, test_set: Context, expected: bool
    ) -> None:
        """Artifacts are immutable, so the two sets cannot both upload coverage-report."""
        upload = step(TEST_JOB, "Upload coverage")
        assert bool(evaluate(upload["if"], ci("push", ref), test_set)) is expected

    @pytest.mark.parametrize(
        ("left", "fails"),
        [(None, False), ("mlflow.db", True), ("mlruns", True)],
        ids=["clean", "database", "artifacts"],
    )
    def test_fails_when_an_mlflow_store_is_left(
        self, tmp_path: Path, left: str | None, fails: bool
    ) -> None:
        """Both are git-ignored, so only this step sees them; run as GitHub runs a step."""
        if left == "mlflow.db":
            (tmp_path / left).write_text("", encoding="utf-8")
        elif left == "mlruns":
            (tmp_path / left).mkdir()
        script = step(TEST_JOB, "Check that no MLflow store was left behind")["run"]
        result = subprocess.run(  # noqa: S603
            [BASH, "-e", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        assert (result.returncode != 0) is fails, result.stderr

    def test_docker_waits_for_both_sets(self) -> None:
        assert "test" in DOCKER["needs"]


def isolated_env(cwd: Path, **extra: str) -> dict[str, str]:
    """The caller's environment, scrubbed so git cannot reach a real repository."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CEILING_DIRECTORIES=str(cwd.parent),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
    )
    env.update(extra)
    return env


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [GIT, *args], cwd=repo, env=isolated_env(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text("Clean line.\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"chore: add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """A scratch repository whose main is also the remote-tracking main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "first.md")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def resolve_base(repo: Path, output: Path) -> dict[str, str]:
    """Run the step as a workflow does on a manual start: no pushed range, a bash -e shell."""
    script = step(CI["jobs"]["text-hygiene"], "Resolve the base commit")["run"]
    env = isolated_env(repo, EVENT="workflow_dispatch", BEFORE="", GITHUB_OUTPUT=str(output))
    result = subprocess.run(  # noqa: S603
        [BASH, "-e", "-c", script], cwd=repo, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


class TestTextHygieneOnAManualStart:
    """A red Text Hygiene job would stop the deploy a manual start exists to run."""

    def test_main_judges_nothing_new(self, repository: Path, tmp_path: Path) -> None:
        head = git(repository, "rev-parse", "HEAD")
        resolved = resolve_base(repository, tmp_path / "output")
        assert resolved == {"sha": head, "range": f"{head}..HEAD"}

    def test_a_branch_ahead_of_main_is_judged_from_main(
        self, repository: Path, tmp_path: Path
    ) -> None:
        main = git(repository, "rev-parse", "HEAD")
        git(repository, "switch", "-q", "-c", "develop")
        commit(repository, "second.md")
        resolved = resolve_base(repository, tmp_path / "output")
        assert resolved == {"sha": main, "range": f"{main}..HEAD"}


class TestEvaluator:
    """The truth tables mean nothing if the evaluator guesses."""

    @pytest.mark.parametrize(
        "expression",
        ["!github.ref", "contains(github.ref, 'main')"],
        ids=["negation", "function"],
    )
    def test_refuses_what_it_does_not_cover(self, expression: str) -> None:
        with pytest.raises(ValueError, match="unsupported expression"):
            evaluate(expression, {"ref": MAIN})

    def test_refuses_an_unknown_context(self) -> None:
        with pytest.raises(KeyError):
            evaluate("github.actor == 'someone'", {"ref": MAIN})

    def test_refuses_the_matrix_context_without_a_matrix(self) -> None:
        with pytest.raises(KeyError):
            evaluate("matrix.extras == 'dev'", {"ref": MAIN})
