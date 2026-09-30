#!/usr/bin/env python3
"""Create/synchronise the isolated workspace for text-variant generation.

The workspace is a *copy* of exactly what the V1-V4 writing stage is allowed to
see — nothing is moved out of the project::

    variant_generation_workspace/
    ├── data/<case_id>/V0.txt … V4.txt
    └── prompts/v1_implicit.txt … v4_paraphrase.txt

Deliberately excluded, so ground truth cannot leak into the variant stage:
``reference_models/``, ``generated/``, ``results/``, ``patterns/`` and
``prompts/model_generation_prompt.txt``. This script reads only ``data/`` and
the four transformation prompts named in ``cfg.VARIANT_PROMPT_FILES``; it has no
code path that touches the reference models.

Re-running is safe. A workspace file is only written when it is missing, or when
it is an empty placeholder being filled from the project. A workspace file that
holds content the project copy does not have is *preserved* — that is the normal
state once variants have been written in the workspace but not yet synced back.
Genuine divergence (both sides non-empty and different) is reported, never
silently resolved.

Usage
-----
    python scripts/prepare_variant_workspace.py --dry-run
    python scripts/prepare_variant_workspace.py
    python scripts/prepare_variant_workspace.py --force   # project wins on conflict
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("prepare_variant_workspace")


class Stats:
    """Mutable counters describing one synchronisation run."""

    def __init__(self) -> None:
        self.cases = 0
        self.copied_v0 = 0
        self.copied_variants = 0
        self.copied_prompts = 0
        self.unchanged = 0
        self.preserved: List[str] = []
        self.mismatches: List[str] = []


def _digest(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    """Return ``path`` relative to the project root, for readable messages."""
    try:
        return str(path.relative_to(cfg.PROJECT_ROOT))
    except ValueError:
        return str(path)


def sync_file(src: Path, dst: Path, stats: Stats, *, force: bool, dry_run: bool) -> bool:
    """Copy ``src`` to ``dst`` when it is safe to do so. Return ``True`` if written.

    Content is copied byte-for-byte, so UTF-8 text and empty placeholders are
    both preserved exactly.
    """
    if not src.is_file():
        stats.mismatches.append(f"missing source file: {_rel(src)}")
        return False

    if dst.exists():
        if _digest(src) == _digest(dst):
            stats.unchanged += 1
            return False

        src_empty = src.stat().st_size == 0
        dst_empty = dst.stat().st_size == 0

        if dst_empty and not src_empty:
            pass  # Workspace placeholder being filled from the project — safe.
        elif not dst_empty and src_empty:
            # The workspace holds a variant the project does not have yet.
            # This is expected mid-experiment; never destroy it.
            if not force:
                stats.preserved.append(_rel(dst))
                return False
        elif not force:
            stats.mismatches.append(
                f"differs on both sides, workspace kept: {_rel(dst)}"
            )
            return False

    action = "Would copy" if dry_run else "Copying"
    LOGGER.debug("%s %s -> %s", action, _rel(src), _rel(dst))
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return True


def sync_case(case_id: str, stats: Stats, *, force: bool, dry_run: bool) -> None:
    """Synchronise the V0-V4 descriptions of a single case into the workspace."""
    for version in cfg.VERSIONS:
        written = sync_file(
            cfg.description_path(case_id, version),
            cfg.workspace_description_path(case_id, version),
            stats, force=force, dry_run=dry_run,
        )
        if not written:
            continue
        if version == cfg.BASELINE_VERSION:
            stats.copied_v0 += 1
        else:
            stats.copied_variants += 1


def sync_prompts(stats: Stats, *, force: bool, dry_run: bool) -> None:
    """Copy the four transformation prompts into the workspace.

    Only the prompts in ``cfg.VARIANT_PROMPT_FILES`` are copied. The
    model-generation prompt belongs to a later stage and is not part of this
    workspace.
    """
    for version, src in sorted(cfg.VARIANT_PROMPT_FILES.items()):
        dst = cfg.WORKSPACE_PROMPTS_DIR / src.name
        if sync_file(src, dst, stats, force=force, dry_run=dry_run):
            stats.copied_prompts += 1
            LOGGER.debug("prompt for %s -> %s", version, _rel(dst))


def audit_workspace() -> List[str]:
    """Return a list of isolation violations found in the workspace.

    Guards the property the workspace exists for: no ground truth, no generated
    models, no results — only descriptions and transformation prompts.
    """
    violations: List[str] = []
    root = cfg.VARIANT_WORKSPACE_DIR
    if not root.is_dir():
        return [f"workspace does not exist: {_rel(root)}"]

    forbidden_dirs = ("reference_models", "generated", "results", "patterns")
    for name in forbidden_dirs:
        for found in root.rglob(name):
            if found.is_dir():
                violations.append(f"forbidden directory present: {_rel(found)}")

    for puml in root.rglob("*.puml"):
        violations.append(f"PlantUML file present: {_rel(puml)}")

    for stray in root.rglob("model_generation_prompt.txt"):
        violations.append(f"model-generation prompt present: {_rel(stray)}")

    allowed_prompts = {src.name for src in cfg.VARIANT_PROMPT_FILES.values()}
    if cfg.WORKSPACE_PROMPTS_DIR.is_dir():
        for entry in cfg.WORKSPACE_PROMPTS_DIR.iterdir():
            if entry.is_file() and entry.name not in allowed_prompts:
                violations.append(f"unexpected prompt file: {_rel(entry)}")

    expected_names = {f"{version}.txt" for version in cfg.VERSIONS}
    if cfg.WORKSPACE_DATA_DIR.is_dir():
        for case_path in cfg.WORKSPACE_DATA_DIR.iterdir():
            if not case_path.is_dir():
                continue
            for entry in case_path.iterdir():
                if entry.is_file() and entry.name not in expected_names:
                    violations.append(f"unexpected file in workspace data: {_rel(entry)}")

    return violations


def verify_workspace() -> List[str]:
    """Return a list of completeness problems in the workspace."""
    problems: List[str] = []

    case_ids = cfg.iter_case_ids()
    workspace_cases = (
        sorted(p.name for p in cfg.WORKSPACE_DATA_DIR.iterdir() if p.is_dir())
        if cfg.WORKSPACE_DATA_DIR.is_dir()
        else []
    )

    if len(workspace_cases) != cfg.CASE_COUNT:
        problems.append(
            f"expected {cfg.CASE_COUNT} case folders, found {len(workspace_cases)}"
        )
    missing_cases = set(case_ids) - set(workspace_cases)
    if missing_cases:
        problems.append(f"cases missing from workspace: {', '.join(sorted(missing_cases))}")

    for case_id in workspace_cases:
        for version in cfg.VERSIONS:
            path = cfg.workspace_description_path(case_id, version)
            if not path.is_file():
                problems.append(f"missing {_rel(path)}")

    for src in cfg.VARIANT_PROMPT_FILES.values():
        dst = cfg.WORKSPACE_PROMPTS_DIR / src.name
        if not dst.is_file():
            problems.append(f"missing prompt {_rel(dst)}")

    return problems


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would change without writing."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="On conflict, let the project copy overwrite the workspace copy.",
    )
    parser.add_argument("--verbose", action="store_true", help="Log every file operation.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    case_ids = cfg.iter_case_ids()
    if not case_ids:
        LOGGER.error("no cases found under data/ — run scripts/prepare_dataset.py first")
        return 1

    stats = Stats()
    for case_id in case_ids:
        sync_case(case_id, stats, force=args.force, dry_run=args.dry_run)
        stats.cases += 1
    sync_prompts(stats, force=args.force, dry_run=args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    LOGGER.info("%s--- summary ---", prefix)
    LOGGER.info("%scases processed   : %d", prefix, stats.cases)
    LOGGER.info("%sV0.txt copied     : %d", prefix, stats.copied_v0)
    LOGGER.info("%sV1-V4 copied      : %d", prefix, stats.copied_variants)
    LOGGER.info("%sprompts copied    : %d", prefix, stats.copied_prompts)
    LOGGER.info("%salready in sync   : %d", prefix, stats.unchanged)
    LOGGER.info("%sworkspace kept    : %d", prefix, len(stats.preserved))
    LOGGER.info("%smismatches        : %d", prefix, len(stats.mismatches))

    for path in stats.preserved:
        LOGGER.info("preserved workspace file (has content the project lacks): %s", path)
    for message in stats.mismatches:
        LOGGER.warning(message)

    if args.dry_run:
        return 0

    problems = verify_workspace()
    violations = audit_workspace()

    for message in problems:
        LOGGER.error(message)
    for message in violations:
        LOGGER.error("ISOLATION VIOLATION: %s", message)

    if not problems and not violations:
        LOGGER.info("workspace verified: complete and free of ground-truth material")

    return 1 if (problems or violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
