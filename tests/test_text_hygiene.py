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
    "MIDDOT",
    "ROBOT",
    "GREENDOT",
    "YELLOWDOT",
    "REDDOT",
    "CHECKMARK",
]

# Surfaced without blocking: the skill asks for judgement on the
# multiplication and degree signs.
WARN_CLASSES = ["TIMES", "DEGREE"]

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

    @pytest.mark.parametrize(
        ("path", "text"),
        [
            ("README.md", "%BOXFIRST%%BOXFIRST% Frontend %BOXLAST%\nPlain line.\n"),
            ("engine/generator.py", "# %BOXFIRST%%BOXFIRST% signal chain %BOXLAST%\nX = 1\n"),
        ],
        ids=["markdown", "python-comment"],
    )
    def test_box_drawing_passes(self, tmp_path: Path, path: str, text: str) -> None:
        """Allowlist item 9: a hand-drawn diagram or tree output is not an authorship trace."""
        write(tmp_path, path, text)
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
            Glue knee target, 128 BPM %TIMES% 64, 90%DEGREE% phase.
            %BOXFIRST%%BOXFIRST% diagram %BOXLAST%
            """
        )
        write(tmp_path, path, kept + "Signal %RARR% bus\n")
        result = run_checker("--fix", "--files", path, cwd=tmp_path)
        assert result.returncode == 0, result.stdout
        assert read(tmp_path, path) == expand(kept + "Signal -> bus\n")

    def test_judgement_classes_are_reported_not_rewritten(self, tmp_path: Path) -> None:
        """Em dash, stray en dash, curly quotes, bullets, the middle dot and emoji have no single safe rewrite."""
        path = "docs/NOTES.md"
        text = (
            "A %EMDASH% B, Detroit%ENDASH%Berlin, %LDQUO%dub%RDQUO%, it%RSQUO%s, "
            "%BULLET% one, Glue %MIDDOT% knee, %CHECKMARK% done\n"
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

    def test_middle_dot_fails_as_a_separator(self, tmp_path: Path) -> None:
        """Banned in every position: between words as much as at the start of a line."""
        path = "docs/NOTES.md"
        write(tmp_path, path, "Intro line.\nGlue %MIDDOT% knee %MIDDOT% target\n")
        result = run_checker("--files", path, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, label("MIDDOT"))
        hits = [line.split()[1] for line in located(result, "FAIL", path, 2)]
        assert hits == [f"{path}:2:6", f"{path}:2:13"], result.stdout

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
        write(tmp_path, "docs/A.md", "Fails %EMDASH% here.\nWarns %TIMES% here.\n")
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


def commit(repo: Path, message: str) -> None:
    """Stage everything in a scratch repository and commit it."""
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


class TestNegativeDiff:
    """--diff judges only what the working tree adds relative to REF."""

    def test_committed_legacy_lines_are_not_rechecked(self, repo: Path) -> None:
        """A commit after REF that adds clean text to a legacy file passes."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\nNew clean line.\n")
        commit(repo, "docs: add a line")
        assert_clean(run_checker("--diff", "base", cwd=repo), "docs/GUIDE.md")

    def test_uncommitted_clean_edit_to_a_legacy_file_passes(self, repo: Path) -> None:
        """The authoring-hook shape: REF is HEAD and the edit is not staged."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\nNew clean line.\n")
        assert_clean(run_checker("--diff", "HEAD", cwd=repo), "docs/GUIDE.md")

    def test_renamed_legacy_file_is_not_rechecked(self, repo: Path) -> None:
        """A rename adds no lines, so moving a legacy file after REF passes."""
        write(repo, "docs/OLD.md", "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        git(repo, "mv", "docs/OLD.md", "docs/NEW.md")
        commit(repo, "chore: rename")
        assert_clean(run_checker("--diff", "base", cwd=repo), "docs/NEW.md")

    def test_renamed_legacy_file_is_not_rechecked_whatever_the_config(self, repo: Path) -> None:
        """Renames are detected explicitly, whatever diff.renames says."""
        git(repo, "config", "diff.renames", "false")
        write(repo, "docs/OLD.md", "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        git(repo, "mv", "docs/OLD.md", "docs/NEW.md")
        commit(repo, "chore: rename")
        assert_clean(run_checker("--diff", "base", cwd=repo), "docs/NEW.md")

    def test_untracked_files_are_ignored(self, repo: Path) -> None:
        """git diff shows tracked files only, so an untracked draft is not judged."""
        write(repo, "docs/GUIDE.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        write(repo, "docs/GUIDE.md", "Clean line.\nSecond clean line.\n")
        write(repo, "docs/DRAFT.md", "Draft %EMDASH% text.\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert_clean(result, "docs/GUIDE.md")
        assert flagged(result, "docs/DRAFT.md") == [], result.stdout

    def test_deleted_file_passes(self, repo: Path) -> None:
        write(repo, "docs/OLD.md", "Legacy %EMDASH% text.\n")
        write(repo, "docs/GUIDE.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        git(repo, "rm", "-q", "docs/OLD.md")
        write(repo, "docs/GUIDE.md", "Clean line.\nSecond clean line.\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert "Traceback" not in result.stderr, result.stderr
        assert_clean(result, "docs/GUIDE.md")
        assert flagged(result, "docs/OLD.md") == [], result.stdout

    def test_symlink_is_skipped(self, repo: Path) -> None:
        """Read from disk, a link is judged by its target's text; --all skips links too."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        write(repo, "docs/NOTES.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        (repo / "docs" / "LINK.md").symlink_to("GUIDE.md")
        git(repo, "add", "docs/LINK.md")
        write(repo, "docs/NOTES.md", "Clean line.\nSecond clean line.\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert_clean(result, "docs/NOTES.md")
        assert flagged(result, "docs/LINK.md") == [], result.stdout

    def test_added_user_facing_strings_pass(self, repo: Path) -> None:
        """Region rules still apply: literals in .py and rendered JSX in .tsx are not read."""
        py = "api/profiles.py"
        tsx = "frontend/src/components/Panel.tsx"
        py_base = '"""Profile lookup endpoints."""\n'
        tsx_base = "export const Panel = () => <h2>Tempo</h2>;\n"
        write(repo, py, py_base)
        write(repo, tsx, tsx_base)
        commit(repo, "chore: baseline")
        write(repo, py, py_base + 'TRACK = "Track #1 %EMDASH% intro"\n')
        write(repo, tsx, tsx_base + "export const H = () => <h2>Tempo %RARR% Swing</h2>;\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert_clean(result, py)
        assert_clean(result, tsx)

    def test_exempt_and_unchecked_files_are_skipped(self, repo: Path) -> None:
        """LICENCE.md, SOPS output and a JSON file stay out of scope in --diff."""
        skipped = ["LICENCE.md", "secrets/app.enc.yaml", "config/presets.json"]
        for path in [*skipped, "docs/NOTES.md"]:
            write(repo, path, "Clean line.\n")
        commit(repo, "chore: baseline")
        for path in skipped:
            write(repo, path, "Clean line.\nLegacy %EMDASH% text.\n")
        write(repo, "docs/NOTES.md", "Clean line.\nSecond clean line.\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert_clean(result, "docs/NOTES.md")
        for path in skipped:
            assert flagged(result, path) == [], path

    def test_edit_reverted_to_ref_content_passes(self, repo: Path) -> None:
        """The working tree is judged, not the history: an edit undone again adds nothing."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        write(repo, "docs/NOTES.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text, edited.\n")
        commit(repo, "docs: edit the legacy line")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        write(repo, "docs/NOTES.md", "Clean line.\nSecond clean line.\n")
        result = run_checker("--diff", "base", cwd=repo)
        assert_clean(result, "docs/NOTES.md")
        assert flagged(result, "docs/GUIDE.md") == [], result.stdout


class TestPositiveDiff:
    """--diff fails on what the working tree adds relative to REF."""

    def test_added_line_since_ref_fails(self, repo: Path) -> None:
        path = "docs/GUIDE.md"
        write(repo, path, "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        write(repo, path, "Legacy %EMDASH% text.\nNew %RARR% line.\n128 BPM %TIMES% 64.\n")
        commit(repo, "docs: add two lines")
        result = run_checker("--diff", "base", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, label("RARR"))
        assert_reported(result, "WARN", path, 3, label("TIMES"))
        assert located(result, "FAIL", path, 1) == [], result.stdout
        summary = SUMMARY.search(result.stdout)
        assert summary, result.stdout
        assert summary.groups() == ("0", "1", "1"), result.stdout

    def test_unstaged_change_is_judged(self, repo: Path) -> None:
        """The authoring-hook shape: REF is HEAD and the edit is not staged."""
        path = "docs/GUIDE.md"
        write(repo, path, "Clean line.\n")
        commit(repo, "chore: baseline")
        write(repo, path, "Clean line.\nUnstaged %EMDASH% line.\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", path, 2, label("EMDASH"))

    def test_committed_staged_and_unstaged_additions_all_count(self, repo: Path) -> None:
        for name in "ABC":
            write(repo, f"docs/{name}.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        git(repo, "tag", "base")
        write(repo, "docs/A.md", "Clean line.\nCommitted %EMDASH% line.\n")
        commit(repo, "docs: committed line")
        write(repo, "docs/B.md", "Clean line.\nStaged %EMDASH% line.\n")
        git(repo, "add", "docs/B.md")
        write(repo, "docs/C.md", "Clean line.\nUnstaged %EMDASH% line.\n")
        result = run_checker("--diff", "base", cwd=repo)
        assert result.returncode == 1, result.stdout
        for name in "ABC":
            assert_reported(result, "FAIL", f"docs/{name}.md", 2, label("EMDASH"))

    def test_new_tracked_file_is_judged_whole(self, repo: Path) -> None:
        """Every line of a file added after REF is an added line."""
        write(repo, "docs/GUIDE.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        write(repo, "docs/NEW.md", "First %RARR% line.\n")
        git(repo, "add", "docs/NEW.md")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/NEW.md", 1, label("RARR"))

    def test_added_line_in_renamed_file_fails(self, repo: Path) -> None:
        legacy = "Legacy %EMDASH% text.\nSecond legacy line.\nThird legacy line.\n"
        write(repo, "docs/OLD.md", legacy)
        commit(repo, "chore: baseline")
        git(repo, "mv", "docs/OLD.md", "docs/NEW.md")
        write(repo, "docs/NEW.md", legacy + "New %RARR% line.\n")
        git(repo, "add", "docs/NEW.md")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/NEW.md", 4, label("RARR"))
        assert located(result, "FAIL", "docs/NEW.md", 1) == [], result.stdout

    def test_merge_first_parent_is_the_pull_request_base(self, repo: Path) -> None:
        """CI shape: on a merge commit, --diff HEAD^1 reports the merged branch's lines only."""
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\n")
        commit(repo, "chore: baseline")
        git(repo, "switch", "-q", "-c", "feature")
        write(repo, "docs/GUIDE.md", "Legacy %EMDASH% text.\nBranch %RARR% line.\n")
        commit(repo, "docs: branch line")
        git(repo, "switch", "-q", "main")
        write(repo, "docs/BASE.md", "Base %EMDASH% moved on.\n")
        commit(repo, "docs: the base moves on")
        git(repo, "merge", "-q", "--no-ff", "-m", "Merge branch feature", "feature")
        result = run_checker("--diff", "HEAD^1", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "docs/GUIDE.md", 2, label("RARR"))
        assert located(result, "FAIL", "docs/GUIDE.md", 1) == [], result.stdout
        assert flagged(result, "docs/BASE.md") == [], result.stdout

    def test_whole_file_finding_is_reported_regardless_of_lines(self, repo: Path) -> None:
        """Invalid UTF-8 has no line number, so a line filter must not drop it."""
        path = "docs/GUIDE.md"
        write(repo, path, "Clean line.\n")
        commit(repo, "chore: baseline")
        write_raw(repo, path, b"Clean line.\nCaf\xe9 society\n")
        result = run_checker("--diff", "HEAD", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert any("not valid UTF-8" in line for line in flagged(result, path)), result.stdout


class TestContractDiff:
    """--diff keeps the preflight contract and fails loudly when misused."""

    def test_help_names_the_diff_mode(self, tmp_path: Path) -> None:
        result = run_checker("--help", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "--diff" in result.stdout, result.stdout

    def test_missing_ref_is_a_usage_error(self, tmp_path: Path) -> None:
        result = run_checker("--diff", cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "usage" in result.stderr.lower(), result.stderr
        assert "expected one argument" in result.stderr, result.stderr

    def test_diff_with_another_mode_is_rejected(self, tmp_path: Path) -> None:
        result = run_checker("--diff", "HEAD", "--all", cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "not allowed with argument" in result.stderr, result.stderr

    def test_fix_with_diff_is_rejected(self, tmp_path: Path) -> None:
        """--fix rewrites whole files, which --diff never judges."""
        result = run_checker("--fix", "--diff", "HEAD", cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "--fix works only with --files or --all" in result.stderr, result.stderr

    def test_unknown_ref_aborts(self, repo: Path) -> None:
        write(repo, "docs/GUIDE.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        result = run_checker("--diff", "no-such-ref", cwd=repo)
        assert "Traceback" not in result.stderr, result.stderr
        assert result.returncode == 2, result.stdout
        assert "[ABORT]" in result.stderr, result.stderr

    def test_ref_naming_a_file_aborts(self, repo: Path) -> None:
        """git diff would take a file name as a pathspec and compare it with the index."""
        write(repo, "README.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        write(repo, "README.md", "Clean line.\nEdited %EMDASH% line.\n")
        result = run_checker("--diff", "README.md", cwd=repo)
        assert result.returncode == 2, result.stdout
        assert "[ABORT]" in result.stderr, result.stderr

    def test_option_like_ref_aborts_without_running_git_diff(self, repo: Path) -> None:
        """Passed on to git diff, --output=FILE would write a file; REF must name a commit."""
        write(repo, "docs/GUIDE.md", "Clean line.\n")
        commit(repo, "chore: baseline")
        result = run_checker("--diff=--output=OUT.txt", cwd=repo)
        assert result.returncode == 2, result.stdout
        assert "[ABORT]" in result.stderr, result.stderr
        assert not (repo / "OUT.txt").exists(), "git diff ran with an injected option"

    def test_diff_outside_a_repository_aborts(self, tmp_path: Path) -> None:
        result = run_checker("--diff", "HEAD", cwd=tmp_path)
        assert result.returncode == 2, result.stdout
        assert "[ABORT]" in result.stderr, result.stderr


# T0 in commit messages: a trailer or footer that credits a tool. The trailer
# form found in this repository's own history and the one the harness
# documents as its default are both covered, beside the other tools' forms.
HARNESS_TRAILER = "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
DOCUMENTED_TRAILER = "Co-authored-by: Claude <claude@anthropic.com>"


def check_message(tmp_path: Path, message: str) -> Result:
    """Write a commit message fixture and run --commit-msg on it."""
    write(tmp_path, "COMMIT_EDITMSG", message)
    return run_checker("--commit-msg", "COMMIT_EDITMSG", cwd=tmp_path)


class TestNegativeAttribution:
    """T0: people's trailers, prose that mentions a key, and footers without a tool pass."""

    @pytest.mark.parametrize(
        "trailer",
        [
            "Co-authored-by: Jane Doe <jane@example.com>",
            "Co-authored-by: Jane Doe <12345+janedoe@users.noreply.github.com>",
            "Signed-off-by: Ai Tanaka <ai.tanaka@example.com>",
            "Reviewed-by: Lena Model <lena@example.com>",
        ],
        ids=["co-author", "github-noreply", "given-name-ai", "surname-model"],
    )
    def test_human_trailers_pass(self, tmp_path: Path, trailer: str) -> None:
        """A name is not an identifier: Ai and Model are people here."""
        message = f"fix(engine): clamp the resonance seed\n\nKeeps the seed audible.\n\n{trailer}\n"
        assert_clean(check_message(tmp_path, message), "COMMIT_EDITMSG")

    def test_trailer_key_in_prose_passes(self, tmp_path: Path) -> None:
        """The rule reads a key followed by a colon, not the words of a sentence."""
        message = dedent(
            """\
            docs(contributing): explain the co-authored-by trailer

            The co-authored-by trailer credits a second person; GitHub reads it
            when the author is a pair. Nothing about Claude or Copilot belongs here.
            """
        )
        assert_clean(check_message(tmp_path, message), "COMMIT_EDITMSG")

    @pytest.mark.parametrize(
        "footer",
        [
            "Generated with the regional profile model.",
            "Created by the dataset generator from params.yaml.",
            "Written by hand from the TR-808 service manual.",
            "Made with a Mackie CR-1604 and a TB-303.",
        ],
        ids=["model", "generator", "by-hand", "hardware"],
    )
    def test_footers_without_a_tool_pass(self, tmp_path: Path, footer: str) -> None:
        """model, generator and hardware names are domain words, not identifiers."""
        message = f"feat(ml): add the profile loader\n\n{footer}\n"
        assert_clean(check_message(tmp_path, message), "COMMIT_EDITMSG")

    def test_tool_words_outside_an_attribution_pass(self, tmp_path: Path) -> None:
        """A verb in mid-sentence and a word that happens to contain AI are not footers."""
        message = dedent(
            """\
            fix(ui): keep the highlight created by the cursor

            The selection is created by the cursor drag and cleared on blur.
            AIFF export stays unchanged.
            """
        )
        assert_clean(check_message(tmp_path, message), "COMMIT_EDITMSG")

    def test_rule_applies_to_messages_only(self, tmp_path: Path) -> None:
        """T0 judges commit messages; a document quoting a trailer is read under T1 alone."""
        path = "docs/CONTRIBUTING.md"
        write(tmp_path, path, f"Never add this trailer to a commit:\n\n{DOCUMENTED_TRAILER}\n")
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestPositiveAttribution:
    """T0: a trailer or footer that credits a tool fails at its line."""

    @pytest.mark.parametrize(
        "trailer",
        [
            HARNESS_TRAILER,
            DOCUMENTED_TRAILER,
            "co-authored-by: claude <noreply@anthropic.com>",
            "Signed-off-by: GitHub Copilot <copilot@github.com>",
            "Assisted-by: GPT-4o",
            "Generated-by: Gemini",
            "Co-authored-by: Cursor Agent <cursoragent@cursor.com>",
            "Co-authored-by: Code Helper <noreply@anthropic.com>",
            "Co-authored-by: AI <bot@example.com>",
            "Co-authored-by: an LLM",
            "Helped-by: a coding assistant",
        ],
        ids=[
            "harness-history",
            "harness-documented",
            "lower-case",
            "copilot-signed-off",
            "gpt-assisted",
            "gemini-generated",
            "cursor",
            "vendor-in-address",
            "ai-alone",
            "llm",
            "assistant",
        ],
    )
    def test_tool_trailer_fails(self, tmp_path: Path, trailer: str) -> None:
        message = f"fix(engine): clamp the resonance seed\n\nKeeps the seed audible.\n\n{trailer}\n"
        result = check_message(tmp_path, message)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "COMMIT_EDITMSG", 5, "T0")

    @pytest.mark.parametrize(
        "footer",
        [
            "Generated with Claude Code",
            "Created by ChatGPT",
            "Written by GitHub Copilot.",
            "Assisted by Gemini",
            "Made with Cursor",
            "Co-written with an AI assistant",
            "_Generated with Claude Code_",
            "> generated using OpenAI Codex",
        ],
        ids=[
            "generated-with",
            "created-by",
            "written-by",
            "assisted-by",
            "made-with",
            "co-written",
            "underscored",
            "quoted-lower-case",
        ],
    )
    def test_tool_footer_fails(self, tmp_path: Path, footer: str) -> None:
        message = f"feat(ml): add the profile loader\n\n{footer}\n"
        result = check_message(tmp_path, message)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "COMMIT_EDITMSG", 3, "T0")

    def test_harness_footer_fails_under_both_tiers(self, tmp_path: Path) -> None:
        """The robot emoji is T1 and the footer text is T0; both are reported on the line."""
        footer = "%ROBOT% Generated with [Claude Code](https://claude.com/claude-code)"
        result = check_message(tmp_path, f"chore: bump ruff\n\n{footer}\n")
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "COMMIT_EDITMSG", 3, label("ROBOT"))
        assert_reported(result, "FAIL", "COMMIT_EDITMSG", 3, "T0")

    def test_trailer_inside_the_body_fails(self, tmp_path: Path) -> None:
        """A key-value line is judged wherever it sits, not only in the last paragraph."""
        message = dedent(
            f"""\
            feat(ml): add the profile loader

            {DOCUMENTED_TRAILER}

            The loader reads the six spokes.
            """
        )
        result = check_message(tmp_path, message)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "COMMIT_EDITMSG", 3, "T0")

    def test_summary_counts_t0_with_t1(self, tmp_path: Path) -> None:
        message = (
            f"docs(readme): clarify the pipeline %EMDASH% registry step\n\n{HARNESS_TRAILER}\n"
        )
        result = check_message(tmp_path, message)
        summary = SUMMARY.search(result.stdout)
        assert summary, result.stdout
        assert summary.groups() == ("0", "0", "2"), result.stdout


# Configuration formats. Docker, ignore and environment files, requirements files,
# the blame-ignore list and the DVC config are read whole, as none of them holds text
# a user reads; CSS and JavaScript are read in comments only.
WHOLE_FILE_TYPES = [
    "Dockerfile",
    "build/lint.Dockerfile",
    ".gitignore",
    "models/.gitignore",
    ".dockerignore",
    "build/lint.Dockerfile.dockerignore",
    ".dvcignore",
    ".env.example",
    ".git-blame-ignore-revs",
    ".dvc/config",
    "requirements.txt",
    "requirements-dev.txt",
]
IGNORE_FILES = [".gitignore", ".dockerignore", ".dvcignore", "build/lint.Dockerfile.dockerignore"]
ALLOWED_TEXT = "Kick from a TR-808 into a Mackie CR-1604 at 80%ENDASH%180 BPM, README.md %SECTION%4"
ALLOWED_CASES = [
    *((path, f"# {ALLOWED_TEXT}\n") for path in WHOLE_FILE_TYPES),
    ("frontend/src/theme.css", f"/* {ALLOWED_TEXT} */\n.a {{ color: red; }}\n"),
    ("frontend/vite.helpers.js", f"// {ALLOWED_TEXT}\nexport default {{}};\n"),
]


class TestNegativeConfigFormats:
    """Frozen files, rendered text and other formats stay out; allowed text passes."""

    def test_frozen_env_shared_stays_skipped_while_env_example_fails(self, tmp_path: Path) -> None:
        """Same text in both, so the skip cannot come from a dead rule."""
        text = "# Rationale %EMDASH% see D-CRF13-99\nKEY=value\n"
        write(tmp_path, ".env.shared", text)
        write(tmp_path, ".env.example", text)
        result = run_checker("--files", ".env.shared", ".env.example", cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert flagged(result, ".env.shared") == [], result.stdout
        assert_reported(result, "FAIL", ".env.example", 1, label("EMDASH"))
        assert_reported(result, "FAIL", ".env.example", 1, "D-CRF13-99")

    def test_css_declarations_and_js_literals_are_not_read(self, tmp_path: Path) -> None:
        """A CSS content value is rendered, and a JavaScript literal may be."""
        css = "frontend/src/notes.css"
        js = "frontend/postcss.config.js"
        write(
            tmp_path,
            css,
            '/* Panel styles */\n.note::after {\n  content: "Tempo %RARR% Swing%ELLIPSIS%";\n}\n',
        )
        write(
            tmp_path,
            js,
            '// Build configuration\nexport const LABEL = "Tempo %EMDASH% Swing";\n'
            "export default { plugins: {} };\n",
        )
        result = run_checker("--files", css, js, cwd=tmp_path)
        assert_clean(result, css)
        assert_clean(result, js)

    @pytest.mark.parametrize(
        ("relpath", "text"), ALLOWED_CASES, ids=[*WHOLE_FILE_TYPES, "css", "js"]
    )
    def test_allowlisted_text_passes_in_new_types(
        self, tmp_path: Path, relpath: str, text: str
    ) -> None:
        """Hardware names, a numeric range and the section sign are not artifacts."""
        write(tmp_path, relpath, text)
        assert_clean(run_checker("--files", relpath, cwd=tmp_path), relpath)

    def test_other_txt_files_stay_out_of_scope(self, tmp_path: Path) -> None:
        """Only requirements files are read; other text files may be data."""
        text = "Legacy %EMDASH% label\n"
        write(tmp_path, "data/labels.txt", text)
        write(tmp_path, "requirements.txt", text)
        result = run_checker("--files", "data/labels.txt", "requirements.txt", cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert flagged(result, "data/labels.txt") == [], result.stdout
        assert_reported(result, "FAIL", "requirements.txt", 1, label("EMDASH"))

    def test_fix_rewrites_only_hash_comments_in_new_types(self, tmp_path: Path) -> None:
        """Instructions, values and inline comments are reported but never rewritten."""
        cases = {
            "Dockerfile": ("# Build %RARR% wheel\n", 'RUN echo "a %RARR% b"\n'),
            ".env.example": ("# Keys %RARR% values\n", 'LABEL="Tempo %RARR% Swing"\n'),
            "requirements.txt": ("# Pins %RARR% CI\n", "numpy>=1.26  # floor %RARR% wheels\n"),
        }
        for path, (comment, code) in cases.items():
            write(tmp_path, path, comment + code)
        result = run_checker("--fix", "--files", *cases, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        for path, (comment, code) in cases.items():
            assert read(tmp_path, path) == expand(comment.replace("%RARR%", "->") + code), path

    @pytest.mark.parametrize("relpath", IGNORE_FILES)
    def test_fix_leaves_indented_hash_lines_in_ignore_files(
        self, tmp_path: Path, relpath: str
    ) -> None:
        """gitignore(5) and Docker read a comment only from a # in column 1."""
        text = "# Build %RARR% output\n  #pattern%RARR%name\n"
        write(tmp_path, relpath, text)
        result = run_checker("--fix", "--files", relpath, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert read(tmp_path, relpath) == expand(text.replace("# Build %RARR%", "# Build ->"))

    def test_css_double_slash_lines_are_not_comments(self, tmp_path: Path) -> None:
        """CSS has block comments only, so a line opening with // is part of a value."""
        path = "frontend/src/fonts.css"
        write(
            tmp_path,
            path,
            "/* Fonts */\n@font-face {\n  src: url(\n"
            "    //cdn.example.org/tempo%EMDASH%swing.woff2\n  );\n}\n",
        )
        assert_clean(run_checker("--files", path, cwd=tmp_path), path)


class TestPositiveConfigFormats:
    """The configuration formats are read where their text lives, at exact lines."""

    @pytest.mark.parametrize("relpath", WHOLE_FILE_TYPES)
    def test_new_whole_file_type_fails_at_its_line(self, tmp_path: Path, relpath: str) -> None:
        """Line 3 is neither the first line nor a comment, so the whole file is read."""
        write(tmp_path, relpath, "# Header\nplain line\nPipeline %EMDASH% registry\n")
        result = run_checker("--files", relpath, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", relpath, 3, label("EMDASH"))

    def test_css_and_js_comment_lines_fail_at_their_lines(self, tmp_path: Path) -> None:
        css = "frontend/src/index.css"
        js = "frontend/postcss.config.js"
        write(
            tmp_path,
            css,
            "/* Scrollbar %EMDASH% minimal */\n.a { color: red; }\n/*\n  Block %RARR% note\n*/\n",
        )
        write(
            tmp_path, js, "// Config %EMDASH% note\nexport default {};\n/* Block %RARR% note */\n"
        )
        result = run_checker("--files", css, js, cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        expected = [(css, 1, "EMDASH"), (css, 4, "RARR"), (js, 1, "EMDASH"), (js, 3, "RARR")]
        for path, lineno, name in expected:
            assert_reported(result, "FAIL", path, lineno, label(name))

    def test_vault_reference_fails_in_a_dockerfile_comment(self, tmp_path: Path) -> None:
        write(tmp_path, "Dockerfile", "FROM python:3.11-slim\n# Pinned for INF-ZZ\n")
        result = run_checker("--files", "Dockerfile", cwd=tmp_path)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "Dockerfile", 2, "INF-ZZ")

    def test_staged_judges_added_dockerfile_lines(self, repo: Path) -> None:
        legacy = "# Legacy %EMDASH% header\nFROM python:3.11-slim\n"
        write(repo, "Dockerfile", legacy)
        git(repo, "add", "Dockerfile")
        git(repo, "commit", "-q", "-m", "chore: baseline")
        write(repo, "Dockerfile", legacy + "# New %RARR% stage\n")
        git(repo, "add", "Dockerfile")
        result = run_checker("--staged", cwd=repo)
        assert result.returncode == 1, result.stdout
        assert_reported(result, "FAIL", "Dockerfile", 3, label("RARR"))
        assert located(result, "FAIL", "Dockerfile", 1) == [], result.stdout

    def test_all_reads_tracked_new_types(self, repo: Path) -> None:
        files = {
            "Dockerfile": "# Stage %EMDASH% one\n",
            ".gitignore": "# Build %EMDASH% output\nbuild/\n",
            "frontend/src/index.css": "/* Theme %EMDASH% dark */\n",
            "requirements.txt": "# Pins %EMDASH% CI\n",
        }
        for path, text in files.items():
            write(repo, path, text)
        commit(repo, "chore: baseline")
        result = run_checker("--all", cwd=repo)
        assert result.returncode == 1, result.stdout
        for path in files:
            assert_reported(result, "FAIL", path, 1, label("EMDASH"))
