"""Smoke test for scripts/temporal_judge_calibration.py — Phase 1E.5.

The calibration harness itself doesn't run real claude calls in CI (each
real run is 20+ subprocess invocations costing real subscription quota).
This test verifies the script:
  - imports cleanly
  - dry-runs cleanly with a temp fixtures directory
  - the agreement helper produces the right verdicts
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import temporal_judge_calibration as cal  # noqa: E402


def test_agree_within_threshold():
    assert cal._agree(0.85, 0.90, "pass", "pass") is True
    assert cal._agree(0.70, 0.85, "pass", "pass") is True  # exactly 0.15
    assert cal._agree(0.69, 0.85, "pass", "pass") is False  # 0.16
    assert cal._agree(0.85, 0.85, "pass", "fail") is False  # verdict mismatch
    assert cal._agree(0.30, 0.30, "fail", "fail") is True


def test_load_fixtures_filters_by_rubric(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "_FIXTURES_DIR", tmp_path)
    (tmp_path / "a.json").write_text(json.dumps({
        "rubric": "relevance_v1",
        "input": "x",
        "operator_verdict": "pass",
        "operator_score": 0.9,
    }))
    (tmp_path / "b.json").write_text(json.dumps({
        "rubric": "submission_v1",
        "input": "y",
        "operator_verdict": "fail",
        "operator_score": 0.2,
    }))

    all_fx = cal._load_fixtures(None)
    assert len(all_fx) == 2

    rel_only = cal._load_fixtures("relevance_v1")
    assert len(rel_only) == 1
    assert rel_only[0][1]["rubric"] == "relevance_v1"


def test_main_returns_2_when_no_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(cal, "_FIXTURES_DIR", tmp_path)
    rc = cal.main(["--dry-run"])
    assert rc == 2


def test_main_dry_run_reports_each_fixture(tmp_path, monkeypatch, capfd):
    monkeypatch.setattr(cal, "_FIXTURES_DIR", tmp_path)
    (tmp_path / "fixture1.json").write_text(json.dumps({
        "rubric": "relevance_v1",
        "input": "test input",
        "operator_verdict": "pass",
        "operator_score": 0.9,
        "notes": "clean",
    }))
    rc = cal.main(["--dry-run"])
    assert rc == 0
    out = capfd.readouterr()
    assert "fixture1.json" in out.out + out.err
