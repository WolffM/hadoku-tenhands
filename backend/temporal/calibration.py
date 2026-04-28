"""Module entry point for `python -m temporal.calibration`.

Phase 5.5 of the crimson-kitty plan documents the calibration harness as
`python -m temporal.calibration --rubric <name>`. The actual implementation
lives in `scripts/temporal_judge_calibration.py` (one level above
`backend/`) so the operator can run it without `cd`-ing into backend.
This module is a thin shim that imports the script's `main()` and forwards
argv. Either invocation works.

Usage:
    python -m temporal.calibration                       # all fixtures
    python -m temporal.calibration --rubric relevance_v1
    python -m temporal.calibration --rubric submission_v1
    python -m temporal.calibration --dry-run
    python -m temporal.calibration --csv-out cal.csv
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "temporal_judge_calibration.py"
)


def _load_script_main():
    spec = importlib.util.spec_from_file_location(
        "temporal_judge_calibration", _SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load calibration script from {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def main(argv: list[str] | None = None) -> int:
    return _load_script_main()(argv)


if __name__ == "__main__":
    sys.exit(main())
