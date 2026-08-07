"""Dispatch every issue in a select_batch output JSON via /api/temporal/dispatch.

Usage:
  python3 scripts/dispatch_batch.py state/selected/batch-YYYYMMDD-HHMM.json
    [--batch-id NAME]   override batch name (default: dyn-YYYYMMDD-HHMM)
    [--dry-run]         show payload, don't POST

The Temporal endpoint dispatches the whole batch in one POST (returns 202).
Temporal's BatchWorkflow + child IssueWorkflows handle fork/sync/assign per-issue
with its own concurrency control. We poll /api/temporal/batch/<batch_id> to watch
progress.

Note: the legacy /api/oss/fork-and-assign route is broken for upstream repos
where a fork already exists under the B23 prefixed name (e.g.
WolffM/microsoft-typescript-go). wait_for_fork polls the wrong slug
(unprefixed) and times out. Temporal's _derive_fork uses the prefixed name
and gh's --fork-name flag.
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


def _post(url: str, body: dict, admin_key: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "X-User-Key": admin_key,
            "Content-Type": "application/json",
            "User-Agent": "dispatch_batch/2.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {"ok": True, "status": resp.status, "body": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        return {"ok": False, "status": e.code, "body": err_body}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _get(url: str, admin_key: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={"X-User-Key": admin_key, "User-Agent": "dispatch_batch/2.0"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("batch_file")
    p.add_argument("--batch-id", default=None,
                   help="batch name (default: dyn-YYYYMMDD-HHMM)")
    p.add_argument("--dry-run", action="store_true",
                   help="print payload, don't POST")
    args = p.parse_args()

    batch = json.load(open(args.batch_file))
    selected = batch["selected"]
    admin = _admin_key()

    batch_id = args.batch_id or f"dyn-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"

    # base_branch intentionally NOT passed — the server-side dispatch
    # endpoint resolves it from each upstream's actual default_branch.
    # See temporal_routes._resolve_default_branch. No hardcoding here
    # OR there; if the client passes a value the server uses it, otherwise
    # it queries gh on the operator's behalf.
    issues_payload = [
        {
            "upstream_slug": s["owner_repo"],
            "issue_number": s["number"],
            "raw_brief": "",
            "branch_name": f"crimson-kitty-{s['number']}",
        }
        for s in selected
    ]

    payload = {"batch_id": batch_id, "issues": issues_payload}

    print(f"== dispatch via temporal: batch_id={batch_id}")
    print(f"   {len(issues_payload)} issues")
    for it in issues_payload[:3]:
        print(f"   - {it['upstream_slug']}#{it['issue_number']}")
    if len(issues_payload) > 3:
        print(f"   ... +{len(issues_payload)-3} more")

    if args.dry_run:
        print("\n--dry-run set; payload not POSTed.")
        return 0

    print()
    print("== POSTing to /api/temporal/dispatch ==")
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.time()
    result = _post("https://hadoku.me/tenhands/api/temporal/dispatch", payload, admin, timeout=120)
    dt = time.time() - t0
    print(f"   {dt:.0f}s  ok={result.get('ok')}  status={result.get('status')}")
    if not result.get("ok"):
        print(f"   body: {result.get('body','')[:600]}")
        return 2

    print(f"   response: {json.dumps(result.get('body'), indent=2)[:600]}")

    # Persist record of the dispatch
    out = Path(args.batch_file).with_name(Path(args.batch_file).stem + "_dispatched.json")
    out.write_text(json.dumps({
        "batch_file": args.batch_file,
        "batch_id": batch_id,
        "started_at": started,
        "payload": payload,
        "result": result,
    }, indent=2))
    print(f"\n  wrote {out}")

    # Quick check: confirm the batch shows up in /api/temporal/batches
    print("\n== verifying batch is registered in temporal ==")
    time.sleep(3)
    try:
        b = _get("https://hadoku.me/tenhands/api/temporal/batches", admin, timeout=15)
        batches = b.get("batches") or []
        match = [x for x in batches if x.get("batch_id") == batch_id]
        if match:
            print(f"  ✓ batch found: {match[0]}")
        else:
            print(f"  ⚠ batch not yet registered; checking newest 3...")
            for x in sorted(batches, key=lambda y: y.get('batch_id',''), reverse=True)[:3]:
                print(f"    {x['batch_id']}: active={x['active']} issues={x['issue_count']}")
    except Exception as e:
        print(f"  could not verify: {e}")

    print(f"\n  watch progress: GET /tenhands/api/temporal/batch/{batch_id}")
    print(f"  inbox:          GET /tenhands/api/temporal/inbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
