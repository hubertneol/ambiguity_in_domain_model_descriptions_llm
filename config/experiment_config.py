"""Central configuration for the controlled UML domain-model experiment.

This module is the single source of truth for

* the experimental design constants (versions, case count, runs, metric),
* every project-relative path,
* the long-form result schema.

All paths are derived from :data:`PROJECT_ROOT` via :mod:`pathlib`, so the
project stays relocatable — no machine-specific absolute path is stored here.

The one input that *does* live outside the project is the original benchmark
corpus. Its location is supplied at call time (``--source`` or the
``BENCHMARK_SOURCE_DIR`` environment variable), never hardcoded.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Final, List, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: Natural-language experiment inputs only (V0-V4 descriptions). This is the
#: only artefact directory the variant-writing and model-generating stages see.
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"

#: Ground-truth UML models, kept out of ``data/`` so they cannot leak into the
#: generation stages. Relevant only during evaluation.
REFERENCE_MODELS_DIR: Final[Path] = PROJECT_ROOT / "reference_models"

GENERATED_DIR: Final[Path] = PROJECT_ROOT / "generated"
PROMPTS_DIR: Final[Path] = PROJECT_ROOT / "prompts"
PATTERNS_DIR: Final[Path] = PROJECT_ROOT / "patterns"
RESULTS_DIR: Final[Path] = PROJECT_ROOT / "results"
SCRIPTS_DIR: Final[Path] = PROJECT_ROOT / "scripts"
CONFIG_DIR: Final[Path] = PROJECT_ROOT / "config"

# ---------------------------------------------------------------------------
# Isolated variant-generation workspace
#
# A self-contained copy of exactly what the text-variant stage may see:
# descriptions and the four transformation prompts. It deliberately excludes
# reference_models/, generated/, results/ and the model-generation prompt, so
# the workspace can be handed to an external agent without exposing ground
# truth. It is a copy, never a relocation — the project tree stays canonical.
# ---------------------------------------------------------------------------

VARIANT_WORKSPACE_DIR: Final[Path] = PROJECT_ROOT / "variant_generation_workspace"
WORKSPACE_DATA_DIR: Final[Path] = VARIANT_WORKSPACE_DIR / "data"
WORKSPACE_PROMPTS_DIR: Final[Path] = VARIANT_WORKSPACE_DIR / "prompts"

# ---------------------------------------------------------------------------
# Experimental design (fixed)
# ---------------------------------------------------------------------------

VERSIONS: Final[List[str]] = ["V0", "V1", "V2", "V3", "V4"]
BASELINE_VERSION: Final[str] = "V0"
DERIVED_VERSIONS: Final[List[str]] = ["V1", "V2", "V3", "V4"]

VERSION_LABELS: Final[Dict[str, str]] = {
    "V0": "baseline / original description",
    "V1": "implicit information",
    "V2": "non-syntactic ambiguity",
    "V3": "semantic anomaly",
    "V4": "paraphrase relation",
}

CASE_COUNT: Final[int] = 45
RUNS_PER_VERSION: Final[int] = 1
METRIC_NAME: Final[str] = "metrik-4"

#: 45 cases x 5 versions x 1 run = 225 generated UML models.
EXPECTED_MODEL_COUNT: Final[int] = CASE_COUNT * len(VERSIONS) * RUNS_PER_VERSION

# ---------------------------------------------------------------------------
# Generation provenance
#
# The current experiment uses a single provider and a single run per version,
# but every result row carries these fields so the design stays extensible.
# ---------------------------------------------------------------------------

PROVIDER: Final[str] = "ChatGPT"
DEFAULT_RUN: Final[int] = 1

# ---------------------------------------------------------------------------
# OpenAI generation settings
#
# These are the knobs that define the generation condition. They are fixed for
# all 225 requests — changing one mid-experiment would make the observations
# incomparable, so they live here rather than being scattered across the
# script.
# ---------------------------------------------------------------------------

#: Environment variable holding the API credential. Never store the key here.
OPENAI_API_KEY_ENV: Final[str] = "OPENAI_API_KEY"

#: The model used for every generation.
#:
#: IMPORTANT: verify this is the exact model you intend to cite in the thesis
#: before running the full experiment, and keep it unchanged for all 225
#: requests. Override per-run with ``--model``; the value actually used is
#: recorded for every request in the generation log.
OPENAI_MODEL: Final[str] = "gpt-5.6-sol"

#: Sampling temperature. ``None`` omits the parameter entirely.
#:
#: Set to ``None`` because ``gpt-5.6-sol`` rejects the parameter outright
#: ("Unsupported parameter: 'temperature' is not supported with this model").
#: Sampling therefore runs at the model's own fixed setting and cannot be
#: constrained from here. See the note on replication in the report: with one
#: generation per condition and no temperature control, the residual generation
#: noise is unmeasured.
#:
#: Use 0.0 only with models that accept it (e.g. gpt-4o).
GENERATION_TEMPERATURE: Final[Optional[float]] = None

#: Nucleus sampling. Deliberately ``None`` so the parameter is never sent:
#: randomness is controlled through temperature alone, and truncating the
#: distribution by both mechanisms at once would make the sampling behaviour
#: hard to reason about.
GENERATION_TOP_P: Final[Optional[float]] = None

#: Reasoning controls for reasoning-capable models. ``None`` omits the whole
#: ``reasoning`` object, which is required by models that do not accept it.
#:
#: ``effort`` fixes the reasoning budget at a documented level rather than
#: leaving it implicit.
GENERATION_REASONING_EFFORT: Final[Optional[str]] = "medium"

#: ``mode`` is left unset: standard processing is the default, so omitting the
#: field selects it, and extended/Pro processing is never requested. Set this
#: to a string only if the API accepts an explicit ``reasoning.mode`` field.
GENERATION_REASONING_MODE: Final[Optional[str]] = None

#: Upper bound on response length. Set above the observed maximum for a
#: PlantUML diagram (574 completion tokens under gpt-4o) with headroom, because
#: on reasoning models the internal reasoning tokens are also charged against
#: this cap and would otherwise truncate the visible answer.
GENERATION_MAX_OUTPUT_TOKENS: Final[Optional[int]] = 8192

#: No tools are ever offered to the model. Generation must depend only on the
#: prompt and the description; a retrieval or code-execution tool could
#: introduce information from outside the experiment.
GENERATION_TOOLS_ENABLED: Final[bool] = False

#: Retries are for transient transport/API failures only (timeouts, 429, 5xx).
#: A retry re-sends the identical request; it never feeds a previous response
#: back to the model.
GENERATION_MAX_RETRIES: Final[int] = 3
GENERATION_RETRY_BASE_DELAY: Final[float] = 2.0

#: Recorded in every result row. These mirror the generation settings so the
#: evaluation output is self-describing.
MODEL_NAME: Final[str] = OPENAI_MODEL
TEMPERATURE: Final[Optional[float]] = GENERATION_TEMPERATURE

# ---------------------------------------------------------------------------
# File-naming conventions
# ---------------------------------------------------------------------------

REFERENCE_MODEL_FILENAME: Final[str] = "reference_model.puml"
GENERATED_MODEL_FILENAME: Final[str] = "generated_model.puml"

#: Filenames in a source benchmark case that may hold the domain description,
#: in order of preference.
SOURCE_DESCRIPTION_CANDIDATES: Final[List[str]] = [
    "description.md",
]

#: Filenames in a source benchmark case that may hold the reference PlantUML
#: model, in order of preference.
SOURCE_PLANTUML_CANDIDATES: Final[List[str]] = [
    "plantuml.txt",
]

#: Environment variable used to locate the read-only source benchmark corpus.
SOURCE_DIR_ENV_VAR: Final[str] = "BENCHMARK_SOURCE_DIR"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

VARIANT_PROMPT_FILES: Final[Dict[str, Path]] = {
    "V1": PROMPTS_DIR / "v1_implicit.txt",
    "V2": PROMPTS_DIR / "v2_non_syntactic_ambiguity.txt",
    "V3": PROMPTS_DIR / "v3_semantic_anomaly.txt",
    "V4": PROMPTS_DIR / "v4_paraphrase.txt",
}

MODEL_GENERATION_PROMPT_FILE: Final[Path] = PROMPTS_DIR / "model_generation_prompt.txt"

# ---------------------------------------------------------------------------
# Result schema (long form: one row per evaluated generated model)
# ---------------------------------------------------------------------------

RESULT_COLUMNS: Final[List[str]] = [
    "case_id",
    "version",
    "provider",
    "model_name",
    "run",
    "input_description",
    "reference_plantuml",
    "generated_plantuml",
    "prompt",
    "timestamp",
    "temperature",
    "class_score",
    "attribute_score",
    "association_score",
]

# ---------------------------------------------------------------------------
# Generation log (one row per API request attempt)
# ---------------------------------------------------------------------------

GENERATION_LOG: Final[Path] = RESULTS_DIR / "generation_log.csv"

GENERATION_LOG_COLUMNS: Final[List[str]] = [
    "timestamp",
    "case_id",
    "version",
    "run",
    "provider",
    "api_model",
    #: The model string the API actually resolved the request to. When
    #: ``api_model`` is an alias such as ``gpt-4o``, this records the dated
    #: snapshot behind it, so the run is reproducible from the log alone.
    "api_model_resolved",
    "temperature",
    "top_p",
    "reasoning_effort",
    "reasoning_mode",
    "tools",
    "max_output_tokens",
    "input_description",
    "generated_plantuml",
    "prompt_file",
    "prompt_sha256",
    "description_sha256",
    "status",
    "attempts",
    "format_ok",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "error",
]

#: Raw evaluation records, one JSON object per line. Written by
#: ``scripts/evaluate_models.py``, consumed by ``scripts/export_results.py``.
RESULTS_JSONL: Final[Path] = RESULTS_DIR / "records.jsonl"
RESULTS_CSV: Final[Path] = RESULTS_DIR / "results.csv"
RESULTS_XLSX: Final[Path] = RESULTS_DIR / "results.xlsx"

# ---------------------------------------------------------------------------
# Path helpers
#
# Every script addresses artefacts through these functions so path logic is
# defined exactly once.
# ---------------------------------------------------------------------------


def validate_version(version: str) -> str:
    """Return ``version`` unchanged, raising ``ValueError`` if it is unknown."""
    if version not in VERSIONS:
        raise ValueError(
            f"Unknown version {version!r}. Expected one of: {', '.join(VERSIONS)}"
        )
    return version


def case_dir(case_id: str) -> Path:
    """Return the input directory holding all descriptions for ``case_id``."""
    return DATA_DIR / case_id


def description_path(case_id: str, version: str) -> Path:
    """Return the path of the ``version`` description text for ``case_id``."""
    return case_dir(case_id) / f"{validate_version(version)}.txt"


def reference_case_dir(case_id: str) -> Path:
    """Return the directory holding the reference model for ``case_id``."""
    return REFERENCE_MODELS_DIR / case_id


def reference_model_path(case_id: str) -> Path:
    """Return the path of the reference PlantUML model for ``case_id``.

    Reference models live under ``reference_models/``, deliberately outside
    ``data/``, so the stages that write V1-V4 and generate UML never see the
    ground truth.
    """
    return reference_case_dir(case_id) / REFERENCE_MODEL_FILENAME


def workspace_case_dir(case_id: str) -> Path:
    """Return the workspace directory holding the descriptions for ``case_id``."""
    return WORKSPACE_DATA_DIR / case_id


def workspace_description_path(case_id: str, version: str) -> Path:
    """Return the workspace path of the ``version`` description for ``case_id``."""
    return workspace_case_dir(case_id) / f"{validate_version(version)}.txt"


def legacy_reference_model_path(case_id: str) -> Path:
    """Return the pre-refactor reference-model location inside ``data/``.

    Used only by validation, to flag ground-truth files that would leak into
    the natural-language input directory.
    """
    return case_dir(case_id) / REFERENCE_MODEL_FILENAME


def generated_version_dir(case_id: str, version: str) -> Path:
    """Return the directory holding the generated model for a case/version."""
    return GENERATED_DIR / case_id / validate_version(version)


def generated_model_path(case_id: str, version: str) -> Path:
    """Return the path of the generated PlantUML model for a case/version.

    The current experiment stores exactly one model per (case, version). The
    surrounding schema still records ``provider``/``model_name``/``run``, so a
    future multi-run design can extend this layout without changing call sites
    elsewhere.
    """
    return generated_version_dir(case_id, version) / GENERATED_MODEL_FILENAME


def iter_case_ids() -> List[str]:
    """Return the sorted case ids currently present under ``data/``.

    Case ids are the benchmark's own folder names (e.g. ``AirTravel``), not
    generic indices, so results stay traceable to the source corpus.
    """
    if not DATA_DIR.is_dir():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def source_root_from_env() -> Optional[Path]:
    """Return the source benchmark directory from the environment, if set."""
    raw = os.environ.get(SOURCE_DIR_ENV_VAR)
    return Path(raw).expanduser() if raw else None
