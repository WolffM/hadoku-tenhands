"""Dynamic batch selector — pulls top-CVS issues through the actionability
gate until N issues pass.

Usage:
  python3 scripts/select_batch.py [--target 25] [--max-per-repo 2] [--out FILE]

How it works:
1. Pull all aggregator-scored issues + the dispatched-repos exclusion list
2. Filter: unclaimed, no high-competition, cvsTier in {go, likely},
   not already dispatched, sorted by cvs descending
3. Optional: cap N per repo for diversity (default 2)
4. Iterate: fetch issue data → compute flags → invoke actionability judge
5. Pass → add to selected batch; Fail/Defer → log and skip
6. Stop when len(selected) >= target

Output JSON has the selected batch + an audit log of every candidate
evaluated and its verdict. Operator reviews the JSON, then dispatches.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# Reuse smoke's data acquisition (fetch_issue_data, compute_flags, build_payload)
import smoke_actionability as smoke  # noqa: E402
from temporal.judge import score, JudgeUnreachable, JudgeParseError  # noqa: E402


def _admin_key() -> str:
    return json.loads((REPO_ROOT / ".devvault.local.json").read_text())["key"]


def _get(url: str, headers: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={**headers, "User-Agent": "select_batch/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def fetch_candidates(admin_key: str) -> list[dict]:
    """Pull all aggregator-scored issues + dispatched-repos exclusion."""
    print("  fetching stage2-issues from aggregator...")
    d = _get("https://hadoku.me/dispatch/api/oss/stage2-issues", {"X-User-Key": admin_key}, timeout=60)
    issues = d.get("issues", []) or []
    print(f"    {len(issues)} issues fetched")

    print("  fetching dispatched-repos exclusion list...")
    d2 = _get("https://hadoku.me/dispatch/api/oss/dispatched-repos", {"X-User-Key": admin_key}, timeout=30)
    dispatched = d2.get("dispatched_repos", []) or []
    dispatched_slugs = {d.get("aggregator_slug") for d in dispatched if d.get("aggregator_slug")}
    print(f"    {len(dispatched_slugs)} repos already dispatched")
    return issues, dispatched_slugs


def filter_and_rank(issues: list[dict], dispatched_slugs: set[str], max_per_repo: int) -> list[dict]:
    """Apply hard filters, sort by cvs descending, cap N per repo."""
    candidates = [
        i for i in issues
        if i.get("claimStatus") == "unclaimed"
        and i.get("competitionLevel") in {"none", "low"}
        and i.get("cvsTier") in {"go", "likely"}
        and i.get("repoSlug") not in dispatched_slugs
    ]
    print(f"  after filters: {len(candidates)} candidates "
          f"(unclaimed, competition≤low, tier∈go/likely, not dispatched)")
    candidates.sort(key=lambda i: i.get("cvs", 0), reverse=True)
    per_repo = defaultdict(int)
    diverse = []
    for c in candidates:
        slug = c.get("repoSlug")
        if per_repo[slug] >= max_per_repo:
            continue
        per_repo[slug] += 1
        diverse.append(c)
    print(f"  after per-repo cap={max_per_repo}: {len(diverse)} candidates")
    return diverse


def evaluate_one(rubric: str, owner_repo: str, number: int) -> dict:
    """Run actionability against a single issue. owner_repo is "owner/repo"."""
    data = smoke.fetch_issue_data(owner_repo, number)
    if data.get("errors"):
        return {"verdict": "fetch_error", "errors": data["errors"]}
    flags = smoke.compute_flags(data)
    payload = smoke.build_payload(data, flags)
    try:
        result = score(rubric, payload)
        evidence = result.raw.get("evidence", []) if isinstance(result.raw, dict) else []
        return {
            "verdict": result.verdict,
            "score": result.score,
            "reasoning": result.reasoning,
            "evidence": evidence,
            "flags_computed": flags,
            "comment_count": len(data.get("comments", [])),
        }
    except JudgeUnreachable as e:
        return {"verdict": "judge_unreachable", "error": str(e)}
    except JudgeParseError as e:
        return {"verdict": "parse_error", "error": str(e)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=25, help="number of passing issues to collect")
    p.add_argument("--max-per-repo", type=int, default=2, help="cap candidates per repo")
    p.add_argument("--max-evaluate", type=int, default=80, help="hard cap on issues to evaluate (cost guard)")
    p.add_argument("--out", default=None, help="output JSON path")
    args = p.parse_args()

    out_path = Path(args.out) if args.out else (
        REPO_ROOT / "state" / "selected" /
        f"batch-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rubric_path = REPO_ROOT / "backend" / "temporal" / "rubrics" / "actionability_v1.md"
    rubric = rubric_path.read_text(encoding="utf-8")
    print(f"== select_batch: target={args.target} max_per_repo={args.max_per_repo} ==")
    print(f"   rubric: {rubric_path.name} ({len(rubric)} chars)")

    admin = _admin_key()
    issues, dispatched_slugs = fetch_candidates(admin)
    candidates = filter_and_rank(issues, dispatched_slugs, args.max_per_repo)
    if not candidates:
        print("  no candidates — aborting")
        return 1

    selected = []
    audit = []
    started = time.time()
    for idx, c in enumerate(candidates[: args.max_evaluate], start=1):
        if len(selected) >= args.target:
            break
        owner_repo = c.get("repo") or c.get("project")  # "owner/repo" form
        slug = c.get("repoSlug")  # hyphenated, used as aggregator key
        number = c.get("number")
        cvs = c.get("cvs")
        title = (c.get("title") or "")[:70]
        elapsed = time.time() - started
        print(f"\n[{idx}/{args.max_evaluate}] {owner_repo}#{number} cvs={cvs} ({elapsed:.0f}s elapsed, {len(selected)}/{args.target} passing)")
        print(f"  {title}")
        res = evaluate_one(rubric, owner_repo, number)
        v = res.get("verdict")
        s = res.get("score")
        print(f"  → verdict: {v}  score: {s}")
        if res.get("reasoning"):
            print(f"    {res['reasoning'][:200]}")
        entry = {
            "owner_repo": owner_repo,
            "aggregator_slug": slug,
            "number": number,
            "title": c.get("title"),
            "url": c.get("url"),
            "cvs": cvs,
            "cvsTier": c.get("cvsTier"),
            **res,
        }
        audit.append(entry)
        if v == "pass":
            selected.append(entry)

    print(f"\n== summary ==")
    print(f"  evaluated: {len(audit)}")
    print(f"  selected (pass): {len(selected)}")
    print(f"  failed/deferred: {len(audit) - len(selected)}")
    from collections import Counter
    print(f"  verdict distribution: {dict(Counter(a.get('verdict') for a in audit))}")
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.target,
        "max_per_repo": args.max_per_repo,
        "rubric": rubric_path.name,
        "selected": selected,
        "audit": audit,
    }, indent=2))
    print(f"\n  wrote {out_path}")
    if len(selected) < args.target:
        print(f"  ⚠ target not met ({len(selected)}/{args.target}). Consider raising --max-evaluate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
