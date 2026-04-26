# engine/ml — Knowledge-Informed ML Pipeline (Layers 3–5)

## Spoke-as-source-of-truth rule

Profile and resonance rule values live in the Obsidian vault markdown spokes:

    02-Knowledge/supporting/profiles/*.md    (6 regional profile spokes)
    02-Knowledge/supporting/resonance/*.md   (5 resonance rule spokes)

Python modules in this package **load** values from the spokes at runtime. They **never** duplicate or hard-code spoke-derived values in `.py` files, except as cached parse output from `load_profile()`.

If a value appears in a spoke and also as a literal in Python code, the Python literal is a spec violation and must be removed. The spoke is always authoritative.

### What this means in practice

- `regional_profiles.py` parses spoke YAML via `python-frontmatter` + `pydantic` and produces frozen `RegionalProfile` dataclasses. Adding a new DSP field means updating the spoke first, then the `_DSPSpecModel` validator, then the composed dataclass.
- `resonance_rules.py` implements the five rule signatures from the resonance spokes. Constants like `SCHUMANN_MODES_HZ` and `SOLFEGGIO_HZ` are transcribed from their respective spoke documents and are the only permitted hard-coded values in this package (they are physical or editorial constants, not profile-derived parameters).
- `deterministic_mapper.py` (Layer 3) consumes both modules and produces `DeterministicMapping` outputs. It does not contain any profile or rule values.
- `gaussian_noise.py` (Layer 4) perturbs deterministic outputs without introducing new values.
- `dataset_generator.py` (Layer 5) composes Layers 3 and 4 into a `pandas.DataFrame` for downstream training.

### Path resolution

The profile spoke directory is resolved via the `IDM_VAULT_PATH` environment variable. If unset, the loader assumes the vault is a sibling directory `IDM_Obsidian` adjacent to the repo root. Tests override this by passing `profiles_dir=` directly.

## Public API

The package exposes 36 symbols via `__init__.py`. See the module docstring in `__init__.py` for the full list grouped by layer.

## Module dependency graph

```
resonance_rules.py          ← pure functions, no I/O
       ↓
regional_profiles.py        ← spoke parser, @cache memoised
       ↓
deterministic_mapper.py     ← Layer 3: scene → DSP targets
       ↓
gaussian_noise.py           ← Layer 4: calibrated perturbation
       ↓
dataset_generator.py        ← Layer 5: synthetic DataFrame
```

## Testing

Tests live in `tests/` at the repo root (per D-S3-08):

- `tests/test_regional_profiles.py` — spoke parsing, validation, Osaka override
- `tests/test_resonance_rules.py` — 12 doctests + unit tests
- `tests/test_deterministic_mapper.py` — 45+ integration tests, all 6 regions
- `tests/test_gaussian_noise.py` — 42 unit tests, reproducibility, clamping
