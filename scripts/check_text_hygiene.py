"""Check committed text for machine-writing artifacts and vault references.

Two rule families, restated from skills that live outside this repository:
T1 typography from idm-text-hygiene, and the reference-namespace rule from
idm-project-protocol. The skills are the human-readable source, and
tests/test_text_hygiene.py keeps this file in step with them.

Text rendered to a user is never read. In .py files only docstrings and
comments are checked, in .ts and .tsx only comment lines, and in .md, .toml,
.yml, .yaml and .sh every line. Commit messages are held to T1 alone, since
their Refs trailers cite the vault by design.

Usage:
    python scripts/check_text_hygiene.py --staged           # lines the next commit adds
    python scripts/check_text_hygiene.py --files PATH [...] # whole files
    python scripts/check_text_hygiene.py --all              # every tracked file
    python scripts/check_text_hygiene.py --commit-msg PATH  # a commit message file
    python scripts/check_text_hygiene.py --fix --files PATH [...]

Output follows scripts/preflight_dvc_repro.sh: one [PASS], [WARN] or [FAIL]
line per outcome, then a summary line.

Exit codes:
    0  nothing fails (WARN allowed)
    1  at least one FAIL
    2  invalid invocation or environment
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import os
import re
import shutil
import subprocess
import sys
import tokenize
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# T1 rows that fail, as codepoints from the skill's table. The en dash is
# conditional and handled on its own.
T1_FAIL = frozenset(
    [
        # em dash, horizontal bar, figure dash
        0x2014,
        0x2015,
        0x2012,
        # curly single and double quotes
        0x2018,
        0x2019,
        0x201C,
        0x201D,
        # ellipsis
        0x2026,
        # no-break, narrow no-break and thin spaces
        0x00A0,
        0x202F,
        0x2009,
        # zero-width space, non-joiner, joiner, byte order mark
        0x200B,
        0x200C,
        0x200D,
        0xFEFF,
        # arrows
        0x2192,
        0x2190,
        0x21D2,
        # bullet glyphs; the middle dot is in T1_WARN
        0x2022,
        0x25AA,
    ]
)

BOX_DRAWING = range(0x2500, 0x2580)

# Reported but never blocking and never rewritten: the middle dot and box
# drawing wait on operator decisions, and the skill asks for judgement on the
# multiplication and degree signs.
T1_WARN = frozenset([0x00B7, 0x00D7, 0x00B0, *BOX_DRAWING])

EN_DASH = 0x2013
DIGITS = frozenset("0123456789")

# The skill bans decorative emoji, meaning any pictographic character. Python
# has no emoji property, so the pictographic ranges are listed here. The music
# symbols U+2669 to U+266F stay out: sharp and flat are notation.
EMOJI = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x2668),
    (0x2670, 0x27BF),
    (0x231A, 0x231B),
    (0x23E9, 0x23FA),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
)
EMOJI_PRESENTATION = 0xFE0F

# The only rewrites --fix makes: one replacement each, and none of them a
# quote or other delimiter.
SAFE_FIXES = {
    0x2026: "...",
    0x2192: "->",
    0x2190: "<-",
    0x21D2: "=>",
    0x2015: "-",
    0x2012: "-",
    0x00A0: " ",
    0x202F: " ",
    0x2009: " ",
    0x200B: "",
    0x200C: "",
    0x200D: "",
    0xFEFF: "",
}

# Vault-internal IDs for decisions, infrastructure debt, code-review findings
# and backlog items, in the shapes the vault uses. A decision series always
# starts with a letter, which keeps model numbers such as the Roland D-50 out.
NAMESPACE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:D-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*"
    r"|INF-[A-Z0-9]+"
    r"|CR-(?:F[0-9]+|[0-9]+)"
    r"|TODO-[A-Z0-9][A-Za-z0-9]*)"
    r"(?![A-Za-z0-9_])"
)

# Allowlist item 4, as the skill words it. Only CR-1604 collides with a
# namespace shape today; the full list keeps the two easy to compare.
HARDWARE = (
    "Mackie CR-1604",
    "TB-303",
    "TR-808",
    "TR-909",
    "SP-1200",
    "S950",
    "SH-101",
    "DX100",
    "RE-201",
    "Quadraverb",
    "Alesis 3630",
    "Roland D-50",
)
HARDWARE_MODELS = frozenset(word for name in HARDWARE for word in name.split() if "-" in word)

# Allowlist items 5 and 6. Lockfiles and generated JSON or Parquet fall
# outside the checked file types in any case.
EXEMPT_NAMES = frozenset({"LICENCE.md", "CLAUDE.md"})
EXEMPT_PATTERNS = ("*.ipynb", "frontend/node_modules/*", "frontend/dist/*", "secrets/*.enc.yaml")
FROZEN = frozenset({".sops.yaml", "scripts/run-with-env.sh", ".env.shared"})

COMMENT_LINES = frozenset({".ts", ".tsx"})
WHOLE_FILE = frozenset({".md", ".toml", ".yml", ".yaml", ".sh"})
DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

LINE = re.compile(r"([^\r\n]*)(\r\n|\r|\n)")
HUNK = re.compile(r"^@@ -[0-9]+(?:,[0-9]+)? [+]([0-9]+)(?:,([0-9]+))? @@")
# git commit -v appends the staged diff below this line, and git drops it.
SCISSORS = re.compile(r"^# -+ >8 -+ *$")

Lines = list[tuple[str, str]]
Spans = dict[int, list[tuple[int, int]]]


class AbortError(Exception):
    """Invalid invocation or environment; the run exits 2."""


class ParseError(Exception):
    """A Python file whose docstrings and comments cannot be located."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(message)
        self.line = line
        self.message = message


@dataclass(frozen=True)
class Finding:
    tag: str
    line: int | None
    column: int | None
    detail: str
    whole_file: bool = False


@dataclass(frozen=True)
class Result:
    findings: list[Finding]
    fixed_text: str | None = None
    rewrites: int = 0


class Report:
    """Prints outcome lines in the preflight format and keeps the counts."""

    def __init__(self) -> None:
        self.counts = {"PASS": 0, "WARN": 0, "FAIL": 0}

    def emit(self, tag: str, location: str, detail: str = "") -> None:
        self.counts[tag] += 1
        print(f"[{tag}]  {location:<32} {detail}".rstrip())

    def file(self, display: str, findings: list[Finding]) -> None:
        if not findings:
            self.emit("PASS", display)
        for finding in findings:
            location = display
            if finding.line is not None:
                location += f":{finding.line}"
                if finding.column is not None:
                    location += f":{finding.column}"
            self.emit(finding.tag, location, finding.detail)

    def finish(self) -> int:
        counts = self.counts
        print(f"summary: pass={counts['PASS']}  warn={counts['WARN']}  fail={counts['FAIL']}")
        return 1 if counts["FAIL"] else 0


def split_lines(text: str) -> Lines:
    """Content and ending of each line, split on LF, CRLF and CR as Python does."""
    lines: Lines = []
    end = 0
    for match in LINE.finditer(text):
        lines.append((match.group(1), match.group(2)))
        end = match.end()
    if end < len(text):
        lines.append((text[end:], ""))
    return lines


def is_emoji(codepoint: int) -> bool:
    return any(low <= codepoint <= high for low, high in EMOJI)


def typography(content: str) -> list[tuple[int, str, str]]:
    """Column, tag and detail of every T1 character on one line."""
    found: list[tuple[int, str, str]] = []
    after_emoji = False
    for column, char in enumerate(content):
        codepoint = ord(char)
        if codepoint < 0x80:
            after_emoji = False
            continue
        tag = ""
        note = ""
        if codepoint in T1_FAIL:
            tag = "FAIL"
        elif codepoint in T1_WARN:
            tag = "WARN"
        elif codepoint == EN_DASH:
            before = content[column - 1] if column else ""
            after = content[column + 1 : column + 2]
            if not (before in DIGITS and after in DIGITS):
                tag, note = "FAIL", " outside a numeric range"
        elif is_emoji(codepoint) or (codepoint == EMOJI_PRESENTATION and not after_emoji):
            tag = "FAIL"
        after_emoji = is_emoji(codepoint)
        if tag:
            name = unicodedata.name(char, "")
            found.append((column, tag, f"U+{codepoint:04X} {name}{note}".rstrip()))
    return found


def references(content: str) -> list[tuple[int, str, str]]:
    """Column, tag and detail of every vault ID on one line, hardware excepted."""
    return [
        (match.start(), "FAIL", f"{match.group(0)} vault reference")
        for match in NAMESPACE.finditer(content)
        if match.group(0) not in HARDWARE_MODELS
    ]


def whole_lines(lines: Lines) -> Spans:
    return {number: [(0, len(content))] for number, (content, _) in enumerate(lines, 1)}


def char_column(content: str, byte_column: int) -> int:
    """ast reports columns in UTF-8 bytes; slicing a line needs characters."""
    return len(content.encode("utf-8")[:byte_column].decode("utf-8", "ignore"))


def python_spans(text: str, lines: Lines) -> Spans:
    """Docstrings located with ast and comments with tokenize.

    Every other string literal is left out: it may be text a user reads.
    """
    offset = 1 if text.startswith(chr(0xFEFF)) else 0
    source = text[offset:]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
            tokens = list(tokenize.generate_tokens(io.StringIO(source, newline=None).readline))
    except SyntaxError as exc:
        raise ParseError(exc.lineno or 1, exc.msg) from exc
    except (tokenize.TokenError, ValueError, RecursionError) as exc:
        raise ParseError(1, str(exc)) from exc

    spans: Spans = {}

    def source_line(number: int) -> str:
        content = lines[number - 1][0]
        return content[offset:] if number == 1 else content

    def add(number: int, start: int, end: int) -> None:
        shift = offset if number == 1 else 0
        spans.setdefault(number, []).append((start + shift, end + shift))

    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        literal = first.value
        last = literal.end_lineno or literal.lineno
        for number in range(literal.lineno, last + 1):
            content = source_line(number)
            start = char_column(content, literal.col_offset) if number == literal.lineno else 0
            end = len(content)
            if number == last and literal.end_col_offset is not None:
                end = char_column(content, literal.end_col_offset)
            add(number, start, end)

    for token in tokens:
        if token.type == tokenize.COMMENT:
            add(token.start[0], token.start[1], token.end[1])
    return spans


def comment_line_spans(lines: Lines) -> Spans:
    """Comment lines: // lines, and /* */ blocks that open a line.

    A line that opens with code is never read, so JSX text, props and string
    literals stay untouched even when they contain // or /*.
    """
    spans: Spans = {}
    in_block = False
    for number, (content, _) in enumerate(lines, 1):
        indent = len(content) - len(content.lstrip())
        if in_block:
            close = content.find("*/")
            in_block = close == -1
            spans[number] = [(0, len(content) if in_block else close + 2)]
        elif content.startswith("//", indent):
            spans[number] = [(indent, len(content))]
        elif content.startswith("/*", indent):
            close = content.find("*/", indent + 2)
            in_block = close == -1
            spans[number] = [(indent, len(content) if in_block else close + 2)]
    return spans


def hash_comment_spans(lines: Lines) -> Spans:
    spans: Spans = {}
    for number, (content, _) in enumerate(lines, 1):
        indent = len(content) - len(content.lstrip())
        if content.startswith("#", indent):
            spans[number] = [(indent, len(content))]
    return spans


def markdown_prose_spans(lines: Lines) -> Spans:
    """Every line outside fenced code blocks."""
    spans: Spans = {}
    fence = ""
    for number, (content, _) in enumerate(lines, 1):
        marker = content.lstrip()[:3]
        if marker in ("```", "~~~"):
            if not fence:
                fence = marker
            elif fence == marker:
                fence = ""
            continue
        if not fence:
            spans[number] = [(0, len(content))]
    return spans


def message_spans(lines: Lines) -> Spans:
    """The lines git keeps: comment lines and everything below the scissors go."""
    spans: Spans = {}
    for number, (content, _) in enumerate(lines, 1):
        if SCISSORS.match(content):
            break
        if not content.startswith("#"):
            spans[number] = [(0, len(content))]
    return spans


def kind_of(relpath: str) -> str:
    """python, comments or whole for the rules that apply; empty to skip the file."""
    path = PurePosixPath(relpath)
    if path.name in EXEMPT_NAMES or relpath in FROZEN:
        return ""
    if any(fnmatch.fnmatchcase(relpath, pattern) for pattern in EXEMPT_PATTERNS):
        return ""
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in COMMENT_LINES:
        return "comments"
    if suffix in WHOLE_FILE:
        return "whole"
    return ""


def check_spans(kind: str, text: str, lines: Lines) -> Spans:
    if kind == "python":
        return python_spans(text, lines)
    if kind == "comments":
        return comment_line_spans(lines)
    return whole_lines(lines)


def fix_spans(kind: str, suffix: str, text: str, lines: Lines) -> Spans:
    """Prose only. A line holding box drawing is a diagram and keeps its width."""
    if kind == "whole":
        spans = markdown_prose_spans(lines) if suffix == ".md" else hash_comment_spans(lines)
    else:
        spans = check_spans(kind, text, lines)
    return {
        number: ranges
        for number, ranges in spans.items()
        if not any(ord(char) in BOX_DRAWING for char in lines[number - 1][0])
    }


def apply_fixes(lines: Lines, spans: Spans) -> tuple[str, int]:
    """The text with SAFE_FIXES applied inside the spans, and the rewrite count."""
    parts: list[str] = []
    rewrites = 0
    for number, (content, ending) in enumerate(lines, 1):
        ranges = spans.get(number, [])
        for column, char in enumerate(content):
            replacement = SAFE_FIXES.get(ord(char))
            if replacement is not None and any(start <= column < end for start, end in ranges):
                parts.append(replacement)
                rewrites += 1
            else:
                parts.append(char)
        parts.append(ending)
    return "".join(parts), rewrites


def findings_in(lines: Lines, spans: Spans, *, namespaces: bool) -> list[Finding]:
    found: list[Finding] = []
    for number in sorted(spans):
        content = lines[number - 1][0]
        hits = typography(content)
        if namespaces:
            hits += references(content)
        for column, tag, detail in sorted(hits):
            if any(start <= column < end for start, end in spans[number]):
                found.append(Finding(tag, number, column + 1, detail))
    return found


def undecodable(exc: UnicodeDecodeError) -> Result:
    detail = f"not valid UTF-8 at byte {exc.start}"
    return Result([Finding("FAIL", None, None, detail, whole_file=True)])


def inspect(relpath: str, kind: str, data: bytes, *, fix: bool = False) -> Result:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return undecodable(exc)
    lines = split_lines(text)
    fixed_text = None
    rewrites = 0
    try:
        spans = check_spans(kind, text, lines)
        if fix:
            suffix = PurePosixPath(relpath).suffix.lower()
            candidate, rewrites = apply_fixes(lines, fix_spans(kind, suffix, text, lines))
            if rewrites:
                fixed_text = candidate
                lines = split_lines(candidate)
                spans = check_spans(kind, candidate, lines)
    except ParseError as exc:
        detail = f"cannot parse Python: {exc.message}"
        return Result([Finding("FAIL", exc.line, None, detail, whole_file=True)])
    return Result(findings_in(lines, spans, namespaces=True), fixed_text, rewrites)


def check_path(display: str, relpath: str, target: Path, *, fix: bool, report: Report) -> None:
    kind = kind_of(relpath)
    if not kind:
        return
    result = inspect(relpath, kind, target.read_bytes(), fix=fix)
    if result.fixed_text is not None:
        target.write_bytes(result.fixed_text.encode("utf-8"))
        print(f"fixed   {display}  rewrites={result.rewrites}")
    report.file(display, result.findings)


def git_executable() -> str:
    found = shutil.which("git")
    if found is None:
        raise AbortError("git not found on PATH")
    return found


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(  # noqa: S603
        [git_executable(), *args], cwd=root, capture_output=True, check=False
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise AbortError(f"git {args[0]} failed: {message}")
    return result.stdout


def repo_root(cwd: Path) -> Path | None:
    """The repository holding cwd, or None outside one or without git."""
    executable = shutil.which("git")
    if executable is None:
        return None
    result = subprocess.run(  # noqa: S603
        [executable, "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.decode("utf-8", "surrogateescape").strip())


def require_repo_root() -> Path:
    git_executable()
    root = repo_root(Path.cwd())
    if root is None:
        raise AbortError("not inside a git repository")
    return root


def check_files(paths: list[str], *, fix: bool, report: Report) -> None:
    missing = [path for path in paths if not os.path.isfile(path)]
    if missing:
        raise AbortError(f"no such file: {', '.join(missing)}")
    cwd = Path.cwd()
    base = os.path.realpath(repo_root(cwd) or cwd)
    for path in paths:
        display = PurePosixPath(os.path.normpath(path)).as_posix()
        relpath = os.path.relpath(os.path.realpath(path), base)
        if relpath == os.pardir or relpath.startswith(os.pardir + os.sep):
            relpath = display
        check_path(display, PurePosixPath(relpath).as_posix(), Path(path), fix=fix, report=report)


def check_all(*, fix: bool, report: Report) -> None:
    root = require_repo_root()
    for relpath in git(root, "ls-files", "-z").decode("utf-8", "surrogateescape").split("\x00"):
        target = root / relpath
        if relpath and not target.is_symlink() and target.is_file():
            check_path(relpath, relpath, target, fix=fix, report=report)


def added_lines(root: Path, old: str, new: str) -> set[int]:
    """Lines the index adds to a file; a rename contributes only its edits."""
    paths = [new] if old == new else [old, new]
    options = ("--cached", "-U0", "-M", "--no-color", "--no-ext-diff", "--no-textconv")
    diff = git(root, "diff", *options, "--", *paths)
    added: set[int] = set()
    for line in diff.decode("utf-8", "replace").splitlines():
        match = HUNK.match(line)
        if match:
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            added.update(range(start, start + count))
    return added


def check_staged(report: Report) -> None:
    root = require_repo_root()
    status = git(root, "diff", "--cached", "--name-status", "-z", "-M", "--diff-filter=ACMR")
    fields = status.decode("utf-8", "surrogateescape").split("\x00")
    index = 0
    while index < len(fields) and fields[index]:
        if fields[index].startswith(("R", "C")):
            old, new = fields[index + 1], fields[index + 2]
            index += 3
        else:
            old = new = fields[index + 1]
            index += 2
        kind = kind_of(new)
        if not kind:
            continue
        added = added_lines(root, old, new)
        result = inspect(new, kind, git(root, "cat-file", "blob", f":{new}"))
        report.file(new, [f for f in result.findings if f.whole_file or f.line in added])


def check_commit_message(path: str, report: Report) -> None:
    if not os.path.isfile(path):
        raise AbortError(f"no such file: {path}")
    try:
        text = Path(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        report.file(path, undecodable(exc).findings)
        return
    lines = split_lines(text)
    report.file(path, findings_in(lines, message_spans(lines), namespaces=False))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check committed text for machine-writing artifacts and vault references.",
        epilog="Exit codes: 0 nothing fails, 1 at least one FAIL, 2 invalid invocation.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--staged", action="store_true", help="lines the index adds, as the next commit records"
    )
    mode.add_argument("--files", nargs="+", metavar="PATH", help="whole files, as given")
    mode.add_argument("--all", dest="all_files", action="store_true", help="every tracked file")
    mode.add_argument("--commit-msg", metavar="PATH", help="a commit message file")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="rewrite the mechanically safe characters in prose; with --files or --all",
    )
    args = parser.parse_args(argv)
    if args.fix and (args.staged or args.commit_msg is not None):
        parser.error("--fix works only with --files or --all")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    args = parse_args(argv)
    report = Report()
    try:
        if args.staged:
            check_staged(report)
        elif args.all_files:
            check_all(fix=args.fix, report=report)
        elif args.commit_msg is not None:
            check_commit_message(args.commit_msg, report)
        else:
            check_files(args.files, fix=args.fix, report=report)
    except (AbortError, OSError) as exc:
        print(f"[ABORT] {exc}", file=sys.stderr)
        return 2
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
