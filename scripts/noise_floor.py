#!/usr/bin/env python3
"""Estimate generation noise by comparing two runs of the same descriptions.

Rationale
---------
The experiment compares scores across text conditions. A difference between
conditions is only interpretable if it is larger than the variation the model
produces on *identical* input. With one generation per condition and no
temperature control, that variation is otherwise unmeasured.

This script takes two independent generations of the same descriptions
(normally V0, generated twice), each already scored against the same reference
model, and reports the distribution of per-case score differences. That
distribution is the noise floor: the magnitude of difference the experiment
cannot distinguish from chance.

Interpretation
--------------
Compare the mean absolute difference reported here against the differences
observed between V0 and the variant conditions:

* condition effect clearly larger than the noise floor -> the effect is
  measurable
* condition effect comparable to or smaller than the noise floor -> the design
  cannot distinguish the effect from generation variability, and a null result
  must be reported as inconclusive rather than as evidence of robustness

Usage
-----
    python scripts/noise_floor.py \\
        --run1 results/records.jsonl \\
        --run2 results/records_run2.jsonl \\
        --version V0
"""

from __future__ import annotations

import argparse
import json
import logging
import csv
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("noise_floor")

SCORE_KEYS = ("class_score", "attribute_score", "association_score")


def load_scores(path: Path, version: str) -> Dict[str, Dict[str, float]]:
    """Return ``{case_id: {score_key: value}}`` for successfully scored records."""
    if not path.is_file():
        raise SystemExit(f"No records file at {path}")

    scores: Dict[str, Dict[str, float]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("version") != version or record.get("error"):
                continue
            if any(record.get(key) is None for key in SCORE_KEYS):
                continue
            scores[record["case_id"]] = {key: float(record[key]) for key in SCORE_KEYS}
    return scores


def paired_differences(
    run1: Dict[str, Dict[str, float]], run2: Dict[str, Dict[str, float]]
) -> Tuple[List[str], Dict[str, List[float]]]:
    """Return the shared case ids and the per-score signed differences."""
    shared = sorted(set(run1) & set(run2))
    diffs: Dict[str, List[float]] = {key: [] for key in SCORE_KEYS}
    for case_id in shared:
        for key in SCORE_KEYS:
            diffs[key].append(run2[case_id][key] - run1[case_id][key])
    return shared, diffs


def summarise(diffs: List[float]) -> Dict[str, float]:
    """Return summary statistics for one score's differences."""
    absolute = [abs(d) for d in diffs]
    return {
        "mean_abs": st.mean(absolute),
        "median_abs": st.median(absolute),
        "max_abs": max(absolute),
        "sd": st.stdev(diffs) if len(diffs) > 1 else 0.0,
        "identical": sum(1 for d in diffs if d == 0.0),
    }


def write_summary_csv(
    path: Path, diffs: Dict[str, List[float]], n_cases: int, version: str
) -> None:
    """Write one row per score with the noise-floor statistics.

    ``mean_abs`` is the value to compare condition effects against.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "version", "n_cases", "score", "mean_abs", "median_abs", "max_abs",
        "sd", "mean_signed", "identical", "identical_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for key in SCORE_KEYS:
            values = diffs[key]
            stats = summarise(values)
            writer.writerow({
                "version": version,
                "n_cases": n_cases,
                "score": key,
                "mean_abs": round(stats["mean_abs"], 6),
                "median_abs": round(stats["median_abs"], 6),
                "max_abs": round(stats["max_abs"], 6),
                "sd": round(stats["sd"], 6),
                "mean_signed": round(st.mean(values), 6),
                "identical": stats["identical"],
                "identical_pct": round(100 * stats["identical"] / n_cases, 2),
            })
    LOGGER.info("wrote %s", path)


def write_pairs_csv(
    path: Path,
    shared: List[str],
    run1: Dict[str, Dict[str, float]],
    run2: Dict[str, Dict[str, float]],
    version: str,
) -> None:
    """Write per-case paired scores in long form, one row per case and score.

    Long form so the noise floor can be plotted on the same axes as the
    condition effects without reshaping.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["case_id", "version", "score", "run1", "run2", "diff", "abs_diff"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for case_id in shared:
            for key in SCORE_KEYS:
                first, second = run1[case_id][key], run2[case_id][key]
                writer.writerow({
                    "case_id": case_id,
                    "version": version,
                    "score": key,
                    "run1": round(first, 6),
                    "run2": round(second, 6),
                    "diff": round(second - first, 6),
                    "abs_diff": round(abs(second - first), 6),
                })
    LOGGER.info("wrote %s (%d rows)", path, len(shared) * len(SCORE_KEYS))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run1", type=Path, default=cfg.RESULTS_DIR / "records.jsonl")
    parser.add_argument("--run2", type=Path, default=cfg.RESULTS_DIR / "records_run2.jsonl")
    parser.add_argument(
        "--version", default=cfg.BASELINE_VERSION, choices=cfg.VERSIONS,
        help="Version that was generated twice (default: %(default)s).",
    )
    parser.add_argument(
        "--summary-csv", type=Path, default=cfg.RESULTS_DIR / "noise_floor_summary.csv",
        help="Per-score summary statistics (default: %(default)s).",
    )
    parser.add_argument(
        "--pairs-csv", type=Path, default=cfg.RESULTS_DIR / "noise_floor_pairs.csv",
        help=(
            "Per-case paired scores and differences, in long form for plotting "
            "(default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--no-csv", action="store_true", help="Print the summary without writing files."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    run1 = load_scores(args.run1, args.version)
    run2 = load_scores(args.run2, args.version)
    shared, diffs = paired_differences(run1, run2)

    if not shared:
        LOGGER.error(
            "no cases scored in both runs (run1: %d, run2: %d)", len(run1), len(run2)
        )
        return 1

    LOGGER.info("version compared : %s", args.version)
    LOGGER.info("cases in both runs: %d", len(shared))
    LOGGER.info("")
    LOGGER.info("%-20s %9s %9s %9s %9s %10s", "score", "mean|d|", "median|d|", "max|d|", "sd", "identical")
    for key in SCORE_KEYS:
        s = summarise(diffs[key])
        LOGGER.info(
            "%-20s %9.4f %9.4f %9.4f %9.4f %6d/%d",
            key, s["mean_abs"], s["median_abs"], s["max_abs"], s["sd"],
            s["identical"], len(shared),
        )

    LOGGER.info("")
    LOGGER.info("The mean |d| column is the noise floor: a difference between two")
    LOGGER.info("conditions of this magnitude is not distinguishable from the")
    LOGGER.info("variation the model produces on identical input.")

    if not args.no_csv:
        write_summary_csv(args.summary_csv, diffs, len(shared), args.version)
        write_pairs_csv(args.pairs_csv, shared, run1, run2, args.version)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
