"""Run actionability_v1 against the 54-decision operator corpus.

Task #55 from the dispatch-readiness-overhaul plan. Goes beyond the
5-issue smoke (task #54) to validate the rubric at scale against every
historical operator decision we have.

Cohort (from M0.3 baseline outcomes):
  - 34 issues: passed/deferred at submission_judge, never operator-approved
    (the silent "don't ship" decision)
  - 20 issues: passed/deferred at judge, operator explicitly aborted

Compares rubric verdict against the operator's implicit decision:
  - operator "did not ship"  → rubric SHOULD lean fail/defer
  - operator "explicit abort" → rubric SHOULD agree with abort

Re-uses the smoke script's payload-building helpers. Once Phase 1 / M1.3
lands and aggregator's signal summary is live in KV, this driver should
read from /dispatch-readiness/{id} instead of fetching live here.

Usage: python3 scripts/backfill_actionability.py
       python3 scripts/backfill_actionability.py --limit 5   # for testing
       python3 scripts/backfill_actionability.py --resume    # skip already-completed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from temporal.judge import score, JudgeUnreachable, JudgeParseError  # noqa: E402

# Reuse the smoke driver's helpers — they're identical to what we need here.
import smoke_actionability as smoke  # noqa: E402


OUTPUT_DIR = REPO_ROOT / "scripts" / "backfill_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def collect_cohort() -> list[dict]:
    """Enumerate the 54-issue calibration cohort from outcome snapshots."""
    state_root = REPO_ROOT / "state"
    cohort: list[dict] = []
    for batch in sorted(state_root.iterdir()):
        if not batch.is_dir():
            continue
        for iss in sorted(batch.iterdir()):
            if not iss.is_dir():
                continue
            outcomes_p = iss / "outcomes" / "upstream_state.json"
            judge_p = iss / "09-submittable" / "submission_judge.json"
            brief_p = iss / "01-eligible" / "issue_brief.json"
            if not (outcomes_p.exists() and judge_p.exists() and brief_p.exists()):
                continue
            try:
                jverdict = json.loads(judge_p.read_text()).get("verdict")
                ostate = json.loads(outcomes_p.read_text()).get("state")
            except Exception:
                continue
            if jverdict not in ("pass", "defer"):
                continue
            if ostate not in ("not_submitted", "aborted_by_operator"):
                continue
            try:
                brief = json.loads(brief_p.read_text())
                issue_obj = brief.get("issue", {})
                iid = iss.name
                slug = None
                num = issue_obj.get("number")
                # Prefer explicit fields, derive otherwise
                if issue_obj.get("repo_full"):
                    slug = issue_obj["repo_full"]
                elif issue_obj.get("html_url"):
                    url = issue_obj["html_url"]
                    parts = url.replace("https://github.com/", "").split("/")
                    if len(parts) >= 2:
                        slug = f"{parts[0]}/{parts[1]}"
                if not slug and "-" in iid:
                    slug = iid.rsplit("-", 1)[0].replace("__", "/")
                if not num and "-" in iid:
                    try:
                        num = int(iid.rsplit("-", 1)[1])
                    except ValueError:
                        pass
                if not slug or not num:
                    continue
            except Exception:
                continue
            # Read operator decision reason (structured if M0.2 present, else free text)
            override_p = iss / "awaiting" / "override_decision.json"
            override = None
            if override_p.exists():
                try:
                    override = json.loads(override_p.read_text())
                except Exception:
                    pass
            cohort.append({
                "batch": batch.name,
                "issue_id": iid,
                "slug": slug,
                "number": num,
                "outcome_state": ostate,
                "judge_verdict": jverdict,
                "judge_score": json.loads(judge_p.read_text()).get("score"),
                "operator_override": override,
            })
    return cohort


def _score_with_retry(rubric: str, payload: str) -> Any:
    """One retry on JudgeUnreachable to absorb canary blips. Canary timeout
    defaults to 10s which is tight under CLI variance; we bump via env in
    main(), then retry once anyway because long backfill runs need
    resilience to a single transient hiccup."""
    try:
        return score(rubric, payload)
    except JudgeUnreachable:
        time.sleep(5.0)
        return score(rubric, payload)


def run_one(target: dict, rubric: str) -> dict:
    """Fetch live data + run the rubric. Returns a result dict suitable for JSON."""
    data = smoke.fetch_issue_data(target["slug"], target["number"])
    if data.get("errors"):
        return {**target, "rubric_verdict": "fetch_error", "errors": data["errors"]}

    flags = smoke.compute_flags(data)
    payload = smoke.build_payload(data, flags)

    try:
        result = _score_with_retry(rubric, payload)
    except JudgeUnreachable as e:
        return {**target, "rubric_verdict": "judge_unreachable", "error": str(e)}
    except JudgeParseError as e:
        return {**target, "rubric_verdict": "parse_error", "error": str(e)}

    evidence = result.raw.get("evidence", []) if isinstance(result.raw, dict) else []
    return {
        **target,
        "rubric_verdict": result.verdict,
        "rubric_score": result.score,
        "rubric_reasoning": result.reasoning,
        "rubric_flags_computed": flags,
        "rubric_evidence_count": len(evidence),
        "rubric_evidence": evidence[:8],  # cap to keep results JSON readable
        "fetched_signals": {
            "comments": len(data.get("comments", [])),
            "sub_issues_count": data.get("sub_issues", {}).get("count", 0),
            "timeline_events": len(data.get("recent_timeline_events", [])),
            "linked_pr_urls": data.get("linked_pr_urls", []),
        },
    }


def expected_disposition(target: dict) -> str:
    """The operator's implicit decision on this issue, in one word."""
    if target["outcome_state"] == "aborted_by_operator":
        return "abort"
    # not_submitted + judge passed/deferred = operator never approved
    return "dont_ship"


def agreement_class(target: dict, rubric_verdict: str) -> str:
    """How does the rubric verdict relate to the operator's decision?"""
    expected = expected_disposition(target)
    if expected == "abort":
        if rubric_verdict == "fail":
            return "agree_fail"
        if rubric_verdict == "defer":
            return "softer_defer"  # rubric defers; operator aborted
        if rubric_verdict == "pass":
            return "disagree_pass"  # rubric says ship; operator aborted
    else:  # dont_ship
        if rubric_verdict == "fail":
            return "agree_fail"
        if rubric_verdict == "defer":
            return "agree_defer"  # operator deferred indefinitely; rubric defers — same call
        if rubric_verdict == "pass":
            return "disagree_pass"  # rubric says ship; operator never approved
    return "error"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Stop after N issues (for testing)")
    ap.add_argument("--resume", action="store_true", help="Skip issues with existing result files")
    args = ap.parse_args(argv)

    rubric_path = REPO_ROOT / "backend" / "temporal" / "rubrics" / "actionability_v1.md"
    rubric = rubric_path.read_text(encoding="utf-8")

    cohort = collect_cohort()
    print(f"Cohort: {len(cohort)} issues")
    print(f"  by outcome: {Counter(c['outcome_state'] for c in cohort)}")
    print(f"  by judge verdict: {Counter(c['judge_verdict'] for c in cohort)}")

    if args.limit:
        cohort = cohort[:args.limit]
        print(f"  limited to first {len(cohort)}")

    results: list[dict] = []
    for i, target in enumerate(cohort, 1):
        result_path = OUTPUT_DIR / f"{target['batch']}__{target['issue_id']}.json"
        if args.resume and result_path.exists():
            existing = json.loads(result_path.read_text())
            results.append(existing)
            print(f"[{i}/{len(cohort)}] SKIP (cached) {target['slug']}#{target['number']} → {existing.get('rubric_verdict')}")
            continue

        print(f"[{i}/{len(cohort)}] running {target['slug']}#{target['number']} (operator: {expected_disposition(target)})...", flush=True)
        t0 = time.monotonic()
        try:
            result = run_one(target, rubric)
        except KeyboardInterrupt:
            print("\n  interrupted; partial results saved")
            break
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            result = {**target, "rubric_verdict": "driver_error", "error": str(e)}

        elapsed = time.monotonic() - t0
        result["elapsed_s"] = round(elapsed, 1)
        result["agreement"] = agreement_class(result, result.get("rubric_verdict", ""))
        result_path.write_text(json.dumps(result, indent=2, default=str))
        results.append(result)
        print(f"  → {result['rubric_verdict']:8s} score={result.get('rubric_score', '?')}  agreement={result['agreement']}  ({elapsed:.1f}s)")

    # Aggregate
    print()
    print("=" * 78)
    print(f"  BACKFILL SUMMARY ({len(results)} issues)")
    print("=" * 78)

    by_verdict = Counter(r.get("rubric_verdict") for r in results)
    print("\nRubric verdicts:")
    for v, n in sorted(by_verdict.items(), key=lambda kv: -kv[1]):
        print(f"  {v:20s}  {n:>4d}")

    by_agreement = Counter(r.get("agreement") for r in results)
    print("\nOperator-vs-rubric agreement (agree_* = same decision; softer_defer = rubric milder; disagree_pass = rubric would have shipped what operator rejected):")
    for ag, n in sorted(by_agreement.items(), key=lambda kv: -kv[1]):
        print(f"  {ag:20s}  {n:>4d}")

    # The single most important number: how often did rubric say PASS on
    # something operator rejected? That's the disagree_pass count — these
    # are the cases where the gate would have shipped something the
    # operator wouldn't have.
    disagree = [r for r in results if r.get("agreement") == "disagree_pass"]
    if disagree:
        print(f"\n!! {len(disagree)} disagree_pass cases — rubric would have shipped, operator rejected:")
        for r in disagree:
            print(f"   {r['slug']}#{r['number']}  rubric_score={r.get('rubric_score')}  operator={r['outcome_state']}")

    summary_path = OUTPUT_DIR / "_summary.json"
    summary_path.write_text(json.dumps({
        "cohort_size": len(results),
        "by_verdict": dict(by_verdict),
        "by_agreement": dict(by_agreement),
        "disagree_pass_targets": [
            {"slug": r["slug"], "number": r["number"], "score": r.get("rubric_score")}
            for r in disagree
        ],
    }, indent=2))
    print(f"\nSummary: {summary_path}")
    print(f"Per-issue results: {OUTPUT_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
