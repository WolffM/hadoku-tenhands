"""Mapping a board's `repo` to a checkout the pipeline fully owns.

The board carries a *remote* ref (`WolffM/tenhands`). This turns that into a
local directory the pipeline can do anything to — `reset --hard`,
`clean -fdx`, force-checkout — without ever touching a human's working copy.

**Why not just use the existing checkout in ~/repos.** Three reasons, in
order of weight: the pipeline needs destructive operations to guarantee a
clean tree, and in a shared checkout those destroy uncommitted work with no
human present to stop them; `suite_green_on_merge_result` (G9) is meaningless
in a dirty tree, since a green run proves nothing and a red one blames the
wrong change; and recovery from a wedged pipeline clone should be `rm -rf`
plus a re-clone, not somebody's evening.

**Why we still borrow from it when it's there.** A fresh clone re-downloads
history we already have on disk. `--reference-if-able` points the clone at a
local object store, and `--dissociate` then copies what it used and drops the
link — so we get the local-speed clone with no lasting coupling. If the local
repo later prunes, moves, or is deleted, our clone doesn't care.

Everything here is written so that "no local copy exists" is the *ordinary*
path, not an error case. A repo we've never cloned must work identically,
just slower.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

logger = logging.getLogger(__name__)

#: Where pipeline-owned clones live. Deliberately outside ~/repos so they
#: never appear in a repo listing or get mistaken for a working checkout.
DEFAULT_ROOT = Path.home() / ".taskauto" / "repos"

#: Where to look for an existing clone worth borrowing objects from.
DEFAULT_LOCAL_SEARCH = (Path.home() / "repos",)


class CheckoutError(RuntimeError):
    """The repo could not be made ready. Never raised for 'no local copy'."""


def _lock_holder(path: Path) -> str:
    """Whatever the current holder wrote about itself, for the log line."""
    try:
        return path.read_text(errors="replace").strip() or "no holder recorded"
    except OSError:
        return "unreadable"


@dataclass
class RunResult:
    ok: bool
    out: str = ""
    err: str = ""


def _default_run(args: Sequence[str], cwd: Optional[Path] = None,
                 timeout: int = 600) -> RunResult:
    import subprocess
    try:
        p = subprocess.run(list(args), cwd=str(cwd) if cwd else None,
                           capture_output=True, text=True, timeout=timeout,
                           check=False)
        return RunResult(p.returncode == 0, p.stdout, p.stderr)
    except subprocess.TimeoutExpired:
        return RunResult(False, "", f"timeout after {timeout}s")
    except OSError as e:
        return RunResult(False, "", str(e))


def _normalise_remote(url: str) -> str:
    """Reduce a remote URL to `owner/name` for comparison.

    `git@github.com:WolffM/tenhands.git`, `https://github.com/WolffM/tenhands`
    and `.../tenhands.git` must all compare equal — otherwise we'd decline a
    perfectly good local reference over URL punctuation.
    """
    u = (url or "").strip().rstrip("/")
    if u.endswith(".git"):
        u = u[: -len(".git")]
    if "://" in u:
        u = u.split("://", 1)[1]
    if "@" in u and ":" in u:                 # scp-style git@host:owner/name
        u = u.split(":", 1)[1]
    else:
        # Drop a leading host segment, but ONLY if it really is one. This
        # function is handed both full URLs and bare `owner/name` slugs, and
        # blindly stripping the first segment turned "WolffM/tenhands" into
        # "tenhands" — which then failed to match its own remote, silently
        # declining every local reference.
        parts = u.split("/")
        if len(parts) > 2 or (len(parts) == 2 and "." in parts[0]):
            u = "/".join(parts[1:])
    return u.strip("/").lower()


@dataclass
class CheckoutManager:
    """Owns the pipeline's clones. One directory per `owner/name`."""

    root: Path = DEFAULT_ROOT
    local_search: Sequence[Path] = DEFAULT_LOCAL_SEARCH
    remote_template: str = "https://github.com/{slug}.git"
    run: Callable[..., RunResult] = _default_run

    # ── paths ─────────────────────────────────────────────────────────────

    def path_for(self, repo_slug: str) -> Path:
        owner, _, name = repo_slug.partition("/")
        if not owner or not name:
            raise CheckoutError(
                f"repo must be 'owner/name', got {repo_slug!r}. This comes "
                f"from the board's `repo` field — an unactivated or "
                f"misconfigured board leaves it empty."
            )
        return self.root / owner / name

    def remote_for(self, repo_slug: str) -> str:
        return self.remote_template.format(slug=repo_slug)

    def lock_path_for(self, repo_slug: str) -> Path:
        """The lockfile guarding this repo's checkout.

        A SIBLING of the checkout, never inside it. `reset_to` runs
        `clean -fdx` and `ensure` will `rmtree` a clone it judges unhealthy —
        either would delete a lockfile kept in the working tree, and the
        process holding it would never notice.
        """
        d = self.path_for(repo_slug)
        return d.parent / f"{d.name}.lock"

    # ── exclusion ─────────────────────────────────────────────────────────

    @contextmanager
    def lock(self, repo_slug: str, *,
             blocking: bool = False) -> Iterator[bool]:
        """Hold this repo's checkout exclusively. Yields whether we got it.

        **What this protects.** The checkout is a fixed host path
        (`~/.taskauto/repos/<owner>/<name>`), not a per-run workspace, and the
        pipeline does `reset --hard` / `clean -fdx` / force-checkout inside it.
        Two processes working the same repo at once would destroy each other's
        tree mid-run.

        **Why the board's claim protocol is not already enough.** It very
        nearly is: `selection.choose` refuses a board with any task in flight,
        one board drives one repo, and `Runner.turn` claims before it touches
        disk. The hole is narrow but real — two processes can both read the
        board before either claims, and if the board changed between those two
        reads they select *different* tasks, both claims succeed, and both run
        against this one directory. A claim serialises a task; only this
        serialises the directory.

        In practice the second process is not another Actions run — GitHub's
        `concurrency: taskauto` group and the single `taskauto`-labelled runner
        both prevent that. It is a manual `run_taskauto.py`, which CLAUDE.md
        documents as the local path and which GitHub cannot see.

        **Why flock and not a pidfile.** The kernel drops it when the holder
        exits, however it exits. A run cancelled mid-agent or killed by
        `timeout-minutes` leaves nothing to clean up, which a pidfile could not
        promise — and a stale lock nobody can clear is worse than the race,
        because it fails closed forever and silently.

        Non-blocking by default: contention means a real run is mid-flight and
        will hold this for minutes, so waiting only burns a job slot. The
        caller reports busy and the next tick retries.
        """
        path = self.lock_path_for(repo_slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
            try:
                fcntl.flock(fd, flags)
            except OSError:
                logger.warning(
                    "checkout for %s is locked by another process (%s); "
                    "skipping this turn", repo_slug, _lock_holder(path))
                yield False
                return
            try:
                # Diagnostics only — flock is what excludes. Written after
                # acquiring so a reader never sees a half-built line, and
                # deliberately not trusted for the decision above: a holder
                # that died leaves this text behind, and only the kernel knows
                # the lock itself is gone.
                os.truncate(fd, 0)
                os.write(fd, f"pid={os.getpid()} host={socket.gethostname()} "
                             f"repo={repo_slug}\n".encode())
                os.fsync(fd)
                yield True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # ── borrowing from a local copy ───────────────────────────────────────

    def local_reference(self, repo_slug: str) -> Optional[Path]:
        """A local clone whose objects are safe to borrow, or None.

        Returning None is a completely ordinary outcome — a repo nobody has
        cloned locally is normal, and the caller must treat it that way.

        We only borrow from a repo we can positively identify as the same
        one. A same-named directory that turns out to be a different project
        would contribute nothing useful, and checking `origin` is one cheap
        command against the alternative of a confusing slow path.
        """
        _, _, name = repo_slug.partition("/")
        want = _normalise_remote(repo_slug)

        for base in self.local_search:
            candidate = Path(base) / name
            if not (candidate / ".git").exists():
                continue

            # A shallow repo is a terrible reference: the objects we need may
            # simply not be there, and git's failure mode is a confusing
            # clone error rather than a clean miss.
            if (candidate / ".git" / "shallow").exists():
                logger.debug("skipping shallow local repo %s", candidate)
                continue

            res = self.run(["git", "-C", str(candidate),
                            "remote", "get-url", "origin"], timeout=30)
            if not res.ok:
                continue
            if _normalise_remote(res.out.strip()) != want:
                logger.debug("local %s points at a different remote", candidate)
                continue
            return candidate
        return None

    # ── the main entry point ──────────────────────────────────────────────

    def ensure(self, repo_slug: str, *, timeout: int = 900) -> Path:
        """Return a ready checkout for `repo_slug`, cloning if needed.

        Reuses an existing pipeline clone when there is a healthy one. A
        clone that exists but is broken is removed and redone rather than
        nursed — it holds nothing a human would miss.
        """
        dest = self.path_for(repo_slug)

        if dest.exists():
            if self._is_healthy(dest):
                return dest
            logger.warning("pipeline clone at %s is unusable; recloning", dest)
            shutil.rmtree(dest, ignore_errors=True)

        dest.parent.mkdir(parents=True, exist_ok=True)
        remote = self.remote_for(repo_slug)
        reference = self.local_reference(repo_slug)

        if reference is not None:
            args = ["git", "clone", "--reference-if-able", str(reference),
                    "--dissociate", remote, str(dest)]
            res = self.run(args, timeout=timeout)
            if res.ok:
                return dest
            # A local repo can be present and still unusable as a reference —
            # mid-gc, corrupt, permissions. Falling back costs a slower clone;
            # not falling back costs the whole task for no reason.
            logger.warning(
                "clone with reference %s failed (%s); retrying without",
                reference, (res.err or "").strip()[:200])
            shutil.rmtree(dest, ignore_errors=True)

        res = self.run(["git", "clone", remote, str(dest)], timeout=timeout)
        if not res.ok:
            raise CheckoutError(
                f"could not clone {remote}: {(res.err or res.out).strip()[:300]}")
        return dest

    def _is_healthy(self, dest: Path) -> bool:
        if not (dest / ".git").exists():
            return False
        return self.run(["git", "-C", str(dest), "rev-parse", "--git-dir"],
                        timeout=30).ok

    # ── housekeeping ──────────────────────────────────────────────────────

    #: Branches this pipeline creates, one per task. Left alone they
    #: accumulate forever — one per landing — and each one pins its commits
    #: against gc. Harmless as refs, expensive once each is a worktree.
    BRANCH_PREFIX = "taskauto/"

    def prune(self, repo_slug: str, *, keep: Sequence[str] = (),
              base: str = "main") -> list[str]:
        """Delete finished pipeline branches and any stale worktrees.

        Only touches refs under `taskauto/` — never a human's branch, and
        never `base`. A branch is finished when `base` already contains it;
        an unmerged one is left, because it is the only remaining copy of
        work that did not land.
        """
        dest = self.path_for(repo_slug)
        if not self._is_healthy(dest):
            return []

        removed: list[str] = []

        # Worktrees first: git refuses to delete a branch that one is on, and
        # a stale worktree directory is the thing that actually costs disk.
        self.run(["git", "-C", str(dest), "worktree", "prune"], timeout=60)

        res = self.run(["git", "-C", str(dest), "branch", "--merged",
                        f"origin/{base}", "--format=%(refname:short)"],
                       timeout=60)
        if not getattr(res, "ok", False):
            return []

        current = (self.run(["git", "-C", str(dest), "rev-parse",
                             "--abbrev-ref", "HEAD"], timeout=30).out or "").strip()

        for name in (getattr(res, "out", "") or "").splitlines():
            name = name.strip()
            if not name.startswith(self.BRANCH_PREFIX):
                continue
            if name in keep or name == current:
                # Deleting the branch we are standing on fails anyway; it
                # gets collected on the next run once HEAD has moved.
                continue
            if self.run(["git", "-C", str(dest), "branch", "-D", name],
                        timeout=60).ok:
                removed.append(name)

        if removed:
            logger.info("pruned %d finished branch(es) in %s",
                        len(removed), dest)
        return removed

    # ── getting to a known-clean state ────────────────────────────────────

    def reset_to(self, repo_slug: str, base_branch: str, *,
                 timeout: int = 600) -> Path:
        """Fetch and force the checkout to exactly `origin/<base_branch>`.

        This is the precondition every gate downstream assumes: no local
        edits, no stale branch, no leftover files from a previous task. It is
        safe *because* the directory is ours — the same commands against a
        human's checkout would be an act of vandalism.
        """
        dest = self.ensure(repo_slug)
        steps = [
            ["git", "-C", str(dest), "fetch", "origin", "--prune"],
            ["git", "-C", str(dest), "checkout", "--force", "-B", base_branch,
             f"origin/{base_branch}"],
            ["git", "-C", str(dest), "reset", "--hard", f"origin/{base_branch}"],
            ["git", "-C", str(dest), "clean", "-fdx"],
        ]
        for args in steps:
            res = self.run(args, timeout=timeout)
            if not res.ok:
                raise CheckoutError(
                    f"{' '.join(args[3:])} failed in {dest}: "
                    f"{(res.err or res.out).strip()[:300]}")
        return dest
