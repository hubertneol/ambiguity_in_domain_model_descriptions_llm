#!/usr/bin/env python3
"""Generate the comparison model set using gpt-4o.

The experiment's primary set is produced by ``generate_models.py`` using the
model configured in ``config/experiment_config.py``. This script produces a
second, parallel set with ``gpt-4o`` so the two can be compared.

It deliberately contains no generation logic of its own: it adjusts the three
settings that differ for ``gpt-4o`` and then delegates to
``generate_models.main``. Prompt handling, request isolation, retry policy,
output handling, logging and validation are therefore identical for both sets
by construction, and cannot drift apart.

What differs from the primary configuration
-------------------------------------------
============  =================  ===============================
setting       gpt-5.6-sol        gpt-4o
============  =================  ===============================
temperature   not supported      0.0
reasoning     effort=medium      not supported
output root   generated/         generated_gpt4o/
============  =================  ===============================

Both sets use the same fixed prompt, so the model is the only variable that
differs between them.

Usage
-----
    python scripts/generate_models_gpt4o.py --dry-run
    python scripts/generate_models_gpt4o.py --case AirTravel --version V0
    python scripts/generate_models_gpt4o.py            # full comparison set

Any flag accepted by generate_models.py may be passed through, except
``--model`` and ``--output-root``, which this script sets.

Evaluate the resulting set with::

    python scripts/evaluate_models.py --generated-root generated_gpt4o \\
        --output results/records_gpt4o.jsonl
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import experiment_config as cfg  # noqa: E402
import generate_models  # noqa: E402

LOGGER = logging.getLogger("generate_models_gpt4o")

#: The comparison model, and the tree its output lives in.
COMPARISON_MODEL = "gpt-4o"
COMPARISON_OUTPUT_ROOT = cfg.PROJECT_ROOT / "generated_gpt4o"

#: gpt-4o accepts a temperature and has no reasoning controls — the reverse of
#: the primary model. Setting these here keeps the difference in one place.
COMPARISON_TEMPERATURE = 0.0
COMPARISON_REASONING_EFFORT = None
COMPARISON_REASONING_MODE = None


def main(argv: Optional[List[str]] = None) -> int:
    """Apply the gpt-4o settings, then run the shared generation pipeline."""
    argv = list(sys.argv[1:] if argv is None else argv)

    for flag in ("--model", "--output-root"):
        if flag in argv:
            raise SystemExit(
                f"{flag} is set by this script and cannot be overridden. "
                "Use scripts/generate_models.py directly for other models."
            )

    # These module-level values are read at request-build time, so overriding
    # them here reconfigures the shared pipeline without duplicating it.
    cfg.GENERATION_TEMPERATURE = COMPARISON_TEMPERATURE
    cfg.GENERATION_REASONING_EFFORT = COMPARISON_REASONING_EFFORT
    cfg.GENERATION_REASONING_MODE = COMPARISON_REASONING_MODE

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    LOGGER.info("comparison set : %s -> %s",
                COMPARISON_MODEL, COMPARISON_OUTPUT_ROOT.name)

    return generate_models.main(
        argv + ["--model", COMPARISON_MODEL,
                "--output-root", str(COMPARISON_OUTPUT_ROOT)]
    )


if __name__ == "__main__":
    raise SystemExit(main())
