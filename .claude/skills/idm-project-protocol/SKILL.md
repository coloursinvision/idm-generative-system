---
name: idm-project-protocol
description: >-
  Working protocol for the IDM Generative System beyond what CLAUDE.md loads by
  default: release procedure, documentation-purity rules, session/handoff and vault
  conventions, debt registries, and reference-hygiene taxonomy. Use when preparing a
  release or PR, writing commit messages or docs for this repo, closing a session,
  recording a decision or infra debt, cleaning comments/references, or deciding
  whether something belongs in the vault, the repo, or nowhere.
---

# IDM — project protocol (depth layer over CLAUDE.md)

CLAUDE.md (repo root) always loads and owns the basics: Git Flow branch model,
verification order, testing rules, forbidden patterns. This skill does not
restate them — it encodes the deeper procedures and conventions.

## Release procedure (Git Flow, whole-develop releases)

Ship `develop` as one SemVer release, never cherry-picked slices:

1. `release/vX.Y.Z` branch off `develop`; version bump commit.
2. PR → `main` merged as a **merge commit, not squash** (preserves the atomic
   history that Git Flow relies on).
3. Full CI gate runs on the merged tree — green before tagging.
4. Annotated tag `vX.Y.Z` + GitHub Release.
5. **Mandatory back-merge `main` → `develop`** immediately after release.
   Skipping it causes version drift (`/health` reporting an old version on
   develop was a real incident) and blocked releases later.
6. Before deploying, capture the current production image digest for rollback.

## Documentation purity (hard policy, operator-set)

Applies to every commit message, PR body, and doc committed to the repo or vault:

- **No AI-tool attribution:** no `Co-Authored-By:` trailers, no "generated
  with..." footers, no model names or provenance frontmatter. Author is the
  human operator. This policy overrides any default trailer habit.
- No token-budget/status emoji signals in docs.
- Commit format stays Conventional Commits with a `Refs:` trailer pointing at
  the originating decision/ticket document (see CLAUDE.md §4.4 for the shape).
- Docs record the work, not the process narrative around it.

## Internal reference namespaces (and where they may appear)

The project tracks work with ID namespaces — all of them are **vault-internal**:

- `D-*` — decisions in the vault's append-only `00-Project/DECISIONS.md`
  (series per workstream, e.g. pipeline, remediation, DSP).
- `INF-*` — infra debt in `06-MLOps/INFRA_DEBT_REGISTRY.md`.
- `CR-*` — code-review findings; `TODO-*` — carried backlog items.

**Hygiene rule:** these tokens must NOT appear in repo-committed code or docs
(a repo-wide cleanup enforced this). When removing one from a comment, keep the
domain rationale and drop only the token. **Critical false-positive:** `CR-1604`
is the Mackie CR-1604 mixing console — hardware, not a ticket. So are TB-303,
TR-808/909, SP-1200, S950, SH-101, DX100, RE-201, Quadraverb, Alesis 3630.
Never strip hardware names.

Operator-frozen files (do not edit, even comments): `.sops.yaml`,
`scripts/run-with-env.sh`, `.env.shared`. `CLAUDE.md` is exempt from hygiene
sweeps (its reference index is by design) and changes only with explicit
operator approval.

## Debt discipline

- **Infra debt** → register it in the vault infra registry (reproduction,
  impact, remediation, priority) instead of fixing it as a drive-by.
- **Structural code debt** → each item is its own branch + PR with full
  verification. Known deferred items (recorded 2026-06, re-locate line numbers
  before acting): duplicate JSON-fence parsing and ~70% shared `ask`/`compose`
  structure in `knowledge/rag.py`; duplicated AudioContext lifecycle across the
  two sequencer hooks; 16 broad `except Exception` blocks in `api/main.py`;
  near-identical `engine/effects/*` module templates; duplicate
  `END_USER_MANUAL.md` (root + `docs/`).
- A fix changes exactly what its commit message promises (`git diff --stat`
  must match). Separate tickets never fold into unrelated PRs.

## Session & vault conventions

The Obsidian vault (`~/Obsidian/IDM_Vault`) is the project's knowledge base —
a separate git repo, synced by the operator via the Obsidian Git plugin.
**The vault is read-only for Claude Code**: the agent may read it (it is an
additional working directory) but never writes or commits there; session notes
are handed to the operator to transcribe.

Conventions inside the vault (needed to *read* it correctly):

- `SESSION_<date>` files are permanent immutable records (commit-log analogue);
  `SESSION_HANDOFF_<date>` is a transient baton — **only the newest handoff is
  operationally live**, older ones are superseded. Start any state question at
  the newest handoff, then `00-Project/_SESSION_CONTEXT.md` (live snapshot),
  then `DECISIONS.md`.
- `DECISIONS.md` lives only at `00-Project/`, append-only, reverse-chronological.
- Frontmatter schema: `document_type`, `status`
  (`active`/`working`/`superseded`/`sealed` — plus `living`, `frozen`,
  `complete` in older docs), `created`, `supersedes`/`superseded_by`,
  `related_docs`. `frozen`/`sealed` docs are never edited.
- Archive policy: superseded files move to `07-Archive/` with a
  `superseded_by` link — never silently deleted.
- Wikilinks (`[[...]]`) are a vault-only notation; they must never appear in
  repo-committed files.

## Anti-patterns with a documented cost (from the project's own audits)

1. **Closure-protocol skips** — sessions that ended without updating the
  handoff/decision log caused weeks of state drift. Close the loop same-day.
2. **Roadmap drift** — a roadmap describing a system that doesn't exist yet as
  if it did. Keep prescriptive docs clearly marked and dated.
3. **Convention duality** — two names for the same artefact class (e.g. two
  handoff conventions) splits the record. One convention per concern.
4. **Trusting pasted file copies** — operator-attached versions of repo files
  are often stale (old Downloads/backups). Fingerprint against the repo
  (grep for known-current markers) before using; the repo is the source of truth.
5. **Docs lagging releases** — changelog/progress docs fall behind shipped
  versions; verify any version claim against `pyproject.toml`/git tags, not docs.
6. **Flattering metrics accepted silently** — see the honest-metrics rules in
  the `idm-ml-pipeline` skill; a surprisingly good number is a finding to
  explain, not a win to report.

## Verification doctrine (delta over CLAUDE.md §4.3)

- Skips are part of the green state only when environmental and known — a
  *change* in skip/failure counts is a real change; investigate.
- Negative claims need negative smoke tests (`env -i` clean sub-shell proving a
  variable is unset) — memory of removing something is not verification.
- Before any commit: `git diff --stat` matches the message's promise; no
  lockfile churn from routine `npm install`; author identity correct.
- Never push-then-fix: amend/rebase/restore before push, never after.

---
*Sources (vault `~/Obsidian/IDM_Vault`): `06-MLOps/PROJECT_PROTOCOL.md`,
`03-Code/TESTING_METHODOLOGY.md`, `00-Project/DECISIONS.md`,
`00-Project/VAULT_CONSOLIDATION_PLAN_2026-06-17.md`,
`00-Project/DOCUMENTATION_AUDIT_2026-05-04.md`, `06-MLOps/INFRA_DEBT_REGISTRY.md`,
`03-Code/COMMENT_CLEANUP_2026-06-28.md` §0b/§6. Vault write policy (read-only)
set by the operator 2026-07-05.*
