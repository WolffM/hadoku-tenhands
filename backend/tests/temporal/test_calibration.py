"""Tests for the judge calibration harness — Phase 5.5.

The calibration script costs ~20 real claude CLI calls per run and isn't
appropriate for CI. These tests cover:
  - The agreement metric (`_agree`) at the threshold boundary
  - Dry-run + fixture loading via the `python -m temporal.calibration`
    module entry point (proves all 20 shipped fixtures parse cleanly)
"""

from __future__ import annotations

import importlib.util
import sys
from io import StringIO
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "temporal_judge_calibration.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "_calibration_under_test", _SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agree_passes_inside_threshold():
    m = _load_script_module()
    # 0.05 score gap, matching verdicts → agree
    assert m._agree(0.85, 0.80, "pass", "pass") is True


def test_agree_passes_at_threshold_boundary():
    """0.15 exactly should pass (epsilon protects floating-point math)."""
    m = _load_script_module()
    assert m._agree(0.85, 0.70, "pass", "pass") is True


def test_agree_fails_above_threshold():
    m = _load_script_module()
    # 0.20 gap → fail
    assert m._agree(0.90, 0.70, "pass", "pass") is False


def test_agree_fails_on_verdict_mismatch_even_with_close_score():
    """Score within tolerance but verdicts differ → agreement fails.
    Critical: a 0.74-pass vs 0.74-defer is exactly the boundary case the
    operator wants to catch (judge thinks borderline → pass, operator
    thinks borderline → defer)."""
    m = _load_script_module()
    assert m._agree(0.75, 0.74, "pass", "defer") is False


def test_dry_run_loads_all_20_fixtures(capsys):
    """Smoke test the shipped fixture set: dry-run should report 20."""
    m = _load_script_module()
    rc = m.main(["--dry-run"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "Loaded 20 fixture(s)" in err


def test_dry_run_filters_by_rubric(capsys):
    m = _load_script_module()
    rc = m.main(["--dry-run", "--rubric", "relevance_v1"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "Loaded 10 fixture(s)" in err

    rc = m.main(["--dry-run", "--rubric", "submission_v1"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "Loaded 10 fixture(s)" in err


def test_module_entry_point_delegates_to_script():
    """`python -m temporal.calibration` resolves to the same main()."""
    sys.path.insert(0, str(_REPO_ROOT / "backend"))
    try:
        from temporal import calibration  # noqa: PLC0415
    finally:
        sys.path.pop(0)
    assert callable(calibration.main)
    rc = calibration.main(["--dry-run", "--rubric", "relevance_v1"])
    assert rc == 0
