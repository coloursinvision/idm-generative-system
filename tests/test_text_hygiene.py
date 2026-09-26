"""Contract tests for scripts/check_text_hygiene.py.

The checker enforces two rule families on committed text: T1 typography from the
idm-text-hygiene skill, and the vault reference namespaces (D-*, INF-*, CR-*,
TODO-*) from idm-project-protocol. Both skills live outside this repository, so
these tests are what keep the checker and the policy in step.

Negative cases come first. A checker that flags a hardware name or a UI string
gets switched off, and then no positive case matters. Fixtures spell every
non-ASCII character as a %NAME% placeholder from GLYPHS, so this file stays
clean under the rules it specifies. Namespace IDs in fixtures are synthetic and
only copy the shapes used in the vault.

Output contract, as in scripts/preflight_dvc_repro.sh: one [PASS], [WARN] or
[FAIL] line per outcome, a summary line, and exit 0 (WARN allowed), 1 (any
FAIL) or 2 (invalid invocation or environment).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check_text_hygiene.py"
GIT = shutil.which("git") or "git"

Result = subprocess.CompletedProcess[str]

SUMMARY = re.compile(r"^summary: pass=(\d+)\s+warn=(\d+)\s+fail=(\d+)$", re.MULTILINE)
PLACEHOLDER = re.compile(r"%([A-Z]+)%")

GLYPHS = {
    "EMDASH": chr(0x2014),
    "ENDASH": chr(0x2013),
    "HBAR": chr(0x2015),
    "FIGDASH": chr(0x2012),
    "LSQUO": chr(0x2018),
    "RSQUO": chr(0x2019),
    "LDQUO": chr(0x201C),
    "RDQUO": chr(0x201D),
    "ELLIPSIS": chr(0x2026),
    "NBSP": chr(0x00A0),
    "NNBSP": chr(0x202F),
    "THINSP": chr(0x2009),
    "ZWSP": chr(0x200B),
    "ZWNJ": chr(0x200C),
    "ZWJ": chr(0x200D),
    "BOM": chr(0xFEFF),
    "RARR": chr(0x2192),
    "LARR": chr(0x2190),
    "RDARR": chr(0x21D2),
    "BULLET": chr(0x2022),
    "SQBULLET": chr(0x25AA),
    "MIDDOT": chr(0x00B7),
    "BOXFIRST": chr(0x2500),
    "BOXLAST": chr(0x257F),
    "TIMES": chr(0x00D7),
    "DEGREE": chr(0x00B0),
    "ROBOT": chr(0x1F916),
    "GREENDOT": chr(0x1F7E2),
    "YELLOWDOT": chr(0x1F7E1),
    "REDDOT": chr(0x1F534),
    "CHECKMARK": chr(0x2705),
    "SHARP": chr(0x266F),
    "FLAT": chr(0x266D),
    "SECTION": chr(0x00A7),
}

# T1 rows that block a commit. The en dash is conditional and tested on its own.
FAIL_CLASSES = [
    "EMDASH",
    "HBAR",
    "FIGDASH",
    "LSQUO",
    "RSQUO",
    "LDQUO",
    "RDQUO",
    "ELLIPSIS",
    "NBSP",
    "NNBSP",
    "THINSP",
    "ZWSP",
    "ZWNJ",
    "ZWJ",
    "BOM",
    "RARR",
    "LARR",
    "RDARR",
    "BULLET",
    "SQBULLET",
    "ROBOT",
    "GREENDOT",
    "YELLOWDOT",
    "REDDOT",
    "CHECKMARK",
]

# Surfaced without blocking. The middle dot and box drawing wait on operator
# decisions; the skill asks for judgement on the multiplication and degree signs.
WARN_CLASSES = ["MIDDOT", "BOXFIRST", "BOXLAST", "TIMES", "DEGREE"]

# The only rewrites --fix may make, each with exactly one replacement. They
# touch prose only: Markdown outside fenced blocks, comments and docstrings in
# .py, and whole comment lines elsewhere. Code, data values and box-drawing
# diagram lines are reported but never rewritten: an arrow is a redirect in
# shell, and a wider glyph shifts a diagram.
SAFE_FIXES = {
    "ELLIPSIS": "...",
    "RARR": "->",
    "LARR": "<-",
    "RDARR": "=>",
    "HBAR": "-",
    "FIGDASH": "-",
    "NBSP": " ",
    "NNBSP": " ",
    "THINSP": " ",
    "ZWSP": "",
    "ZWNJ": "",
    "ZWJ": "",
    "BOM": "",
}


def expand(text: str) -> str:
    """Replace each %NAME% with its character; an unknown name raises KeyError."""
    return PLACEHOLDER.sub(lambda match: GLYPHS[match.group(1)], text)


def label(name: str) -> str:
    """How the checker names a character in its output, e.g. U+2014."""
    return f"U+{ord(GLYPHS[name]):04X}"


def write_raw(root: Path, relpath: str, data: bytes) -> None:
    """Create a fixture file from exact bytes."""
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write(root: Path, relpath: str, text: str) -> None:
    """Create a UTF-8 fixture file with placeholders expanded."""
    write_raw(root, relpath, expand(text).encode("utf-8"))


def read(root: Path, relpath: str) -> str:
    """Read a fixture back without newline translation."""
    return (root / relpath).read_bytes().decode("utf-8")


def isolated_env(cwd: Path) -> dict[str, str]:
    """The caller's environment, scrubbed so git cannot reach a real repository.

    Hooks export GIT_DIR and GIT_INDEX_FILE; a test run from a hook would
    otherwise stage into the enclosing repository. The ceiling stops git from
    climbing out of the scratch directory.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CEILING_DIRECTORIES=str(cwd.parent),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="Test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="Test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        NO_COLOR="1",
        PYTHONIOENCODING="utf-8",
    )
    return env


def run_checker(*args: str, cwd: Path) -> Result:
    """Invoke the checker the way pre-commit and CI do: its own process, exit code, stdout."""
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CHECKER), *args],
        cwd=cwd,
        env=isolated_env(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git(repo: Path, *args: str) -> None:
    """Run git in a scratch repository; a failure fails the test."""
    subprocess.run(  # noqa: S603
        [GIT, *args],
        cwd=repo,
        env=isolated_env(repo),
        capture_output=True,
        check=True,
    )


def lines_tagged(result: Result, tag: str) -> list[str]:
    """Stdout lines carrying one outcome tag: PASS, WARN or FAIL."""
    return [line for line in result.stdout.splitlines() if line.startswith(f"[{tag}]")]


def located(result: Result, tag: str, relpath: str, lineno: int) -> list[str]:
    """Outcome lines of one tag that point at relpath:lineno."""
    at = re.compile(rf"(^|\s){re.escape(relpath)}:{lineno}(:\d+)?:?(\s|$)")
    return [line for line in lines_tagged(result, tag) if at.search(line)]


def flagged(result: Result, relpath: str) -> list[str]:
    """WARN and FAIL lines that name relpath anywhere."""
    named = re.compile(rf"(^|\s){re.escape(relpath)}(:|\s|$)")
    outcomes = lines_tagged(result, "WARN") + lines_tagged(result, "FAIL")
    return [line for line in outcomes if named.search(line)]


def assert_clean(result: Result, relpath: str) -> None:
    """Exit 0, nothing flagged, and a PASS line proving the file was read at all."""
    report = result.stdout + result.stderr
    assert result.returncode == 0, report
    assert lines_tagged(result, "FAIL") == [], report
    assert lines_tagged(result, "WARN") == [], report
    assert any(relpath in line for line in lines_tagged(result, "PASS")), report


def assert_reported(result: Result, tag: str, relpath: str, lineno: int, marker: str) -> None:
    """Some line of the tag points at relpath:lineno and names the marker."""
    report = result.stdout + result.stderr
    hits = [line for line in located(result, tag, relpath, lineno) if marker in line]
    assert hits, f"no [{tag}] at {relpath}:{lineno} naming {marker}\n{report}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh repository on branch main."""
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


class TestNegativeHardwareNames:
    """Allowlist 4: TR-808 and CR-1604 are hardware, not ticket references."""

    @pytest.mark.parametrize(
        ("relpath", "text"),
        [
            ("docs/HARDWARE.md", "Kick from a TR-808, summed on a Mackie CR-1604.\n"),
            (
                "engine/effects/noise_floor.py",
                '"""Mackie CR-1604 (pre-VLZ) bus crosstalk under a TR-808 kick."""\n',
            ),
            (
                "engine/effects/__init__.py",
                "# Block 1 - Analogue noise floor (Mackie CR-1604), TR-808 reference\n",
            ),
            (
                "frontend/src/hooks/useSequencer.ts",
                "// TR-808 accent into the Mackie CR-1604 bus\nexport {};\n",
            ),
            (".github/workflows/ci.yml", "# Kit: TR-808 into a Mackie CR-1604\non: push\n"),
            ("scripts/render.sh", "#!/usr/bin/env bash\n# TR-808 into the Mackie CR-1604\n"),
            ("pyproject.toml", "[tool.idm]\n# Kit: TR-808 into a Mackie CR-1604\n"),
        ],
        ids=["md", "py-docstring", "py-comment", "ts-comment-line", "yml", "sh", "toml"],
    )
    def test_tr808_and_cr1604_pass_in_every_checked_region(
        self, tmp_path: Path, relpath: str, text: str
    ) -> None:
        write(tmp_path, relpath, text)
        assert_clean(run_checker("--files", relpath, cwd=tmp_path), relpath)

    def test_every_listed_hardware_name_passes(self, tmp_path: Path) -> None:
        """Every hardware name in the skill's list, and the Roland D-50 from the dataset spec."""
        names = [
            "Mackie CR-1604",
            "TB-303",
            "TR-808",
            "TR-909",
            "TR-808/909",
            "SP-1200",
            "S950",
            "SH-101",
            "DX100",
            "RE-201",
            "Quadraverb",
            "Alesis 3630",
            "Roland D-50",
        ]
        path = "docs/HARDWARE.md"
        write(tmp_path, path, "".join(f"- {name}\n" for name in names))
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestNegativeMusicalNotation:
    """Allowlist 3: sharp and flat signs are notation, not decoration."""

    @pytest.mark.parametrize(
        ("relpath", "text"),
        [
            ("engine/ml/resonance_rules.py", '"""60 Hz sits between A%SHARP%1 and B1."""\n'),
            ("engine/codegen/mappings.py", "# Key of C%SHARP% minor, enharmonic D%FLAT% minor\n"),
            ("tests/test_resonance_rules.py", '"""128 BPM at octave 64 is nearest C%SHARP%3."""\n'),
            ("docs/THEORY.md", "Detroit pads in F%SHARP% minor, Sheffield in E%FLAT% major.\n"),
        ],
        ids=["engine-ml", "engine-codegen", "tests", "docs"],
    )
    def test_sharp_and_flat_pass(self, tmp_path: Path, relpath: str, text: str) -> None:
        write(tmp_path, relpath, text)
        assert_clean(run_checker("--files", relpath, cwd=tmp_path), relpath)


class TestNegativeNumericRangeEnDash:
    """Allowlist 2: an en dash directly between two digits is a numeric range."""

    @pytest.mark.parametrize(
        ("relpath", "text"),
        [
            ("docs/TEMPO.md", "Tempos run 80%ENDASH%180 BPM; releases 1991%ENDASH%1995.\n"),
            ("engine/effects/filter.py", '"""Cutoff range 20%ENDASH%20000 Hz."""\n'),
            ("engine/effects/noise_floor.py", "# Mains hum at 50%ENDASH%60 Hz\n"),
            ("frontend/src/lib/tempo.ts", "// Clamp to 60%ENDASH%200 BPM\nexport {};\n"),
            (".github/workflows/ci.yml", "# Finishes in 3%ENDASH%5 minutes\non: push\n"),
        ],
        ids=["md", "py-docstring", "py-comment", "ts-comment-line", "yml"],
    )
    def test_digit_range_passes(self, tmp_path: Path, relpath: str, text: str) -> None:
        write(tmp_path, relpath, text)
        assert_clean(run_checker("--files", relpath, cwd=tmp_path), relpath)


class TestNegativeUserFacingTsx:
    """Allowlist 1: in .ts and .tsx only comment lines are checked."""

    def test_rendered_text_passes(self, tmp_path: Path) -> None:
        """JSX text, props and literals, plus lines a naive comment scan would misread."""
        path = "frontend/src/components/advisor/AdvisorPanel.tsx"
        write(
            tmp_path,
            path,
            dedent(
                """\
                const include = ["src/**/*.test.tsx"];

                export function Panel({ label, lineCount, loading, bpm, swing }: PanelProps) {
                  return (
                    <section title="Tempo %RARR% Swing">
                      <h2>{label} %EMDASH% {lineCount} LINES</h2>
                      <button>{loading ? "SEARCHING%ELLIPSIS%" : "ASK"}</button>
                      <p>{`${bpm} BPM %EMDASH% ${swing}%`}</p>
                      <a href="https://example.org">https://example.org %EMDASH% docs</a>
                      <p>
                        * Required %EMDASH% set a tempo first
                      </p>
                    </section>
                  );
                }
                """
            ),
        )
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestNegativePythonLiterals:
    """Allowlist 1: in .py only docstrings and comments are checked."""

    def test_non_docstring_literals_pass(self, tmp_path: Path) -> None:
        """API details, log lines, a code template, a hash in a string, a late bare string."""
        path = "api/profiles.py"
        write(
            tmp_path,
            path,
            dedent(
                '''\
                """Profile lookup endpoints."""

                import logging

                from fastapi import HTTPException

                logger = logging.getLogger(__name__)
                TRACK = "Track #1 %EMDASH% intro"
                HEADER = "%CHECKMARK% Presets loaded"
                SYNTHDEF = """
                // Block 1: Noise floor %EMDASH% Mackie CR-1604 bus emulation
                """


                def lookup(region: str) -> str:
                    """Return the profile name for a region."""
                    logger.warning("V2.3 /tuning disabled %EMDASH% mlflow not installed.")
                    if not region:
                        raise HTTPException(status_code=404, detail="Profile not found %EMDASH% check the region")
                    label = f"{region} %RARR% loading%ELLIPSIS%"
                    """A bare string after the first statement %EMDASH% not a docstring."""
                    return label
                '''
            ),
        )
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestNegativeOtherAllowedText:
    """Characters and markers the skills keep that a broader rule would catch."""

    def test_section_sign_passes(self, tmp_path: Path) -> None:
        """The project cites sections with U+00A7; the rule is not ASCII only."""
        path = "docs/RELEASE.md"
        write(tmp_path, path, "Commit format: CLAUDE.md %SECTION%4.4.\n")
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)

    def test_plain_todo_marker_passes(self, tmp_path: Path) -> None:
        """The namespace is TODO-<id> backlog items; a bare TODO marker is not one."""
        path = "engine/ml/mapper.py"
        write(tmp_path, path, "# TODO: handle the stereo case\nX = 1\n")
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestNegativeExemptFiles:
    """Allowlist 5 and 6, and file types outside the checker's scope."""

    @pytest.mark.parametrize(
        ("exempt", "twin"),
        [
            ("LICENCE.md", "docs/LICENCE_NOTES.md"),
            ("CLAUDE.md", "docs/CLAUDE_NOTES.md"),
            ("secrets/app.enc.yaml", "config/app.yaml"),
            ("frontend/node_modules/pkg/index.d.ts", "frontend/src/types/index.d.ts"),
            ("frontend/dist/NOTES.md", "frontend/NOTES.md"),
            (".sops.yaml", "config/sops_notes.yaml"),
            ("scripts/run-with-env.sh", "scripts/run_other.sh"),
        ],
        ids=["licence", "claude-md", "secrets", "node-modules", "dist", "sops", "run-with-env"],
    )
    def test_exempt_file_is_skipped_while_its_twin_fails(
        self, tmp_path: Path, exempt: str, twin: str
    ) -> None:
        """Same text at a checked path, so the pass cannot come from a dead rule."""
        text = "// Rationale %EMDASH% see D-CRF13-99\n"
        write(tmp_path, exempt, text)
        write(tmp_path, twin, text)
        result = run_checker("--files", exempt, twin, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert flagged(result, exempt) == [], result.stdout
        assert_reported(result, "FAIL", twin, 1, label("EMDASH"))
        assert_reported(result, "FAIL", twin, 1, "D-CRF13-99")

    def test_types_outside_scope_are_skipped(self, tmp_path: Path) -> None:
        """Lockfiles, notebooks, HTML, C++ and binaries, none of which may crash the run."""
        text = "Legacy %EMDASH% text\n"
        skipped = [
            "frontend/package-lock.json",
            "dvc.lock",
            ".env.shared",
            "frontend/index.html",
            "engine/AcidSynthEngine.cpp",
            "notebooks/explore.ipynb",
        ]
        binaries = ["samples/click.wav", "data/train.parquet"]
        for path in skipped:
            write(tmp_path, path, text)
        for path in binaries:
            write_raw(tmp_path, path, b"RIFF\x00\xff" + expand(text).encode() + b"\x80\x81")
        write(tmp_path, "docs/NOTES.md", text)
        result = run_checker("--files", *skipped, *binaries, "docs/NOTES.md", cwd=tmp_path)
        assert "Traceback" not in result.stderr, result.stderr
        assert result.returncode == 1, result.stdout
        for path in [*skipped, *binaries]:
            assert flagged(result, path) == [], path
        assert_reported(result, "FAIL", "docs/NOTES.md", 1, label("EMDASH"))


class TestNegativeCommitMessages:
    """--commit-msg: vault IDs in Refs trailers and git's own comment lines pass."""

    def test_refs_trailers_pass(self, tmp_path: Path) -> None:
        """Refs trailers must cite the vault; the namespace rule covers code and docs only."""
        msg = "COMMIT_EDITMSG"
        write(
            tmp_path,
            msg,
            dedent(
                """\
                fix(engine): clamp the resonance seed

                Keeps the seed inside the audible band.

                Refs: 00-Project/DECISIONS.md#D-PIPE-99
                Refs: 06-MLOps/INFRA_DEBT_REGISTRY.md#INF-ZZ
                Refs: CODE_REVIEW_2026-06-01.md %SECTION%CR-F99
                """
            ),
        )
        assert_clean(run_checker("--commit-msg", msg, cwd=tmp_path), msg)

    def test_git_comments_and_verbose_diff_pass(self, tmp_path: Path) -> None:
        """git commit -v gives the hook the comment block and, below the scissors, the diff."""
        msg = "COMMIT_EDITMSG"
        write(
            tmp_path,
            msg,
            dedent(
                """\
                docs(readme): replace arrows with ASCII

                # Please enter the commit message for your changes. Lines starting
                # with '#' will be ignored.
                # Note %EMDASH% a comment line with an %RARR% arrow
                # ------------------------ >8 ------------------------
                # Do not modify or remove the line above.
                # Everything below it will be ignored.
                diff --git a/README.md b/README.md
                -Pipeline %RARR% model %EMDASH% registry
                +Pipeline -> model - registry
                """
            ),
        )
        assert_clean(run_checker("--commit-msg", msg, cwd=tmp_path), msg)


class TestNegativeStaged:
    """--staged judges what the commit adds: staged content, added lines only."""

    def test_unstaged_changes_are_ignored(self, repo: Path) -> None:
        write(repo, "docs/GUIDE.md", "Clean text.\n")
        git(repo, "add", "docs/GUIDE.md")
        write(repo, "docs/GUIDE.md", "Clean text.\nUnstaged %EMDASH% edit.\n")
        assert_clean(run_checker("--staged", cwd=repo), "docs/GUIDE.md")

    def test_committed_lines_are_not_rechecked(self, repo: Path) -> None:
        """Existing files predate the policy, so only the lines a commit adds are judged."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        git(repo, "add", "docs/GUIDE.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\nNew clean line.\n")
        git(repo, "add", "docs/GUIDE.md")
        assert_clean(run_checker("--staged", cwd=repo), "docs/GUIDE.md")

    def test_renamed_file_is_not_rechecked(self, repo: Path) -> None:
        """git mv adds no lines, so moving a legacy file must not block the commit."""
        write(repo, "docs/OLD.md", "Legacy %EMDASH% text.\n")
        git(repo, "add", "docs/OLD.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        git(repo, "mv", "docs/OLD.md", "docs/NEW.md")
        result = run_checker("--staged", cwd=repo)
        assert result.returncode == 0, result.stdout
        assert flagged(result, "docs/NEW.md") == [], result.stdout

    def test_staged_deletion_passes(self, repo: Path) -> None:
        write(repo, "docs/OLD.md", "Legacy %EMDASH% text.\n")
        git(repo, "add", "docs/OLD.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        git(repo, "rm", "-q", "docs/OLD.md")
        result = run_checker("--staged", cwd=repo)
        assert "Traceback" not in result.stderr, result.stderr
        assert result.returncode == 0, result.stdout
        assert flagged(result, "docs/OLD.md") == [], result.stdout


class TestNegativeFix:
    """--fix rewrites only SAFE_FIXES, and only in prose."""

    def test_literals_and_jsx_stay_byte_identical(self, tmp_path: Path) -> None:
        py = "streamlit_app/labels.py"
        tsx = "frontend/src/components/Header.tsx"
        py_text = 'LABEL = "Tempo %RARR% Swing%ELLIPSIS%"  # tempo %RARR% swing\n'
        tsx_text = "// Panel %RARR% header\nexport const H = () => <h2>Tempo %RARR% Swing</h2>;\n"
        write(tmp_path, py, py_text)
        write(tmp_path, tsx, tsx_text)
        result = run_checker("--fix", "--files", py, tsx, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert read(tmp_path, py) == expand(py_text.replace("# tempo %RARR%", "# tempo ->"))
        assert read(tmp_path, tsx) == expand(tsx_text.replace("// Panel %RARR%", "// Panel ->"))

    def test_allowed_and_warn_classes_stay(self, tmp_path: Path) -> None:
        path = "docs/NOTES.md"
        kept = dedent(
            """\
            TR-808 into a Mackie CR-1604, 80%ENDASH%180 BPM, C%SHARP% minor, CLAUDE.md %SECTION%4.4.
            Glue %MIDDOT% knee %MIDDOT% target, 128 BPM %TIMES% 64, 90%DEGREE% phase.
            %BOXFIRST%%BOXFIRST% diagram %BOXLAST%
            """
        )
        write(tmp_path, path, kept + "Signal %RARR% bus\n")
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert read(tmp_path, path) == expand(kept + "Signal -> bus\n")

    def test_judgement_classes_are_reported_not_rewritten(self, tmp_path: Path) -> None:
        """Em dash, stray en dash, curly quotes, bullets and emoji have no single safe rewrite."""
        path = "docs/NOTES.md"
        text = (
            "A %EMDASH% B, Detroit%ENDASH%Berlin, %LDQUO%dub%RDQUO%, it%RSQUO%s, "
            "%BULLET% one, %CHECKMARK% done\n"
        )
        write(tmp_path, path, text)
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert read(tmp_path, path) == expand(text)

    def test_nothing_else_changes(self, tmp_path: Path) -> None:
        """CRLF line endings and a missing final newline survive byte for byte."""
        path = "docs/CRLF.md"
        write_raw(tmp_path, path, expand("One\r\nSignal %RARR% bus\r\nNo final newline").encode())
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert (tmp_path / path).read_bytes() == b"One\r\nSignal -> bus\r\nNo final newline"

    def test_exempt_and_frozen_files_are_never_edited(self, tmp_path: Path) -> None:
        paths = [
            ".sops.yaml",
            "secrets/app.enc.yaml",
            "scripts/run-with-env.sh",
            ".env.shared",
            "notebooks/archive/exploration.ipynb",
            "CLAUDE.md",
            "LICENCE.md",
        ]
        for path in paths:
            write(tmp_path, path, "# Signal %RARR% bus\n")
        result = run_checker("--fix", "--files", *paths, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        for path in paths:
            assert read(tmp_path, path) == expand("# Signal %RARR% bus\n"), path

    def test_code_and_data_are_reported_not_rewritten(self, tmp_path: Path) -> None:
        """An arrow in shell code becomes a redirect; YAML and TOML values are data."""
        cases = {
            "scripts/render.sh": (
                "# Render %RARR% mix\n",
                'echo a %RARR% b\necho "Track #1 %RARR% intro"\n',
            ),
            ".github/workflows/ci.yml": ("# Lint %RARR% test\n", "name: lint %RARR% test\n"),
            "pyproject.toml": ("# Build %RARR% wheel\n", 'description = "Engine %RARR% DSP"\n'),
        }
        for path, (comment, code) in cases.items():
            write(tmp_path, path, comment + code)
        result = run_checker("--fix", "--files", *cases, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        for path, (comment, code) in cases.items():
            assert read(tmp_path, path) == expand(comment.replace("%RARR%", "->") + code), path

    def test_markdown_code_blocks_are_not_rewritten(self, tmp_path: Path) -> None:
        """A fenced block holds code or a diagram; only the prose around it is rewritten."""
        path = "docs/GUIDE.md"
        block = "```bash\nmake train %RARR% model.pkl\n```\n"
        write(tmp_path, path, "Train %RARR% register.\n\n" + block)
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert read(tmp_path, path) == expand("Train -> register.\n\n" + block)

    def test_diagram_lines_keep_their_alignment(self, tmp_path: Path) -> None:
        """A wider replacement on a box-drawing line would shift the diagram's right edge."""
        path = "frontend/src/components/codegen/CodegenPanel.tsx"
        text = dedent(
            """\
            /**
             * %BOXFIRST%%BOXFIRST% CONFIG / STUDIO / %ELLIPSIS% %BOXFIRST%%BOXFIRST%  %LARR% drawer
             * Flow: SC %RARR% GENERATE %RARR% COPY
             */
            """
        )
        write(tmp_path, path, text)
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert read(tmp_path, path) == expand(text.replace("%RARR%", "->"))


class TestPositiveTypography:
    """T1: banned characters fail, the WARN classes warn without blocking."""

    @pytest.mark.parametrize("name", FAIL_CLASSES)
    def test_banned_character_fails(self, tmp_path: Path, name: str) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, f"Intro line.\nBefore%{name}%after\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, label(name))

    @pytest.mark.parametrize("name", WARN_CLASSES)
    def test_warn_class_is_surfaced_without_blocking(self, tmp_path: Path, name: str) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, f"Intro line.\nBefore%{name}%after\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert lines_tagged(result, "FAIL") == [], result.stdout
        assert_reported(result, "WARN", path, 2, label(name))

    @pytest.mark.parametrize(
        "text",
        [
            "Detroit%ENDASH%Berlin axis",
            "Kick %ENDASH% then snare",
            "Target DR8%ENDASH%DR10",
            "Gain %ENDASH%6 dB",
        ],
        ids=["between-letters", "spaced", "digit-then-letter", "leading-minus"],
    )
    def test_en_dash_outside_a_digit_range_fails(self, tmp_path: Path, text: str) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, f"Intro line.\n{text}\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, label("ENDASH"))


class TestPositiveNamespaces:
    """Vault IDs must not reach committed code or docs; shapes copied from the vault."""

    @pytest.mark.parametrize(
        "ref",
        [
            "D-PIPE-99",
            "D-CRF13-99",
            "D-S99-01",
            "D-SKILL-99",
            "INF-ZZ",
            "INF-Q",
            "CR-F99",
            "CR-99",
            "TODO-99",
            "TODO-S99",
        ],
    )
    def test_vault_reference_fails(self, tmp_path: Path, ref: str) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, f"Intro line.\nSee {ref} for the rationale.\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, ref)


class TestPositiveRegions:
    """Each file type is checked where its prose lives, at exact line numbers."""

    def test_python_docstrings_and_comments(self, tmp_path: Path) -> None:
        path = "engine/ml/mapper.py"
        write(
            tmp_path,
            path,
            dedent(
                '''\
                """Module summary %EMDASH% line one."""


                class Mapper:
                    """Class summary.

                    Reserved for TODO-99 once tuning lands.
                    """

                    def tune(self) -> float:
                        """Return A4 %RARR% 440 Hz."""
                        # TODO-99: inspect the profile for an alternative tuning
                        return 440.0  # concert pitch %EMDASH% ISO 16


                async def fetch() -> None:
                    """Fetch %ELLIPSIS% later."""
                '''
            ),
        )
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        expected = [
            (1, label("EMDASH")),
            (7, "TODO-99"),
            (11, label("RARR")),
            (12, "TODO-99"),
            (13, label("EMDASH")),
            (17, label("ELLIPSIS")),
        ]
        for lineno, marker in expected:
            assert_reported(result, "FAIL", path, lineno, marker)

    def test_typescript_comment_lines(self, tmp_path: Path) -> None:
        path = "frontend/src/components/codegen/CodegenPanel.tsx"
        write(
            tmp_path,
            path,
            dedent(
                """\
                /**
                 * 3-click live flow: SC|TIDAL %RARR% GENERATE %RARR% COPY
                 */
                // PascalCase %RARR% class/type name
                export const LABEL = "Tempo %RARR% Swing";
                   // indented comment %EMDASH% still a comment line
                /*
                  Block without stars %EMDASH% still a comment
                */
                // See CR-F99 for the lifecycle fix
                """
            ),
        )
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        expected = [
            (2, label("RARR")),
            (4, label("RARR")),
            (6, label("EMDASH")),
            (8, label("EMDASH")),
            (10, "CR-F99"),
        ]
        for lineno, marker in expected:
            assert_reported(result, "FAIL", path, lineno, marker)
        assert located(result, "FAIL", path, 5) == [], result.stdout

    @pytest.mark.parametrize(
        ("relpath", "text"),
        [
            ("docs/GUIDE.md", "Title\n\nPipeline %EMDASH% registry\n"),
            ("pyproject.toml", '[project]\nname = "x"\ndescription = "Engine %EMDASH% DSP"\n'),
            (".github/workflows/ci.yml", "name: ci\non: push\n# Lint %EMDASH% then test\n"),
            ("dvc.yaml", "stages:\n  train:\n    cmd: python train.py  # %EMDASH% model\n"),
            ("scripts/render.sh", '#!/usr/bin/env bash\nset -eu\necho "Render %EMDASH% done"\n'),
        ],
        ids=["md", "toml", "yml", "yaml", "sh"],
    )
    def test_whole_file_types(self, tmp_path: Path, relpath: str, text: str) -> None:
        """No UI strings live in these types, so every line is in scope."""
        write(tmp_path, relpath, text)
        result = run_checker("--files", relpath, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", relpath, 3, label("EMDASH"))

    def test_notebook_readme_is_checked(self, tmp_path: Path) -> None:
        """Only the notebooks are exempt; the README beside them is documentation."""
        path = "notebooks/README.md"
        write(tmp_path, path, "Notebooks\n\n%CHECKMARK% Baseline run\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 3, label("CHECKMARK"))


class TestPositiveCommitMessages:
    """--commit-msg applies T1 to the message git is about to record."""

    @pytest.mark.parametrize(
        ("message", "lineno", "name"),
        [
            ("docs(readme): clarify the pipeline %EMDASH% registry step\n", 1, "EMDASH"),
            (
                "feat(engine): add the vinyl block\n\nModels %LDQUO%surface noise%RDQUO%.\n",
                3,
                "LDQUO",
            ),
            ("chore: bump ruff\n\n%ROBOT% footer\n", 3, "ROBOT"),
        ],
        ids=["subject", "body", "footer"],
    )
    def test_typography_in_the_message_fails(
        self, tmp_path: Path, message: str, lineno: int, name: str
    ) -> None:
        msg = "COMMIT_EDITMSG"
        write(tmp_path, msg, message)
        result = run_checker("--commit-msg", msg, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", msg, lineno, label(name))


class TestPositiveStaged:
    """--staged fails on what the commit would record."""

    def test_violation_on_an_added_line_fails(self, repo: Path) -> None:
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        git(repo, "add", "docs/GUIDE.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\nNew %RARR% line.\n")
        git(repo, "add", "docs/GUIDE.md")
        result = run_checker("--staged", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/GUIDE.md", 2, label("RARR"))
        assert located(result, "FAIL", "docs/GUIDE.md", 1) == [], result.stdout

    def test_the_index_is_checked_not_the_worktree(self, repo: Path) -> None:
        write(repo, "docs/GUIDE.md", "Staged %EMDASH% text.\n")
        git(repo, "add", "docs/GUIDE.md")
        write(repo, "docs/GUIDE.md", "Staged - text.\n")
        result = run_checker("--staged", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/GUIDE.md", 1, label("EMDASH"))

    def test_added_line_in_a_renamed_file_fails(self, repo: Path) -> None:
        legacy = "Legacy %EMDASH% text.\nSecond legacy line.\nThird legacy line.\n"
        write(repo, "docs/OLD.md", legacy)
        git(repo, "add", "docs/OLD.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        git(repo, "mv", "docs/OLD.md", "docs/NEW.md")
        write(repo, "docs/NEW.md", legacy + "New %RARR% line.\n")
        git(repo, "add", "docs/NEW.md")
        result = run_checker("--staged", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/NEW.md", 4, label("RARR"))
        assert located(result, "FAIL", "docs/NEW.md", 1) == [], result.stdout


class TestPositiveAll:
    """--all audits whole tracked files and nothing else."""

    def test_tracked_files_only(self, repo: Path) -> None:
        write(repo, ".gitignore", "build/\n")
        write(repo, "docs/GUIDE.md", "Tracked %EMDASH% text.\n")
        write(repo, "LICENCE.md", "Exempt %EMDASH% text.\n")
        git(repo, "add", ".gitignore", "docs/GUIDE.md", "LICENCE.md")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        write(repo, "docs/DRAFT.md", "Untracked %EMDASH% text.\n")
        write(repo, "build/OUT.md", "Ignored %EMDASH% text.\n")
        result = run_checker("--all", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/GUIDE.md", 1, label("EMDASH"))
        for path in ["docs/DRAFT.md", "build/OUT.md", "LICENCE.md"]:
            assert flagged(result, path) == [], path


class TestPositiveFix:
    """--fix applies SAFE_FIXES to prose and leaves every other byte alone."""

    @pytest.mark.parametrize(
        ("name", "replacement"), list(SAFE_FIXES.items()), ids=list(SAFE_FIXES)
    )
    def test_safe_character_is_rewritten(self, tmp_path: Path, name: str, replacement: str) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, f"Before%{name}%after\n")
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert read(tmp_path, path) == f"Before{replacement}after\n"

    def test_python_file_still_compiles(self, tmp_path: Path) -> None:
        path = "engine/ml/mapper.py"
        source = '"""Map A4 %RARR% 440 Hz%ELLIPSIS%"""\n\nPITCH = 440.0  # %RARR% ISO 16\n'
        write(tmp_path, path, source)
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        fixed = read(tmp_path, path)
        assert fixed == '"""Map A4 -> 440 Hz..."""\n\nPITCH = 440.0  # -> ISO 16\n'
        compile(fixed, path, "exec")

    def test_second_run_changes_nothing(self, tmp_path: Path) -> None:
        path = "docs/NOTES.md"
        write(tmp_path, path, "Signal %RARR% bus%ELLIPSIS% then %EMDASH% by hand\n")
        run_checker("--fix", "--files", path, cwd=tmp_path)
        once = read(tmp_path, path)
        assert once == expand("Signal -> bus... then %EMDASH% by hand\n")
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert read(tmp_path, path) == once
        assert result.returncode == 1, result.stdout


class TestContract:
    """The preflight contract: tagged lines, a summary, exit 0, 1 or 2."""

    def test_summary_counts_match_the_outcome_lines(self, tmp_path: Path) -> None:
        write(tmp_path, "docs/A.md", "Fails %EMDASH% here.\nWarns %MIDDOT% here.\n")
        write(tmp_path, "docs/B.md", "Clean.\n")
        result = run_checker("--files", "docs/A.md", "docs/B.md", cwd=tmp_path)
        summary = SUMMARY.search(result.stdout)
        assert summary, result.stdout
        counted = tuple(len(lines_tagged(result, tag)) for tag in ("PASS", "WARN", "FAIL"))
        assert tuple(int(count) for count in summary.groups()) == counted
        assert counted == (1, 1, 1)
        assert result.returncode == 1

    def test_help_names_every_mode(self, tmp_path: Path) -> None:
        result = run_checker("--help", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        for flag in ["--staged", "--files", "--all", "--commit-msg", "--fix"]:
            assert flag in result.stdout, flag

    @pytest.mark.parametrize(
        "args",
        [
            [],
            ["--fix"],
            ["--files"],
            ["--commit-msg"],
            ["--all", "--staged"],
            ["--bogus"],
            ["--fix", "--staged"],
            ["--fix", "--commit-msg", "COMMIT_EDITMSG"],
        ],
        ids=[
            "no-mode",
            "fix-alone",
            "files-empty",
            "commit-msg-empty",
            "two-modes",
            "unknown",
            "fix-with-staged",
            "fix-with-commit-msg",
        ],
    )
    def test_invalid_invocation_exits_2_with_usage(self, tmp_path: Path, args: list[str]) -> None:
        """A misconfigured hook must fail loudly, never pass having checked nothing."""
        write(tmp_path, "COMMIT_EDITMSG", "chore: placeholder\n")
        result = run_checker(*args, cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "usage" in result.stderr.lower(), result.stderr

    @pytest.mark.parametrize(
        "args",
        [["--files", "docs/MISSING.md"], ["--commit-msg", "MISSING_MSG"]],
        ids=["files", "commit-msg"],
    )
    def test_missing_path_exits_2(self, tmp_path: Path, args: list[str]) -> None:
        result = run_checker(*args, cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert args[-1] in result.stderr, result.stderr

    @pytest.mark.parametrize("mode", ["--staged", "--all"])
    def test_git_mode_outside_a_repository_aborts(self, tmp_path: Path, mode: str) -> None:
        result = run_checker(mode, cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "[ABORT]" in result.stderr, result.stderr

    @pytest.mark.parametrize(
        ("relpath", "data"),
        [
            ("docs/LATIN1.md", b"Caf\xe9 society\n"),
            ("engine/broken.py", b'def broken(:\n    """Half written."""\n'),
        ],
        ids=["invalid-utf8", "python-syntax-error"],
    )
    def test_unreadable_file_is_reported_not_a_crash(
        self, tmp_path: Path, relpath: str, data: bytes
    ) -> None:
        write_raw(tmp_path, relpath, data)
        result = run_checker("--files", relpath, cwd=tmp_path)
        assert "Traceback" not in result.stderr, result.stderr
        assert result.returncode in (0, 1), result.stdout
        assert flagged(result, relpath), result.stdout

    def test_checker_obeys_its_own_rules(self) -> None:
        """The policy tool and its specification are clean under the policy."""
        result = run_checker(
            "--files", "scripts/check_text_hygiene.py", "tests/test_text_hygiene.py", cwd=REPO_ROOT
        )
        assert result.returncode == 0, result.stdout
        assert lines_tagged(result, "FAIL") == [], result.stdout
        assert lines_tagged(result, "WARN") == [], result.stdout
