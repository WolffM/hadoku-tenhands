#!/usr/bin/env python3
"""Smoke test for the WolffM-temporal quarantine PAT.

Phase 0 step 0.3: after the operator creates a classic PAT scoped
`repo, delete_repo, workflow` and stores it in `.env` as
`TEMPORAL_QUARANTINE_PAT`, this script proves the token works end-to-end:

  1. Create a private test repo `WolffM-temporal/_pat-canary-{timestamp}`
  2. Push a single empty commit via the GitHub API
  3. Delete the repo
  4. Verify the deletion (404 expected)

The script never touches the real `gh` user token — it routes everything
through `GH_TOKEN={TEMPORAL_QUARANTINE_PAT}` so a passing run is proof the
PAT itself has the required scopes.

Exits 0 on success. Non-zero (with a diagnostic message) on any failure.
A failure on step 1 most likely means the org doesn't exist yet, the PAT
is missing the `repo` scope, or the operator isn't a member of the org.
A failure on step 3 most likely means the PAT is missing `delete_repo`.

Usage:
  scripts/test_quarantine_pat.py
  scripts/test_quarantine_pat.py --org WolffM-temporal --keep
  scripts/test_quarantine_pat.py --dry-run    # print what it would do, do nothing
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

DEFAULT_ORG = "WolffM-temporal"
PAT_ENV_VAR = "TEMPORAL_QUARANTINE_PAT"


class CanaryError(RuntimeError):
    pass


def _load_pat() -> str:
    pat = os.environ.get(PAT_ENV_VAR, "").strip()
    if not pat:
        # Best-effort .env load so the script "just works" outside of pm2.
        env_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".env"
        )
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == PAT_ENV_VAR:
                        pat = value.strip().strip('"').strip("'")
                        break
    if not pat:
        raise CanaryError(
            f"{PAT_ENV_VAR} not set in env or .env. "
            "See docs/crimson-kitty/quarantine.md for setup."
        )
    return pat


def _run_gh(args: list[str], pat: str) -> tuple[int, str, str]:
    """Run a gh command with the quarantine PAT injected via GH_TOKEN.

    Returns (returncode, stdout, stderr). Does not raise — callers decide.
    Isolated for monkeypatching in tests.
    """
    env = os.environ.copy()
    env["GH_TOKEN"] = pat
    # Strip any inherited gh keyring auth so the PAT is the only credential.
    env.pop("GITHUB_TOKEN", None)
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _gh_or_raise(args: list[str], pat: str, what: str) -> str:
    code, out, err = _run_gh(args, pat)
    if code != 0:
        raise CanaryError(f"{what} failed (exit {code}): {err.strip() or out.strip()}")
    return out


def create_canary_repo(org: str, name: str, pat: str) -> str:
    """Create a private repo via the REST API. Returns the repo full name."""
    payload = {
        "name": name,
        "private": True,
        "auto_init": True,
        "description": "PAT canary — safe to delete",
    }
    out = _gh_or_raise(
        [
            "api",
            "--method", "POST",
            f"orgs/{org}/repos",
            "-f", f"name={name}",
            "-F", "private=true",
            "-F", "auto_init=true",
            "-f", "description=PAT canary — safe to delete",
        ],
        pat,
        "create canary repo",
    )
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise CanaryError(f"create returned non-JSON: {e}: {out[:200]}")
    full = data.get("full_name")
    if not full:
        raise CanaryError(f"create response missing full_name: {out[:200]}")
    return full


def push_empty_commit(full_name: str, pat: str) -> str:
    """Create one commit by writing a small file via the contents API.

    Avoids needing a local clone or git binary. Returns the new commit SHA.
    """
    payload_path = "PAT_CANARY.txt"
    out = _gh_or_raise(
        [
            "api",
            "--method", "PUT",
            f"repos/{full_name}/contents/{payload_path}",
            "-f", "message=PAT canary commit",
            "-f", f"content={_b64('canary ok\n')}",
        ],
        pat,
        "create canary commit",
    )
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise CanaryError(f"commit returned non-JSON: {e}: {out[:200]}")
    sha = (data.get("commit") or {}).get("sha")
    if not sha:
        raise CanaryError(f"commit response missing sha: {out[:200]}")
    return sha


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def delete_canary_repo(full_name: str, pat: str) -> None:
    _gh_or_raise(
        ["api", "--method", "DELETE", f"repos/{full_name}"],
        pat,
        "delete canary repo",
    )


def verify_deleted(full_name: str, pat: str) -> None:
    code, out, err = _run_gh(
        ["api", f"repos/{full_name}", "--silent", "-i"], pat
    )
    # On a 404, gh exits non-zero. That's the success signal.
    if code == 0:
        raise CanaryError(
            f"verify failed: repo {full_name} still exists after delete"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default=DEFAULT_ORG)
    parser.add_argument("--keep", action="store_true", help="skip delete (debug)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        pat = _load_pat()
    except CanaryError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    name = f"_pat-canary-{int(time.time())}"

    if args.dry_run:
        print(f"[dry-run] would create {args.org}/{name}, commit, delete, verify")
        return 0

    try:
        full_name = create_canary_repo(args.org, name, pat)
        print(f"  ✓ created {full_name}")

        sha = push_empty_commit(full_name, pat)
        print(f"  ✓ committed {sha[:8]}")

        if args.keep:
            print(f"  • --keep: leaving {full_name} in place. Delete manually.")
            return 0

        delete_canary_repo(full_name, pat)
        print(f"  ✓ deleted {full_name}")

        verify_deleted(full_name, pat)
        print(f"  ✓ verified 404 for {full_name}")
    except CanaryError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    print("PASS — PAT works end-to-end (create / commit / delete / verify)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
