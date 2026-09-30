#!/usr/bin/env python3
"""Check that the experiment skeleton is structurally complete.

This validator is intended to run at *any* stage of the workflow. Missing V1-V4
text or missing generated models are reported as warnings, not errors, because
they are filled in by later steps. Only genuinely broken structure — a missing
baseline description, a missing reference model, an unreadable file — is an
error.

It also enforces the experimental isolation introduced by the reference-model
split: any ``.puml`` found under ``data/`` is an error, because ``data/`` is the
only tree the variant-writing and UML-generating stages are allowed to read.

Usage
-----
    python scripts/validate_dataset.py
    python scripts/validate_dataset.py --strict   # warnings count as failure
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("validate_dataset")


class Findings:
    """Collects errors and warnings produced during validation."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def error(self, message: str) -> None:
        """Record a structural defect that must be fixed."""
        self.errors.append(message)

    def warn(self, message: str) -> None:
        """Record something still to be filled in by a later workflow step."""
        self.warnings.append(message)


def _rel(path: Path) -> str:
    """Return ``path`` relative to the project root, for readable messages."""
    try:
        return str(path.relative_to(cfg.PROJECT_ROOT))
    except ValueError:
        return str(path)


def check_directories(findings: Findings) -> None:
    """Verify the top-level project directories exist."""
    for directory in (
        cfg.DATA_DIR,
        cfg.REFERENCE_MODELS_DIR,
        cfg.GENERATED_DIR,
        cfg.PROMPTS_DIR,
        cfg.RESULTS_DIR,
    ):
        if not directory.is_dir():
            findings.error(f"missing directory: {_rel(directory)}")


def check_prompts(findings: Findings) -> None:
    """Verify all prompt files exist and are non-empty."""
    prompt_files = list(cfg.VARIANT_PROMPT_FILES.values()) + [cfg.MODEL_GENERATION_PROMPT_FILE]
    for path in prompt_files:
        if not path.is_file():
            findings.error(f"missing prompt file: {_rel(path)}")
        elif path.stat().st_size == 0:
            findings.warn(f"prompt file is empty: {_rel(path)}")


def check_patterns(findings: Findings) -> None:
    """Verify the documented prompt patterns exist, one per derived version.

    Patterns are documentation rather than executable inputs, so a missing file
    is a warning.
    """
    if not cfg.PATTERNS_DIR.is_dir():
        findings.warn(f"missing directory: {_rel(cfg.PATTERNS_DIR)}")
        return
    for version in cfg.DERIVED_VERSIONS:
        matches = list(cfg.PATTERNS_DIR.glob(f"{version.lower()}_*_pattern.md"))
        if not matches:
            findings.warn(f"no pattern document found for {version} in {_rel(cfg.PATTERNS_DIR)}")


def check_case_count(case_ids: List[str], findings: Findings) -> None:
    """Verify the number of prepared cases matches the experimental design."""
    if not case_ids:
        findings.error(
            "no cases found under data/ — run scripts/prepare_dataset.py first"
        )
    elif len(case_ids) != cfg.CASE_COUNT:
        findings.error(
            f"expected {cfg.CASE_COUNT} cases by design, found {len(case_ids)}"
        )


def _readable_utf8(path: Path) -> bool:
    """Return ``True`` if ``path`` can be decoded as UTF-8."""
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def check_case(case_id: str, findings: Findings) -> None:
    """Validate the inputs and output slots of a single case."""
    # V0 is the baseline and must exist with content.
    v0 = cfg.description_path(case_id, cfg.BASELINE_VERSION)
    if not v0.is_file():
        findings.error(f"{case_id}: missing {_rel(v0)}")
    elif v0.stat().st_size == 0:
        findings.error(f"{case_id}: V0.txt is empty")
    elif not _readable_utf8(v0):
        findings.error(f"{case_id}: V0.txt is not valid UTF-8")

    # The reference model must exist with content.
    reference = cfg.reference_model_path(case_id)
    if not reference.is_file():
        findings.error(f"{case_id}: missing {_rel(reference)}")
    elif reference.stat().st_size == 0:
        findings.error(f"{case_id}: reference_model.puml is empty")
    elif not _readable_utf8(reference):
        findings.error(f"{case_id}: reference_model.puml is not valid UTF-8")

    # V1-V4 are placeholders at preparation time — absence/emptiness is a warning.
    for version in cfg.DERIVED_VERSIONS:
        path = cfg.description_path(case_id, version)
        if not path.is_file():
            findings.warn(f"{case_id}: {version}.txt not created yet")
        elif path.stat().st_size == 0:
            findings.warn(f"{case_id}: {version}.txt is still empty")

    # Generated output slots must exist; the models themselves need not.
    for version in cfg.VERSIONS:
        version_dir = cfg.generated_version_dir(case_id, version)
        if not version_dir.is_dir():
            findings.error(f"{case_id}: missing output directory {_rel(version_dir)}")
            continue
        model = cfg.generated_model_path(case_id, version)
        if not model.is_file():
            findings.warn(f"{case_id}/{version}: generated_model.puml not written yet")
        elif model.stat().st_size == 0:
            findings.warn(f"{case_id}/{version}: generated_model.puml is empty")


def check_no_stray_versions(case_id: str, findings: Findings) -> None:
    """Warn about unexpected ``V*.txt`` files that no version maps to."""
    expected = {f"{version}.txt" for version in cfg.VERSIONS}
    case_path = cfg.case_dir(case_id)
    if not case_path.is_dir():
        return
    for entry in case_path.iterdir():
        if entry.is_file() and entry.suffix == ".txt" and entry.name not in expected:
            findings.warn(f"{case_id}: unrecognised description file {entry.name}")


def check_no_ground_truth_leakage(case_id: str, findings: Findings) -> None:
    """Error if ground-truth UML is present in the natural-language input tree.

    ``data/`` is the only directory the variant-writing and UML-generating
    stages read. A reference model there — at the legacy path or under any
    other name — would expose the ground truth to those stages, so it is a
    hard error rather than a warning.
    """
    legacy = cfg.legacy_reference_model_path(case_id)
    if legacy.is_file():
        findings.error(
            f"{case_id}: ground-truth leakage — {_rel(legacy)} must live under "
            f"{_rel(cfg.reference_model_path(case_id))}"
        )

    case_path = cfg.case_dir(case_id)
    if not case_path.is_dir():
        return
    for entry in case_path.iterdir():
        if entry.is_file() and entry.suffix == ".puml" and entry != legacy:
            findings.error(f"{case_id}: unexpected UML file in data/: {_rel(entry)}")


def validate() -> Findings:
    """Run every structural check and return the collected findings."""
    findings = Findings()
    check_directories(findings)
    check_prompts(findings)
    check_patterns(findings)

    case_ids = cfg.iter_case_ids()
    check_case_count(case_ids, findings)
    for case_id in case_ids:
        check_case(case_id, findings)
        check_no_stray_versions(case_id, findings)
        check_no_ground_truth_leakage(case_id, findings)

    return findings


def _count_present(case_ids: List[str]) -> dict:
    """Return summary counts of populated variants and generated models."""
    variants = sum(
        1
        for case_id in case_ids
        for version in cfg.DERIVED_VERSIONS
        if cfg.description_path(case_id, version).is_file()
        and cfg.description_path(case_id, version).stat().st_size > 0
    )
    models = sum(
        1
        for case_id in case_ids
        for version in cfg.VERSIONS
        if cfg.generated_model_path(case_id, version).is_file()
        and cfg.generated_model_path(case_id, version).stat().st_size > 0
    )
    return {"variants": variants, "models": models}


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return 0 when the skeleton is structurally sound."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (use once the dataset should be complete).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    findings = validate()
    case_ids = cfg.iter_case_ids()
    counts = _count_present(case_ids)

    for message in findings.warnings:
        LOGGER.warning(message)
    for message in findings.errors:
        LOGGER.error(message)

    expected_variants = len(case_ids) * len(cfg.DERIVED_VERSIONS)
    references = sum(1 for case_id in case_ids if cfg.reference_model_path(case_id).is_file())

    LOGGER.info("--- summary ---")
    LOGGER.info("cases                    : %d / %d", len(case_ids), cfg.CASE_COUNT)
    LOGGER.info("reference models         : %d / %d", references, cfg.CASE_COUNT)
    LOGGER.info("populated V1-V4 variants : %d / %d", counts["variants"], expected_variants)
    LOGGER.info(
        "generated models         : %d / %d", counts["models"], cfg.EXPECTED_MODEL_COUNT
    )
    LOGGER.info("errors                   : %d", len(findings.errors))
    LOGGER.info("warnings                 : %d", len(findings.warnings))

    if findings.errors:
        return 1
    if args.strict and findings.warnings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
