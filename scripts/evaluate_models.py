#!/usr/bin/env python3
"""Evaluate generated PlantUML models against their reference models.

Evaluation is the only stage that reads the ground truth. For every
(case_id, version) pair this compares::

    reference_models/<case_id>/reference_model.puml       (reference)
    generated/<case_id>/<version>/generated_model.puml    (generated)

using the Metrik-4 implementation exposed by the ``domain_model_metrics``
package, and appends one record per comparison to ``results/records.jsonl``.

Metric API (verified against the installed source, not assumed)::

    from domain_model_metrics import get_metric
    metric = get_metric("metrik-4")
    metric.compute(reference_plantuml: str, generated_plantuml: str) -> {
        "class_score": float,
        "attribute_score": float,
        "association_score": float,
    }

``compute`` parses both inputs with ``PlantUMLParser(strict=True)`` and raises
``ValueError`` if either model is not a valid parsed model. Such failures are
recorded with an ``error`` field and null scores — never with a substituted or
invented number.

Pairs whose generated model is missing or empty are skipped with a warning, so
the script can be run repeatedly while generation is still in progress.

Usage
-----
    python scripts/evaluate_models.py
    python scripts/evaluate_models.py --case AirTravel --version V0
    python scripts/evaluate_models.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("evaluate_models")

SCORE_KEYS = ("class_score", "attribute_score", "association_score")


def load_metric(metric_name: str = cfg.METRIC_NAME):
    """Return the configured metric instance.

    Raises ``RuntimeError`` with actionable guidance if ``domain_model_metrics``
    is not importable, since that is the most likely setup failure.
    """
    try:
        from domain_model_metrics import get_metric
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Could not import 'domain_model_metrics'. Install it from the "
            "metrics-comparison source checkout into this project's virtualenv."
        ) from exc

    return get_metric(metric_name)


def iter_pairs(
    case_ids: Iterable[str], versions: Iterable[str]
) -> Iterable[Tuple[str, str]]:
    """Yield every (case_id, version) combination to evaluate."""
    for case_id in case_ids:
        for version in versions:
            yield case_id, version


def _read(path: Path) -> Optional[str]:
    """Return the UTF-8 contents of ``path``, or ``None`` if unusable."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    return text if text.strip() else None


def load_generation_metadata() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Return per-(case, version) generation provenance from the generation log.

    Lets each result row record the model and temperature that actually
    produced that observation, rather than the current config defaults. Returns
    an empty mapping when no log exists, in which case the config values are
    used as a fallback.
    """
    if not cfg.GENERATION_LOG.is_file():
        return {}

    metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}
    with cfg.GENERATION_LOG.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "generated":
                continue
            # Later rows win, so a re-generation supersedes the earlier attempt.
            metadata[(row["case_id"], row["version"])] = row
    return metadata


def build_record(
    case_id: str,
    version: str,
    *,
    scores: Optional[Dict[str, float]],
    error: Optional[str] = None,
    generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble one long-form result record.

    Paths are stored rather than file contents, keeping the record compact
    while still making every input fully traceable.
    """
    prompt_file = cfg.VARIANT_PROMPT_FILES.get(version)
    generation = generation or {}

    model_name = generation.get("api_model") or cfg.MODEL_NAME
    raw_temperature = generation.get("temperature")
    if raw_temperature not in (None, ""):
        try:
            temperature: Optional[float] = float(raw_temperature)
        except (TypeError, ValueError):
            temperature = cfg.TEMPERATURE
    else:
        temperature = cfg.TEMPERATURE
    record: Dict[str, Any] = {
        "case_id": case_id,
        "version": version,
        "provider": cfg.PROVIDER,
        "model_name": model_name,
        "run": cfg.DEFAULT_RUN,
        "input_description": str(
            cfg.description_path(case_id, version).relative_to(cfg.PROJECT_ROOT)
        ),
        "reference_plantuml": str(
            cfg.reference_model_path(case_id).relative_to(cfg.PROJECT_ROOT)
        ),
        "generated_plantuml": str(
            cfg.generated_model_path(case_id, version).relative_to(cfg.PROJECT_ROOT)
        ),
        "prompt": str(
            (prompt_file or cfg.MODEL_GENERATION_PROMPT_FILE).relative_to(cfg.PROJECT_ROOT)
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature": temperature,
        "metric": cfg.METRIC_NAME,
    }

    for key in SCORE_KEYS:
        record[key] = None if scores is None else float(scores[key])
    if error is not None:
        record["error"] = error

    return record


def evaluate_pair(
    metric,
    case_id: str,
    version: str,
    generation: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Evaluate one (case, version) pair. Return a record, or ``None`` to skip."""
    reference = _read(cfg.reference_model_path(case_id))
    if reference is None:
        LOGGER.error("%s: reference model missing or empty — skipping %s", case_id, version)
        return None

    generated = _read(cfg.generated_model_path(case_id, version))
    if generated is None:
        LOGGER.warning("%s/%s: generated model not available yet — skipping", case_id, version)
        return None

    try:
        scores = metric.compute(reference, generated)
    except Exception as exc:  # noqa: BLE001 - the metric raises several types
        LOGGER.error("%s/%s: metric failed: %s", case_id, version, exc)
        return build_record(
            case_id, version, scores=None,
            error=f"{type(exc).__name__}: {exc}", generation=generation,
        )

    LOGGER.info(
        "%s/%s: class=%.4f attribute=%.4f association=%.4f",
        case_id, version,
        scores["class_score"], scores["attribute_score"], scores["association_score"],
    )
    return build_record(case_id, version, scores=scores, generation=generation)


def write_records(records: List[Dict[str, Any]], destination: Path) -> None:
    """Write ``records`` as JSON Lines, replacing any previous run's output."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    LOGGER.info("Wrote %d record(s) to %s", len(records), destination.relative_to(cfg.PROJECT_ROOT))


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", action="append", dest="cases", help="Case id (repeatable).")
    parser.add_argument(
        "--version", action="append", dest="versions",
        choices=cfg.VERSIONS, help="Version to evaluate (repeatable).",
    )
    parser.add_argument("--metric", default=cfg.METRIC_NAME, help="Metric name to use.")
    parser.add_argument(
        "--output", type=Path, default=cfg.RESULTS_JSONL,
        help="Destination JSONL file for the evaluation records.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List the pairs that would be evaluated without loading the metric.",
    )
    parser.add_argument(
        "--generated-root", type=Path,
        help=(
            "Directory tree holding the generated models (default: generated/). "
            "Use with --output to score a second model set separately."
        ),
    )
    parser.add_argument(
        "--run", type=int, default=cfg.DEFAULT_RUN,
        help="Run number recorded in each result record (default: %(default)s).",
    )
    args = parser.parse_args(argv)

    cfg.DEFAULT_RUN = args.run

    # Reference models are unaffected: only the generated side varies by set.
    if args.generated_root is not None:
        cfg.GENERATED_DIR = args.generated_root.expanduser().resolve()
        LOGGER.info("evaluating models from %s", cfg.GENERATED_DIR)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    known = cfg.iter_case_ids()
    if not known:
        LOGGER.error("no cases found under data/ — run scripts/prepare_dataset.py first")
        return 1

    if args.cases:
        unknown = [c for c in args.cases if c not in known]
        if unknown:
            LOGGER.error("unknown case id(s): %s", ", ".join(unknown))
            return 1
        case_ids = args.cases
    else:
        case_ids = known

    versions = args.versions or cfg.VERSIONS
    pairs = list(iter_pairs(case_ids, versions))

    if args.dry_run:
        for case_id, version in pairs:
            LOGGER.info("would evaluate %s/%s", case_id, version)
        LOGGER.info("--- summary ---")
        LOGGER.info("pairs: %d", len(pairs))
        return 0

    metric = load_metric(args.metric)
    LOGGER.info("Using metric %s (version %s)", metric.name, metric.version)

    generation_metadata = load_generation_metadata()
    if generation_metadata:
        LOGGER.info(
            "Loaded generation provenance for %d model(s) from %s",
            len(generation_metadata), cfg.GENERATION_LOG.relative_to(cfg.PROJECT_ROOT),
        )

    records = [
        record
        for case_id, version in pairs
        if (
            record := evaluate_pair(
                metric, case_id, version, generation_metadata.get((case_id, version))
            )
        ) is not None
    ]

    failed = sum(1 for record in records if record.get("error"))
    LOGGER.info("--- summary ---")
    LOGGER.info("pairs considered : %d", len(pairs))
    LOGGER.info("records written  : %d", len(records))
    LOGGER.info("scored           : %d", len(records) - failed)
    LOGGER.info("metric failures  : %d", failed)
    LOGGER.info("skipped          : %d", len(pairs) - len(records))

    if records:
        write_records(records, args.output)
    else:
        LOGGER.warning("No records produced — nothing written.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
