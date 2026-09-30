#!/usr/bin/env python3
"""Structural checks on the V1-V4 description variants.

This is a lightweight companion to ``validate_dataset.py``, meant to be run
once the variant-writing step has produced V1-V4. It checks structure only —
whether the files exist, are non-empty, are valid UTF-8, and differ from each
other and from the baseline.

It deliberately does **not** judge whether a transformation is semantically
correct; that is out of scope at this stage.

By design it reads only ``data/<case_id>/V0..V4.txt``. It never touches
``reference_models/``, so it can be run during the variant-writing stage
without exposing the ground truth.

Usage
-----
    python scripts/validate_variants.py
    python scripts/validate_variants.py --strict          # require all variants
    python scripts/validate_variants.py --case AirTravel  # limit to one case
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("validate_variants")


class Findings:
    """Collects errors and warnings produced during validation."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, message: str) -> None:
        """Record a defect in a populated variant."""
        self.errors.append(message)

    def warn(self, message: str) -> None:
        """Record a variant that is not populated yet."""
        self.warnings.append(message)


def _read_text(path: Path) -> Optional[str]:
    """Return the UTF-8 contents of ``path``, or ``None`` if undecodable."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def check_case_variants(case_id: str, findings: Findings, *, strict: bool) -> None:
    """Validate the V1-V4 files of one case against V0."""
    baseline_path = cfg.description_path(case_id, cfg.BASELINE_VERSION)
    baseline = _read_text(baseline_path) if baseline_path.is_file() else None
    if baseline is None:
        findings.error(f"{case_id}: V0.txt missing or not valid UTF-8")

    contents: Dict[str, str] = {}

    for version in cfg.DERIVED_VERSIONS:
        path = cfg.description_path(case_id, version)

        if not path.is_file():
            message = f"{case_id}: {version}.txt does not exist"
            findings.error(message) if strict else findings.warn(message)
            continue

        if path.stat().st_size == 0:
            message = f"{case_id}: {version}.txt is empty"
            findings.error(message) if strict else findings.warn(message)
            continue

        text = _read_text(path)
        if text is None:
            findings.error(f"{case_id}: {version}.txt is not valid UTF-8")
            continue

        if not text.strip():
            findings.error(f"{case_id}: {version}.txt contains only whitespace")
            continue

        contents[version] = text

        if baseline is not None and text.strip() == baseline.strip():
            findings.error(f"{case_id}: {version}.txt is identical to V0.txt")

    # Two different conditions producing byte-identical text means one of them
    # was not actually applied.
    seen: Dict[str, str] = {}
    for version, text in contents.items():
        key = text.strip()
        if key in seen:
            findings.error(
                f"{case_id}: {version}.txt is identical to {seen[key]}.txt"
            )
        else:
            seen[key] = version


def validate(case_ids: List[str], *, strict: bool) -> Findings:
    """Run the variant checks over ``case_ids``."""
    findings = Findings()
    for case_id in case_ids:
        check_case_variants(case_id, findings, strict=strict)
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return 0 when no errors were found."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require every V1-V4 file to exist and be non-empty.",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Limit validation to this case id (repeatable).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    known = cfg.iter_case_ids()
    if args.cases:
        unknown = [c for c in args.cases if c not in known]
        if unknown:
            LOGGER.error("unknown case id(s): %s", ", ".join(unknown))
            return 1
        case_ids = args.cases
    else:
        case_ids = known

    if not case_ids:
        LOGGER.error("no cases found under data/ — run scripts/prepare_dataset.py first")
        return 1

    findings = validate(case_ids, strict=args.strict)

    for message in findings.warnings:
        LOGGER.warning(message)
    for message in findings.errors:
        LOGGER.error(message)

    populated = sum(
        1
        for case_id in case_ids
        for version in cfg.DERIVED_VERSIONS
        if cfg.description_path(case_id, version).is_file()
        and cfg.description_path(case_id, version).stat().st_size > 0
    )

    LOGGER.info("--- summary ---")
    LOGGER.info("cases checked      : %d", len(case_ids))
    LOGGER.info(
        "populated variants : %d / %d", populated, len(case_ids) * len(cfg.DERIVED_VERSIONS)
    )
    LOGGER.info("errors             : %d", len(findings.errors))
    LOGGER.info("warnings           : %d", len(findings.warnings))

    return 1 if findings.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
