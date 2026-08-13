"""Seed the sandbox repo's demo issues from the manifest in demo/issues/.

Idempotent: records the created issue numbers in demo/issues/seeded.lock.json.
On a second run it verifies each seeded issue still exists, is open, and has the
manifest body byte-for-byte (restoring via `gh issue edit` on drift). Reset
re-opens the same numbers rather than recreating, so dispatch payloads stay
deterministic across demos.

Usage:
  python3 scripts/demo/seed_issues.py            # create or verify
  python3 scripts/demo/seed_issues.py --verify   # verify only, non-zero on drift
"""

from __future__ import annotations

import argparse
import json
import sys

from _common import (  # type: ignore
    ISSUES_DIR,
    SANDBOX_REPO,
    SEEDED_LOCK,
    DemoGuardError,
    gh,
    require_sandbox,
)


def _parse_manifest(path):
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path} missing YAML front-matter")
    _, fm, body = text.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    title = meta["title"].strip().strip('"')
    labels = meta.get("labels", "").strip().strip("[]")
    label_list = [x.strip() for x in labels.split(",") if x.strip()]
    return title, label_list, body.strip() + "\n"


def _manifests():
    return sorted(p for p in ISSUES_DIR.glob("*.md"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="verify only; do not create")
    args = ap.parse_args()

    require_sandbox(SANDBOX_REPO)

    manifests = _manifests()
    if not manifests:
        raise DemoGuardError(f"no issue manifests in {ISSUES_DIR}")

    lock = json.loads(SEEDED_LOCK.read_text()) if SEEDED_LOCK.exists() else {"repo": SANDBOX_REPO, "issues": {}}
    if lock.get("repo") != SANDBOX_REPO:
        raise DemoGuardError(f"lock repo {lock.get('repo')} != sandbox {SANDBOX_REPO}")

    drift = False
    for path in manifests:
        key = path.stem
        title, labels, body = _parse_manifest(path)
        existing_num = lock["issues"].get(key)

        if existing_num:
            issue = gh(
                ["issue", "view", str(existing_num), "--repo", SANDBOX_REPO,
                 "--json", "number,state,title,body"],
                json_out=True,
            )
            needs_body = issue["body"].strip() != body.strip()
            needs_reopen = issue["state"] != "OPEN"
            if args.verify:
                if needs_body or needs_reopen:
                    drift = True
                    print(f"  DRIFT #{existing_num} {key}: "
                          f"{'body ' if needs_body else ''}{'closed' if needs_reopen else ''}")
                else:
                    print(f"  ok #{existing_num} {key}")
                continue
            if needs_reopen:
                gh(["issue", "reopen", str(existing_num), "--repo", SANDBOX_REPO])
                print(f"  reopened #{existing_num} {key}")
            if needs_body:
                gh(["issue", "edit", str(existing_num), "--repo", SANDBOX_REPO,
                    "--body", body])
                print(f"  restored body #{existing_num} {key}")
            if not (needs_reopen or needs_body):
                print(f"  ok #{existing_num} {key}")
        else:
            if args.verify:
                drift = True
                print(f"  MISSING {key} (never seeded)")
                continue
            label_args = []
            for lb in labels:
                label_args += ["--label", lb]
            url = gh(["issue", "create", "--repo", SANDBOX_REPO,
                      "--title", title, "--body", body, *label_args])
            num = int(url.rstrip("/").split("/")[-1])
            lock["issues"][key] = num
            print(f"  created #{num} {key}")

    if not args.verify:
        SEEDED_LOCK.write_text(json.dumps(lock, indent=2) + "\n")
        print(f"\nwrote {SEEDED_LOCK}")
    if args.verify and drift:
        print("\nseed drift detected", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DemoGuardError as e:
        print(f"guard: {e}", file=sys.stderr)
        sys.exit(3)
