"""Dispatch a preview-only demo batch against the sandbox repo.

The batch id is `demo-YYYYMMDD-HHMM`, which makes the server force
submit_to_upstream=False and restrict the batch to the sandbox allowlist — so
this can never open an upstream PR even if someone clicks approve in the inbox.

Usage:
  python3 scripts/demo/run_demo.py               # dispatch all seeded issues
  python3 scripts/demo/run_demo.py --count 2     # dispatch the first N
  python3 scripts/demo/run_demo.py --dry-run     # print payload, don't POST
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from _common import (  # type: ignore
    BASE_URL,
    SANDBOX_REPO,
    api_post,
    load_seeded,
    require_sandbox,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=None,
                    help="dispatch only the first N seeded issues")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch-id", default=None,
                    help="override (must start with 'demo-')")
    args = ap.parse_args()

    require_sandbox(SANDBOX_REPO)
    seeded = load_seeded()["issues"]
    nums = sorted(seeded.values())
    if args.count:
        nums = nums[: args.count]
    if not nums:
        print("no seeded issues to dispatch", file=sys.stderr)
        return 1

    batch_id = args.batch_id or f"demo-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    if not batch_id.startswith("demo-"):
        print("batch id must start with 'demo-' for the preview brake", file=sys.stderr)
        return 2

    issues = [
        {
            "upstream_slug": SANDBOX_REPO,
            # self-owned target: fork_slug == upstream_slug tells the fork
            # activity to skip fork creation and work in place.
            "fork_slug": SANDBOX_REPO,
            "issue_number": n,
            "branch_name": f"crimson-kitty-{n}",
        }
        for n in nums
    ]
    # submit_to_upstream is forced False server-side for demo- batches; we set
    # it here too so the intent is explicit and a dry-run shows the truth.
    payload = {"batch_id": batch_id, "submit_to_upstream": False, "issues": issues}

    print(f"== demo dispatch: {batch_id} ({len(issues)} issue(s) on {SANDBOX_REPO})")
    for it in issues:
        print(f"   - {it['upstream_slug']}#{it['issue_number']}  [preview-only]")

    if args.dry_run:
        import json
        print("\n--dry-run; payload:")
        print(json.dumps(payload, indent=2))
        return 0

    r = api_post("/api/temporal/dispatch", payload)
    print(f"\n   ok={r.get('ok')} status={r.get('status')}")
    if not r.get("ok"):
        print(f"   body: {r.get('body') or r.get('error')}")
        return 3
    print(f"   {r.get('body')}")
    print(f"\n  watch:  {BASE_URL}/api/temporal/batch/{batch_id}")
    print(f"  inbox:  {BASE_URL}/api/temporal/inbox")
    print(f"  UI:     {BASE_URL.replace('/tenhands','')}/tenhands?view=temporal&batch={batch_id}")
    print(f"\n  when done: python3 scripts/demo/teardown.py {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
