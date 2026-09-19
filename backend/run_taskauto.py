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
that has been activated with a lane set is driven — granting the key
`contributor` on an automation board IS the act of enrolling it. A configured
list would have to be kept in step by hand, and its drift is silent: a new
board nobody wired up sits unwatched, and a stale handle makes the service
idle against nothing while looking healthy.

**And so are repos, as of autoland v3.** A board now carries one lane per
repo, each with the `owner/name` hung off the lane object, so adding a repo to
the pipeline is adding a lane — no deploy, no list here. What still lives in
this file is per-repo *policy* (`POLICIES`, `HEALTH`): what to run to verify a
change, and what to probe afterwards. A repo with no entry gets no test
command and the lander says so loudly rather than pretending otherwise.

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
    HADOKU_SERVICE_KEY  service-tier key for the board API. Must be the
                      `tenhands-service-key` identity — shares are granted
                      to it, and a valid key for any other identity simply
                      sees no boards.
"""

from __future__ import annotations

import logging
import os
import sys

from services.task_board import TaskBoardClient, _ambient_key, far_side_has_v3
from temporal.taskauto.agent import AgentUnavailable, ClaudeCodeAgent
from temporal.taskauto.checkout import CheckoutManager
from temporal.taskauto.jobs import (
    make_implement_job,
    make_plan_job,
    make_route_job,
)
from temporal.taskauto.landing import Lander
from temporal.taskauto import reconcile
from temporal.taskauto.refs import RepoPolicy
from temporal.taskauto.runner import BoardRunner, LaneRunner
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
#: host: one fewer credential in the probe path, and one fewer hop that can fail
#: independently of the thing being measured.
#:
#: The trap worth keeping in mind is still live — the bare prefix
#: `hadoku.me/tenhands/` serves the SPA shell, so it answers 200 whether or not
#: Flask is up, and a status-code check there would call a dead service healthy.
#: That is why the probe matches a substring below rather than trusting the
#: status: an HTML shell has to fail closed.
#:
#: What changed (hadoku-site cba34656, 2026-07-29) is that `/tenhands/api/*` is
#: now an edge route to Flask, so `hadoku.me/tenhands/api/healthcheck` returns
#: real health to an authenticated caller — verified. The edge is therefore no
#: longer *useless* for this, as this comment used to claim; it is merely
#: needless. Loopback stays because the reasons above don't depend on how the
#: edge routes this week.
HEALTH = {
    "WolffM/tenhands": ("http://127.0.0.1:5024/tenhands/api/healthcheck",
                        '"status":"healthy"'),
}


#: Exit code for "the agent cannot run". Distinct from 2 (misconfiguration)
#: because the fix is different — 2 wants someone to read this file's docstring,
#: this wants someone to replace a credential — and because `taskauto.yml`'s
#: reporting step keys the health check off the step's exit status. Any
#: non-zero turns the run red; a separate number makes the log say which.
EXIT_AGENT_DOWN = 3

#: Exit code for "the board provider is behind us". Distinct from 2 for the
#: same reason 3 is: the fix is neither a config change here nor a credential,
#: it is a deploy on the other side of the contract.
EXIT_FAR_SIDE_STALE = 4


def _agent_down(exc: Exception, *, acted: int = 0) -> int:
    """Report an unusable agent as a failed run, not a quiet success.

    This exists because the alternative is what actually happened on
    2026-08-08: a revoked `CLAUDE_CODE_OAUTH_TOKEN` produced a run that swept
    every board, "planned" a task, released it to `plan-review` and exited 0.
    Monitoring saw a healthy sweep. The only evidence was a task whose notes
    said `_No open questions._` and a `plan_s` of 3.7 seconds.

    Nothing here is recoverable in-process — every subsequent task would fail
    identically — so the run stops. The claim was already handed back in
    `Runner._run_claimed`, so no task is pinned while this is being fixed.
    """
    logger.error(
        "the coding agent could not be run — stopping this sweep after %d "
        "task(s). Every remaining task would fail the same way. Check "
        "CLAUDE_CODE_OAUTH_TOKEN (a revoked one exits 1 in ~3s and prints "
        "the 401 to stdout): %s", acted, exc)
    return EXIT_AGENT_DOWN


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


def build_board_runner(client: TaskBoardClient, board, *, live: bool,
                       mode: str = "pr") -> BoardRunner:
    """Wire up one board: a lane runner per repo, plus routing and reconcile.

    The per-repo bits that used to be per-board — the checkout, the policy, the
    health probe — are resolved from the LANE now. Everything that is genuinely
    board-wide (the agent, the checkout manager, PR reconciliation, the router)
    is built once and shared, which is the point of the board/lane split.
    """
    checkouts = CheckoutManager()
    agent = ClaudeCodeAgent()
    handle = board.handle

    def lane_runner(lane_tag: str) -> LaneRunner:
        repo = board.repo_for(lane_tag)
        policy = POLICIES.get(repo, RepoPolicy())
        health_url, _ = HEALTH.get(repo, ("", ""))

        # In `pr` mode nothing reaches `main`, so there is nothing to watch and
        # nothing to revert. Wiring the watcher anyway would be worse than
        # useless: it would sample production health after a run that changed
        # nothing, and attribute whatever it found to this task.
        watching = mode == "push" and bool(health_url)

        # `lock=` is what stops a second process working this repo's checkout at
        # the same time. GitHub already serialises Actions runs (the `taskauto`
        # concurrency group, plus a single `taskauto`-labelled runner), so the
        # process this excludes is a manual `run_taskauto.py` on the same host —
        # which is the documented local path and which GitHub cannot see.
        return LaneRunner(client, handle, lane_tag, lock=checkouts.lock, jobs={
            "plan": make_plan_job(agent, checkouts,
                                  base_branch=policy.base_branch),
            "implement": make_implement_job(
                agent, checkouts, Lander(dry_run=not live, mode=mode),
                base_branch=policy.base_branch,
                test_command=list(policy.test_command) or None,
                test_cwd=policy.test_cwd, policy=policy,
                watcher=ProdWatcher(run=_gh, http=_http) if watching else None,
                reverter=Reverter(run=_git) if watching else None,
                health_url=health_url if watching else ""),
        })

    for lane in board.repo_lanes:
        repo = lane.repo
        policy = POLICIES.get(repo, RepoPolicy())
        logger.info("  %-24s → %-28s | suite: %s", lane.tag, repo,
                    " ".join(policy.test_command) if mode == "push"
                    else "CI gates it")

    # Reconciliation is wired in BOTH modes on purpose. `pr` mode is where it
    # earns its keep — the PR being merged or closed is the only signal that a
    # task is finished or refused, and with auto-merge armed that signal is
    # usually GitHub rather than a person — but a `push`-mode board can still
    # hold tasks left over from a spell in `pr` mode, and those deserve
    # correcting too.
    return BoardRunner(client, handle, lane_runner_for=lane_runner,
                       route_job=make_route_job(agent),
                       pr_lookup=reconcile.gh_lookup(_gh))


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("TASKAUTO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    if not _ambient_key():
        logger.error("No board credential. Set HADOKU_SERVICE_KEY.")
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
        posture = ("LIVE: will open pull requests and arm auto-merge — they "
                   "land themselves on green, except on repos whose base "
                   "branch has no required checks, which hold for a human")
    else:
        posture = "LIVE: will push straight to main, unreviewed"
    logger.warning("taskauto starting — %s", posture)

    client = TaskBoardClient()
    boards = client.automation_boards()
    if not boards:
        logger.error("no automation boards are shared with this key. Share one "
                     "at `contributor` and activate it; nothing else is needed.")
        return 2

    # Two LANES driving one repo would land into the same checkout
    # concurrently, and two commits inside one prod-watch window cannot be
    # attributed if health goes red. v2 checked this per board, one repo each;
    # the hazard is unchanged and only the granularity moved, because the
    # serialisation was always really per-repo.
    #
    # Checked across every board, not within one: two boards each carrying a
    # `hadoku-conjure` lane collide exactly as two lanes on one board would.
    runners, claimed_repos, v2_boards = {}, {}, []
    for board in boards:
        if not board.repo_lanes:
            # A v2 board. Not an error and not our business any more — it is
            # simply a board this pipeline no longer drives. INFO, not WARNING:
            # one line per board per run, and a fleet mid-migration is a normal
            # state to be in for weeks.
            v2_boards.append(board.name)
            continue

        clash = [ln.tag for ln in board.repo_lanes if ln.repo in claimed_repos]
        if clash:
            logger.error("board %s (%s): lane(s) %s target repos already "
                         "driven elsewhere (%s) — skipping the whole board. "
                         "One lane per repo.",
                         board.handle[:10], board.name, ", ".join(clash),
                         ", ".join(sorted(
                             {claimed_repos[board.repo_for(t)] for t in clash})))
            continue

        logger.info("board %s (%s) | mode: %s | %d repo lane(s)",
                    board.handle[:10], board.name, mode,
                    len(board.repo_lanes))
        try:
            runners[board.handle] = build_board_runner(client, board,
                                                       live=live, mode=mode)
        except Exception as e:
            logger.error("skipping board %s: %s: %s",
                         board.handle[:10], type(e).__name__, e)
            continue
        for lane in board.repo_lanes:
            claimed_repos[lane.repo] = board.name

    if v2_boards:
        logger.info("not driving %d v2 board(s): %s", len(v2_boards),
                    ", ".join(sorted(v2_boards)))

    # Refuse to drive a repo-laned board against a pre-v3 worker. Unknown keys
    # are stripped rather than refused there, so every chip we published would
    # be silently discarded and every task would re-plan forever — the one
    # failure here with no symptom. `None` means we could not find out, which
    # is not evidence of a rollback, so it warns and carries on.
    if runners:
        ready = far_side_has_v3()
        if ready is False:
            logger.error(
                "hadoku-task does not advertise %s — its worker is pre-v3 or "
                "has been rolled back. Refusing to drive %d repo-laned "
                "board(s): a `status` we publish would be dropped without an "
                "error and every task would be re-planned forever. Nothing was "
                "claimed.", "NOTES_CHANGED", len(runners))
            return EXIT_FAR_SIDE_STALE
        if ready is None:
            logger.warning("could not confirm hadoku-task is on v3; "
                           "proceeding, because a failed probe is not evidence "
                           "of a rollback")

    if not runners:
        # **This is the line that cost 47 hours**, and the fix is to tell the
        # two cases apart rather than to soften both.
        #
        # v2 boards present, no v3 board yet: a fleet part-way through the
        # migration, which is a state it is legitimately in from the moment
        # this code ships until the first board is activated. Exiting non-zero
        # there turns every hourly run red for as long as that takes, which is
        # what happened between 2026-09-16 and 2026-09-18 — 95 red runs
        # reporting a misconfiguration that was really just an ordering.
        #
        # Nothing at all: still a misconfiguration, still exit 2. The share is
        # wrong, or the key is the wrong identity, and silence there is the
        # failure mode this pipeline fears most.
        if v2_boards:
            logger.info("nothing to drive yet — %d board(s) discovered and "
                        "none carry repo lanes. Activate one with the autoland "
                        "v3 lane set and this picks it up on the next run; "
                        "see docs/hadoku-task-automation/autoland-v3.md",
                        len(boards))
            return 0
        logger.error("no usable boards out of %d discovered", len(boards))
        return 2

    scheduler = Scheduler(client=client, boards=list(runners),
                          runner_for=runners.__getitem__)

    if not once:
        try:
            scheduler.run()
        except AgentUnavailable as e:
            return _agent_down(e)
        return 0

    # One-shot: drain whatever is actionable right now, then exit. This is the
    # shape a CI job wants — a fresh process sweeps every board on its first
    # tick (`Scheduler._last_sweep` starts as None, which is unconditionally
    # due), so nothing is missed by not having been running earlier. That is the
    # property that makes the daemon unnecessary: the sweep does not need to
    # have been watching, it only needs to look.
    #
    # Drain rather than a single tick because a tick acts on at most one task
    # per board, and a cron that lands one task per run makes a queue of five
    # take five cron periods for no reason.
    acted = 0
    for i in range(MAX_TICKS_PER_RUN):
        try:
            result = scheduler.tick()
        except AgentUnavailable as e:
            return _agent_down(e, acted=acted)
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
