"""Shared helpers for the dispatch demo scripts.

The whole point of these scripts is a repeatable, discard-after demo against a
throwaway sandbox repo. Every mutating call goes through the allowlist guard
here so a demo script can never touch a real repo, and every batch id is
`demo-*` so the server-side dispatch guard forces preview-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("TENHANDS_BASE_URL", "https://hadoku.me/tenhands")

# The only repo any demo script is allowed to mutate. Override via env for a
# different sandbox, but it must match CRIMSON_DEMO_REPOS on the server.
SANDBOX_REPO = os.environ.get("CRIMSON_DEMO_REPOS", "WolffM/tenhands-demo-target").split(",")[0].strip()

ISSUES_DIR = REPO_ROOT / "demo" / "issues"
SEEDED_LOCK = ISSUES_DIR / "seeded.lock.json"


class DemoGuardError(RuntimeError):
    pass


def require_sandbox(repo: str) -> None:
    """Refuse to operate on anything but the sandbox repo."""
    if repo != SANDBOX_REPO:
        raise DemoGuardError(
            f"refusing to act on {repo!r}: demo scripts only touch the sandbox "
            f"{SANDBOX_REPO!r} (set CRIMSON_DEMO_REPOS to change)"
        )


def admin_key() -> str:
    return json.loads((REPO_ROOT / ".devvault.local.json").read_text())["key"]


def api_post(path: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode(),
        headers={
            "X-User-Key": admin_key(),
            "Content-Type": "application/json",
            "User-Agent": "tenhands-demo/1.0",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {"ok": True, "status": resp.status, "body": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:600] if e.fp else ""
        return {"ok": False, "status": e.code, "body": body_txt}
    except Exception as e:  # noqa: BLE001 - surfaced to the operator
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def api_get(path: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"X-User-Key": admin_key(), "User-Agent": "tenhands-demo/1.0"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def gh(args: list[str], *, check: bool = True, json_out: bool = False):
    """Run a gh command. Any command that names a repo must have passed
    require_sandbox() first — this helper does not itself guard, callers do."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        # `gh api` splits its failure across both streams: stderr carries the
# category ("gh: Validation Failed (HTTP 422)") and stdout carries the
# response body naming the offending field. Quoting stderr alone keeps the
# half you cannot act on.
        body = " ".join(result.stdout.split())  # flatten the pretty-printed JSON
        detail = " ".join(
            part for part in (result.stderr.strip(), body[:500]) if part
        ) or "no output on either stream"
        raise RuntimeError(f"gh {' '.join(args)} failed: {detail}")
    if json_out:
        return json.loads(result.stdout or "null")
    return result.stdout.strip()


def load_seeded() -> dict:
    if not SEEDED_LOCK.exists():
        raise DemoGuardError(
            f"no seed lock at {SEEDED_LOCK}; run scripts/demo/seed_issues.py first"
        )
    return json.loads(SEEDED_LOCK.read_text())


def eprint(*a) -> None:
    print(*a, file=sys.stderr)
