#!/usr/bin/env python3
"""Judge calibration harness — Phase 1E.5.

Runs the local `claude` CLI against the 20 hand-scored fixtures shipped
in `backend/temporal/calibration_fixtures/` and measures agreement with
the operator's verdicts.

The fixtures live as `.json` files with the shape:
    {
      "rubric": "relevance_v1" | "submission_v1",
      "input": "<the payload to score>",
      "operator_verdict": "pass" | "fail" | "defer",
      "operator_score": 0.0..1.0,
      "notes": "why the operator scored it this way"
    }

Agreement criterion (per phase-1-plan.md step 1E.5):
    - Each fixture passes if the judge's score is within ±0.15 of the
      operator's score AND the verdicts match
    - Overall agreement rate must be ≥ 80% on each rubric

Usage:
    python3 scripts/temporal_judge_calibration.py
    python3 scripts/temporal_judge_calibration.py --rubric relevance_v1
    python3 scripts/temporal_judge_calibration.py --csv-out calibration.csv
    python3 scripts/temporal_judge_calibration.py --dry-run

Requires:
    - claude CLI installed on PATH
    - CLAUDE_CODE_OAUTH_TOKEN set in env or .env

This is intentionally NOT a pytest test — it costs ~20 real claude calls
per run and the operator decides when to trigger it. Run after every
rubric edit to verify the rubric still matches operator intent.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
_FIXTURES_DIR = _BACKEND / "temporal" / "calibration_fixtures"
_RUBRICS_DIR = _BACKEND / "temporal" / "rubrics"

# Add backend/ to sys.path so we can import temporal.judge
sys.path.insert(0, str(_BACKEND))


def _load_env() -> None:
    """Best-effort .env load so the script works outside pm2."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


_AGREEMENT_THRESHOLD = 0.15
_FLOAT_EPSILON = 1e-9


def _agree(judge_score: float, op_score: float, judge_verdict: str, op_verdict: str) -> bool:
    """Per phase-1-plan: within ±0.15 score AND matching verdict.

    Tiny epsilon on the threshold check so floating-point representations
    of decimal values (e.g. 0.85 - 0.70 = 0.15000000000000002) don't trip
    the boundary.
    """
    return (
        abs(judge_score - op_score) <= _AGREEMENT_THRESHOLD + _FLOAT_EPSILON
        and judge_verdict == op_verdict
    )


def _load_fixtures(rubric_filter: str | None) -> list[tuple[Path, dict]]:
    if not _FIXTURES_DIR.exists():
        return []
    out = []
    for fp in sorted(_FIXTURES_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ! skipping {fp.name}: {e}", file=sys.stderr)
            continue
        if rubric_filter and data.get("rubric") != rubric_filter:
            continue
        out.append((fp, data))
    return out


def _load_rubric(name: str) -> str:
    return (_RUBRICS_DIR / f"{name}.md").read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", choices=("relevance_v1", "submission_v1"), default=None)
    parser.add_argument("--csv-out", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    _load_env()

    fixtures = _load_fixtures(args.rubric)
    if not fixtures:
        print(
            f"No fixtures found in {_FIXTURES_DIR}. Add hand-scored .json files to "
            f"this directory before running calibration. See the docstring for the "
            f"expected schema.",
            file=sys.stderr,
        )
        return 2

    print(f"Loaded {len(fixtures)} fixture(s)", file=sys.stderr)

    if args.dry_run:
        print("[dry-run] would call claude CLI for each fixture; exiting", file=sys.stderr)
        for fp, fx in fixtures:
            print(f"  - {fp.name}: rubric={fx.get('rubric')} op={fx.get('operator_verdict')} score={fx.get('operator_score')}")
        return 0

    from temporal.judge import (  # noqa: E402
        JudgeError,
        score as judge_score,
    )

    results: list[dict] = []
    by_rubric: dict[str, list[bool]] = {}

    for fp, fx in fixtures:
        rubric_name = fx.get("rubric") or "relevance_v1"
        rubric_text = _load_rubric(rubric_name)
        try:
            jr = judge_score(rubric_text, fx.get("input", ""))
        except JudgeError as e:
            print(f"  ! {fp.name}: judge error: {e}", file=sys.stderr)
            results.append({
                "fixture": fp.name,
                "rubric": rubric_name,
                "judge_verdict": "ERROR",
                "judge_score": "",
                "op_verdict": fx.get("operator_verdict"),
                "op_score": fx.get("operator_score"),
                "agree": False,
            })
            by_rubric.setdefault(rubric_name, []).append(False)
            continue

        agree = _agree(
            jr.score,
            float(fx.get("operator_score", 0)),
            jr.verdict,
            str(fx.get("operator_verdict", "")),
        )
        results.append({
            "fixture": fp.name,
            "rubric": rubric_name,
            "judge_verdict": jr.verdict,
            "judge_score": jr.score,
            "op_verdict": fx.get("operator_verdict"),
            "op_score": fx.get("operator_score"),
            "agree": agree,
        })
        by_rubric.setdefault(rubric_name, []).append(agree)
        marker = "✓" if agree else "✗"
        print(
            f"  {marker} {fp.name:30s}  judge={jr.verdict}/{jr.score:.2f}  "
            f"op={fx.get('operator_verdict')}/{fx.get('operator_score')}",
            file=sys.stderr,
        )

    print(file=sys.stderr)
    print("Per-rubric agreement:", file=sys.stderr)
    overall_pass = True
    for rubric, agreements in by_rubric.items():
        rate = sum(agreements) / len(agreements)
        ok = rate >= 0.80
        overall_pass = overall_pass and ok
        marker = "PASS" if ok else "FAIL"
        print(f"  {rubric}: {sum(agreements)}/{len(agreements)} = {rate:.0%}  [{marker}]", file=sys.stderr)

    if args.csv_out:
        with open(args.csv_out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["fixture", "rubric", "judge_verdict", "judge_score", "op_verdict", "op_score", "agree"])
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"  csv: {args.csv_out}", file=sys.stderr)

    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
