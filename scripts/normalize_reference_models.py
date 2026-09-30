#!/usr/bin/env python3
"""Normalise reference PlantUML into the syntax Metrik-4's parser accepts.

The benchmark's reference models use PlantUML constructs that
``PlantUMLParser(strict=True)`` rejects, which made 25 of 45 cases unscoreable.
Each rule below rewrites a construct into the equivalent form documented in the
parser's README, without changing what the model means.

Rules
-----
A  ``enum Genre <<enum>> {``            -> ``enum Genre {``
                                          (stereotype is decoration)
B  ``Author .. (Article,Person)``       -> ``(Article,Person) .. Author``
                                          (documented argument order)
B2 ``(A, B) . C``                       -> ``(A, B) .. C``
                                          (``.`` is not the dependency token)
C  ``*-`` ``-*`` ``-o`` ``*->``         -> ``*--`` ``--*`` ``--o`` ``*-->``
                                          (identical semantics, documented spelling)
D  ``A "0..1" <--> "0..*" B``           -> ``A "0..1" -- "0..*" B``
                                          (bidirectional = plain association)
E  ``note "{XOR}" as N1`` + the pseudo-relationships referencing ``N1``
                                          -> removed entirely

Rule E needs care. ``N1`` is an XOR *constraint*, not a class. Rewriting
``N1..(Screenplay,Concept)`` under rule B would invent a class called ``N1`` and
inflate the reference's class count. The parser has no XOR concept, so the
constraint is unrepresentable either way; dropping it is the option that does
not corrupt the ground truth. This affects FilmSet and TransportCompany.

Not handled: Cruise uses an n-ary association diamond (``<> diamond``), which
has no mechanical equivalent. It is left untouched and reported.

Originals are archived to ``reference_models_original/`` before the first write
and are never overwritten afterwards, so ``--restore`` always returns the true
benchmark files.

Usage
-----
    python scripts/normalize_reference_models.py --dry-run
    python scripts/normalize_reference_models.py
    python scripts/normalize_reference_models.py --restore
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("normalize_reference_models")

ARCHIVE_DIR = cfg.PROJECT_ROOT / "reference_models_original"


def _drop_constraint_notes(text: str) -> str:
    """Remove ``note "..." as ALIAS`` blocks and lines referencing the alias.

    See rule E in the module docstring: keeping them would turn a constraint
    note into a spurious class.
    """
    aliases = re.findall(r'^[ \t]*note\s+"[^"]*"\s+as\s+(\w+)[ \t]*$', text, flags=re.M)
    text = re.sub(r'^[ \t]*note\s+"[^"]*"\s+as\s+\w+[ \t]*$\n?', "", text, flags=re.M)
    for alias in aliases:
        text = re.sub(rf"^.*\b{re.escape(alias)}\b.*$\n?", "", text, flags=re.M)
    return text


def normalize(text: str) -> str:
    """Return ``text`` rewritten into parser-accepted PlantUML.

    The function is idempotent: normalising an already-normalised model is a
    no-op, so the script is safe to re-run.
    """
    text = _drop_constraint_notes(text)

    # A. Enum stereotype.
    text = re.sub(r"(enum\s+\w+)\s*<<enum>>", r"\1", text)

    # C. Single-dash composition/aggregation. The lookbehind requires the token
    # to follow a cardinality quote or whitespace, which both anchors it to a
    # relationship line and makes the rules idempotent (in `--*` the second
    # dash is preceded by `-`, so it cannot match again).
    text = re.sub(r'(?<=["\s])([*o])->', r"\1-->", text)
    text = re.sub(r'(?<=["\s])-([*o])(?=\s*["A-Za-z])', r"--\1", text)
    text = re.sub(r'(?<=["\s])([*o])-(?=\s*["A-Za-z])', r"\1--", text)

    # D. Bidirectional arrow.
    text = re.sub(r"<-->", "--", text)

    # B. Association class: reversed order and/or single dot.
    text = re.sub(r"^[ \t]*(\w+)\s*\.\.?\s*\(([^)]+)\)[ \t]*$", r"(\2) .. \1", text, flags=re.M)
    text = re.sub(r"^[ \t]*\(([^)]+)\)\s*\.\s*(\w+)[ \t]*$", r"(\1) .. \2", text, flags=re.M)

    return text


def diff_lines(before: str, after: str) -> List[Tuple[str, str]]:
    """Return the (old, new) line pairs that differ, for reporting.

    Uses a simple opcode walk so removed lines show an empty replacement.
    """
    import difflib

    old, new = before.splitlines(), after.splitlines()
    changes: List[Tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag == "equal":
            continue
        olds = [line for line in old[i1:i2] if line.strip()]
        news = [line for line in new[j1:j2] if line.strip()]
        for index in range(max(len(olds), len(news))):
            changes.append((
                olds[index] if index < len(olds) else "",
                news[index] if index < len(news) else "",
            ))
    return changes


def archive_original(case_id: str, *, dry_run: bool) -> None:
    """Copy the untouched reference model into the archive, once.

    An existing archived file is never replaced, so repeated runs cannot
    overwrite the true original with an already-normalised version.
    """
    destination = ARCHIVE_DIR / case_id / cfg.REFERENCE_MODEL_FILENAME
    if destination.exists():
        return
    LOGGER.debug("archiving original for %s", case_id)
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cfg.reference_model_path(case_id), destination)


def try_parse(text: str) -> Optional[str]:
    """Return ``None`` if ``text`` parses in strict mode, else the error."""
    try:
        from domain_model_metrics import get_metric
        import importlib

        get_metric(cfg.METRIC_NAME)  # puts the metric's Parser on sys.path
        parser_cls = importlib.import_module("Parser").PlantUMLParser
        parser_cls(strict=True).parse(text)
    except Exception as exc:  # noqa: BLE001 - parser raises several types
        return str(exc).splitlines()[0][:90]
    return None


def restore(*, dry_run: bool) -> int:
    """Copy archived originals back over the working reference models."""
    if not ARCHIVE_DIR.is_dir():
        LOGGER.error("no archive at %s — nothing to restore", ARCHIVE_DIR)
        return 1
    count = 0
    for case_dir in sorted(ARCHIVE_DIR.iterdir()):
        source = case_dir / cfg.REFERENCE_MODEL_FILENAME
        if not source.is_file():
            continue
        LOGGER.info("%s restoring %s", "[dry-run]" if dry_run else "", case_dir.name)
        if not dry_run:
            shutil.copyfile(source, cfg.reference_model_path(case_dir.name))
        count += 1
    LOGGER.info("restored %d reference model(s)", count)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Report changes, write nothing.")
    parser.add_argument(
        "--restore", action="store_true",
        help="Copy the archived originals back over reference_models/.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    if args.restore:
        return restore(dry_run=args.dry_run)

    case_ids = cfg.iter_case_ids()
    if not case_ids:
        LOGGER.error("no cases found — run scripts/prepare_dataset.py first")
        return 1

    changed = unchanged = 0
    parsed_before = parsed_after = 0
    still_failing: List[Tuple[str, str]] = []

    for case_id in case_ids:
        path = cfg.reference_model_path(case_id)
        if not path.is_file():
            LOGGER.error("%s: reference model missing", case_id)
            continue

        before = path.read_text(encoding="utf-8")
        after = normalize(before)

        if try_parse(before) is None:
            parsed_before += 1

        if before == after:
            unchanged += 1
        else:
            changed += 1
            LOGGER.info("─── %s ───", case_id)
            for old, new in diff_lines(before, after):
                if old and new:
                    LOGGER.info("    - %s", old.strip())
                    LOGGER.info("    + %s", new.strip())
                elif old:
                    LOGGER.info("    - %s   (removed)", old.strip())
                else:
                    LOGGER.info("    + %s", new.strip())

            archive_original(case_id, dry_run=args.dry_run)
            if not args.dry_run:
                path.write_text(after, encoding="utf-8")

        error = try_parse(after)
        if error is None:
            parsed_after += 1
        else:
            still_failing.append((case_id, error))

    prefix = "[dry-run] " if args.dry_run else ""
    LOGGER.info("%s--- summary ---", prefix)
    LOGGER.info("%scases                  : %d", prefix, len(case_ids))
    LOGGER.info("%sfiles changed          : %d", prefix, changed)
    LOGGER.info("%sfiles already fine     : %d", prefix, unchanged)
    LOGGER.info("%sparsed before          : %d / %d", prefix, parsed_before, len(case_ids))
    LOGGER.info("%sparsed after           : %d / %d", prefix, parsed_after, len(case_ids))
    if not args.dry_run and changed:
        LOGGER.info("originals archived in  : %s", ARCHIVE_DIR.relative_to(cfg.PROJECT_ROOT))
        LOGGER.info("revert with            : --restore")

    for case_id, error in still_failing:
        LOGGER.warning("still unparseable: %s — %s", case_id, error)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
