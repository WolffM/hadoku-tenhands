"""Landing: commit, verify against current `main`, then push or open a PR.

Two modes:

* **`pr` (preferred)** — push the branch, open a pull request, and arm GitHub
  auto-merge so it lands when the repo's required checks go green. Verification
  is those checks, so nothing here runs the suite: the pull request *is* the dry
  run, and unlike the old one it persists, is reviewable, and lands itself.

  Auto-merge is armed **only if the base branch has required status checks**.
  See `_arm_auto_merge` — the distinction is the whole safety property, and it
  is not the one you would guess from the flag's name.
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
from . import proc
from .manifests import ManifestVerdict, classify_diff, classify_files
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
    #: `pr` mode: GitHub is holding this PR to merge when its required checks
    #: go green. False means it is waiting for a human, and `checks` says why.
    auto_merge_armed: bool = False


@dataclass
class CmdResult:
    ok: bool
    out: str = ""
    err: str = ""

    @property
    def text(self) -> str:
        return (self.out or "") + (("\n" + self.err) if self.err else "")


def _default_run(args: Sequence[str], cwd: Path, timeout: int = 1800) -> CmdResult:
    """Run a git/gh/test command with its whole tree bounded.

    The test command is why this goes through `proc.run` rather than
    `subprocess.run`: `pnpm test` is a process *tree*, and a repo's suite can
    spawn a typechecker, a bundler or a browser. A timeout that kills `pnpm`
    and leaves the rest running is the exact shape of bug that took the host
    down on 2026-07-29 — from the agent's side that time, but this side has the
    same anatomy and had the same hole.

    Timeout output is preserved on purpose: a suite that hangs usually names
    the hanging test in its last lines, and reporting a bare "timeout after
    1800s" throws away the only evidence of which one.
    """
    res = proc.run(list(args), cwd=cwd, timeout=timeout, label="land")
    if res.timed_out:
        return CmdResult(False, res.out, f"timeout after {timeout}s\n{res.err}")
    if res.out_of_memory:
        return CmdResult(False, res.out,
                         f"killed: this command's process tree exceeded "
                         f"{proc.DEFAULT_MEMORY_MAX}\n{res.err}")
    return CmdResult(res.ok, res.out, res.err)


@dataclass
class Lander:
    run: Callable[..., CmdResult] = _default_run
    dry_run: bool = True
    #: "push" merges straight into `base`; "pr" pushes the branch and opens a
    #: pull request, leaving the verification to the repo's own required
    #: checks. See `land()` for why `pr` runs no suite.
    mode: str = "push"
    #: `pr` mode: ask GitHub to merge the PR when its required checks pass.
    #: Ignored on repos whose base branch has none — see `_arm_auto_merge`.
    auto_merge: bool = True

    # ── gates that run before anything is committed ───────────────────────

    def preflight(self, task: TaskRef, changed_files: Sequence[str],
                  policy: Optional[RepoPolicy] = None, *,
                  checkout: Optional[Path] = None,
                  diff_text: Optional[str] = None) -> list[str]:
        """Refuse anything that must not land. Returns the checks that passed.

        `checkout` and `diff_text` are what the manifest rule reads. With a
        checkout it is exact — both sides of every manifest, parsed — and with
        only a diff it is the conservative form. With neither, a touched
        manifest is a refusal: this is the last thing between the diff and
        `main`, so "a manifest changed and I could not see how" cannot pass.
        """
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
            # States the fact, and deliberately does NOT name the
            # `allow-protected:` override. This string is read on a phone by
            # someone who wanted a change, not a lesson in the gate's API; the
            # override needs an exact incantation in the task title and nobody
            # is going to recall it months later. `jobs._refusal_advice` says
            # what this class of refusal means instead. The mechanism still
            # exists for the rare case someone reaches for it deliberately.
            raise LandingRefused(
                f"protected paths touched: {', '.join(sorted(unauthorised))}")
        checks.append("protected_paths: clean"
                      + (f" ({len(hits)} authorised)" if hits else ""))

        # Manifests are judged by content, not by being touched — see
        # `manifests` for why the path rule was the wrong question. The
        # `allow-protected:` override still applies, and is still the only way
        # a genuine new dependency lands unattended.
        manifests = [p for p, _ in protected_hits(changed_files,
                                                  policy.manifest_paths)]
        to_judge = [p for p in manifests
                    if not any(_glob_ok(p, a) for a in allowed)]
        if to_judge:
            verdict = self._judge_manifests(to_judge, checkout, diff_text)
            if not verdict.ok:
                raise LandingRefused(f"manifest change refused: {verdict.reason}")
            checks.append(f"manifests: {verdict.reason}")
        elif manifests:
            checks.append(f"manifests: {len(manifests)} authorised")
        return checks

    def _judge_manifests(self, paths: Sequence[str], checkout: Optional[Path],
                         diff_text: Optional[str]) -> ManifestVerdict:
        """Exact from a checkout, conservative from a diff, refuse from
        neither."""
        if checkout is not None:
            sides: dict[str, tuple[Optional[str], Optional[str]]] = {}
            for path in paths:
                # HEAD is the "before": preflight runs before `checkout -B`,
                # so the working tree holds the agent's edits and HEAD holds
                # what the branch was cut from.
                shown = self.run(
                    ["git", "-C", str(checkout), "show", f"HEAD:{path}"],
                    checkout, 60)
                old_text = shown.out if shown.ok else None
                disk = Path(checkout) / path
                try:
                    new_text = disk.read_text(encoding="utf-8")
                except OSError:
                    new_text = None
                sides[path] = (old_text, new_text)
            return classify_files(sides)
        if diff_text is not None:
            return classify_diff(diff_text, paths)
        return ManifestVerdict(
            ok=False,
            reason=(f"{len(paths)} manifest(s) changed with neither a checkout "
                    f"nor a diff to judge them by"),
            refusals=tuple(f"{p}: nothing to read" for p in paths),
        )

    # ── the sequence ──────────────────────────────────────────────────────

    def land(self, checkout: Path, task: TaskRef, *, branch: str,
             message: str, changed_files: Sequence[str],
             base: str = "main", test_command: Optional[Sequence[str]] = None,
             policy: Optional[RepoPolicy] = None, test_cwd: str = ".",
             test_timeout: int = 1800,
             diff_text: Optional[str] = None) -> LandResult:
        policy = policy or task.policy
        checks = self.preflight(task, changed_files, policy,
                                checkout=checkout, diff_text=diff_text)

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

        # Read protection *before* creating the PR, so the body can state which
        # of the two things is about to happen rather than describing a policy
        # and leaving the reader to work out which branch of it they got.
        required = self._required_check_count(gh, task, base) if self.auto_merge else 0
        if self.auto_merge and required == 0:
            checks.append(
                f"auto-merge HELD — {task.repo_slug}@{base} has no required "
                f"status checks, and `--auto` on an unprotected branch merges "
                f"immediately rather than on green. A human merges this one")
            logger.warning("auto-merge held on %s: %s@%s has no required checks",
                           task.task_id, task.repo_slug, base)

        title = message.splitlines()[0].strip() or f"taskauto: {task.task_id}"
        body = self._pr_body(task, checks, base=base, required=required)

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

        armed = False
        if required:
            merged = gh("pr", "merge", branch, "--repo", task.repo_slug,
                        "--squash", "--auto", "--delete-branch", timeout=60)
            armed = merged.ok
            if armed:
                checks.append(f"auto-merge armed — lands when {required} "
                              f"required check(s) on {base} go green")
            else:
                # Never raise: the branch is pushed and the PR is open by now,
                # so this is a worse outcome to report, not a reason to strand
                # real work. A human merges it, which is where we were before.
                checks.append(f"auto-merge could not be armed, so a human "
                              f"merges this one: {merged.text[:200]}")
                logger.warning("auto-merge not armed on %s: %s",
                               task.task_id, merged.text[:200])

        return LandResult(False, commit_sha=sha, branch=branch,
                          reason=("pull request opened — merges itself on green"
                                  if armed else
                                  "pull request opened — a human merges it"),
                          checks=checks, test_output=test_output, pr_url=url,
                          auto_merge_armed=armed)

    @staticmethod
    def _required_check_count(gh: Callable[..., CmdResult], task: TaskRef,
                              base: str) -> int:
        """How many *required* status checks `base` has. Zero holds the merge.

        **The question is not "does this PR have checks" — it is "does `base`
        require any".** Those are different, and only the second is safe to act
        on. `--auto` waits for required checks and nothing else, so on a branch
        with none configured it schedules nothing: it merges on the spot,
        unreviewed. A PR covered in green non-required checks looks identical
        from here, which is exactly how that mistake gets made. So this reads
        the repo's protection, never the pull request's own rollup.

        Fails closed. An unreadable response, a `gh` error, or a payload shape
        we did not expect all count as *no* protection, because every one of
        them means we do not know — and not knowing is the case where merging
        unattended is worst.
        """
        res = gh("api", f"repos/{task.repo_slug}/branches/{base}",
                 "--jq", ".protection.required_status_checks.contexts "
                         "// [] | length", timeout=30)
        if not res.ok:
            logger.warning("could not read protection for %s@%s: %s",
                           task.repo_slug, base, res.text[:200])
            return 0
        try:
            return int((res.out or "").strip())
        except ValueError:
            logger.warning("unreadable protection payload for %s@%s: %r",
                           task.repo_slug, base, (res.out or "")[:200])
            return 0

    @staticmethod
    def _pr_body(task: TaskRef, checks: Sequence[str], *,
                 base: str = "main", required: int = 0) -> str:
        gate = (
            f"Nobody has reviewed this. **Auto-merge is armed**: GitHub lands it "
            f"when the {required} required check(s) on `{base}` go green, and "
            f"leaves it open if any of them go red. Close it or disable "
            f"auto-merge if the diff reads wrong."
            if required else
            "Nobody has reviewed this, and auto-merge is **not** armed because "
            "this repo's base branch has no required status checks — arming it "
            "there would merge on the spot rather than on green. Merge it by "
            "hand if the diff reads right."
        )
        lines = [
            f"Opened by hadoku-task-automation for task `{task.task_id}`.",
            "",
            f"**Task as filed:** {task.title}",
            "",
            gate,
            "",
            "### Preflight",
        ]
        lines += [f"- {c}" for c in checks]
        return "\n".join(lines)


def _glob_ok(path: str, pattern: str) -> bool:
    from ..gates.taskauto.protected_paths import _matches
    return _matches(path, pattern)
