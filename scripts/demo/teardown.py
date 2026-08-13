"""Discard a demo batch's work and reset the sandbox for the next run.

Idempotent and hard-guarded: refuses any batch id that does not start with
`demo-` and never mutates a repo other than the sandbox. Safe to re-run.

Order:
  1. Signal abort to each child workflow; terminate the batch workflow if the
     `temporal` CLI is available and it is still running.
  2. Close every open PR on the sandbox (copilot/* drafts and crimson-kitty-*
     preview PRs) and delete their branches; close context issues; reopen the
     seeded issues and restore their bodies.
  3. Resolve this batch's inbox entries (per-issue, never the global resolve-all).
  4. Archive the batch's state/ dir to demo/archive/ and delete it, which drops
     the batch from the batches list, the Archive tab, and the retro tooling.
  5. Re-run preflight; exit non-zero unless the sandbox is demo-ready again.

Usage:
  python3 scripts/demo/teardown.py demo-YYYYMMDD-HHMM
  python3 scripts/demo/teardown.py demo-... --no-archive
  python3 scripts/demo/teardown.py demo-... --deep-clean   # delete context issues, not just close
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from _common import (  # type: ignore
    REPO_ROOT,
    SANDBOX_REPO,
    api_get,
    api_post,
    gh,
    require_sandbox,
)
from seed_issues import main as reseed  # type: ignore


def _terminate_temporal(batch_id: str) -> None:
    wf_id = f"batch-{batch_id}"
    if shutil.which("temporal") is None:
        print("  temporal CLI not found; skipping workflow terminate "
              "(child workflows close with the batch or time out)")
        return
    try:
        subprocess.run(
            ["temporal", "workflow", "terminate", "--workflow-id", wf_id,
             "--reason", "demo teardown"],
            capture_output=True, text=True, check=False,
        )
        print(f"  terminate signalled: {wf_id}")
    except Exception as e:  # noqa: BLE001
        print(f"  terminate skipped: {e}")


def _abort_children(batch_id: str) -> None:
    # Child ids follow {batch_id}-{slug__}-{N}; we discover them from the
    # batch detail rather than reconstructing.
    try:
        detail = api_get(f"/api/temporal/batch/{batch_id}")
    except Exception as e:  # noqa: BLE001
        print(f"  batch detail unavailable ({e}); relying on terminate")
        return
    for issue in detail.get("issues", []) or []:
        wf = issue.get("workflow_id")
        if not wf:
            continue
        r = api_post(f"/api/temporal/issue/{wf}/signal", {"decision": "abort"})
        print(f"  abort {wf}: ok={r.get('ok')} status={r.get('status')}")


def _clean_sandbox_prs() -> None:
    require_sandbox(SANDBOX_REPO)
    prs = gh(["pr", "list", "--repo", SANDBOX_REPO, "--state", "open",
              "--json", "number,headRefName"], json_out=True)
    for pr in prs:
        gh(["pr", "close", str(pr["number"]), "--repo", SANDBOX_REPO,
            "--delete-branch"], check=False)
        print(f"  closed PR #{pr['number']} ({pr['headRefName']})")
    # sweep any stray demo/agent branches left behind
    for prefix in ("copilot/", "crimson-kitty-"):
        refs = gh(["api", f"repos/{SANDBOX_REPO}/git/matching-refs/heads/{prefix}",
                   "--jq", ".[].ref"], check=False)
        for ref in (refs or "").splitlines():
            name = ref.replace("refs/heads/", "")
            gh(["api", "-X", "DELETE",
                f"repos/{SANDBOX_REPO}/git/refs/heads/{name}"], check=False)
            print(f"  deleted branch {name}")


def _close_context_issues(batch_id: str, deep: bool) -> None:
    require_sandbox(SANDBOX_REPO)
    # Context issues carry the batch id in a body tag; find & close them.
    hits = gh(["issue", "list", "--repo", SANDBOX_REPO, "--state", "open",
               "--search", batch_id, "--json", "number"], json_out=True)
    for it in hits:
        gh(["issue", "close", str(it["number"]), "--repo", SANDBOX_REPO], check=False)
        print(f"  closed context issue #{it['number']}")
        if deep:
            gh(["issue", "delete", str(it["number"]), "--repo", SANDBOX_REPO,
                "--yes"], check=False)


def _resolve_inbox(batch_id: str) -> None:
    try:
        inbox = api_get("/api/temporal/inbox").get("items", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"  inbox unavailable: {e}")
        return
    for entry in inbox:
        if entry.get("batch_id") != batch_id:
            continue
        issue_id = entry.get("issue_id") or entry.get("issue")
        r = api_post(f"/api/temporal/inbox/{batch_id}/{issue_id}/resolve", {})
        print(f"  resolved inbox {batch_id}/{issue_id}: ok={r.get('ok')}")


def _archive_state(batch_id: str, archive: bool) -> None:
    state_dir = REPO_ROOT / "state" / batch_id
    if not state_dir.exists():
        print(f"  no state dir {state_dir} (already clean)")
        return
    if archive:
        out_dir = REPO_ROOT / "demo" / "archive"
        out_dir.mkdir(parents=True, exist_ok=True)
        tar_path = out_dir / f"{batch_id}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tf:
            tf.add(state_dir, arcname=batch_id)
        print(f"  archived → {tar_path}")
    shutil.rmtree(state_dir)
    print(f"  removed {state_dir}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_id")
    ap.add_argument("--no-archive", action="store_true",
                    help="delete state/ without tarring it first")
    ap.add_argument("--deep-clean", action="store_true",
                    help="delete context issues instead of just closing them")
    args = ap.parse_args()

    if not args.batch_id.startswith("demo-"):
        print("refusing: teardown only operates on 'demo-' batches", file=sys.stderr)
        return 2

    print(f"== teardown {args.batch_id} (sandbox={SANDBOX_REPO}) ==")
    print("\n[1/5] Temporal")
    _abort_children(args.batch_id)
    _terminate_temporal(args.batch_id)

    print("\n[2/5] GitHub sandbox")
    _clean_sandbox_prs()
    _close_context_issues(args.batch_id, args.deep_clean)
    print("  reopening seeded issues + restoring bodies:")
    reseed([])  # seed_issues.main() reopens + restores drift idempotently

    print("\n[3/5] inbox")
    _resolve_inbox(args.batch_id)

    print("\n[4/5] evidence")
    _archive_state(args.batch_id, archive=not args.no_archive)

    print("\n[5/5] preflight")
    from preflight import main as preflight_main  # type: ignore
    code = preflight_main()
    print("\nteardown complete" if code == 0 else "\nteardown done, but sandbox NOT demo-ready")
    return code


if __name__ == "__main__":
    sys.exit(main())
