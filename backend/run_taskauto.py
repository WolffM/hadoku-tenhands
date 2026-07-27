"""Pm2 entrypoint for the hadoku-task-automation scheduler.

Thin shim, same shape as `run_worker.py`: pm2 invokes it directly, and
`sys.path[0]` resolves to `backend/` so `temporal.taskauto` finds the
in-repo package.

**This service does not push by default.** It runs the full pipeline —
clone, plan, implement, commit, merge current `main` in, run the whole
suite — and stops before the push unless `TASKAUTO_LIVE=1`. Deploying an
always-on process that merges to `main` should be a deliberate act, not a
side effect of a deploy landing, so arming it is one explicit env var.

**Boards are discovered, not configured.** Any board shared with this key
that has been activated with a lane set and records a repo is driven —
granting the key `contributor` on an automation board IS the act of
enrolling it. A configured list would have to be kept in step by hand, and
its drift is silent: a new board nobody wired up sits unwatched, and a
stale handle makes the service idle against nothing while looking healthy.

**Two shapes, one entrypoint.** `TASKAUTO_ONCE=1` drains what is actionable
now and exits — this is the CI-job shape, and it is the preferred one: a
long-lived process is a long-lived credential holder sitting next to the
services it can break, and it has to poll to find work. A fresh one-shot
process sweeps every board on its first tick, so it misses nothing by not
having been running; the sweep does not need to have been *watching*, only to
*look*. Without the flag it runs the scheduler loop forever (the pm2 shape).

**`TASKAUTO_MODE` decides what "done" means.** `pr` (default) pushes a branch
and opens a pull request for a human to merge, leaving verification to the
repo's own required checks. `push` merges into `main` unattended and is kept
only for repos where a pull request adds nothing.

Configuration:

    TASKAUTO_LIVE     "1" to actually push. Anything else is a dry run.
    TASKAUTO_MODE     "pr" (default) or "push".
    TASKAUTO_ONCE     "1" for a single drain pass, then exit.
    HADOKU_TASK_KEY   service-tier key for the board API.
"""

from __future__ import annotations

import logging
import os
import sys

from services.task_board import TaskBoardClient, _ambient_key
from temporal.taskauto.agent import ClaudeCodeAgent
from temporal.taskauto.checkout import CheckoutManager
from temporal.taskauto.jobs import make_implement_job, make_plan_job
from temporal.taskauto.landing import Lander
from temporal.taskauto.refs import RepoPolicy
from temporal.taskauto.runner import Runner
from temporal.taskauto.scheduler import Scheduler
from temporal.taskauto.watch import ProdWatcher, Reverter

logger = logging.getLogger("taskauto")

#: Ceiling on how much one one-shot run will do. A drain loop with no cap is
#: an unbounded CI job holding a runner; the next scheduled run picks up the
#: remainder, so stopping early costs latency and nothing else.
MAX_TICKS_PER_RUN = 8

#: Per-repo policy. A repo with no entry gets no test command, and the
#: lander records that loudly rather than pretending the change was verified.
POLICIES = {
    "WolffM/tenhands": RepoPolicy(
        test_command=(sys.executable, "-m", "pytest", "tests/", "-q"),
        test_cwd="backend",
        max_files_changed=12,
    ),
}

#: Health signal per repo, probed on loopback because this runs on the same
#: host. Going through the edge is worse than useless: hadoku.me/tenhands/
#: health returns 200 with the SPA shell whether or not the backend is
#: alive, so a status-code check would call a dead service healthy.
HEALTH = {
    "WolffM/tenhands": ("http://127.0.0.1:5024/tenhands/api/healthcheck",
                        '"status":"healthy"'),
}


def _gh(argv):
    import subprocess
    p = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    return p.returncode == 0, p.stdout


def _http(url):
    import requests
    r = requests.get(url, timeout=15)
    return r.status_code, r.text


def _git(argv):
    import subprocess
    from temporal.taskauto.landing import CmdResult
    p = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    return CmdResult(p.returncode == 0, p.stdout, p.stderr)


def build_runner(client: TaskBoardClient, board, *, live: bool,
                 mode: str = "pr") -> Runner:
    handle = board.handle
    policy = POLICIES.get(board.repo, RepoPolicy())
    health_url, _ = HEALTH.get(board.repo, ("", ""))
    checkouts = CheckoutManager()
    agent = ClaudeCodeAgent()

    # In `pr` mode nothing reaches `main`, so there is nothing to watch and
    # nothing to revert. Wiring the watcher anyway would be worse than
    # useless: it would sample production health after a run that changed
    # nothing, and attribute whatever it found to this task.
    watching = mode == "push" and bool(health_url)

    logger.info("board %s → %s | mode: %s | suite: %s | health: %s",
                handle[:10], board.repo, mode,
                " ".join(policy.test_command) if mode == "push" else "CI gates it",
                health_url if watching else "n/a in pr mode")

    return Runner(client, handle, jobs={
        "plan": make_plan_job(agent, checkouts, base_branch=policy.base_branch),
        "implement": make_implement_job(
            agent, checkouts, Lander(dry_run=not live, mode=mode),
            base_branch=policy.base_branch,
            test_command=list(policy.test_command) or None,
            test_cwd=policy.test_cwd, policy=policy,
            watcher=ProdWatcher(run=_gh, http=_http) if watching else None,
            reverter=Reverter(run=_git) if watching else None,
            health_url=health_url if watching else ""),
    })


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("TASKAUTO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if not _ambient_key():
        logger.error("No board credential. Set HADOKU_TASK_KEY.")
        return 2

    live = os.environ.get("TASKAUTO_LIVE", "") == "1"
    mode = os.environ.get("TASKAUTO_MODE", "pr").strip().lower()
    if mode not in ("pr", "push"):
        logger.error("TASKAUTO_MODE=%r is not 'pr' or 'push'", mode)
        return 2
    once = os.environ.get("TASKAUTO_ONCE", "") == "1"

    if not live:
        posture = "DRY RUN: will verify but not push (set TASKAUTO_LIVE=1 to arm)"
    elif mode == "pr":
        posture = "LIVE: will open pull requests — nothing merges without a human"
    else:
        posture = "LIVE: will push straight to main, unreviewed"
    logger.warning("taskauto starting — %s", posture)

    client = TaskBoardClient()
    boards = client.automation_boards()
    if not boards:
        logger.error("no automation boards are shared with this key. Share one "
                     "at `contributor` and activate it; nothing else is needed.")
        return 2

    # Two boards driving one repo would land into the same checkout
    # concurrently, and two commits inside one prod-watch window cannot be
    # attributed if health goes red. Almost certainly a mistake, so say so
    # loudly and drive the first rather than silently doing both.
    runners, claimed_repos = {}, {}
    for board in boards:
        if board.repo in claimed_repos:
            logger.error("board %s (%s) drives %s, already driven by %s — "
                         "skipping it. One board per repo.",
                         board.handle[:10], board.name, board.repo,
                         claimed_repos[board.repo])
            continue
        try:
            runners[board.handle] = build_runner(client, board, live=live,
                                                 mode=mode)
            claimed_repos[board.repo] = board.name
        except Exception as e:
            logger.error("skipping board %s: %s: %s",
                         board.handle[:10], type(e).__name__, e)

    if not runners:
        logger.error("no usable boards out of %d discovered", len(boards))
        return 2

    scheduler = Scheduler(client=client, boards=list(runners),
                          runner_for=runners.__getitem__)

    if not once:
        scheduler.run()
        return 0

    # One-shot: drain whatever is actionable right now, then exit. This is the
    # shape a CI job wants — a fresh process sweeps every board on its first
    # tick (the cursor is unprimed and `_last_sweep` is 0), so nothing is
    # missed by not having been running earlier. That is the property that
    # makes the daemon unnecessary: the sweep does not need to have been
    # watching, it only needs to look.
    #
    # Drain rather than a single tick because a tick acts on at most one task
    # per board, and a cron that lands one task per run makes a queue of five
    # take five cron periods for no reason.
    acted = 0
    for i in range(MAX_TICKS_PER_RUN):
        result = scheduler.tick()
        logger.info("tick %d: %s", i + 1, result)
        if not result.acted:
            break
        acted += 1
    else:
        logger.warning("hit the %d-tick cap with work still pending; the next "
                       "run picks up where this left off", MAX_TICKS_PER_RUN)

    logger.info("one-shot run finished: %d task(s) actioned", acted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
