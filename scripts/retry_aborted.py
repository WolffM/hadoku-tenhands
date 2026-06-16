"""Re-dispatch the CRASHED runs of a batch — runs killed by an activity
failure (fork 403, timeout, …), not by a gate decision.

Crashed runs have no gate verdict and are worth retrying; gate-fail and
operator aborts are decisions that re-dispatch won't change, so they are
skipped. An aborted workflow is COMPLETED in Temporal and cannot resume in
place — "retry" means starting a fresh workflow, which is what this does.

Talks to production through the edge-router (vault broker for the admin
key, then the dispatch API). stdlib only; sends a curl-style User-Agent so
Cloudflare doesn't 403 it.

Dry-run by default. Pass --apply to actually dispatch.

Usage:
  python3 scripts/retry_aborted.py crimson-kitty-big-batch-2026-05-14
  python3 scripts/retry_aborted.py crimson-kitty-big-batch-2026-05-14 --apply
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

VAULT_KEY_URL = "https://hadoku.me/mgmt/api/secrets/get/TENHANDS_ADMIN_KEY"
DISPATCH_BASE = "https://hadoku.me/dispatch/api/temporal"
DEVVAULT_LOCAL = Path(__file__).parent.parent / ".devvault.local.json"


def _request(url: str, headers: dict, data: bytes | None = None, timeout: int = 30):
    # curl-style UA — Cloudflare 403s the default Python-urllib agent.
    headers = {"User-Agent": "curl/8.5.0", **headers}
    req = urllib.request.Request(url, headers=headers, data=data,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _admin_key() -> str:
    vkey = json.loads(DEVVAULT_LOCAL.read_text())["key"]
    try:
        body = _request(VAULT_KEY_URL, {"X-User-Key": vkey})
    except urllib.error.HTTPError as e:
        raise SystemExit(f"vault broker HTTP {e.code} — mgmt-api may be down")
    val = body.get("value")
    if not val:
        raise SystemExit(f"vault response had no value: {body}")
    return val


def _issue_id_to_slug(issue_id: str) -> tuple[str, int]:
    """`owner__repo-name-1234` → ('owner/repo-name', 1234).

    The issue id is `{slug.replace('/', '__')}-{number}`; the number is
    always the final `-`-delimited segment, so rsplit is unambiguous even
    when the repo name itself contains hyphens (e.g. typescript-go)."""
    stem, num = issue_id.rsplit("-", 1)
    return stem.replace("__", "/"), int(num)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    apply = "--apply" in argv
    if not args:
        print("usage: retry_aborted.py <batch_id> [--apply]", file=sys.stderr)
        return 2
    batch_id = args[0]
    admin = _admin_key()

    detail = _request(f"{DISPATCH_BASE}/batch/{batch_id}", {"X-User-Key": admin})
    issues = detail.get("data", {}).get("issues", [])
    if not issues:
        print(f"batch '{batch_id}' has no issues (or was not found)")
        return 1

    crashed = [i for i in issues
               if i.get("current_state") == "aborted" and i.get("abort_kind") == "crashed"]
    skipped = [i for i in issues
               if i.get("current_state") == "aborted" and i.get("abort_kind") != "crashed"]

    print(f"\nbatch {batch_id}: {len(crashed)} crashed (retryable), "
          f"{len(skipped)} aborted-by-decision (skipped)\n")
    for i in skipped:
        print(f"  skip  {i['issue_id']}  ({i.get('abort_kind')})")
    payload_issues = []
    for i in crashed:
        slug, num = _issue_id_to_slug(i["issue_id"])
        payload_issues.append({"upstream_slug": slug, "issue_number": num})
        print(f"  retry {i['issue_id']}  -> {slug}#{num}")

    if not payload_issues:
        print("\nnothing crashed to retry.")
        return 0

    new_batch = f"{batch_id}-retry-{datetime.now(timezone.utc):%Y%m%d-%H%M}"
    print(f"\n{'APPLYING' if apply else 'DRY-RUN'} — new batch id: {new_batch}")
    if not apply:
        print("Re-run with --apply to dispatch.")
        return 0

    body = json.dumps({
        "batch_id": new_batch,
        "submit_to_upstream": False,
        "issues": payload_issues,
    }).encode("utf-8")
    resp = _request(f"{DISPATCH_BASE}/dispatch",
                    {"X-User-Key": admin, "Content-Type": "application/json"},
                    data=body)
    data = resp.get("data", {})
    print(f"dispatched: batch={data.get('batch_id')} "
          f"workflow={data.get('workflow_id')} issues={data.get('issue_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
