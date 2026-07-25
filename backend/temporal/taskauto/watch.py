"""Watching production after a landing, and undoing it if prod goes red.

This is the load-bearing safety property of the whole pipeline. The gates
cut the failure rate; they do not eliminate it, and pretending otherwise is
how you end up trusting them too much. What makes landing-without-review
acceptable is that **the pipeline watches what it did and can take it back**.

Two signals, and they answer different questions:

- **The deploy** answers "did the change ship?" A failed deploy is
  unambiguous and arrives in a minute or two.
- **Health** answers "is the thing still working?" It has to be sampled for
  a while, because a service that restarts cleanly and then falls over
  thirty seconds later is exactly the case a single probe misses.

Three rules learned the hard way while wiring this up:

1. **A health check that can't fail is worse than none.** `/tenhands/health`
   through the edge returns 200 with the SPA shell whether or not the backend
   is alive. The watcher requires a *positive* assertion about the body, not
   just a status code, so a health signal has to actually mean something.
2. **Unknown is not healthy.** If the deploy can't be found or health can't
   be reached, the window ends in `unknown`, and an unknown is treated as a
   reason to revert — not a reason to relax.
3. **Revert first, ask later.** A revert is cheap and reversible; leaving a
   broken deploy up while someone decides is not.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_S = 600      # 10 min of watching after the deploy concludes
DEFAULT_POLL_S = 20
DEFAULT_DEPLOY_TIMEOUT_S = 900


@dataclass
class WatchResult:
    healthy: bool
    reason: str
    deploy_conclusion: str = ""
    samples: list[str] = field(default_factory=list)

    @property
    def should_revert(self) -> bool:
        return not self.healthy


@dataclass
class ProdWatcher:
    """Watches a deploy, then samples health for a window."""

    #: (args) -> (ok, stdout). Used for `gh`.
    run: Callable[[Sequence[str]], tuple]
    #: (url) -> (status:int, body:str). Raising is treated as unreachable.
    http: Callable[[str], tuple]
    sleep: Callable[[float], None] = time.sleep

    def deploy_conclusion(self, repo_slug: str, sha: str, *,
                          timeout_s: int = DEFAULT_DEPLOY_TIMEOUT_S,
                          poll_s: int = DEFAULT_POLL_S) -> str:
        """Wait for every workflow run on `sha` to finish. Worst wins.

        Returns a gh conclusion, or "" if no run ever appeared — which is
        not the same as success and must not be read as one.
        """
        deadline = time.monotonic() + timeout_s
        seen_any = False
        while time.monotonic() < deadline:
            ok, out = self.run(["gh", "run", "list", "-R", repo_slug,
                                "--commit", sha, "--json",
                                "status,conclusion", "--limit", "20"])
            if ok:
                try:
                    runs = json.loads(out or "[]")
                except (ValueError, TypeError):
                    runs = []
                if runs:
                    seen_any = True
                    if all(r.get("status") == "completed" for r in runs):
                        bad = [r.get("conclusion") for r in runs
                               if r.get("conclusion") not in ("success", "skipped",
                                                              "neutral")]
                        return bad[0] or "failure" if bad else "success"
            self.sleep(poll_s)
        return "timeout" if seen_any else ""

    def sample_health(self, url: str, must_contain: str, *,
                      window_s: int = DEFAULT_WINDOW_S,
                      poll_s: int = DEFAULT_POLL_S) -> tuple[bool, list[str]]:
        """Poll health across the window. **Any** bad sample fails it.

        Not "healthy at the end" — a service that comes up and then falls
        over is the case a single final probe is blind to.
        """
        samples: list[str] = []
        deadline = time.monotonic() + window_s
        first = True
        while True:
            try:
                status, body = self.http(url)
            except Exception as e:
                samples.append(f"unreachable: {type(e).__name__}")
                return False, samples
            if status != 200:
                samples.append(f"HTTP {status}")
                return False, samples
            if must_contain not in (body or ""):
                # The 200-with-SPA-shell case: a status code alone would
                # have called this healthy.
                samples.append(f"HTTP 200 but body lacks {must_contain!r}")
                return False, samples
            samples.append("ok")
            if not first and time.monotonic() >= deadline:
                return True, samples
            first = False
            if time.monotonic() >= deadline:
                return True, samples
            self.sleep(poll_s)

    def watch(self, repo_slug: str, sha: str, *, health_url: str,
              must_contain: str = '"status":"healthy"',
              window_s: int = DEFAULT_WINDOW_S,
              poll_s: int = DEFAULT_POLL_S) -> WatchResult:
        conclusion = self.deploy_conclusion(repo_slug, sha, poll_s=poll_s)
        if conclusion == "":
            return WatchResult(False, "no deploy run ever appeared for this "
                                      "commit — cannot confirm it shipped",
                               deploy_conclusion="")
        if conclusion != "success":
            return WatchResult(False, f"deploy concluded {conclusion}",
                               deploy_conclusion=conclusion)

        ok, samples = self.sample_health(health_url, must_contain,
                                         window_s=window_s, poll_s=poll_s)
        if not ok:
            return WatchResult(False, f"health check failed: {samples[-1]}",
                               deploy_conclusion=conclusion, samples=samples)
        return WatchResult(True, f"deploy success, health ok across "
                                 f"{len(samples)} sample(s)",
                           deploy_conclusion=conclusion, samples=samples)


@dataclass
class Reverter:
    """Puts `main` back. Deliberately blunt."""

    run: Callable[..., object]

    def revert(self, checkout: Path, sha: str, *, base: str = "main") -> str:
        """Revert `sha` on `base` and push. Returns the revert commit sha.

        A revert, not a force-push: history people may already have pulled
        stays intact, and the undo is itself reviewable. `-m 1` is passed so
        this works whether the landing was a plain commit or a merge.
        """
        def git(*args):
            return self.run(["git", "-C", str(checkout), *args])

        for args in (("fetch", "origin", base),
                     ("checkout", "--force", "-B", f"revert-{sha[:8]}",
                      f"origin/{base}")):
            res = git(*args)
            if not getattr(res, "ok", False):
                raise RuntimeError(f"revert setup failed at {args[0]}")

        res = git("revert", "--no-edit", "-m", "1", sha)
        if not getattr(res, "ok", False):
            # Try without -m for a non-merge commit.
            res = git("revert", "--no-edit", sha)
            if not getattr(res, "ok", False):
                raise RuntimeError(
                    f"could not revert {sha[:8]}: "
                    f"{getattr(res, 'err', '') or getattr(res, 'out', '')}"[:300])

        push = git("push", "origin", f"HEAD:{base}")
        if not getattr(push, "ok", False):
            raise RuntimeError(f"revert produced but push failed for {sha[:8]}")

        head = git("rev-parse", "HEAD")
        return (getattr(head, "out", "") or "").strip()
