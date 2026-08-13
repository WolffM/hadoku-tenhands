"""Check that everything a demo dispatch needs is up, before we go live.

Prints a pass/fail line per check and exits non-zero if any fails. Read-only:
it never mutates the sandbox or the pipeline.

Usage:
  python3 scripts/demo/preflight.py
"""

from __future__ import annotations

import sys

from _common import (  # type: ignore
    SANDBOX_REPO,
    api_get,
    api_post,
    gh,
    load_seeded,
    require_sandbox,
)


def _check(label, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    return ok


def check_gh_auth():
    who = gh(["api", "user", "--jq", ".login"])
    return bool(who), f"authenticated as {who}"


def check_sandbox_write():
    require_sandbox(SANDBOX_REPO)
    perm = gh(["api", f"repos/{SANDBOX_REPO}", "--jq", ".permissions.push"])
    return perm == "true", f"push={perm} on {SANDBOX_REPO}"


def check_judge():
    r = api_post("/api/temporal/judge/canary", {})
    return r.get("ok"), f"canary status={r.get('status')}"


def check_aggregator_health():
    slug = SANDBOX_REPO.replace("/", "-")
    data = api_get(f"/api/oss/dossier/{slug}")
    # dossier presence implies the aggregator indexes the sandbox; the health
    # score gate needs >= 10 (what killed the earlier canary at score 0).
    score = (data.get("repoHealth") or {}).get("maintainerHealthScore")
    return (score is not None and score >= 10), f"maintainerHealthScore={score} (need >= 10)"


def check_sandbox_clean():
    require_sandbox(SANDBOX_REPO)
    prs = gh(["pr", "list", "--repo", SANDBOX_REPO, "--state", "open",
              "--json", "number"], json_out=True)
    seeded = load_seeded()["issues"]
    open_issues = gh(["issue", "list", "--repo", SANDBOX_REPO, "--state", "open",
                      "--json", "number,assignees"], json_out=True)
    seeded_nums = set(seeded.values())
    extra = [i["number"] for i in open_issues if i["number"] not in seeded_nums]
    assigned = [i["number"] for i in open_issues
                if i["number"] in seeded_nums and i["assignees"]]
    problems = []
    if prs:
        problems.append(f"{len(prs)} open PR(s)")
    if extra:
        problems.append(f"unexpected open issues {extra}")
    if assigned:
        problems.append(f"seeded issues already assigned {assigned}")
    return (not problems), ("clean" if not problems else "; ".join(problems))


def check_no_leftover_batches():
    batches = api_get("/api/temporal/batches").get("batches") or []
    demo = [b["batch_id"] for b in batches if b.get("demo")]
    return (not demo), ("none" if not demo else f"leftover demo batches: {demo}")


def main() -> int:
    print(f"== demo preflight (sandbox={SANDBOX_REPO}) ==")
    checks = [
        ("gh auth", check_gh_auth),
        ("sandbox write access", check_sandbox_write),
        ("judge alive", check_judge),
        ("aggregator health", check_aggregator_health),
        ("sandbox clean", check_sandbox_clean),
        ("no leftover demo batches", check_no_leftover_batches),
    ]
    results = [_check(label, fn) for label, fn in checks]
    ok = all(results)
    print(f"\n{'READY' if ok else 'NOT READY'} ({sum(results)}/{len(results)} checks passed)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
