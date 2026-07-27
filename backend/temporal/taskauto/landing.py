"""Landing: commit, verify against current `main`, then push or open a PR.

Two modes:

* **`pr` (preferred)** — push the branch, open a pull request, stop. A human
  merges it. Verification is the repo's own required checks, so nothing here
  runs the suite: the pull request *is* the dry run, and unlike the old one it
  persists, is reviewable, and is already wired to a merge button.
* **`push`** — merge straight into `base` with nobody watching. Kept for the
  crimson-kitty-shaped case and for repos where a PR adds nothing, but it is
  no longer the default posture for new work.

This is the only component that touches a real branch people depend on, and
in `push` mode it runs with nobody watching, so it is written to refuse rather
than to proceed. Every check below is a reason *not* to push.

**The load-bearing one is `verify`.** The suite runs on the merge result —
the branch with current `origin/main` merged in — not on the branch in
isolation. A branch cut an hour ago passes against the `main` it remembers,
not the one it is about to become part of. Since we serialise to one task per
repo, the window between verifying and pushing is small, and the push is a
fast-forward that fails if anything landed meanwhile.

**`dry_run` is not a testing affordance**, it is the default posture. A
landing that has done everything except the push has produced all the
evidence and none of the consequences, which is exactly what you want the
first time a new repo is automated.
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..gates.taskauto.protected_paths import protected_hits
from .refs import RepoPolicy, TaskRef
from .task_text import extract_allow_protected

logger = logging.getLogger(__name__)


class LandingRefused(RuntimeError):
    """A gate said no. The work stays on the branch; nothing was pushed."""


@dataclass
class LandResult:
    pushed: bool
    commit_sha: str = ""
    branch: str = ""
    reason: str = ""
    checks: list[str] = field(default_factory=list)
    test_output: str = ""
    #: Set in `pr` mode. `pushed` stays False — nothing reached `main`.
    pr_url: str = ""


@dataclass
class CmdResult:
    ok: bool
    out: str = ""
    err: str = ""

    @property
    def text(self) -> str:
        return (self.out or "") + (("\n" + self.err) if self.err else "")


def _default_run(args: Sequence[str], cwd: Path, timeout: int = 1800) -> CmdResult:
    import subprocess
    try:
        p = subprocess.run(list(args), cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout, check=False)
        return CmdResult(p.returncode == 0, p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return CmdResult(False, "", f"timeout after {timeout}s")
    except OSError as e:
        return CmdResult(False, "", str(e))


@dataclass
class Lander:
    run: Callable[..., CmdResult] = _default_run
    dry_run: bool = True
    #: "push" merges straight into `base`; "pr" pushes the branch and opens a
    #: pull request, leaving the merge to a human and the verification to the
    #: repo's own required checks. See `land()` for why `pr` runs no suite.
    mode: str = "push"

    # ── gates that run before anything is committed ───────────────────────

    def preflight(self, task: TaskRef, changed_files: Sequence[str],
                  policy: Optional[RepoPolicy] = None) -> list[str]:
        """Refuse anything that must not land. Returns the checks that passed."""
        policy = policy or task.policy
        checks: list[str] = []

        if not changed_files:
            raise LandingRefused(
                "nothing changed — the agent reported no edits, so there is "
                "nothing to land")
        checks.append(f"diff_non_empty: {len(changed_files)} file(s)")

        if len(changed_files) > policy.max_files_changed:
            raise LandingRefused(
                f"blast radius: {len(changed_files)} files changed, cap is "
                f"{policy.max_files_changed}. A correct fix this wide is still "
                f"an unreviewable one")
        checks.append(f"blast_radius: within {policy.max_files_changed} files")

        allowed = extract_allow_protected(
            title=task.title, notes_at_claim=task.notes_at_claim)
        hits = protected_hits(changed_files, policy.protected_paths)
        unauthorised = [
            p for p, _ in hits
            if not any(_glob_ok(p, a) for a in allowed)
        ]
        if unauthorised:
            raise LandingRefused(
                f"protected paths touched without `allow-protected:` "
                f"authorisation: {', '.join(sorted(unauthorised))}")
        checks.append("protected_paths: clean"
                      + (f" ({len(hits)} authorised)" if hits else ""))
        return checks

    # ── the sequence ──────────────────────────────────────────────────────

    def land(self, checkout: Path, task: TaskRef, *, branch: str,
             message: str, changed_files: Sequence[str],
             base: str = "main", test_command: Optional[Sequence[str]] = None,
             policy: Optional[RepoPolicy] = None, test_cwd: str = ".",
             test_timeout: int = 1800) -> LandResult:
        policy = policy or task.policy
        checks = self.preflight(task, changed_files, policy)

        def git(*args, timeout=300) -> CmdResult:
            return self.run(["git", "-C", str(checkout), *args], checkout, timeout)

        if not git("checkout", "-B", branch).ok:
            raise LandingRefused(f"could not create branch {branch}")
        if not git("add", "-A").ok:
            raise LandingRefused("git add failed")
        commit = git("commit", "-m", message)
        if not commit.ok and "nothing to commit" in commit.text.lower():
            raise LandingRefused("nothing to commit after staging")
        if not commit.ok:
            raise LandingRefused(f"commit failed: {commit.text[:200]}")
        checks.append(f"committed on {branch}")

        # Verify against what main IS, not what it was when the branch started.
        if not git("fetch", "origin", base).ok:
            raise LandingRefused(f"could not fetch origin/{base}")
        merge = git("merge", "--no-edit", f"origin/{base}")
        if not merge.ok:
            git("merge", "--abort")
            raise LandingRefused(
                f"conflicts with current origin/{base} — a human should "
                f"resolve this rather than an unattended merge")
        checks.append(f"merged current origin/{base}")

        # In `pr` mode the repo's own required checks are the gate, so running
        # the suite here as well would burn the expensive half of the job twice
        # on one runner to learn the same thing. It is also the wrong place to
        # learn it: a suite failure here would be swallowed into an agent log
        # nobody reads, whereas the same failure on a pull request is visible,
        # attributable and already wired to the merge button. A branch that
        # cannot pass CI should still become a PR — a red PR is a reviewable
        # artifact, and discarding it is what the old dry run got wrong.
        test_output = ""
        if test_command and self.mode == "pr":
            checks.append("suite skipped — the pull request's own checks gate this")
        elif test_command:
            res = self.run(list(test_command), checkout / test_cwd, test_timeout)
            test_output = res.text[-8000:]
            if not res.ok:
                raise LandingRefused(
                    f"suite failed on the merge result — refusing to push. "
                    f"Last output:\n{test_output[-1500:]}")
            checks.append(f"suite green: {shlex.join(test_command)}")
        else:
            # Not fatal, but it must be visible: without a suite, "lands on
            # green" is an empty phrase, and the prod watcher is the only
            # remaining net.
            checks.append("NO TEST COMMAND — nothing verified this change")
            logger.warning("landing %s with no test command", task.task_id)

        sha = git("rev-parse", "HEAD").out.strip()

        if self.dry_run:
            return LandResult(False, commit_sha=sha, branch=branch,
                              reason="dry run — everything but the push",
                              checks=checks, test_output=test_output)

        if self.mode == "pr":
            return self._open_pr(checkout, task, sha=sha, branch=branch,
                                 message=message, base=base, checks=checks,
                                 test_output=test_output)

        # Explicit refspec: a bare `git push origin main` pushes the local
        # `main` ref regardless of which branch we are standing on, which
        # silently no-ops while the commit sits somewhere else.
        push = git("push", "origin", f"HEAD:{base}")
        if not push.ok:
            raise LandingRefused(
                f"push rejected (someone else landed first?): "
                f"{push.text[:200]}")
        checks.append(f"pushed {sha[:8]} → {base}")
        return LandResult(True, commit_sha=sha, branch=branch,
                          reason="landed", checks=checks,
                          test_output=test_output)

    # ── pr mode ───────────────────────────────────────────────────────────

    def _open_pr(self, checkout: Path, task: TaskRef, *, sha: str, branch: str,
                 message: str, base: str, checks: list[str],
                 test_output: str) -> LandResult:
        """Push the branch and open a pull request. Never touches `base`."""
        def git(*args, timeout=300) -> CmdResult:
            return self.run(["git", "-C", str(checkout), *args], checkout, timeout)

        def gh(*args, timeout=300) -> CmdResult:
            return self.run(["gh", *args], checkout, timeout)

        # --force-with-lease so a re-run after a crash updates the branch it
        # already owns, while still refusing if someone else moved it. A plain
        # push would wedge every retry; a plain --force would not notice.
        push = git("push", "--force-with-lease", "origin",
                   f"HEAD:refs/heads/{branch}")
        if not push.ok:
            raise LandingRefused(f"could not push branch {branch}: "
                                 f"{push.text[:200]}")
        checks.append(f"pushed {sha[:8]} → {branch}")

        title = message.splitlines()[0].strip() or f"taskauto: {task.task_id}"
        body = self._pr_body(task, checks)

        pr = gh("pr", "create", "--base", base, "--head", branch,
                "--title", title, "--body", body)
        url = pr.out.strip().splitlines()[-1] if pr.ok and pr.out.strip() else ""

        if not pr.ok:
            # The usual cause is a PR already open for this head, which is the
            # normal state on a retry rather than an error. Ask for it before
            # deciding this failed — the branch is pushed either way, so
            # raising here would strand real work over a duplicate-create.
            existing = gh("pr", "view", branch, "--json", "url", "--jq", ".url")
            if existing.ok and existing.out.strip():
                url = existing.out.strip().splitlines()[-1]
                checks.append("pull request already open for this branch")
            else:
                raise LandingRefused(
                    f"branch {branch} is pushed but opening a pull request "
                    f"failed: {pr.text[:200]}")
        else:
            checks.append(f"opened pull request {url}")

        return LandResult(False, commit_sha=sha, branch=branch,
                          reason="pull request opened — a human merges it",
                          checks=checks, test_output=test_output, pr_url=url)

    @staticmethod
    def _pr_body(task: TaskRef, checks: Sequence[str]) -> str:
        lines = [
            f"Opened by hadoku-task-automation for task `{task.task_id}`.",
            "",
            f"**Task as filed:** {task.title}",
            "",
            "Nobody has reviewed this. The repo's own required checks are the "
            "gate — merge it if they are green and the diff reads right.",
            "",
            "### Preflight",
        ]
        lines += [f"- {c}" for c in checks]
        return "\n".join(lines)


def _glob_ok(path: str, pattern: str) -> bool:
    from ..gates.taskauto.protected_paths import _matches
    return _matches(path, pattern)
