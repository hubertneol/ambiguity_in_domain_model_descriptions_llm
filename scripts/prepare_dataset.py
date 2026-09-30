#!/usr/bin/env python3
"""Normalise the original benchmark corpus into the experiment structure.

The source corpus is treated as strictly read-only: files are copied out of it,
never written back, moved or deleted.

For every discovered source case this script produces::

    data/<case_id>/V0.txt                        <- copied from the source description
    data/<case_id>/V1.txt .. V4.txt              <- empty placeholders (never generated)
    reference_models/<case_id>/reference_model.puml <- copied from the source PlantUML
    generated/<case_id>/V0 .. V4/                <- empty directories for later models

Note that ``data/`` holds natural-language input only. The ground-truth model is
written to a separate ``reference_models/`` tree so it cannot leak into the
variant-writing or UML-generation stages, which read ``data/`` and ``prompts/``.

Existing V0/reference files are left untouched unless ``--force`` is given, so
re-running the script is safe.

Usage
-----
    python scripts/prepare_dataset.py --source /path/to/benchmark/models
    BENCHMARK_SOURCE_DIR=/path/to/benchmark/models python scripts/prepare_dataset.py
    python scripts/prepare_dataset.py --source ... --dry-run
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

# Make the project root importable when the script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("prepare_dataset")


class SourceCase(NamedTuple):
    """A source benchmark case with its resolved input files."""

    case_id: str
    root: Path
    description: Path
    plantuml: Path


class Report(NamedTuple):
    """Counters describing what a run changed."""

    cases: int = 0
    v0_copied: int = 0
    v0_skipped: int = 0
    references_copied: int = 0
    references_skipped: int = 0
    placeholders_created: int = 0
    generated_dirs_created: int = 0


def _first_existing(root: Path, candidates: List[str]) -> Optional[Path]:
    """Return the first candidate filename that exists directly under ``root``."""
    for name in candidates:
        path = root / name
        if path.is_file():
            return path
    return None


def discover_source_cases(source_root: Path) -> List[SourceCase]:
    """Discover benchmark cases under ``source_root``.

    A directory qualifies as a case when it contains both a recognised
    description file and a recognised PlantUML file. Directories that are
    missing one of the two are reported as warnings and skipped, so a partially
    populated corpus never silently produces an incomplete dataset.
    """
    if not source_root.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {source_root}")

    cases: List[SourceCase] = []
    for entry in sorted(source_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        description = _first_existing(entry, cfg.SOURCE_DESCRIPTION_CANDIDATES)
        plantuml = _first_existing(entry, cfg.SOURCE_PLANTUML_CANDIDATES)

        if description is None:
            LOGGER.warning("Skipping %s: no description file found", entry.name)
            continue
        if plantuml is None:
            LOGGER.warning("Skipping %s: no PlantUML file found", entry.name)
            continue

        cases.append(
            SourceCase(case_id=entry.name, root=entry, description=description, plantuml=plantuml)
        )

    return cases


def _copy_preserving(src: Path, dst: Path, *, force: bool, dry_run: bool) -> bool:
    """Copy ``src`` to ``dst`` byte-for-byte. Return ``True`` if it was written.

    An existing destination is never overwritten unless ``force`` is set; the
    original content is copied verbatim, so descriptions and reference models
    keep the exact text of the benchmark.
    """
    if dst.exists() and not force:
        LOGGER.debug("Keeping existing %s", dst)
        return False

    action = "Would copy" if dry_run else "Copying"
    LOGGER.info("%s %s -> %s", action, src, dst.relative_to(cfg.PROJECT_ROOT))
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return True


def _touch_placeholder(path: Path, *, dry_run: bool) -> bool:
    """Create ``path`` as an empty file if absent. Return ``True`` if created.

    Placeholders are deliberately left empty — variant text is produced by a
    later step, never by this script.
    """
    if path.exists():
        return False

    action = "Would create" if dry_run else "Creating"
    LOGGER.info("%s empty placeholder %s", action, path.relative_to(cfg.PROJECT_ROOT))
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return True


def _ensure_dir(path: Path, *, dry_run: bool) -> bool:
    """Create ``path`` if absent. Return ``True`` if it was created."""
    if path.is_dir():
        return False

    action = "Would create" if dry_run else "Creating"
    LOGGER.info("%s directory %s", action, path.relative_to(cfg.PROJECT_ROOT))
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)
    return True


def prepare_case(case: SourceCase, *, force: bool, dry_run: bool) -> Report:
    """Normalise one source case into ``data/``, ``reference_models/`` and ``generated/``.

    Destination paths come from the config helpers, so the description and the
    reference model land in their respective trees without any path logic here.
    """
    v0_copied = _copy_preserving(
        case.description, cfg.description_path(case.case_id, cfg.BASELINE_VERSION),
        force=force, dry_run=dry_run,
    )
    ref_copied = _copy_preserving(
        case.plantuml, cfg.reference_model_path(case.case_id),
        force=force, dry_run=dry_run,
    )

    placeholders = sum(
        _touch_placeholder(cfg.description_path(case.case_id, version), dry_run=dry_run)
        for version in cfg.DERIVED_VERSIONS
    )
    generated_dirs = sum(
        _ensure_dir(cfg.generated_version_dir(case.case_id, version), dry_run=dry_run)
        for version in cfg.VERSIONS
    )

    return Report(
        cases=1,
        v0_copied=int(v0_copied),
        v0_skipped=int(not v0_copied),
        references_copied=int(ref_copied),
        references_skipped=int(not ref_copied),
        placeholders_created=placeholders,
        generated_dirs_created=generated_dirs,
    )


def prepare_dataset(source_root: Path, *, force: bool = False, dry_run: bool = False) -> Report:
    """Normalise every discovered source case. Return the aggregated report."""
    cases = discover_source_cases(source_root)
    LOGGER.info("Discovered %d source case(s) under %s", len(cases), source_root)

    if len(cases) != cfg.CASE_COUNT:
        LOGGER.warning(
            "Expected %d cases by design, discovered %d", cfg.CASE_COUNT, len(cases)
        )

    totals = Report()
    for case in cases:
        result = prepare_case(case, force=force, dry_run=dry_run)
        totals = Report(*(a + b for a, b in zip(totals, result)))

    return totals


def _log_report(report: Report, *, dry_run: bool) -> None:
    """Emit a human-readable summary of what the run changed."""
    prefix = "[dry-run] " if dry_run else ""
    LOGGER.info("%s--- summary ---", prefix)
    LOGGER.info("%scases processed        : %d", prefix, report.cases)
    LOGGER.info("%sV0.txt copied          : %d", prefix, report.v0_copied)
    LOGGER.info("%sV0.txt already present : %d", prefix, report.v0_skipped)
    LOGGER.info("%sreference copied       : %d", prefix, report.references_copied)
    LOGGER.info("%sreference already there: %d", prefix, report.references_skipped)
    LOGGER.info("%sV1-V4 placeholders     : %d", prefix, report.placeholders_created)
    LOGGER.info("%sgenerated dirs created : %d", prefix, report.generated_dirs_created)


def _resolve_source(explicit: Optional[str]) -> Path:
    """Resolve the source corpus from the CLI argument or the environment."""
    if explicit:
        return Path(explicit).expanduser().resolve()

    from_env = cfg.source_root_from_env()
    if from_env is not None:
        return from_env.resolve()

    raise SystemExit(
        "No source corpus given. Pass --source /path/to/benchmark/models or set "
        f"the {cfg.SOURCE_DIR_ENV_VAR} environment variable."
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        help=(
            "Directory holding the original benchmark case folders. "
            f"Defaults to ${cfg.SOURCE_DIR_ENV_VAR}."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-copy V0.txt and reference_models/<case>/reference_model.puml "
            "even if they already exist."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    source_root = _resolve_source(args.source)
    report = prepare_dataset(source_root, force=args.force, dry_run=args.dry_run)
    _log_report(report, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
