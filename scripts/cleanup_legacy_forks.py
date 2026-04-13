#!/usr/bin/env python3
"""One-time Phase 0 cleanup of legacy WolffM/* forks before crimson-kitty.

Lists every fork under WolffM/*, gathers metadata (parent, branches, last
commit, open PR refs), writes one JSONL record per fork to
state/legacy-forks-backup.jsonl, and — only with --confirm — deletes them.

Per decision F2c, ALL forks are deleted regardless of open PRs. The open PRs
are still recorded in the backup file so the history is preserved.

Usage:
  scripts/cleanup_legacy_forks.py                   # dry-run (default)
  scripts/cleanup_legacy_forks.py --dry-run         # explicit dry-run
  scripts/cleanup_legacy_forks.py --confirm         # actually delete
  scripts/cleanup_legacy_forks.py --owner WolffM    # override fork owner
  scripts/cleanup_legacy_forks.py --backup PATH     # override backup path

The script ALWAYS writes the backup, dry-run or not — that way an operator can
review the file before re-running with --confirm.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_OWNER = "WolffM"
DEFAULT_BACKUP = "state/legacy-forks-backup.jsonl"


class GhError(RuntimeError):
    pass


def _run_gh(args: list[str]) -> str:
    """Run a `gh` command and return stdout. Raises GhError on non-zero exit.

    Isolated as a single seam so tests can monkeypatch it.
    """
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GhError(
            f"gh {' '.join(args)} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def list_forks(owner: str) -> list[dict]:
    """Return all forks under {owner}/*.

    Uses the REST list endpoint instead of `gh repo list` (which is GraphQL
    and walks each fork's `parent` field — that walk trips SAML enforcement
    on Microsoft-owned upstreams and fails the whole call).

    The REST list endpoint does NOT include `parent` on each node, so we do
    a second per-fork GET to enrich. The single-repo GET succeeds even for
    SAML-enforced parents because it doesn't dereference parent metadata
    beyond the slug.

    Returns dicts in the shape that gather_metadata expects:
      {
        nameWithOwner, name,
        parent: {nameWithOwner: ...} | None,
        defaultBranchRef: {name: ...} | None,
        pushedAt, isArchived,
      }
    """
    out = _run_gh([
        "api",
        f"users/{owner}/repos?type=owner&per_page=100",
        "--paginate",
        "--jq", "[.[] | select(.fork == true) | {name: .name, full_name: .full_name}]",
    ])
    bare = json.loads(out) if out.strip() else []
    if not isinstance(bare, list):
        raise GhError(f"unexpected REST list output: {out[:200]!r}")

    enriched: list[dict] = []
    for entry in bare:
        full = entry.get("full_name") or f"{owner}/{entry.get('name', '')}"
        try:
            detail_out = _run_gh([
                "api",
                f"repos/{full}",
                "--jq",
                "{full_name: .full_name, name: .name, "
                "parent_full: (.parent.full_name // null), "
                "default_branch: (.default_branch // null), "
                "pushed_at: (.pushed_at // null), "
                "archived: (.archived // false)}",
            ])
            detail = json.loads(detail_out) if detail_out.strip() else {}
        except (GhError, json.JSONDecodeError) as e:
            # Best-effort: keep the record with whatever we know.
            detail = {"full_name": full, "name": entry.get("name"), "_enrich_error": str(e)}

        enriched.append({
            "nameWithOwner": detail.get("full_name") or full,
            "name": detail.get("name") or entry.get("name"),
            "parent": (
                {"nameWithOwner": detail["parent_full"]}
                if detail.get("parent_full") else None
            ),
            "defaultBranchRef": (
                {"name": detail["default_branch"]}
                if detail.get("default_branch") else None
            ),
            "pushedAt": detail.get("pushed_at"),
            "isArchived": bool(detail.get("archived")),
        })

    return enriched


def gather_metadata(fork: dict) -> dict:
    """Gather backup metadata for a single fork.

    Returns a dict with: nameWithOwner, parent, default_branch, pushed_at,
    branches, last_commit, open_pr_refs, archived.

    Failures on individual sub-calls are recorded in the dict rather than
    raising — we want a best-effort backup, not an all-or-nothing one.
    """
    name_with_owner = fork.get("nameWithOwner") or ""
    parent_obj = fork.get("parent") or {}
    parent_slug = (
        parent_obj.get("nameWithOwner")
        if isinstance(parent_obj, dict) else None
    )
    default_branch_obj = fork.get("defaultBranchRef") or {}
    default_branch = (
        default_branch_obj.get("name")
        if isinstance(default_branch_obj, dict) else None
    )

    record: dict = {
        "nameWithOwner": name_with_owner,
        "parent": parent_slug,
        "default_branch": default_branch,
        "pushed_at": fork.get("pushedAt"),
        "archived": bool(fork.get("isArchived")),
        "branches": [],
        "last_commit": None,
        "open_pr_refs": [],
        "errors": [],
    }

    try:
        # No --paginate: it concatenates pages into invalid JSON. 100 branches
        # per page (gh default) is plenty for a one-off backup snapshot.
        branches_out = _run_gh([
            "api",
            f"repos/{name_with_owner}/branches?per_page=100",
            "--jq", "[.[] | {name: .name, sha: .commit.sha}]",
        ])
        branches = json.loads(branches_out) if branches_out.strip() else []
        if isinstance(branches, list):
            record["branches"] = branches
    except (GhError, json.JSONDecodeError) as e:
        record["errors"].append(f"branches: {e}")

    if default_branch:
        try:
            commit_out = _run_gh([
                "api",
                f"repos/{name_with_owner}/commits/{default_branch}",
                "--jq", "{sha: .sha, message: .commit.message, date: .commit.committer.date}",
            ])
            if commit_out.strip():
                record["last_commit"] = json.loads(commit_out)
        except (GhError, json.JSONDecodeError) as e:
            record["errors"].append(f"last_commit: {e}")

    try:
        prs_out = _run_gh([
            "pr", "list",
            "--repo", name_with_owner,
            "--state", "open",
            "--limit", "200",
            "--json", "number,title,headRefName,baseRefName,url,isCrossRepository",
        ])
        prs = json.loads(prs_out) if prs_out.strip() else []
        if isinstance(prs, list):
            record["open_pr_refs"] = prs
    except (GhError, json.JSONDecodeError) as e:
        record["errors"].append(f"open_prs: {e}")

    return record


def write_backup(records: list[dict], path: Path) -> None:
    """Write one JSONL record per fork. Always overwrites the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")


def delete_fork(name_with_owner: str) -> None:
    """Delete a fork via `gh repo delete --yes`. Raises GhError on failure."""
    _run_gh(["repo", "delete", name_with_owner, "--yes"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="(default) list and back up; do not delete")
    mode.add_argument("--confirm", action="store_true", help="actually delete every fork after backup")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--backup", default=DEFAULT_BACKUP)
    args = parser.parse_args(argv)

    confirm = args.confirm
    mode_label = "CONFIRM (will delete)" if confirm else "DRY-RUN"
    print(f"[cleanup_legacy_forks] mode={mode_label} owner={args.owner}", file=sys.stderr)

    try:
        forks = list_forks(args.owner)
    except GhError as e:
        print(f"ERROR listing forks: {e}", file=sys.stderr)
        return 2

    print(f"[cleanup_legacy_forks] found {len(forks)} fork(s) under {args.owner}/", file=sys.stderr)

    records: list[dict] = []
    for fork in forks:
        slug = fork.get("nameWithOwner", "<unknown>")
        print(f"  • {slug}", file=sys.stderr)
        records.append(gather_metadata(fork))

    backup_path = Path(args.backup)
    write_backup(records, backup_path)
    print(
        f"[cleanup_legacy_forks] wrote {len(records)} record(s) to {backup_path}",
        file=sys.stderr,
    )

    if not confirm:
        print(
            "[cleanup_legacy_forks] dry-run: NO deletes performed. "
            "Re-run with --confirm to delete.",
            file=sys.stderr,
        )
        return 0

    deleted, failed = 0, 0
    for record in records:
        slug = record["nameWithOwner"]
        try:
            delete_fork(slug)
            deleted += 1
            print(f"  ✓ deleted {slug}", file=sys.stderr)
        except GhError as e:
            failed += 1
            print(f"  ✗ FAILED to delete {slug}: {e}", file=sys.stderr)

    print(
        f"[cleanup_legacy_forks] deleted={deleted} failed={failed} "
        f"backup={backup_path} at {datetime.now(timezone.utc).isoformat()}",
        file=sys.stderr,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
