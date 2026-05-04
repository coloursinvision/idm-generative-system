"""Validate synthetic dataset against pandera schema via DVC pipeline.

CLI entry point for the ``validate`` stage in ``dvc.yaml``.
Reads the parquet file produced by the ``generate`` stage and validates
it against :data:`DATASET_SCHEMA`. Writes a JSON validation report to
``data/synthetic/validation_report.json`` (DVC metric).

Usage:
    python scripts/validate_schema.py            # standalone
    dvc repro validate                            # via DVC pipeline

Exit codes:
    0 — validation passed
    1 — validation failed (SchemaError details in report + stderr)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import pandera.errors

from engine.ml.dataset_schema import DATASET_SCHEMA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INPUT_PATH = Path("data/synthetic/dataset.parquet")
_REPORT_PATH = Path("data/synthetic/validation_report.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Load parquet, validate schema, write report."""
    if not _INPUT_PATH.exists():
        logger.error("Input file not found: %s", _INPUT_PATH)
        sys.exit(1)

    logger.info("Loading dataset from %s", _INPUT_PATH)
    df = pd.read_parquet(_INPUT_PATH, engine="pyarrow")
    logger.info("Loaded: %d rows × %d columns", len(df), len(df.columns))

    t0 = time.monotonic()
    report: dict[str, object] = {
        "input_path": str(_INPUT_PATH),
        "n_rows": len(df),
        "n_columns": len(df.columns),
        "columns": list(df.columns),
    }

    try:
        DATASET_SCHEMA.validate(df, lazy=True)
        elapsed_ms = (time.monotonic() - t0) * 1000
        report["status"] = "passed"
        report["errors"] = []
        report["validation_ms"] = round(elapsed_ms, 2)
        logger.info("Schema validation PASSED (%.1f ms)", elapsed_ms)

    except pandera.errors.SchemaErrors as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        report["status"] = "failed"
        report["validation_ms"] = round(elapsed_ms, 2)

        # Extract structured error details for the DVC metric.
        error_cases = exc.failure_cases
        errors: list[dict[str, object]] = []
        for _, row in error_cases.iterrows():
            errors.append(
                {
                    "schema_context": str(row.get("schema_context", "")),
                    "column": str(row.get("column", "")),
                    "check": str(row.get("check", "")),
                    "check_number": (
                        int(row["check_number"]) if pd.notna(row.get("check_number")) else None
                    ),
                    "failure_case": str(row.get("failure_case", "")),
                    "index": str(row.get("index", "")),
                }
            )

        report["errors"] = errors
        report["n_errors"] = len(errors)

        logger.error(
            "Schema validation FAILED: %d error(s) (%.1f ms)",
            len(errors),
            elapsed_ms,
        )
        for err in errors[:10]:
            logger.error(
                "  Column '%s' check '%s': %s",
                err["column"],
                err["check"],
                err["failure_case"],
            )
        if len(errors) > 10:
            logger.error("  ... and %d more errors", len(errors) - 10)

    # --- Write report (DVC metric) ---
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _REPORT_PATH.open("w") as f:
        json.dump(report, f, indent=2)
    logger.info("Validation report written to %s", _REPORT_PATH)

    if report["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
