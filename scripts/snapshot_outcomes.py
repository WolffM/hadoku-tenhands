"""Snapshot upstream outcomes for every dispatched issue — Phase 0 / M0.3.

Walks state/<batch>/<issue>/ and runs the outcome classifier against each
issue. Terminal evidence (11-merged/, 11-closed_by_upstream/) reads from
disk; open PRs get one live GH poll. Writes outcomes/upstream_state.json
under each issue's state root.

Designed as a one-shot script for the baseline-snapshot pass over the May
2026 23-pass cohort, AND as the daily cron entry point once Phase 0 settles.

Usage:
  python3 scripts/snapshot_outcomes.py                     # all issues
  python3 scripts/snapshot_outcomes.py --batch <id>        # one batch
  python3 scripts/snapshot_outcomes.py --reached-submission # only those
                                                           # that shipped upstream
  python3 scripts/snapshot_outcomes.py --dry-run           # classify but
                                                           # don't write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from temporal.activities.outcome_snapshot import classify_outcome, write_outcome_snapshot  # noqa: E402
from temporal.evidence.store import EvidenceStore  # noqa: E402


def _state_root() -> Path:
    return REPO_ROOT / "state"


def _iter_issue_dirs(batch_filter: str | None) -> list[tuple[str, str, Path]]:
    """Yield (batch_id, issue_id, dir) for every issue dir under state/."""
    root = _state_root()
    if not root.exists():
        return []
    out: list[tuple[str, str, Path]] = []
    for batch_dir in sorted(root.iterdir()):
        if not batch_dir.is_dir():
            continue
        if batch_filter and batch_dir.name != batch_filter:
            continue
        for issue_dir in sorted(batch_dir.iterdir()):
            if issue_dir.is_dir():
                out.append((batch_dir.name, issue_dir.name, issue_dir))
    return out


def _reached_submission(ev: EvidenceStore) -> bool:
    """Did this issue actually reach upstream submission?"""
    return ev.exists("10-submitted/upstream_pr_url")


def _passed_submission_judge(ev: EvidenceStore) -> bool:
    """Did this issue pass submission_judge (regardless of operator decision)?

    A pass means submission_judge wrote its evidence AND the gate didn't
    fail. Used to scope reports to the cohort the plan's success metric
    cares about.
    """
    if not ev.exists("09-submittable/submission_judge.json"):
        return False
    judge = ev.read_json("09-submittable/submission_judge.json")
    if not isinstance(judge, dict):
        return False
    return judge.get("verdict") in ("pass", "defer")  # defers reached the inbox


def _summarize(results: list[dict]) -> None:
    """Print state counts + the 23-pass-cohort focused breakdown."""
    print()
    print("=" * 60)
    print(f"  TOTAL CLASSIFIED: {len(results)}")
    print("=" * 60)

    states = Counter(r["snapshot"]["state"] for r in results)
    print()
    print("By state (all issues):")
    for state, n in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"  {state:25s}  {n:>4d}")

    # Focus: issues that passed submission_judge (regardless of whether
    # they reached upstream submission). This is the "23-pass cohort" the
    # plan's success metric anchors on.
    judged_pass = [r for r in results if r["passed_judge"]]
    print()
    print(f"Submission-judge cohort: {len(judged_pass)} issues passed/deferred at submission_judge")
    cohort_states = Counter(r["snapshot"]["state"] for r in judged_pass)
    for state, n in sorted(cohort_states.items(), key=lambda kv: -kv[1]):
        print(f"  {state:25s}  {n:>4d}")

    # Issues that actually shipped upstream — subset of the cohort
    shipped = [r for r in judged_pass if r["reached_submission"]]
    print()
    print(f"Shipped upstream: {len(shipped)} issues reached 10-submitted/")
    if shipped:
        shipped_states = Counter(r["snapshot"]["state"] for r in shipped)
        for state, n in sorted(shipped_states.items(), key=lambda kv: -kv[1]):
            print(f"  {state:25s}  {n:>4d}")

    # Open + stale breakdowns
    open_results = [r for r in results if r["snapshot"]["state"] == "open"]
    if open_results:
        print()
        print(f"Currently open: {len(open_results)}")
        stale_30 = sum(1 for r in open_results if r["snapshot"]["stale_30d_at_snapshot"])
        stale_90 = sum(1 for r in open_results if r["snapshot"]["stale_90d_at_snapshot"])
        print(f"  stale_30d: {stale_30}")
        print(f"  stale_90d: {stale_90}")

    # Anything stuck in unknown — surface errors
    unknown = [r for r in results if r["snapshot"]["state"] == "unknown"]
    if unknown:
        print()
        print(f"!! {len(unknown)} issues with state=unknown (live-poll errors):")
        for r in unknown[:5]:
            print(f"  {r['batch_id']}/{r['issue_id']}: {r['snapshot'].get('errors', [])}")
        if len(unknown) > 5:
            print(f"  ... and {len(unknown) - 5} more")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Snapshot upstream PR outcomes for every dispatched issue.")
    ap.add_argument("--batch", help="Limit to one batch_id")
    ap.add_argument(
        "--reached-submission",
        action="store_true",
        help="Only issues with 10-submitted/upstream_pr_url",
    )
    ap.add_argument(
        "--passed-judge",
        action="store_true",
        help="Only issues that passed/deferred at submission_judge",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify but don't write outcomes/upstream_state.json",
    )
    args = ap.parse_args(argv)

    issues = _iter_issue_dirs(args.batch)
    if not issues:
        print(f"No issues found under state/" + (f"{args.batch}/" if args.batch else ""))
        return 1

    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for batch_id, issue_id, d in issues:
        ev = EvidenceStore(d)
        passed_judge = _passed_submission_judge(ev)
        reached_sub = _reached_submission(ev)

        if args.passed_judge and not passed_judge:
            continue
        if args.reached_submission and not reached_sub:
            continue

        try:
            snapshot = classify_outcome(ev, now=now)
        except Exception as e:
            print(f"  ERROR  {batch_id}/{issue_id}: {type(e).__name__}: {e}")
            continue

        if not args.dry_run:
            write_outcome_snapshot(ev, snapshot)

        results.append({
            "batch_id": batch_id,
            "issue_id": issue_id,
            "snapshot": snapshot,
            "passed_judge": passed_judge,
            "reached_submission": reached_sub,
        })
        marker = ("●" if snapshot["snapshot_source"] == "live_poll" else "·")
        print(f"  {marker} {batch_id}/{issue_id:50s}  {snapshot['state']}")

    _summarize(results)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
