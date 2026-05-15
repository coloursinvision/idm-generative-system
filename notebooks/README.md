# notebooks/

Jupyter notebooks for **documentation, demos, and exploration** in the IDM Generative System.

## Pattern: literate documentation, not source of truth

Notebooks here follow **Pattern A — notebooks-as-documentation**. They are *consumers* of `engine/`, not *definers* of logic. Production code lives in `engine/`, `api/`, and `knowledge/` — never in notebooks.

### Allowed in notebooks

- Worked examples showing how to use functions from `engine.*`
- Visualisations of pattern matrices, audio waveforms, ML feature distributions
- Experiment runners that orchestrate calls into engine + log results
- Onboarding / educational walkthroughs for new contributors

### Not allowed in notebooks

- Function definitions that should live in `engine/` (use `from engine.X import Y` instead)
- Logic referenced from `api/`, `dvc.yaml`, or production code paths
- Hard-coded paths to local data — use `params.yaml` config or env vars
- Committed cell outputs (use nbstripout — see below)

If you find yourself defining a non-trivial function inside a notebook and considering reusing it elsewhere, **stop and refactor it into `engine/`** first. Then import it back into the notebook.

## Authoritative imports

Notebooks should import from the package, not redefine:

```python
# ✓ Good
from engine.generator import euclidean_rhythm, generate_pattern
from engine.sample_maker import glitch_click, noise_burst, fm_blip
from engine.effects import EffectChain

# ✗ Bad — copies logic out of single source of truth
def euclidean_rhythm(k, n):
    pattern = [1] * k + [0] * (n - k)
    # ...
```

If you need a one-off helper for visualisation (e.g., `plot_pattern(df)` matplotlib wrapper), defining it inline in the notebook is fine — that is exploration tooling, not production logic.

## Output hygiene — strip before commit

Notebook outputs (cell results, plot PNGs, DataFrame HTML) bloat the diff and the repo. Strip them at commit time:

**Recommended:** install [`nbstripout`](https://github.com/kynan/nbstripout) as a git filter:

```bash
pip install nbstripout
nbstripout --install
```

After this, every `git commit` automatically strips outputs from staged `.ipynb` files. The working copy keeps outputs (you still see them in Jupyter), but the committed version is clean.

**Manual alternative** (one-shot strip):

```bash
jupyter nbconvert --clear-output --inplace notebooks/your_notebook.ipynb
```

## Folder layout

```
notebooks/
├── README.md          ← this file
└── archive/           ← historical/genesis artefacts (read-only reference)
    └── exploration_2026-02-03_pattern_genesis.ipynb
```

The top-level `notebooks/` directory is intentionally minimal. Active demo notebooks land here; pre-V1 genesis artefacts that document project history live under `archive/`.

## Archive policy

Files in `notebooks/archive/` are **not authoritative reference for current work**. They preserve design lineage (early prototypes, abandoned approaches, visual records of bug-then-fix evolution). Authoritative production code lives in `engine/` and elsewhere.

Naming convention for archived notebooks: `<purpose>_<YYYY-MM-DD>_<short-descriptor>.ipynb` (e.g., `exploration_2026-02-03_pattern_genesis.ipynb`).

Disposition principle adapted from vault `DECISIONS.md` D-S9-02 (vault-to-archive rule for code-equivalent files), applied here to repo notebooks. See vault `07-Archive/idm_project_01_genesis_2026-02-03.ipynb` for cross-domain counterpart.

## Running notebooks

Notebooks expect the `idm` conda environment with `[ml]` extras installed:

```bash
conda activate idm
jupyter lab
```

Repository conventions (Python version, dependencies, formatting) are specified in `pyproject.toml` and `environment.yml` at the repo root.
