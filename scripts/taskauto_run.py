#!/usr/bin/env python3
"""Run one turn of the hadoku-task-automation pipeline.

    node ../hadoku_site/scripts/secrets/dev-vault.mjs -- \\
        python3 scripts/taskauto_run.py <board-handle> [--live] [--turns N]

**Dry run by default.** Without `--live` the pipeline does everything —
clones, plans, implements, commits, merges current `main` in, runs the whole
suite — and stops short of the push. That produces all the evidence and none
of the consequences, which is what you want the first time a repo is
automated. `--live` is the only difference between a rehearsal and a landing.

One turn does at most one thing. Looping is `--turns`, and it stops early the
moment a turn is idle, so a quiet board costs one board read.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.task_board import TaskBoardClient, _ambient_key  # noqa: E402
from temporal.taskauto.agent import ClaudeCodeAgent  # noqa: E402
from temporal.taskauto.checkout import CheckoutManager  # noqa: E402
from temporal.taskauto.jobs import make_implement_job, make_plan_job  # noqa: E402
from temporal.taskauto.landing import Lander  # noqa: E402
from temporal.taskauto.refs import RepoPolicy  # noqa: E402
from temporal.taskauto.runner import Runner  # noqa: E402
from temporal.taskauto.scheduler import Scheduler  # noqa: E402
from temporal.taskauto.watch import ProdWatcher, Reverter  # noqa: E402

#: Per-repo policy. A repo with no entry gets defaults — which means no test
#: command, and the lander records that loudly rather than pretending the
#: change was verified.
#:
#: tenhands runs its suite through the interpreter of the *human* checkout's
#: venv: the pipeline clone has no venv of its own, and the deps are identical.
#: The code under test still comes from the pipeline checkout (cwd), so this
#: borrows an interpreter, not a codebase. A pipeline-owned venv is the
#: correct fix and is not built yet.
#: Health signal per repo, probed on localhost because the watcher runs on
#: the same host. Going through the edge is worse than useless here:
#: hadoku.me/tenhands/health returns 200 with the SPA shell whether or not
#: the backend is alive, so a status-code check would call a dead service
#: healthy. `must_contain` is what makes the check mean something.
HEALTH = {
    "WolffM/tenhands": ("http://127.0.0.1:5024/tenhands/api/healthcheck",
                        '"status":"healthy"'),
}

POLICIES = {
    "WolffM/tenhands": RepoPolicy(
        test_command=("/home/hadoku/repos/tenhands/.venv/bin/python",
                      "-m", "pytest", "tests/", "-q"),
        test_cwd="backend",
        max_files_changed=12,
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("handle")
    ap.add_argument("--live", action="store_true",
                    help="actually push to main (default: stop before the push)")
    ap.add_argument("--turns", type=int, default=1)
    ap.add_argument("--serve", action="store_true",
                    help="run the scheduler loop instead of a fixed number of "
                         "turns (this is the unattended mode)")
    ap.add_argument("--max-ticks", type=int, default=None,
                    help="with --serve: stop after N polls (default: forever)")
    ap.add_argument("--settle-seconds", type=int, default=None,
                    help="override the Inbox settle delay")
    ap.add_argument("--watch-seconds", type=int, default=600,
                    help="how long to sample prod health after a landing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if not _ambient_key():
        print("No board credential — run through dev-vault.mjs.", file=sys.stderr)
        return 2

    client = TaskBoardClient()
    board = client.get_board(args.handle)
    if not board.repo:
        print(f"board {args.handle} has no `repo` set; cannot map to a checkout.",
              file=sys.stderr)
        return 2

    policy = POLICIES.get(board.repo, RepoPolicy())
    checkouts = CheckoutManager()
    agent = ClaudeCodeAgent()
    lander = Lander(dry_run=not args.live)

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

    health_url, must_contain = HEALTH.get(board.repo, ("", ""))
    watcher = ProdWatcher(run=_gh, http=_http) if health_url else None
    reverter = Reverter(run=_git)

    kw = {}
    if args.settle_seconds is not None:
        from datetime import timedelta
        kw["settle"] = timedelta(seconds=args.settle_seconds)

    runner = Runner(client, args.handle, jobs={
        "plan": make_plan_job(agent, checkouts,
                              base_branch=policy.base_branch),
        "implement": make_implement_job(
            agent, checkouts, lander, base_branch=policy.base_branch,
            test_command=list(policy.test_command) or None,
            test_cwd=policy.test_cwd, policy=policy,
            watcher=watcher, reverter=reverter, health_url=health_url,
            watch_window_s=args.watch_seconds),
    }, **kw)

    print(f"board  : {board.name} ({board.repo})")
    print(f"mode   : {'LIVE — will push to main' if args.live else 'dry run'}")
    print(f"suite  : {' '.join(policy.test_command) or '(none configured)'}")
    print(f"health : {health_url or 'NONE — nothing will watch a landing'}")
    print()

    if args.serve:
        # Unattended. Polls the change feed for cheap hints and sweeps every
        # board periodically regardless — the sweep is the only thing that
        # recovers a crashed run or picks up a settled Inbox task, since
        # neither produces a change-feed entry when it becomes actionable.
        sched = Scheduler(client=client, boards=[args.handle],
                          runner_for=lambda _h: runner)
        print(f"serving: sweep every {sched.full_sweep_s:.0f}s, "
              f"poll {sched.active_interval_s:.0f}-{sched.idle_interval_s:.0f}s")
        sched.run(max_ticks=args.max_ticks,
                  on_tick=lambda r: print(f"  {time.strftime('%H:%M:%S')}  {r}"))
        return 0

    for i in range(args.turns):
        started = time.time()
        result = runner.turn()
        print(f"turn {i + 1}/{args.turns} ({time.time() - started:.0f}s): {result}")
        if not result.acted:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
