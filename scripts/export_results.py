#!/usr/bin/env python3
"""Export evaluation records to results/results.csv and results/results.xlsx.

Input is the JSON Lines file written by ``scripts/evaluate_models.py``. The CSV
is produced with the standard library; the Excel workbook needs ``openpyxl``
and is skipped with a warning if that package is not installed.

When no records exist yet, both files are written with headers only — the
script never invents rows.

Usage
-----
    python scripts/export_results.py
    python scripts/export_results.py --no-xlsx
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("export_results")


def _rel(path: Path) -> str:
    """Return ``path`` relative to the project root, or as given if outside it.

    Destination paths come from the command line and may be relative or point
    outside the project, so this must never raise.
    """
    try:
        return str(path.resolve().relative_to(cfg.PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_records(source: Path) -> List[Dict[str, Any]]:
    """Read evaluation records from a JSON Lines file.

    A missing file yields an empty list, so a fresh project exports an empty
    table rather than failing.
    """
    if not source.is_file():
        LOGGER.warning("No records file at %s — exporting headers only.", source)
        return []

    records: List[Dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                LOGGER.error("%s:%d is not valid JSON: %s", source, line_number, exc)
    return records


def to_rows(records: List[Dict[str, Any]]) -> List[List[Any]]:
    """Project records onto the fixed column order of the result schema."""
    return [[record.get(column) for column in cfg.RESULT_COLUMNS] for record in records]


def write_csv(rows: List[List[Any]], destination: Path) -> None:
    """Write the result table as CSV, including the header row."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(cfg.RESULT_COLUMNS)
        writer.writerows(rows)
    LOGGER.info("Wrote %d row(s) to %s", len(rows), _rel(destination))


def write_xlsx(rows: List[List[Any]], destination: Path) -> bool:
    """Write the result table as an Excel workbook. Return ``False`` if skipped."""
    try:
        from openpyxl import Workbook
    except ImportError:
        LOGGER.warning(
            "openpyxl is not installed — skipping %s. Install it with: pip install openpyxl",
            destination.name,
        )
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "results"
    sheet.append(cfg.RESULT_COLUMNS)
    for row in rows:
        sheet.append(row)
    workbook.save(destination)
    LOGGER.info("Wrote %d row(s) to %s", len(rows), _rel(destination))
    return True


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", type=Path, default=cfg.RESULTS_JSONL,
        help="JSONL file produced by scripts/evaluate_models.py.",
    )
    parser.add_argument("--csv", type=Path, default=cfg.RESULTS_CSV, help="CSV destination.")
    parser.add_argument("--xlsx", type=Path, default=cfg.RESULTS_XLSX, help="XLSX destination.")
    parser.add_argument("--no-xlsx", action="store_true", help="Skip the Excel export.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    records = load_records(args.source)
    rows = to_rows(records)

    write_csv(rows, args.csv)
    if not args.no_xlsx:
        write_xlsx(rows, args.xlsx)

    LOGGER.info("--- summary ---")
    LOGGER.info("records exported : %d", len(rows))
    LOGGER.info("expected total   : %d", cfg.EXPECTED_MODEL_COUNT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
