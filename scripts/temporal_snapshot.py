"""Live snapshot of the crimson-kitty pipeline — Inbox + Active batches.

Powers the /inbox and /active skills so the operator doesn't have to
copy-paste API output. Talks to production through the edge-router:

  vault broker  → hadoku.me/mgmt/api/secrets/get/TENHANDS_ADMIN_KEY
  dispatch API  → hadoku.me/tenhands/api/temporal/{inbox,batches,batch/<id>}

stdlib only (urllib) so it runs under the system python with no deps.

Usage:
  python3 scripts/temporal_snapshot.py inbox     # operator inbox only
  python3 scripts/temporal_snapshot.py active    # active batches only
  python3 scripts/temporal_snapshot.py           # both (default)
"""

import json
import sys
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

VAULT_KEY_URL = "https://hadoku.me/mgmt/api/secrets/get/TENHANDS_ADMIN_KEY"
DISPATCH_BASE = "https://hadoku.me/tenhands/api/temporal"
DEVVAULT_LOCAL = Path(__file__).parent.parent / ".devvault.local.json"


def _get(url: str, headers: dict, timeout: int = 20):
    # Cloudflare (in front of hadoku.me) 403s the default `Python-urllib`
    # User-Agent as a suspected bot — send a curl-style UA so the request
    # is treated the same as the curl calls this script replaces.
    headers = {"User-Agent": "curl/8.5.0", **headers}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _admin_key() -> str:
    """Fetch the tenhands admin key from the vault broker."""
    try:
        vkey = json.loads(DEVVAULT_LOCAL.read_text())["key"]
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"cannot read .devvault.local.json: {e}")
    try:
        body = _get(VAULT_KEY_URL, {"X-User-Key": vkey})
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"vault broker returned HTTP {e.code} — mgmt-api may be down "
            f"(better-sqlite3 platform clobber). Fix: rebuild better-sqlite3 "
            f"for Windows + restart mgmt-api."
        )
    except urllib.error.URLError as e:
        raise SystemExit(f"vault broker unreachable: {e}")
    val = body.get("value")
    if not val:
        raise SystemExit(f"vault response had no value: {body}")
    return val


def _pretty_issue(item: dict) -> str:
    """`owner/repo#N` when the inbox entry carries the upstream fields,
    else the raw issue_id."""
    slug = item.get("upstream_slug")
    num = item.get("issue_number")
    if slug and num:
        return f"{slug}#{num}"
    return str(item.get("issue_id", "?"))


def show_inbox(admin: str) -> None:
    body = _get(f"{DISPATCH_BASE}/inbox", {"X-User-Key": admin})
    items = body.get("items", [])
    print(f"\n=== INBOX — {len(items)} awaiting decision ===")
    if not items:
        print("  (empty — nothing needs a decision)")
        return
    for it in items:
        gate = it.get("gate", "?")
        score = it.get("score")
        score_s = f" {score:.2f}" if isinstance(score, (int, float)) else ""
        print(f"\n  • {_pretty_issue(it)}   [{gate}{score_s}]")
        print(f"    batch:    {it.get('batch_id', '?')}")
        reason = (it.get("reason") or "").strip()
        if reason:
            print(f"    reason:   {reason[:160]}")
        pr = it.get("operator_pr_url")
        if pr:
            print(f"    fork PR:  {pr}")
        wf = it.get("workflow_id") or f"{it.get('batch_id')}-{it.get('issue_id')}"
        print(f"    workflow: {wf}")


def show_active(admin: str) -> None:
    body = _get(f"{DISPATCH_BASE}/batches", {"X-User-Key": admin})
    batches = body.get("batches", [])
    active = [b for b in batches if b.get("active")]
    print(f"\n=== ACTIVE — {len(active)} batch(es) "
          f"({len(batches) - len(active)} archived) ===")
    if not active:
        print("  (no active batches — inbox is clear)")
        return
    for b in active:
        bid = b["batch_id"]
        detail = _get(f"{DISPATCH_BASE}/batch/{bid}", {"X-User-Key": admin})
        issues = detail.get("issues", [])
        states = Counter(i["current_state"] for i in issues)
        deferred = [i for i in issues if i.get("is_deferred")]
        print(f"\n  ▸ {bid}  ({b.get('issue_count', len(issues))} runs, "
              f"{b.get('deferred_count', len(deferred))} deferred)")
        print("    states:  " + ", ".join(f"{s}×{c}" for s, c in states.most_common()))
        for i in deferred:
            print(f"      ⏸ {i['issue_id']}  @ {i.get('deferred_gate', '?')}")


def main(argv: list[str]) -> int:
    mode = (argv[1] if len(argv) > 1 else "all").lower()
    if mode not in ("inbox", "active", "all"):
        print(f"unknown mode '{mode}' — use: inbox | active | all", file=sys.stderr)
        return 2
    admin = _admin_key()
    if mode in ("inbox", "all"):
        show_inbox(admin)
    if mode in ("active", "all"):
        show_active(admin)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
