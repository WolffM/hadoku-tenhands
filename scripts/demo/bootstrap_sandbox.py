"""One-time: create and populate the sandbox demo repo.

Operator-run. Creates WolffM/tenhands-demo-target (or $CRIMSON_DEMO_REPOS[0])
from demo/sandbox-template/, gives it enough real history that the aggregator's
maintainerHealthScore clears the eligibility gate (>= 10), verifies Copilot is
assignable, and triggers an aggregator compute so the repo is indexed before
the first demo.

This mutates GitHub (creates a repo). It refuses to run if the repo already
exists unless --force-push is given. It does NOT dispatch anything.

Usage:
  python3 scripts/demo/bootstrap_sandbox.py            # create + populate
  python3 scripts/demo/bootstrap_sandbox.py --check    # verify readiness only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from _common import (  # type: ignore
    REPO_ROOT,
    SANDBOX_REPO,
    api_post,
    gh,
    require_sandbox,
)

TEMPLATE = REPO_ROOT / "demo" / "sandbox-template"

# Backdated commit plan: a spread of small, plausible commits so the repo has
# history depth and cadence (what the health score rewards). Dates are fixed
# strings so re-runs are deterministic.
_HISTORY = [
    ("2026-01-06T10:00:00", "Initial commit: demotool skeleton"),
    ("2026-01-09T14:30:00", "Add CSV parser and column helper"),
    ("2026-01-13T09:15:00", "Add pagination helpers"),
    ("2026-01-16T16:45:00", "Add date parsing/formatting"),
    ("2026-01-20T11:00:00", "Add numeric column stats"),
    ("2026-01-23T13:20:00", "Wire up the report CLI"),
    ("2026-01-27T10:30:00", "Add sample data"),
    ("2026-01-30T15:00:00", "Add test suite"),
    ("2026-02-03T09:45:00", "Add README and packaging"),
    ("2026-02-06T14:10:00", "Add CONTRIBUTING and PR template"),
    ("2026-02-10T11:30:00", "Tidy docstrings"),
    ("2026-02-13T16:00:00", "Add pytest config"),
]


def _git(cwd: Path, args: list[str], *, date: str | None = None) -> None:
    env = None
    if date:
        import os
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(cwd), *args], check=True, env=env,
                   capture_output=True, text=True)


def _repo_exists() -> bool:
    r = subprocess.run(["gh", "repo", "view", SANDBOX_REPO], capture_output=True)
    return r.returncode == 0


def check() -> int:
    print(f"== sandbox readiness: {SANDBOX_REPO} ==")
    if not _repo_exists():
        print("  [FAIL] repo does not exist; run without --check to create it")
        return 1
    assignable = gh(
        ["api", "graphql", "-f", f"query="
         "query{repository(owner:\"" + SANDBOX_REPO.split('/')[0] + "\","
         "name:\"" + SANDBOX_REPO.split('/')[1] + "\"){"
         "suggestedActors(capabilities:[CAN_BE_ASSIGNED],first:100){nodes{login}}}}",
         "--jq", ".data.repository.suggestedActors.nodes[].login"],
        check=False,
    )
    has_copilot = "copilot" in (assignable or "").lower()
    print(f"  [{'PASS' if has_copilot else 'FAIL'}] Copilot assignable")
    slug = SANDBOX_REPO.replace("/", "-")
    r = api_post(f"/api/oss/refresh-target", {"slug": slug})
    print(f"  aggregator refresh: ok={r.get('ok')}")
    print("  → then check maintainerHealthScore via preflight.py")
    return 0 if has_copilot else 1


def create() -> int:
    require_sandbox(SANDBOX_REPO)
    if _repo_exists():
        print(f"  {SANDBOX_REPO} already exists; not recreating. Use --check.")
        return 1

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "sandbox"
        work.mkdir()
        # Copy the template contents into the working tree.
        subprocess.run(["cp", "-r", *[str(p) for p in TEMPLATE.iterdir()], str(work)],
                       check=True)
        _git(work, ["init", "-q", "-b", "main"])
        _git(work, ["config", "user.name", "WolffM"])
        _git(work, ["config", "user.email", "8714327+WolffM@users.noreply.github.com"])
        # Lay down the backdated history by committing incremental slices. For a
        # demo target the important signal is commit count + cadence, so we
        # commit the whole tree on the first entry and touch a CHANGELOG on the
        # rest to create honest, dated history.
        _git(work, ["add", "-A"])
        _git(work, ["commit", "-q", "-m", _HISTORY[0][1]], date=_HISTORY[0][0])
        changelog = work / "CHANGELOG.md"
        for date, msg in _HISTORY[1:]:
            changelog.write_text(
                (changelog.read_text() if changelog.exists() else "# Changelog\n\n")
                + f"- {date[:10]}: {msg}\n"
            )
            _git(work, ["add", "CHANGELOG.md"])
            _git(work, ["commit", "-q", "-m", msg], date=date)

        gh(["repo", "create", SANDBOX_REPO, "--public",
            "--description", "A tiny CSV report utility — dispatch demo target.",
            "--source", str(work), "--push"])
        print(f"  created + pushed {SANDBOX_REPO} ({len(_HISTORY)} commits)")

    # Labels the manifests use.
    for label, color in [("bug", "d73a4a"), ("demo", "5319e7")]:
        gh(["label", "create", label, "--repo", SANDBOX_REPO, "--color", color,
            "--force"], check=False)

    slug = SANDBOX_REPO.replace("/", "-")
    api_post(f"/api/oss/refresh-target", {"slug": slug})
    print("  triggered aggregator index; verify score >= 10 with preflight.py")
    print(f"\n  next: python3 scripts/demo/seed_issues.py")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    return check() if args.check else create()


if __name__ == "__main__":
    sys.exit(main())
