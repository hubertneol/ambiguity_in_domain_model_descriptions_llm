#!/usr/bin/env python3
"""Generate one PlantUML domain model per description via the OpenAI API.

Pipeline position::

    data/<case_id>/<version>.txt                     (225 descriptions)
        -> generate_models.py
    generated/<case_id>/<version>/generated_model.puml  (225 models)
        -> evaluate_models.py  (Metrik-4)

Requests go through the OpenAI Responses API (``client.responses.create``).

Experimental isolation
----------------------
Every one of the 225 generations is an independent request. For each request
the input list is rebuilt from scratch and contains exactly two items:

1. the verbatim contents of ``prompts/model_generation_prompt.txt``
2. the single description being processed

Nothing else is ever sent. No prior response, no other version of the same
case, no other case, no reference model, no metric score, no accumulated
conversation. The OpenAI client object is a stateless HTTP session — it carries
no history between calls — and this script never appends to a message list.

Because each observation must correspond to exactly one generation attempt, the
script does not sample multiple candidates or ask the model to revise its
output. Retries exist only for transient transport failures (timeout, 429,
5xx); a retry re-sends the byte-identical request and never includes the
failed response.

Usage
-----
    # inspect what would run, no API calls, no key needed
    python scripts/generate_models.py --dry-run

    # single-description smoke test
    python scripts/generate_models.py --case AirTravel --version V0 --limit 1

    # full experiment
    python scripts/generate_models.py

    # technical completeness/format check only
    python scripts/generate_models.py --validate-only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402

LOGGER = logging.getLogger("generate_models")

#: Fences the API may wrap the answer in despite being told not to.
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)


class Task(NamedTuple):
    """One description to generate a model for."""

    case_id: str
    version: str
    description_path: Path
    output_path: Path


class Outcome(NamedTuple):
    """The result of processing one task."""

    status: str
    attempts: int
    format_ok: Optional[bool]
    usage: Dict[str, Optional[int]]
    error: str
    #: Model string the API resolved the request to (the dated snapshot behind
    #: an alias such as ``gpt-4o``). Empty when the request never succeeded.
    resolved_model: str = ""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_tasks(
    case_ids: Optional[List[str]] = None,
    versions: Optional[List[str]] = None,
) -> List[Task]:
    """Return the description/output pairs to process, in deterministic order."""
    selected_cases = case_ids if case_ids is not None else cfg.iter_case_ids()
    selected_versions = versions if versions is not None else cfg.VERSIONS

    tasks: List[Task] = []
    for case_id in selected_cases:
        for version in selected_versions:
            tasks.append(
                Task(
                    case_id=case_id,
                    version=version,
                    description_path=cfg.description_path(case_id, version),
                    output_path=cfg.generated_model_path(case_id, version),
                )
            )
    return tasks


def _sha256(text: str) -> str:
    """Return the SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rel(path: Path) -> str:
    """Return ``path`` relative to the project root, or absolute if outside it."""
    try:
        return str(path.relative_to(cfg.PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_prompt() -> str:
    """Return the fixed model-generation prompt verbatim.

    The file is authoritative and is never rewritten by this script.
    """
    path = cfg.MODEL_GENERATION_PROMPT_FILE
    if not path.is_file():
        raise SystemExit(f"Missing generation prompt: {path}")
    prompt = path.read_text(encoding="utf-8")
    if not prompt.strip():
        raise SystemExit(f"Generation prompt is empty: {path}")
    return prompt


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def strip_code_fences(text: str) -> str:
    """Remove a surrounding Markdown code fence, if the response has one.

    This is purely mechanical unwrapping. The PlantUML inside is never
    reformatted, corrected or otherwise altered.
    """
    match = _FENCE_RE.match(text.strip())
    return match.group(1) if match else text.strip()


def check_format(text: str) -> bool:
    """Return ``True`` if ``text`` starts with @startuml and ends with @enduml."""
    stripped = text.strip()
    return stripped.startswith("@startuml") and stripped.endswith("@enduml")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def build_client():
    """Return an OpenAI client, or exit with actionable guidance.

    The client is a stateless HTTP session. It is reused across requests purely
    to avoid reopening connections; it never accumulates conversation state.
    """
    api_key = os.environ.get(cfg.OPENAI_API_KEY_ENV)
    if not api_key:
        raise SystemExit(
            f"{cfg.OPENAI_API_KEY_ENV} is not set.\n"
            f"  export {cfg.OPENAI_API_KEY_ENV}='sk-...'\n"
            "Run with --dry-run to inspect the pipeline without a key."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise SystemExit(
            "The OpenAI SDK is not installed. Install it with:\n"
            "  .venv/bin/pip install openai"
        ) from exc

    return OpenAI(api_key=api_key)


def _is_retryable(exc: Exception) -> bool:
    """Return ``True`` for transient transport/API failures worth re-sending."""
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        )
    except ImportError:  # pragma: no cover - only when SDK is absent
        return False
    return isinstance(
        exc, (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)
    )


def request_model(
    client, prompt: str, description: str, *, model: str
) -> Tuple[str, Dict, str]:
    """Send one independent request and return ``(text, usage, resolved_model)``.

    ``messages`` is constructed fresh here on every call, from the fixed prompt
    and this one description only. There is no state shared with any other
    generation.
    """
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": description},
    ]

    # No tools are offered. Asserted rather than merely omitted, so a future
    # edit cannot quietly introduce an external information source.
    assert not cfg.GENERATION_TOOLS_ENABLED, (
        "Tool use must stay disabled: generation may depend only on the fixed "
        "prompt and the single description."
    )

    kwargs: Dict[str, Any] = {"model": model, "input": messages, "tools": []}
    if cfg.GENERATION_TEMPERATURE is not None:
        kwargs["temperature"] = cfg.GENERATION_TEMPERATURE
    if cfg.GENERATION_TOP_P is not None:
        kwargs["top_p"] = cfg.GENERATION_TOP_P
    if cfg.GENERATION_MAX_OUTPUT_TOKENS is not None:
        kwargs["max_output_tokens"] = cfg.GENERATION_MAX_OUTPUT_TOKENS

    # Reasoning controls, sent only when configured so that models which do not
    # accept them are unaffected.
    reasoning = {}
    if cfg.GENERATION_REASONING_EFFORT is not None:
        reasoning["effort"] = cfg.GENERATION_REASONING_EFFORT
    if cfg.GENERATION_REASONING_MODE is not None:
        reasoning["mode"] = cfg.GENERATION_REASONING_MODE
    if reasoning:
        kwargs["reasoning"] = reasoning

    response = client.responses.create(**kwargs)

    text = getattr(response, "output_text", "") or ""

    # The Responses API names its token counts input/output rather than
    # prompt/completion; accept either so the log stays comparable across runs.
    usage_obj = getattr(response, "usage", None)

    def _count(*names):
        for name in names:
            value = getattr(usage_obj, name, None)
            if value is not None:
                return value
        return None

    details = getattr(usage_obj, "output_tokens_details", None)
    usage = {
        "prompt_tokens": _count("input_tokens", "prompt_tokens"),
        "completion_tokens": _count("output_tokens", "completion_tokens"),
        "total_tokens": _count("total_tokens"),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }
    # ``model`` in the response is the dated snapshot the alias resolved to.
    resolved = getattr(response, "model", "") or ""
    return text, usage, resolved


def generate_one(client, task: Task, prompt: str, *, model: str) -> Outcome:
    """Generate and save exactly one model for ``task``.

    Retries re-send the identical request on transient failures only.
    """
    last_error = ""
    for attempt in range(1, cfg.GENERATION_MAX_RETRIES + 1):
        try:
            description = task.description_path.read_text(encoding="utf-8")
            text, usage, resolved = request_model(client, prompt, description, model=model)
        except Exception as exc:  # noqa: BLE001 - SDK raises a range of types
            last_error = f"{type(exc).__name__}: {exc}"
            if _is_retryable(exc) and attempt < cfg.GENERATION_MAX_RETRIES:
                delay = cfg.GENERATION_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                LOGGER.warning(
                    "%s/%s: transient failure (attempt %d/%d), resending identical "
                    "request in %.1fs: %s",
                    task.case_id, task.version, attempt, cfg.GENERATION_MAX_RETRIES,
                    delay, last_error,
                )
                time.sleep(delay)
                continue
            LOGGER.error("%s/%s: generation failed: %s", task.case_id, task.version, last_error)
            return Outcome("error", attempt, None, _empty_usage(), last_error)

        model_text = strip_code_fences(text)
        format_ok = check_format(model_text)

        # The response is saved exactly as returned (minus any code fence).
        # A malformed model is a real experimental observation, not something
        # to repair or regenerate.
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(model_text + "\n", encoding="utf-8")

        if not format_ok:
            LOGGER.warning(
                "%s/%s: response is not wrapped in @startuml/@enduml — saved unmodified",
                task.case_id, task.version,
            )
        return Outcome("generated", attempt, format_ok, usage, "", resolved)

    return Outcome("error", cfg.GENERATION_MAX_RETRIES, None, _empty_usage(), last_error)


def _empty_usage() -> Dict[str, Optional[int]]:
    """Return a usage dict with all fields unset."""
    return {
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "total_tokens": None,
    }


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _migrate_log_header() -> None:
    """Rewrite the log with the current columns if its header is out of date.

    The log is append-only across runs, so a schema change would otherwise
    write rows that do not line up with the existing header. Older rows are
    preserved and the new fields are left blank for them.
    """
    if not cfg.GENERATION_LOG.exists():
        return
    with cfg.GENERATION_LOG.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames == cfg.GENERATION_LOG_COLUMNS:
            return
        old_rows = list(reader)

    LOGGER.info(
        "migrating %s to the current column set (%d existing row(s) preserved)",
        _rel(cfg.GENERATION_LOG), len(old_rows),
    )
    with cfg.GENERATION_LOG.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cfg.GENERATION_LOG_COLUMNS)
        writer.writeheader()
        for row in old_rows:
            writer.writerow({key: row.get(key, "") for key in cfg.GENERATION_LOG_COLUMNS})


def append_log_row(
    task: Task, outcome: Outcome, *, model: str, prompt_hash: str, description_hash: str
) -> None:
    """Append one row to the machine-readable generation log."""
    cfg.GENERATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    _migrate_log_header()
    is_new = not cfg.GENERATION_LOG.exists()

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "case_id": task.case_id,
        "version": task.version,
        "run": cfg.DEFAULT_RUN,
        "provider": cfg.PROVIDER,
        "api_model": model,
        "api_model_resolved": outcome.resolved_model,
        "temperature": cfg.GENERATION_TEMPERATURE,
        "top_p": cfg.GENERATION_TOP_P if cfg.GENERATION_TOP_P is not None else "api-default",
        "reasoning_effort": cfg.GENERATION_REASONING_EFFORT,
        "reasoning_mode": cfg.GENERATION_REASONING_MODE,
        "tools": "none",
        "max_output_tokens": cfg.GENERATION_MAX_OUTPUT_TOKENS,
        "input_description": _rel(task.description_path),
        "generated_plantuml": _rel(task.output_path),
        "prompt_file": _rel(cfg.MODEL_GENERATION_PROMPT_FILE),
        "prompt_sha256": prompt_hash,
        "description_sha256": description_hash,
        "status": outcome.status,
        "attempts": outcome.attempts,
        "format_ok": outcome.format_ok,
        "prompt_tokens": outcome.usage.get("prompt_tokens"),
        "completion_tokens": outcome.usage.get("completion_tokens"),
        "reasoning_tokens": outcome.usage.get("reasoning_tokens"),
        "total_tokens": outcome.usage.get("total_tokens"),
        "error": outcome.error,
    }

    with cfg.GENERATION_LOG.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=cfg.GENERATION_LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Validation (technical completeness and formatting only)
# ---------------------------------------------------------------------------


def validate(tasks: List[Task]) -> Tuple[List[str], List[str]]:
    """Return ``(errors, warnings)`` describing technical completeness.

    This deliberately never looks at the reference models — it checks counts,
    the description/output mapping and PlantUML delimiters, nothing semantic.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Exactly 225 descriptions, and every case complete.
    case_ids = cfg.iter_case_ids()
    descriptions = [t for t in discover_tasks() if t.description_path.is_file()]
    if len(descriptions) != cfg.EXPECTED_MODEL_COUNT:
        errors.append(
            f"expected {cfg.EXPECTED_MODEL_COUNT} descriptions, found {len(descriptions)}"
        )
    for case_id in case_ids:
        missing = [
            v for v in cfg.VERSIONS if not cfg.description_path(case_id, v).is_file()
        ]
        if missing:
            errors.append(f"{case_id}: missing description(s) {', '.join(missing)}")

    # No duplicate case/version combinations.
    seen = set()
    for task in tasks:
        key = (task.case_id, task.version)
        if key in seen:
            errors.append(f"duplicate case/version combination: {key[0]}/{key[1]}")
        seen.add(key)

    # Every generated output maps back to a description, and is well-formed.
    generated = 0
    for task in discover_tasks():
        if not task.output_path.is_file():
            continue
        generated += 1
        if not task.description_path.is_file():
            errors.append(
                f"{task.case_id}/{task.version}: generated model has no source description"
            )
        text = task.output_path.read_text(encoding="utf-8").strip()
        if not text:
            errors.append(f"{task.case_id}/{task.version}: generated model is empty")
            continue
        if not text.startswith("@startuml"):
            errors.append(f"{task.case_id}/{task.version}: does not start with @startuml")
        if not text.endswith("@enduml"):
            errors.append(f"{task.case_id}/{task.version}: does not end with @enduml")

    # Orphan outputs: a .puml somewhere the mapping does not account for.
    expected_outputs = {t.output_path for t in discover_tasks()}
    for found in cfg.GENERATED_DIR.rglob("*.puml"):
        if found not in expected_outputs:
            errors.append(f"unexpected generated file (unmapped): {found}")

    if generated < cfg.EXPECTED_MODEL_COUNT:
        warnings.append(
            f"{generated}/{cfg.EXPECTED_MODEL_COUNT} models generated so far"
        )

    return errors, warnings


def report_validation(errors: List[str], warnings: List[str]) -> int:
    """Log validation findings and return a process exit code."""
    for message in warnings:
        LOGGER.warning(message)
    for message in errors:
        LOGGER.error(message)
    LOGGER.info("--- validation ---")
    LOGGER.info("errors   : %d", len(errors))
    LOGGER.info("warnings : %d", len(warnings))
    if not errors:
        LOGGER.info("technical validation passed")
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", action="append", dest="cases", help="Case id (repeatable).")
    parser.add_argument(
        "--version", action="append", dest="versions", choices=cfg.VERSIONS,
        help="Version to generate (repeatable).",
    )
    parser.add_argument("--limit", type=int, help="Process at most N descriptions.")
    parser.add_argument(
        "--model", default=cfg.OPENAI_MODEL,
        help=f"API model to use (default: {cfg.OPENAI_MODEL}).",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Regenerate models that already exist. Replaces experimental observations.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be generated. Makes no API calls and needs no API key.",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Run the technical completeness/format check and exit.",
    )
    parser.add_argument(
        "--output-root", type=Path,
        help=(
            "Directory tree to write models into (default: generated/). Use a "
            "separate root per model so two model sets can coexist."
        ),
    )
    parser.add_argument(
        "--run", type=int, default=cfg.DEFAULT_RUN,
        help=(
            "Run number recorded in the generation log (default: %(default)s). "
            "Use with --output-root to produce a repeated run of the same "
            "descriptions for estimating generation variability."
        ),
    )
    args = parser.parse_args(argv)

    cfg.DEFAULT_RUN = args.run

    # Redirect every generated-model path at once; cfg.generated_model_path()
    # reads GENERATED_DIR at call time, so this is the single point of control.
    if args.output_root is not None:
        cfg.GENERATED_DIR = args.output_root.expanduser().resolve()

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

    tasks = discover_tasks(args.cases, args.versions)

    if args.validate_only:
        return report_validation(*validate(tasks))

    # Skip descriptions that are missing or empty — never send an empty prompt.
    runnable: List[Task] = []
    for task in tasks:
        if not task.description_path.is_file():
            LOGGER.error("%s/%s: description missing", task.case_id, task.version)
            continue
        if not task.description_path.read_text(encoding="utf-8").strip():
            LOGGER.error("%s/%s: description is empty", task.case_id, task.version)
            continue
        runnable.append(task)

    existing = [t for t in runnable if t.output_path.is_file()]
    if existing and not args.overwrite:
        LOGGER.info(
            "%d model(s) already exist and will be skipped (use --overwrite to replace)",
            len(existing),
        )
        runnable = [t for t in runnable if not t.output_path.is_file()]
    elif existing:
        LOGGER.warning(
            "--overwrite: %d existing model(s) WILL be replaced", len(existing)
        )

    if args.limit is not None:
        runnable = runnable[: args.limit]

    prompt = load_prompt()
    prompt_hash = _sha256(prompt)

    LOGGER.info("model        : %s", args.model)
    LOGGER.info("temperature  : %s", cfg.GENERATION_TEMPERATURE)
    LOGGER.info("top_p        : %s", cfg.GENERATION_TOP_P or "api default (not sent)")
    LOGGER.info("reasoning    : effort=%s mode=%s",
                cfg.GENERATION_REASONING_EFFORT, cfg.GENERATION_REASONING_MODE)
    LOGGER.info("tools        : none")
    LOGGER.info("max tokens   : %s", cfg.GENERATION_MAX_OUTPUT_TOKENS)
    LOGGER.info("prompt       : %s (sha256 %s)",
                cfg.MODEL_GENERATION_PROMPT_FILE.name, prompt_hash[:12])
    LOGGER.info("to generate  : %d", len(runnable))

    if args.dry_run:
        for task in runnable:
            LOGGER.info(
                "would generate %s/%s -> %s",
                task.case_id, task.version,
                _rel(task.output_path),
            )
        LOGGER.info("--- dry run, no API calls made ---")
        return 0

    if not runnable:
        LOGGER.info("nothing to do")
        return 0

    client = build_client()

    generated = failed = malformed = 0
    for index, task in enumerate(runnable, start=1):
        LOGGER.info("[%d/%d] %s/%s", index, len(runnable), task.case_id, task.version)
        description = task.description_path.read_text(encoding="utf-8")
        outcome = generate_one(client, task, prompt, model=args.model)
        append_log_row(
            task, outcome,
            model=args.model,
            prompt_hash=prompt_hash,
            description_hash=_sha256(description),
        )
        if outcome.status == "generated":
            generated += 1
            if outcome.format_ok is False:
                malformed += 1
        else:
            failed += 1

    LOGGER.info("--- summary ---")
    LOGGER.info("generated        : %d", generated)
    LOGGER.info("failed           : %d", failed)
    LOGGER.info("malformed output : %d", malformed)
    LOGGER.info("log              : %s", _rel(cfg.GENERATION_LOG))

    errors, warnings = validate(discover_tasks())
    report_validation(errors, warnings)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
