"""One turn of the pipeline: read a board, claim one task per repo, run a job.

Deliberately *one turn* rather than a daemon loop. A single pass that either
does something or explains why it didn't is the unit that's easy to run by
hand, easy to schedule, and easy to reason about when something goes wrong.
Looping is the caller's business.

Two levels, because autoland v3 gave the board and the repo different jobs:

- **`BoardRunner`** owns one board. It reads it ONCE, reconciles the pull
  requests, routes the Inbox, and then drives each repo lane. The single read
  is the point: N lane runners each calling `get_board` on the same board
  would be N identical round trips per tick, and it is what makes one board
  with N repos cheaper than N boards rather than merely tidier.
- **`LaneRunner`** owns one repo lane. One task in flight, one checkout lock,
  one claim.

The claim is the boundary of responsibility. Before it, nothing is ours and a
crash costs nothing. After it, **every path out must release it** — a claim
that outlives a turn idles the whole repo until the lease expires.
"""

from __future__ import annotations

import logging
import traceback
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, ContextManager, Optional

from services.task_board import (
    RELEASE_ABORTED,
    RELEASE_ABORTED_CLAIM_HELD,
    BoardSnapshot,
    ClaimHeld,
    LeaseLost,
    TaskBoardClient,
    TaskBoardError,
    TaskStatus,
)

from . import plan_notes, reconcile, selection
from .agent import AgentUnavailable
from .progress import METRICS_KEY, BoardSink
from .selection import Idle, Pickup

logger = logging.getLogger(__name__)

#: Requested at claim time. The server clamps to its own maximum (1 h); we ask
#: for less than we might need and heartbeat, so a crashed worker frees the
#: task sooner rather than pinning it for the maximum.
CLAIM_LEASE_SECONDS = 900

#: Routing reads a task and writes a lane. It needs no checkout and no agent
#: run of any length, so it holds a much shorter lease — a crashed router
#: should not pin an Inbox task for a quarter of an hour.
ROUTE_LEASE_SECONDS = 120


@dataclass
class TurnResult:
    """What one pass did. `acted` is False for every no-op reason."""

    acted: bool
    reason: str
    task_id: str = ""
    job: str = ""
    repo: str = ""
    #: What the job CONCLUDED — `plan:no-op`, `implement:no-plan`,
    #: `landed:<sha>`. Distinct from `reason`, which is why the task was picked
    #: up. Both are needed and they answer different questions: "why did this
    #: run" versus "what did it decide".
    outcome: str = ""
    #: The chip we left on the task, for the log.
    status: str = ""

    def __str__(self) -> str:
        if not self.acted:
            return f"idle: {self.reason}"
        tail = f" [{self.outcome}]" if self.outcome else ""
        where = f" in {self.repo}" if self.repo else ""
        return (f"{self.job} on {self.task_id}{where} → {self.status}"
                f"{tail} ({self.reason})")


#: A job takes (pickup, board, sink) and returns (status, notes, outcome).
#: Raising is allowed — the runner routes the failure to `blocked` rather than
#: leaving the task claimed.
Job = Callable[..., tuple]


def _blocked(label: str) -> TaskStatus:
    return TaskStatus(kind=selection.STATUS_BLOCKED, label=label)


class LaneRunner:
    """Drives one repo lane on one board."""

    def __init__(self, client: TaskBoardClient, board_handle: str,
                 lane_tag: str, *,
                 jobs: Optional[dict[str, Job]] = None,
                 settle: timedelta = selection.DEFAULT_SETTLE,
                 now: Optional[Callable[[], datetime]] = None,
                 lock: Optional[Callable[[str], ContextManager[bool]]] = None,
                 ) -> None:
        self.client = client
        self.board_handle = board_handle
        self.lane_tag = lane_tag
        self.jobs = jobs or {}
        self.settle = settle
        self._now = now or (lambda: datetime.now(timezone.utc))
        #: Called with the repo to exclude other processes from its checkout
        #: for the length of a job — `CheckoutManager.lock` in production.
        #: None means no exclusion, which is right for a runner whose jobs
        #: never touch disk (every unit test here) and wrong for anything real.
        self._lock = lock

    def turn(self, board: BoardSnapshot) -> TurnResult:
        """Claim at most one task in this lane and run its job.

        Takes the snapshot rather than reading one: `BoardRunner` has already
        read it, and re-reading per lane is the cost this design exists to
        avoid.
        """
        decision = selection.choose(board, self.lane_tag, now=self._now(),
                                    settle=self.settle)
        if isinstance(decision, Idle):
            return TurnResult(False, decision.reason)
        assert isinstance(decision, Pickup)

        job = self.jobs.get(decision.job)
        if job is None:
            # Claiming work we can't run would pin the repo behind a task
            # nothing will ever finish.
            return TurnResult(False, f"no handler for job {decision.job!r}",
                              task_id=decision.task.id, job=decision.job,
                              repo=decision.repo)

        # Take the checkout BEFORE claiming. The claim serialises a task; this
        # serialises the directory the job will `reset --hard`, and the two are
        # not the same guarantee. Ordered this way round, losing the race costs
        # nothing: we hold no claim, so no task is parked waiting out a lease.
        # Claim first and the same contention would strand one.
        #
        # This ordering is why routing is a separate, checkout-free job: an
        # Inbox task's repo is not known until an agent has read it, so there
        # would be nothing to lock here.
        lock = self._lock(decision.repo) if self._lock else nullcontext(True)
        with lock as got_checkout:
            if not got_checkout:
                return TurnResult(
                    False,
                    f"checkout for {decision.repo} is held by another process",
                    task_id=decision.task.id, job=decision.job,
                    repo=decision.repo)

            try:
                token = self.client.claim(
                    self.board_handle, decision.task.id,
                    lane=decision.lane, lease_seconds=CLAIM_LEASE_SECONDS)
            except ClaimHeld as e:
                # Someone claimed it between our read and our write. Normal.
                return TurnResult(
                    False, f"raced: held by {e.holder or 'another worker'}",
                    task_id=decision.task.id, repo=decision.repo)

            return run_claimed(self, decision, board, token, job)


def run_claimed(runner, pickup: Pickup, board: BoardSnapshot, token: str,
                job: Job) -> TurnResult:
    """Run one job under a held claim, and release it however that goes.

    Shared by `LaneRunner` and `BoardRunner`'s routing pass — the claim
    lifecycle is identical and the failure paths are the subtle part, so there
    is one copy of them.
    """
    # Seed the sink with whatever this task already accumulated, so a second
    # planning pass adds to the first rather than replacing it — the board's
    # metadata merge is shallow and would otherwise drop it.
    prior = (pickup.task.metadata or {}).get(METRICS_KEY) or {}
    sink = BoardSink(runner.client, runner.board_handle, pickup.task.id, token,
                     # "" not None: the empty string is a real lane value
                     # meaning "untagged", which is what an Inbox task being
                     # routed carries, and it guards the release against a
                     # human tagging it first. None would send no guard at all.
                     lane=pickup.lane or "",
                     metrics=prior,
                     notes_at_claim=pickup.task.notes)
    lane_override = None
    try:
        result = job(pickup, board, sink)
        status, notes, outcome = result[0], result[1], result[2]
        # A routing job names the repo lane it decided on; everything else
        # leaves the card where it is.
        lane_override = result[3] if len(result) > 3 else None
        complete = bool(result[4]) if len(result) > 4 else False
    except LeaseLost:
        # The lease is gone — expired, or a human cancelled us. We hold no
        # claim, so releasing would fail too. Write nothing.
        logger.info("lease lost on %s; aborting without writing",
                    pickup.task.id)
        return TurnResult(False, "lease lost (cancelled or expired)",
                          task_id=pickup.task.id, job=pickup.job,
                          repo=pickup.repo)
    except AgentUnavailable:
        # The pipeline is down, not the task. Stalling would blame a task that
        # is fine, hide the outage behind a green run, and require a human to
        # come and unblock it once the credential is replaced.
        #
        # So: give the claim back — a claim that outlives the turn idles the
        # whole repo until the lease expires — and leave the task exactly as
        # we found it. Under v3 that is easier than it was: the task never
        # moved, so handing back means asserting the lane it is already in
        # rather than reconstructing a pre-claim lane it was dragged out of.
        #
        # Then re-raise. Nothing below may swallow it: the run has to exit
        # non-zero so the workflow reports `failed` to /health/api/jobs. A
        # pipeline that cannot run its agent is not a successful sweep,
        # however many repos it read.
        logger.exception("agent unavailable during %s on %s; handing the "
                         "claim back and failing the run",
                         pickup.job, pickup.task.id)
        sink.abandon(lane=pickup.lane or None)
        raise
    except Exception as e:
        # Any other failure still has to hand the task back. Blocking it with
        # the reason is strictly better than a task pinned with no explanation.
        logger.exception("job %s failed on %s", pickup.job, pickup.task.id)
        status = _blocked(f"{pickup.job} failed")
        notes = _failure_notes(pickup, e)
        outcome = f"error:{type(e).__name__}"
        complete = False

    try:
        sink.finish(status, notes=notes, outcome=outcome, complete=complete,
                    lane=lane_override)
    except RELEASE_ABORTED as e:
        # All three mean "the task is no longer ours to describe", and none may
        # write. They differ in the one way that matters here: whether we are
        # still holding a claim that nothing will release.
        #
        # LEASE_LOST — the lease is already gone; there is no claim to hand
        # back and a release would fail too.
        #
        # LANE_CHANGED / NOTES_CHANGED — the board refused the write, but OUR
        # TOKEN IS STILL LIVE. Returning here is what pinned the `task` board
        # for 32 minutes on 2026-08-05: the orphaned claim outlived the turn,
        # and selection idles a repo while any claim on it is live, so four
        # consecutive sweeps did nothing. Give it back explicitly instead of
        # waiting out the lease. `abandon()` writes nothing — it only stops the
        # claim being ours.
        handed_back = (isinstance(e, RELEASE_ABORTED_CLAIM_HELD)
                       and sink.abandon(lane=pickup.lane or None))
        reason = (f"release aborted ({e.code}); wrote nothing"
                  + (", claim handed back" if handed_back else ""))
        return TurnResult(False, reason, task_id=pickup.task.id,
                          job=pickup.job, repo=pickup.repo)
    except TaskBoardError as e:
        # The work happened; only the handback failed. Say so loudly — the task
        # stays claimed until the lease expires.
        logger.error("release failed for %s; it will free itself when the "
                     "lease expires: %s", pickup.task.id, e)
        return TurnResult(False, f"release failed: {e}",
                          task_id=pickup.task.id, job=pickup.job,
                          repo=pickup.repo)

    return TurnResult(True, pickup.reason, task_id=pickup.task.id,
                      job=pickup.job, repo=pickup.repo or lane_override or "",
                      outcome=outcome, status=status.kind)


@dataclass
class BoardResult:
    """What one board did this tick, across every repo on it."""

    acted: bool
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return "; ".join(self.details) if self.details else "nothing to do"


class BoardRunner:
    """Drives one board: reconcile, route, then every repo lane."""

    def __init__(self, client: TaskBoardClient, board_handle: str, *,
                 lane_runner_for: Callable[[str], LaneRunner],
                 route_job: Optional[Job] = None,
                 settle: timedelta = selection.DEFAULT_SETTLE,
                 now: Optional[Callable[[], datetime]] = None,
                 pr_lookup: Optional[reconcile.Lookup] = None) -> None:
        self.client = client
        self.board_handle = board_handle
        self._lane_runner_for = lane_runner_for
        self._route_job = route_job
        self.settle = settle
        self._now = now or (lambda: datetime.now(timezone.utc))
        #: Resolves a pull request's real state, so a task waiting on one can
        #: be corrected against what the human actually did with it. None
        #: disables reconciliation — right for unit tests, wrong for anything
        #: real, so `build_board_runner` always supplies it.
        self._pr_lookup = pr_lookup
        self.jobs: dict[str, Job] = {}

    def turn(self) -> BoardResult:
        board = self.client.get_board(self.board_handle)

        # Correct against reality BEFORE selecting, and re-read if anything
        # moved. A rejected PR puts its task back in play, so reconciling first
        # means the retry starts on THIS tick instead of waiting for the next
        # one. It also means selection never sees a status we already know to
        # be a lie.
        if self._pr_lookup is not None:
            corrected = reconcile.reconcile(board, self.client,
                                            self.board_handle,
                                            lookup=self._pr_lookup)
            if corrected:
                logger.info("reconciled %d task(s) on %s: %s",
                            len(corrected), self.board_handle,
                            "; ".join(corrected))
                board = self.client.get_board(self.board_handle)

        if not board.repo_lanes:
            return BoardResult(False, ["no repo lanes — not a v3 board"])

        result = BoardResult(False)

        note = selection.malformed_note(board)
        if note:
            result.details.append(note)

        # Route first: a task routed this tick becomes claimable by its repo's
        # lane runner in the same pass, which is the whole latency win of
        # routing being cheap.
        routed = self._route(board)
        if routed is not None:
            result.details.append(f"route: {routed}")
            if routed.acted:
                result.acted = True
                board = self.client.get_board(self.board_handle)

        for lane in board.repo_lanes:
            try:
                turn = self._lane_runner_for(lane.tag).turn(board)
            except AgentUnavailable:
                # The one failure that is NOT per-repo. Every remaining lane
                # would fail identically, so carrying on would turn one outage
                # into a row of blocked tasks across every repo.
                logger.error("agent unavailable — abandoning this board; the "
                             "remaining lanes would fail the same way")
                raise
            except TaskBoardError as e:
                result.details.append(f"{lane.tag}: board error {e}")
                continue
            except Exception as e:
                # A crashing job already routes the task to `blocked` inside
                # the lane runner; anything reaching here is the runner itself
                # failing, and the loop still has to survive it.
                logger.exception("turn failed on lane %s", lane.tag)
                result.details.append(f"{lane.tag}: {type(e).__name__}: {e}")
                continue
            if turn.acted:
                result.acted = True
            result.details.append(f"{lane.tag}: {turn}")

        return result

    def _route(self, board: BoardSnapshot) -> Optional[TurnResult]:
        """Claim one Inbox task and file it under a repo. None if unwired."""
        if self._route_job is None:
            return None
        decision = selection.choose_unrouted(board, now=self._now(),
                                             settle=self.settle)
        if isinstance(decision, Idle):
            return TurnResult(False, decision.reason)
        assert isinstance(decision, Pickup)

        # No checkout lock: routing reads the task text and the board's lane
        # set, and touches no working directory. That is the property that
        # lets it claim safely without one.
        try:
            token = self.client.claim(self.board_handle, decision.task.id,
                                      lease_seconds=ROUTE_LEASE_SECONDS)
        except ClaimHeld as e:
            return TurnResult(False,
                              f"raced: held by {e.holder or 'another worker'}",
                              task_id=decision.task.id)
        return run_claimed(self, decision, board, token, self._route_job)


def _failure_notes(pickup: Pickup, exc: Exception) -> str:
    """A note a human can act on from a phone.

    The traceback is trimmed hard on purpose: `notes` is read on a small
    screen, and the full trace belongs in the evidence store.
    """
    tb = traceback.format_exception_only(type(exc), exc)[-1].strip()
    doc = plan_notes.PlanDoc(
        understanding=f"The {pickup.job} step failed and handed this back.",
        questions=[f"{tb}"],
        pass_number=1,
    )
    return plan_notes.render(doc)
