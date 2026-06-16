# CLAUDE.md

> **Persistent project context for Claude Code.**
> This file is the canonical bootstrap for any Claude (chat or Claude Code) working
> on this repository. It is committed to the root of `coloursinvision/idm-generative-system`
> and read automatically by Claude Code on session start.
>
> **Branch context:** This repository hosts the **CR-F13 production branch** of the
> IDM Generative System. This file's rules apply to all work on this branch; general
> development rules for other projects do not override these.
>
> **Last update:** 2026-05-29 (post-Dropbox migration; SOPS+age secrets architecture
> live; vault separated to `coloursinvision/idm-obsidian-vault`).

---

## 1. Project overview

IDM Generative System is a production-grade application that combines a Vite+React 18 frontend (interactive audio sequencer guides for Teenage Engineering PO-33 and EP-133 devices) with a FastAPI backend (regional profile lookup, Qdrant vector search, OpenAI generation, Langfuse tracing, MLflow tracking). The repository is currently in the **CR-F13 production branch** after an off-Dropbox migration completed on 2026-05-29.

The single source of truth for code is GitHub. The Obsidian vault (architectural decisions, session handoffs, methodology records) lives in a separate repository `coloursinvision/idm-obsidian-vault`. Operational runbooks live outside both repos, on an external SSD.

---

## 2. Commands

All commands are listed assuming the current working directory is the repo root unless stated otherwise.

### 2.1 Frontend (Vite + React 18 + TypeScript)

```bash
cd frontend
npm install              # one-time per machine; idempotent thereafter
npm run dev              # dev server on localhost:5173 with HMR + proxy to localhost:8000
npm run build            # production bundle to frontend/dist/
npx tsc --noEmit         # type check only (no emit)
npx vitest run           # unit tests (expected: 57/57 at 2026-05-29)
npx vitest               # watch mode
```

### 2.2 Backend (FastAPI + Python 3.11 in conda env `idm`)

All backend commands that touch application credentials must run through the wrapper:

```bash
conda activate idm

# Boot the API server with credentials loaded
./scripts/run-with-env.sh uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Run tests requiring credentials at collection time (anything importing api.main)
./scripts/run-with-env.sh pytest tests/test_api.py

# Run tests that don't touch credentials (pure-function suites)
pytest tests/test_regional_profiles.py
# expected: 29 passed, 2 skipped

# Type check
mypy engine api
# expected: Success: no issues found in 31 source files
```

### 2.3 The wrapper itself

`./scripts/run-with-env.sh <command>` is the canonical entry point for any process that needs application credentials. It:
1. Sources `.env.shared` (plaintext non-secrets, committed).
2. Decrypts `secrets/app.enc.yaml` via SOPS to a mode-600 tmp file.
3. Sources the decrypted file.
4. Exports boto3 aliases (`AWS_ACCESS_KEY_ID = DO_SPACES_KEY`, `AWS_SECRET_ACCESS_KEY = DO_SPACES_SECRET`).
5. `exec`s the command. On exit (any cause), a trap removes the tmp file.

If the wrapper exits with `OSError: OPENAI_API_KEY not set`, the cause is one of: `SOPS_AGE_KEY_FILE` not set, key file at wrong path, key file corrupt. Diagnose at the wrapper, not at the consumer.

### 2.4 Smoke test in a clean sub-shell

The canonical "does it work outside my interactive shell" check:

```bash
env -i \
  HOME="$HOME" \
  PATH="/usr/bin:/bin:/usr/local/bin:$HOME/miniconda3/envs/idm/bin" \
  SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt" \
  bash -c 'cd ~/dev/IDM_Generative_System_app && \
           ./scripts/run-with-env.sh pytest tests/test_api.py --collect-only'
# expected: 23 tests collected in N.NNs
```

If this fails on a new machine, the provisioning is incomplete. See `RUNBOOK_NEW_LINUX_STATION.md` (outside vault) for full setup.

---

## 3. Architecture (one-paragraph orientation)

The frontend is a Vite+React SPA that proxies `/api/*` requests during dev to the FastAPI backend; in production the backend serves the SPA from `STATIC_DIR` and routes `/api/*` to its own endpoints. Audio handling lives in `frontend/src/hooks/useSequencer.ts` (the file CR-F13 remediates) and is consumed by `frontend/src/components/guide/PO33Guide.tsx` and `EP133Guide.tsx`. Frontend tests live in `frontend/src/tests/<module>/` (central tree, not co-located) per `[[DECISIONS#D-CRF13-02]]`. Backend modules: `api/main.py` (FastAPI app + route registration), `engine/*` (business logic including ML feature engineering), `tests/` at repo root. Secrets architecture: encrypted-as-code (SOPS+age) for credentials in `secrets/app.enc.yaml`, plaintext committed for non-secrets in `.env.shared`, loaded via `scripts/run-with-env.sh`. The age private key is per-machine at `~/.config/sops/age/keys.txt` with iCloud Keychain backup; the public key `age1ulhtjzwwt8raewsmnlkmg4glwwafyfpr3mp4qq8488qc9l9lve2sz6a8wz` is declared in `.sops.yaml`.

---

## 4. Conventions

### 4.1 TypeScript

- **Strict mode is non-negotiable.** No `any`, no `// @ts-ignore` without an accompanying issue reference.
- Constructor mocks in tests: **`function` expression**, never arrow. Arrow functions have no `[[Construct]]` and crash with `TypeError: ... is not a constructor`. Pattern:
  ```typescript
  vi.stubGlobal(
    "AudioContext",
    vi.fn(function (this: unknown) { return currentMockCtx; }),
  );
  ```
- Tests live in central tree `frontend/src/tests/<module>/`. Import source via `../../<module>/...`. Do not co-locate test files beside source files.

### 4.2 Python

- conda env `idm` (Python 3.11). Bootstrap via `pip install -e ".[dev,ml,monitoring]"` from `pyproject.toml`.
- mypy must pass on `engine` and `api` for every commit that touches them.
- pytest convention: tests under `tests/` at repo root, fixtures in `tests/conftest.py`. Skips are part of the green state when they reflect environmental dependencies (e.g. vault-path tests skip when vault is at `~/Obsidian/IDM_Vault` rather than project-internal).

### 4.3 Verification order (cheap before expensive)

For every change:
1. `tsc --noEmit` (frontend) or `mypy engine api` (backend) — fastest static check.
2. Unit tests for the changed module.
3. Full suite — catches cross-module regression.
4. Build (`npm run build`) or backend boot — production-build sanity.
5. Real-browser AC for frontend, manual smoke for backend — when applicable.

Stop on first failure. Do not push past a red check.

### 4.4 Git workflow

- **Branch model:** Git Flow. `develop` is the integration branch; `main` is release.
- **Branch names:** `fix/<ticket>-<slug>`, `chore/<scope>-<slug>`, `feat/<scope>-<slug>`.
- **Commit messages:** Conventional Commits with `Refs:` trailer pointing to the originating decision / ticket / document:
  ```
  fix(useSequencer): handle Safari/WebKit AudioContext lifecycle

  - Add AudioContext suspended-state recovery on page load.
  - Wire unlockAudioContext() to first user gesture.
  - Cover lifecycle transitions with 9-case vitest suite.

  Refs: 03-Code/CR-F13_REMEDIATION_2026-05-28.md
  Refs: 00-Project/DECISIONS.md#D-CRF13-02
  ```
- **Atomic commits:** each commit must build and pass tests on its own. Never fabricate atomic history that fails at intermediate states.
- **Lockfile discipline:** `package-lock.json` changes from `npm install` are NOT committed unless intentional. Phantom shrinkage from Node-version drift between local and CI is the canonical example (see [[INFRA_DEBT_REGISTRY#INF-E]]).
- **Never push-then-fix.** Use `git rebase --reset-author --committer-date-is-author-date`, `git update-index --chmod=-x`, `git restore`, `git commit --amend` BEFORE push. Once pushed, history rewrite has team impact.

### 4.5 Secrets and credentials

**Three-tier classification.** Every environment value falls into exactly one tier:

1. **Root of trust** — age private key at `~/.config/sops/age/keys.txt`. NEVER in Git, NEVER in sync clouds.
2. **Encrypted secrets** — `secrets/app.enc.yaml`. API keys, service tokens. Committed encrypted. Six values: `OPENAI_API_KEY`, `QDRANT_API_KEY`, `DO_SPACES_KEY`, `DO_SPACES_SECRET`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
3. **Shared non-secrets** — `.env.shared`. URLs, bucket names, region IDs. Committed plaintext. Six values: `QDRANT_URL`, `DO_SPACES_BUCKET`, `DO_SPACES_ENDPOINT_URL`, `MLFLOW_TRACKING_URI`, `MLFLOW_S3_ENDPOINT_URL`, `LANGFUSE_HOST`.

**Decision rule for new variables:** "If this value leaked to a public repo right now, would I rotate it at the provider?" Yes → tier 2 encrypted. No → tier 3 plaintext.

**Operations:**
```bash
sops secrets/app.enc.yaml                                    # edit (opens $EDITOR on decrypted content)
sops --decrypt --extract '["openai_api_key"]' secrets/app.enc.yaml  # read one value
sops updatekeys secrets/app.enc.yaml                         # re-encrypt after recipient change
```

See `03-Code/SECRETS_ARCHITECTURE_2026-05-29.md` (in the vault) for the full architecture record.

---

## 5. Testing (rules that must not be relaxed)

### 5.1 Constructor mocks — function form, not arrow

The most common source of vitest failures in this codebase. See §4.1 above.

### 5.2 Central tests tree

New tests go in `frontend/src/tests/<module>/`. The codegen tests (`frontend/src/tests/codegen/codegen.test.tsx`, 48 cases) and the hook tests (`frontend/src/tests/hooks/useSequencer.test.ts`, 9 cases) are the canonical examples.

### 5.3 Wrapper for credentialed tests

Tests that import modules which read credentials at collection time (`api.main` and anything that triggers eager OpenAI/Qdrant/Langfuse client construction) MUST run through `./scripts/run-with-env.sh pytest ...`. Tests that don't touch credentials run without the wrapper. The distinction is import-time dependency.

### 5.4 Skips are not failures

`tests/test_regional_profiles.py` reports `29 passed, 2 skipped` at 2026-05-29. The 2 skips are intentional (vault-path tests that skip on machines with `~/Obsidian/IDM_Vault` outside the project). A change in skip count is a real change — investigate, don't ignore.

### 5.5 Negative smoke tests for negative claims

"This file no longer exports secrets" requires a clean sub-shell assertion that the variables are `(unset)`. Trusting memory is not verification. Pattern in `03-Code/TESTING_METHODOLOGY.md` §6.5.

---

## 6. Forbidden — patterns that re-introduce eliminated failure modes

These cost real time before. Each is a hard rule on this branch.

### 6.1 No file-sync clouds anywhere near the working tree

- Working tree path is `~/dev/IDM_Generative_System_app`. Never under Dropbox (eliminated), iCloud Drive, OneDrive, Google Drive, Syncthing, or `~/Library/Mobile Documents/`.
- The Obsidian vault is at `~/Obsidian/IDM_Vault`, also non-synced — sync is via the Git plugin, not via a watcher.
- If `npm install` fails with `TAR_ENTRY_ERROR` or `ENOENT`, suspect a re-introduced watcher. Diagnose; do not work around.

### 6.2 No application secrets in shell init

`~/.zshrc` / `~/.bashrc` exports `SOPS_AGE_KEY_FILE` (a pointer) and nothing else credential-related. Adding `export OPENAI_API_KEY=...` back to shell init re-introduces every problem the 2026-05-29 migration solved.

### 6.3 No wrapper bypass

Do not invoke `uvicorn`, `pytest tests/test_api.py`, or `python -m api.main` directly without `./scripts/run-with-env.sh`. The expected `OSError` is a feature, not a bug — it enforces the canonical loading path.

### 6.4 No drive-by changes mixed into a bugfix

A fix changes exactly what its commit message says it changes. `git diff --stat` for any commit must match the commit message's promise. Opportunistic refactors, drive-by formatting, unrelated dependency bumps — each gets its own commit (or its own PR if they're substantial).

### 6.5 No trust of pasted file copies

When the operator says "use this version of `useSequencer.ts`" and attaches it, do not trust it as authoritative. Verify against what's on disk in the repo:

```bash
# Fingerprint check (canonical example: post-CR-F13 useSequencer test)
grep -n 'from "\.\./\.\./hooks/useSequencer"' frontend/src/tests/hooks/useSequencer.test.ts \
  && echo "OK: central-tree import"

grep -n 'vi.fn(function (this: unknown)' frontend/src/tests/hooks/useSequencer.test.ts \
  && echo "OK: function-form mock" || echo "WARN: arrow mock or missing"
```

Pasted files from old folders (Downloads, prior backups) are often stale relative to the repo. The repo is the source of truth.

### 6.6 No running ahead step-by-step without confirmation

On multi-step changes (migrations, refactors spanning files, dependency updates), pause after each step and report state before proceeding. Do not chain N commands and announce results post-hoc.

### 6.7 No folding separate tickets into unrelated fixes

T-A (`/api` prefix mismatch) and T-B (backend 500) are **separate tickets**. They are NOT to be addressed inside a CR-F13 audio fix commit, a SOPS PR, or any other unrelated change. Each gets its own feature branch.

### 6.8 The age private key has exactly two allowed locations per machine

`~/.config/sops/age/keys.txt` on the machine itself (mode 600) and the iCloud Keychain note `IDM age private key (SOPS secrets master)`. Nowhere else. Not in Git, not in cloud docs, not in email, not in `/tmp`, not in a sync folder. Not "for a moment."

### 6.9 No stray writes — project root and system disk are off-limits

Claude Code MUST NOT create, write, or save any file in the **project root directory** or anywhere else **on the system disk** — explicitly including ephemeral, scratch, planning, hand-off, or generated documents. The **only** permitted location for such artifacts is `~/Downloads/`, and **only after explicit operator confirmation for that specific write**. Never write first and ask later.

This does not block the version-controlled source work an approved task requires — editing existing tracked files, or adding new source files inside their proper subdirectory (`engine/`, `frontend/src/…`, `tests/`), committed via the Git Flow in §4.4. It forbids depositing ephemeral or stray files into the repo root or scattering them across the system disk. The project root is never a scratch space. When in doubt, ask before writing.

---

## 7. References (where the canonical documents live)

### 7.1 In the vault `~/Obsidian/IDM_Vault/`

- `00-Project/DECISIONS.md` — every architectural decision (D-CRF13-01 through D-CRF13-08 are current)
- `03-Code/CR-F13_REMEDIATION_2026-05-28.md` — the active remediation document; §8 has 2026-05-29 updates
- `03-Code/MIGRATION_LOG_2026-05-29.md` — chronological detail of the 2026-05-29 migration
- `03-Code/SECRETS_ARCHITECTURE_2026-05-29.md` — secrets layer architectural reference
- `03-Code/TESTING_METHODOLOGY.md` — test conventions and verification techniques
- `05-HANDOFFS/SESSION_HANDOFF_2026-05-29.md` — state at last session close
- `06-MLOps/INFRA_DEBT_REGISTRY.md` — known infra debt (INF-A through INF-I)

### 7.2 Outside the vault (operational runbooks)

Located at `/Volumes/StorageGo/Downloads/Downloads GO/Dropshit_Migration/` on the operator's Mac (path may differ on Linux):

- `MIGRATION_RUNBOOK_cloud-to-git.md` — umbrella migration procedure (Mac complete)
- `SOPS_AGE_RUNBOOK.md` — secrets bootstrap procedure
- `RUNBOOK_NEW_LINUX_STATION.md` — Linux workstation provisioning
- `NEXT_SESSION_BOOTSTRAP_2026-05-30.md` — opening for the next session

### 7.3 External

- age — https://github.com/FiloSottile/age (v1.3.1)
- SOPS — https://github.com/getsops/sops (v3.13.1)
- Obsidian Git plugin — community plugin in vault

---

## 8. Session ground rules (what to do when opening a session)

1. **Read first**: `05-HANDOFFS/SESSION_HANDOFF_2026-05-29.md` (or the most recent handoff), then `03-Code/MIGRATION_LOG_2026-05-29.md` (or relevant log), then `00-Project/DECISIONS.md` for the current decision set.
2. **Verify state**: `git status` in `~/dev/IDM_Generative_System_app` (clean), `echo $SOPS_AGE_KEY_FILE` (set), `sops --decrypt secrets/app.enc.yaml >/dev/null && echo OK` (works).
3. **Confirm scope**: ask the operator which scope is in play for this session (CR-F13 finish, Linux provisioning, infra debt, etc.).
4. **One step at a time**: pause after each substantive change to report state before proceeding.
5. **Stop conditions**: if a fix would require editing files outside the current ticket's scope, if a tool produces unexpected output, if the operator gives "STOP" — halt and ask, do not proceed.

---

## 9. Identity and authorship

Operator: **Tom Boro** — `coloursinvision@outlook.com` — GitHub `coloursinvision`.

The operator works in Polish; technical writing (code, docs, commit messages, PRs, this file) is in English. Standards: **INDUSTRIAL GRADE PRO** (terse, verify-before-act, minimal diff, no scope creep, atomic commits, Conventional Commits with `Refs:` trailer).

Multiple AI assistants have contributed to this repository. The 2026-05-28 CR-F13 remediation and the 2026-05-29 migration were executed by Claude (Anthropic), Opus 4.7 family. Future sessions should reference and extend that work, not restart from scratch.

---

## 10. Last words

This file is the boundary between "Claude knows this project" and "Claude doesn't yet". If something contradicts this file, this file wins until updated. If this file is silent on something, default to the standards in `03-Code/SECRETS_ARCHITECTURE_2026-05-29.md`, `03-Code/TESTING_METHODOLOGY.md`, and the most recent `05-HANDOFFS/SESSION_HANDOFF_*.md`.

When in doubt: ask. Never push past a red check. Never invent.
