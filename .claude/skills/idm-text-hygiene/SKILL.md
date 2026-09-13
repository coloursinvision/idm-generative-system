---
name: idm-text-hygiene
description: >-
  Artifact hygiene for every text this project commits: machine-authorship traces,
  typography, prose register, and comment-level tells in code, docs, commit messages
  and PR bodies. Use when writing or reviewing any committed text - a commit message,
  PR body, docstring, code comment, README or repo doc - when normalising an existing
  file, or when deciding whether a character, term or comment belongs in this
  repository.
---

# IDM - committed-text hygiene

Every text this project commits must read as a human work product. This skill is
the single source for what that means, in four tiers, with an explicit allowlist.

CLAUDE.md §4.4 owns the commit format. `idm-project-protocol` owns the release
procedure and the internal reference namespaces. This skill owns the character,
word and comment level, and it supersedes the shorter purity note in
`idm-project-protocol` (which stays as a pointer here).

## The rule is not "ASCII only"

`§` (U+00A7) is not ASCII and is correct: the project references sections that way
throughout CLAUDE.md and the vault. A blanket ASCII rule would destroy a working
convention. The rule is therefore **no artifact characters**, enumerated below,
with everything not enumerated allowed. Banned characters are named here by name
and codepoint rather than glyph, so this file needs no exemption from its own rule.

## Scope

Applies to: commit messages, PR bodies and titles, code comments, docstrings,
repo-committed Markdown, configuration comments, and new vault documents.

Does not apply to: the allowlist in §Allowlist, and any file listed there.

Existing files predate this policy. A measured baseline and a staged cleanup are
separate work. An artifact already sitting in an untouched file is not licence to
add another one.

## T0 - authorship and process traces

Hard rule, zero tolerance. This is the one rule the project has already proven it
can hold: no commit has carried a machine-attribution trailer since the policy was
written, and none may.

Never write:

- `Co-Authored-By:` trailers naming any assistant, model or vendor.
- "generated with", "created by", "written by", "assisted by" footers naming a tool.
- The robot emoji (U+1F916) or any badge standing in for tool attribution.
- Provenance frontmatter keys: `model_used`, `model_next`, `token_signal`,
  `token_signal_at_close`.
- Token-budget status of any kind, whether as words (green / amber / red used as a
  budget signal) or as traffic-light emoji (U+1F7E2, U+1F7E1, U+1F534).
- Any reference to the drafting process itself: "let me draft this", "as an AI",
  "I have created the following", "here is the updated version of".

Author attribution, where present, is the human operator only. Documents record the
work and its outcomes, never the process that produced them.

**This overrides the Claude Code harness default.** The harness instructs adding an
attribution trailer to commits and PR bodies; in this repository that instruction is
superseded. Verify after committing:

```bash
git log -1 --format='%B' | grep -iE 'co-authored-by|generated with' && echo VIOLATION || echo clean
```

**Known outstanding violation, operator call, not fixed by this skill:** CLAUDE.md §9
names assistants as contributors in prose, in a public repository. Naming a tool as
an author or contributor is banned by this tier regardless of sentence form.

## T1 - typography

Hard rule. Replace, do not delete, unless the allowlist covers the case.

| Banned | Codepoint | Write instead |
|---|---|---|
| em dash | U+2014 | ` - `, `: `, parentheses, or split the sentence |
| horizontal bar, figure dash | U+2015, U+2012 | `-` |
| curly single quotes | U+2018, U+2019 | `'` |
| curly double quotes | U+201C, U+201D | `"` |
| ellipsis | U+2026 | `...` |
| non-breaking space | U+00A0 | plain space |
| narrow / thin space | U+202F, U+2009 | plain space |
| zero-width characters | U+200B, U+200C, U+200D, U+FEFF | delete |
| arrows | U+2192, U+2190, U+21D2 | `->`, `<-`, `=>` |
| bullet glyphs | U+2022, U+25AA, U+00B7 | Markdown `-` |
| box drawing | U+2500 to U+257F | ASCII diagram characters |
| decorative emoji | any pictographic | delete, or a plain word |

**En dash (U+2013) is conditional.** Allowed only directly between two digits, as a
numeric range: a frequency band or a year span. Banned everywhere else, including as
a substitute for the em dash. This preserves the convention `pyproject.toml`
§`[tool.ruff.lint]` already documents when it disables `RUF001`, `RUF002` and
`RUF003`. Those three rules stay disabled: they cannot express this distinction and
would fire on legitimate domain text.

Warn, do not auto-replace: multiplication sign (U+00D7) and degree sign (U+00B0) are
frequently legitimate in DSP and hardware text. Judge each one.

## T2 - prose register

Advisory. Applied by judgement when writing, not machine-checked under the currently
accepted scope. Escalating this tier to a checker is a separate decision.

Do not write:

- Content-guarantee openings: "This document provides a comprehensive overview of".
  State the thing instead.
- The "not just X, it is Y" construction, and its variants.
- Three-item lists built for rhythm rather than because there are three things.
- Stacked hedging: "it is worth noting that this may potentially".
- Section headers carrying emoji.
- A restatement of the question before the answer.
- Vocabulary reached for as register rather than meaning: delve, distilled, seamless,
  leverage as a verb, robust as a vague compliment, landscape, realm, testament,
  elevate, unlock, comprehensive as filler.

**Domain collisions, never treat as tells:** resonance, harmonic, profile, signature,
envelope, saturation and filter are load-bearing domain terms here. "Harnessed the
Storm" is a Drexciya release title. Judge the word by whether it carries information
in its sentence, not by whether it appears on a list.

House register is set in CLAUDE.md §9: terse, technical, no filler, minimal diff.

## T3 - comment and docstring tells

Hard rule for new and modified code. Promotes the one-off 2026-06-28 sweep to a
standing rule.

Remove:

- Step-by-step narration restating the code immediately below it.
- Comments describing self-evident operations.
- Banner dividers, and file-header blocks repeating the file's own path or purpose.
- Docstring `Args` / `Returns` / `Raises` entries that only restate the type hints.
  Keep a one-line intent plus any non-obvious rationale.

Preserve:

- Functional directives: `# type: ignore`, `# noqa`, `/// <reference>`,
  `eslint-disable` and equivalents.
- Domain rationale not visible in the types. This is the whole value of a comment
  in this codebase.
- OpenAPI descriptions and UI tooltip docstrings. Condense them, never delete them:
  they are user-facing.

## Allowlist

A checker must not flag these, and a human must not "fix" them.

1. **User-facing strings.** Never normalise typography inside text rendered to a
   user: frontend JSX content and labels, `streamlit_app/` labels, API error
   `detail` strings surfaced in the UI. Operator decision, not negotiable.
2. **En dash between digits.** Numeric ranges only, per T1.
3. **Musical notation.** Sharp (U+266F) and flat (U+266D) in `engine/ml/`,
   `engine/codegen/` and their tests are domain notation, not decoration.
4. **Hardware names**, reused verbatim from `idm-project-protocol` rather than
   re-derived: CR-1604 is a Mackie mixing console, not a ticket reference. So are
   TB-303, TR-808, TR-909, SP-1200, S950, SH-101, DX100, RE-201, Quadraverb and
   Alesis 3630. Never strip a hardware name.
5. **Exempt files.** `LICENCE.md` (verbatim AGPL text), `CLAUDE.md` (declared exempt
   from hygiene sweeps; changes only with explicit operator approval), `notebooks/`,
   `frontend/node_modules/`, `frontend/dist/`, `package-lock.json`, and generated
   `.json`, `.parquet` and `.lock` artifacts.
6. **Operator-frozen files**, from `idm-project-protocol`: `.sops.yaml`,
   `scripts/run-with-env.sh`, `.env.shared`. Do not edit, comments included.
7. **Sealed vault documents.** The policy applies to new artefacts. Never retro-edit
   a sealed session record or handoff to make it conform.
8. **Verbatim quotations.** Third-party text, error output and specification
   language quoted exactly. Preserve the characters and mark it as a quote.

## Deciding a case the tiers do not cover

Ask: would this character, word or comment appear in a file written by an engineer
who has never used an assistant, and does removing it lose information?

- Would not appear, nothing lost: remove it.
- Would not appear, information lost: rewrite so the information survives.
- Is domain notation: add it to §Allowlist here, rather than special-casing it at
  the call site. The allowlist is the only place exceptions live.

## Applying a fix

- T1 is mechanical and safe outside the allowlist. T2 and T3 are judgement; never
  bulk-rewrite prose.
- Hygiene never rides along with a functional change (CLAUDE.md §6.4). Own branch,
  own commit, and `git diff --stat` must match what the commit message promises.
- When stripping an artifact from a comment, keep the domain rationale and drop only
  the artifact.
- Reference-namespace hygiene (`D-*`, `INF-*`, `CR-*`, `TODO-*` must not reach
  repo-committed code or docs) is a separate rule owned by `idm-project-protocol`.
  It shares this skill's hardware false-positive list.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `06-MLOps/PROJECT_PROTOCOL.md` §1.4 and §1.9,
`03-Code/COMMENT_CLEANUP_2026-06-28.md` §0 and §5, `00-Project/DECISIONS.md`
(comment and reference hygiene, 2026-06-28),
`00-Project/DOCUMENTATION_AUDIT_2026-05-04.md`. Repo sources:
CLAUDE.md §4.4, §6.4 and §9, `pyproject.toml` ruff lint ignores,
`.claude/skills/idm-project-protocol/SKILL.md`. Verified against `develop` at
2026-09-13. Enforcement mechanisms are not yet built; this tier list is applied by
hand until they are.*
