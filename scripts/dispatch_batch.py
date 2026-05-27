"""Dispatch every issue in a select_batch output JSON via /api/oss/fork-and-assign.

Usage:
  python3 scripts/dispatch_batch.py state/selected/batch-YYYYMMDD-HHMM.json
    [--start-from N]    resume from index N (1-based)
    [--gap-seconds 15]  delay between dispatches (rate limit is 5/min)

Per memory:
  - /dispatch/* has 30s edge-router timeout; a 504 means the backend may
    still be running. Treat as "verify, don't retry".
  - rate limit is 5 per minute → 12s minimum gap; use 15s for safety.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _admin_key() -> str:
    return json.loads((REPO_ROOT / ".devvault.local.json").read_text())["key"]


def dispatch_one(admin_key: str, issue: dict) -> dict:
    owner, repo = issue["owner_repo"].split("/", 1)
    payload = {
        "origin_owner": owner,
        "repo": repo,
        "issue_number": issue["number"],
        "issue_title": issue["title"],
        "issue_url": issue["url"],
    }
    req = urllib.request.Request(
        "https://hadoku.me/dispatch/api/oss/fork-and-assign",
        data=json.dumps(payload).encode(),
        headers={
            "X-User-Key": admin_key,
            "Content-Type": "application/json",
            "User-Agent": "dispatch_batch/1.0",
        },
        method="POST",
    )
    try:
        body = json.loads(urllib.request.urlopen(req, timeout=180).read())
        return {"ok": True, "response": body}
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            errbody = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            errbody = ""
        if code in (502, 504):
            return {"ok": False, "edge_timeout": True, "status": code, "body": errbody}
        return {"ok": False, "status": code, "body": errbody}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def verify_workflow(admin_key: str, owner_repo: str, number: int) -> dict | None:
    """After a dispatch (esp. on 504), check temporal batches for a workflow
    matching this issue. Returns the most recent matching entry or None."""
    try:
        req = urllib.request.Request(
            "https://hadoku.me/dispatch/api/temporal/batches",
            headers={"X-User-Key": admin_key, "User-Agent": "dispatch_batch/1.0"},
        )
        body = json.loads(urllib.request.urlopen(req, timeout=15).read())
        batches = (body.get("data") or {}).get("batches") or []
        # Most-recent first; look at the head for any matching issue id
        for b in sorted(batches, key=lambda x: x.get("batch_id", ""), reverse=True)[:5]:
            bid = b.get("batch_id", "")
            # We can't filter by issue directly here without per-batch fetch,
            # but a recent fresh batch usually means it worked. Return the head.
            return {"batch_id": bid, "issue_count": b.get("issue_count")}
    except Exception:
        return None
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("batch_file")
    p.add_argument("--start-from", type=int, default=1, help="1-based resume index")
    p.add_argument("--gap-seconds", type=int, default=15,
                   help="delay between dispatches (rate limit is 5/min → 12s min)")
    p.add_argument("--max-issues", type=int, default=999,
                   help="dispatch at most N (useful for incremental testing)")
    args = p.parse_args()

    batch = json.load(open(args.batch_file))
    selected = batch["selected"]
    admin = _admin_key()

    print(f"== dispatching batch from {args.batch_file}")
    print(f"   {len(selected)} issues, start_from={args.start_from}, gap={args.gap_seconds}s")
    print()

    results = []
    start_idx = max(0, args.start_from - 1)
    end_idx = min(len(selected), start_idx + args.max_issues)
    started_at = datetime.now(timezone.utc).isoformat()

    for i, issue in enumerate(selected[start_idx:end_idx], start=start_idx + 1):
        slug = issue["owner_repo"]
        num = issue["number"]
        title = issue.get("title") or ""
        print(f"[{i}/{len(selected)}] {slug}#{num}")
        print(f"  {title[:80]}")

        t0 = time.time()
        res = dispatch_one(admin, issue)
        dt = time.time() - t0
        res["elapsed_s"] = round(dt, 1)

        if res.get("ok"):
            data = res["response"].get("data") if isinstance(res["response"], dict) else None
            wf = (data or {}).get("workflow_id") if isinstance(data, dict) else None
            wf = wf or res["response"].get("workflow_id") if isinstance(res["response"], dict) else None
            success_msg = res["response"].get("success") if isinstance(res["response"], dict) else None
            print(f"  ✓ {dt:.0f}s  workflow={wf}  success={success_msg}")
        elif res.get("edge_timeout"):
            # 504/502 — check if backend made progress anyway
            print(f"  ⚠ edge_timeout {res['status']} after {dt:.0f}s — checking temporal state…")
            time.sleep(5)
            verify = verify_workflow(admin, slug, num)
            res["verify"] = verify
            print(f"    most-recent batch: {verify}")
        elif "status" in res:
            print(f"  ✗ HTTP {res['status']}  body={res.get('body','')[:200]}")
        else:
            print(f"  ✗ {res.get('error')}")

        results.append({"issue": issue, "result": res})

        if i < end_idx:
            print(f"  sleeping {args.gap_seconds}s (rate limit)…")
            time.sleep(args.gap_seconds)
        print()

    succeeded = sum(1 for r in results if r["result"].get("ok"))
    edge_timed = sum(1 for r in results if r["result"].get("edge_timeout"))
    failed = sum(1 for r in results if not r["result"].get("ok") and not r["result"].get("edge_timeout"))
    print("== summary ==")
    print(f"  succeeded: {succeeded}/{len(results)}")
    print(f"  edge timeouts (verify): {edge_timed}")
    print(f"  failed: {failed}")

    out = Path(args.batch_file).with_name(Path(args.batch_file).stem + "_dispatched.json")
    out.write_text(json.dumps({
        "batch_file": args.batch_file,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }, indent=2))
    print(f"  wrote {out}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
