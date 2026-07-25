"""Pm2 entrypoint for the hadoku-task-automation scheduler.

Thin shim, same shape as `run_worker.py`: pm2 invokes it directly, and
`sys.path[0]` resolves to `backend/` so `temporal.taskauto` finds the
in-repo package.

**This service does not push by default.** It runs the full pipeline —
clone, plan, implement, commit, merge current `main` in, run the whole
suite — and stops before the push unless `TASKAUTO_LIVE=1`. Deploying an
always-on process that merges to `main` should be a deliberate act, not a
side effect of a deploy landing, so arming it is one explicit env var.

Configuration (all via the pm2 wrapper's vault mapping):

    TASKAUTO_BOARDS   comma-separated board handles. Required; the service
                      exits rather than guessing, because a wrong handle
                      would silently watch nothing.
    TASKAUTO_LIVE     "1" to actually push. Anything else is a dry run.
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


def build_runner(client: TaskBoardClient, handle: str, *, live: bool) -> Runner:
    board = client.get_board(handle)
    if not board.repo:
        raise SystemExit(
            f"board {handle} has no `repo` set — cannot map it to a checkout. "
            f"Re-activate it with `repo` in the payload.")

    policy = POLICIES.get(board.repo, RepoPolicy())
    health_url, _ = HEALTH.get(board.repo, ("", ""))
    checkouts = CheckoutManager()
    agent = ClaudeCodeAgent()

    logger.info("board %s → %s | suite: %s | health: %s",
                handle[:10], board.repo,
                " ".join(policy.test_command) or "NONE",
                health_url or "NONE")

    return Runner(client, handle, jobs={
        "plan": make_plan_job(agent, checkouts, base_branch=policy.base_branch),
        "implement": make_implement_job(
            agent, checkouts, Lander(dry_run=not live),
            base_branch=policy.base_branch,
            test_command=list(policy.test_command) or None,
            test_cwd=policy.test_cwd, policy=policy,
            watcher=ProdWatcher(run=_gh, http=_http) if health_url else None,
            reverter=Reverter(run=_git), health_url=health_url),
    })


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("TASKAUTO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    handles = [h.strip() for h in
               os.environ.get("TASKAUTO_BOARDS", "").split(",") if h.strip()]
    if not handles:
        logger.error("TASKAUTO_BOARDS is empty — nothing to watch. Set it to a "
                     "comma-separated list of board handles (the ULID, not the "
                     "slug: slugs are per-user and collide).")
        return 2

    if not _ambient_key():
        logger.error("No board credential. Set HADOKU_TASK_KEY.")
        return 2

    live = os.environ.get("TASKAUTO_LIVE", "") == "1"
    logger.warning("taskauto starting — %s",
                   "LIVE: will push to main" if live else
                   "DRY RUN: will verify but not push (set TASKAUTO_LIVE=1 to arm)")

    client = TaskBoardClient()

    # One unusable board must not crashloop the service. pm2 restarts on
    # exit, so an exception here becomes a restart loop that watches nothing
    # — including the boards that were fine.
    runners = {}
    for handle in handles:
        try:
            runners[handle] = build_runner(client, handle, live=live)
        except Exception as e:
            logger.error("skipping board %s: %s: %s",
                         handle, type(e).__name__, e)
    if not runners:
        logger.error("no usable boards out of %d configured — exiting rather "
                     "than idling forever against nothing", len(handles))
        return 2

    Scheduler(client=client, boards=list(runners),
              runner_for=runners.__getitem__).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
