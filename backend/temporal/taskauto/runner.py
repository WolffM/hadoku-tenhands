"""One turn of the pipeline: read a board, claim one task, run one job.

Deliberately *one turn* rather than a daemon loop. A single pass that either
does one thing or explains why it didn't is the unit that's easy to run by
hand, easy to schedule, and easy to reason about when something goes wrong.
Looping is the caller's business.

The claim is the boundary of responsibility. Before it, nothing is ours and
a crash costs nothing. After it, the task sits in an `agent` lane where only
we can write, so **every path out of here must release it** — otherwise it
stays pinned until the lease expires, invisible to the human and blocking
the whole board, since we serialise to one task per repo.
"""

from __future__ import annotations

import logging
import traceback
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, ContextManager, Optional

from services.task_board import (
    RELEASE_ABORTED,
    BoardSnapshot,
    ClaimHeld,
    LaneChanged,
    LeaseLost,
    TaskBoardClient,
    TaskBoardError,
)

from . import plan_notes, reconcile, selection
from .agent import AgentUnavailable
from .progress import METRICS_KEY, BoardSink
from .selection import Idle, Pickup

logger = logging.getLogger(__name__)

#: Requested at claim time. The server clamps to its own maximum (1 h); we
#: ask for less than we might need and heartbeat, so a crashed worker frees
#: the task sooner rather than pinning it for the maximum.
CLAIM_LEASE_SECONDS = 900


@dataclass
class TurnResult:
    """What one pass did. `acted` is False for every no-op reason."""

    acted: bool
    reason: str
    task_id: str = ""
    job: str = ""
    released_to: str = ""
    #: What the job CONCLUDED — `plan:no-op`, `plan:unverifiable`,
    #: `implement:no-plan`, `landed:<sha>`. Distinct from `reason`, which is
    #: why the task was picked up. Both are needed and they answer different
    #: questions: "why did this run" versus "what did it decide".
    outcome: str = ""

    def __str__(self) -> str:
        if not self.acted:
            return f"idle: {self.reason}"
        # The outcome goes first because it is the part you cannot reconstruct
        # from anywhere else. Two very different conclusions — "this looks
        # already done" and "I could not state an acceptance check" — both
        # release to plan-review, and without this they are indistinguishable
        # in the logs. Working that out cost a round of guessing.
        tail = f" [{self.outcome}]" if self.outcome else ""
        return (f"{self.job} on {self.task_id} → {self.released_to}"
                f"{tail} ({self.reason})")


#: A job takes (pickup, board, sink) and returns (destination_lane, notes,
#: outcome). Raising is allowed — the runner routes the failure to `stalled`
#: rather than leaving the task claimed.
Job = Callable[..., tuple]


class Runner:
    def __init__(self, client: TaskBoardClient, board_handle: str, *,
                 jobs: Optional[dict[str, Job]] = None,
                 settle: timedelta = selection.DEFAULT_SETTLE,
                 now: Optional[Callable[[], datetime]] = None,
                 lock: Optional[Callable[[str], ContextManager[bool]]] = None,
                 pr_lookup: Optional[reconcile.Lookup] = None,
                 ) -> None:
        self.client = client
        self.board_handle = board_handle
        self.jobs = jobs or {}
        self.settle = settle
        self._now = now or (lambda: datetime.now(timezone.utc))
        #: Resolves a pull request's real state, so `landed` tasks can be
        #: corrected against what the human actually did with the PR. None
        #: disables reconciliation — right for unit tests, wrong for anything
        #: real, so `build_runner` always supplies it.
        self._pr_lookup = pr_lookup
        #: Called with the board's `repo` to exclude other processes from its
        #: checkout for the length of a job — `CheckoutManager.lock` in
        #: production. None means no exclusion, which is right for a Runner
        #: whose jobs never touch disk (every unit test here) and wrong for
        #: anything real, so `build_runner` always supplies it.
        self._lock = lock

    def turn(self) -> TurnResult:
        board = self.client.get_board(self.board_handle)

        # Correct `landed` against reality BEFORE selecting, and re-read if
        # anything moved. A rejected PR sends its task to `replan`, which is a
        # claimable lane — so reconciling first means the retry starts on THIS
        # tick instead of waiting for the next one. It also means selection
        # never sees a task whose lane we already know to be a lie.
        if self._pr_lookup is not None:
            corrected = reconcile.reconcile(
                board, self.client, self.board_handle,
                lookup=self._pr_lookup)
            if corrected:
                logger.info("reconciled %d task(s) on %s: %s",
                            len(corrected), self.board_handle,
                            "; ".join(corrected))
                board = self.client.get_board(self.board_handle)

        decision = selection.choose(board, now=self._now(), settle=self.settle)

        if isinstance(decision, Idle):
            return TurnResult(False, decision.reason)
        assert isinstance(decision, Pickup)

        job = self.jobs.get(decision.job)
        if job is None:
            # Claiming work we can't run would pin the board behind a task
            # nothing will ever finish.
            return TurnResult(False, f"no handler for job {decision.job!r}",
                              task_id=decision.task.id, job=decision.job)

        # Take the checkout BEFORE claiming. The claim serialises a task; this
        # serialises the directory the job will `reset --hard`, and the two are
        # not the same guarantee (see CheckoutManager.lock). Ordered this way
        # round, losing the race costs nothing: we hold no claim, so there is
        # no task parked in an agent lane waiting for a lease to expire. Claim
        # first and the same contention would strand one.
        lock = self._lock(board.repo) if self._lock else nullcontext(True)
        with lock as got_checkout:
            if not got_checkout:
                return TurnResult(
                    False,
                    f"checkout for {board.repo} is held by another process",
                    task_id=decision.task.id, job=decision.job)

            try:
                token = self.client.claim(
                    self.board_handle, decision.task.id,
                    lane=decision.lane, lease_seconds=CLAIM_LEASE_SECONDS)
            except ClaimHeld as e:
                # Someone claimed it between our read and our write. Normal.
                return TurnResult(
                    False, f"raced: held by {e.holder or 'another worker'}",
                    task_id=decision.task.id)

            return self._run_claimed(decision, board, token, job)

    def _run_claimed(self, pickup: Pickup, board: BoardSnapshot,
                     token: str, job: Job) -> TurnResult:
        # `pickup.lane` is where the claim just put the task, so the sink
        # starts out knowing the board's state rather than guessing at it.
        # Seed the sink with whatever this task already accumulated, so a
        # second planning pass adds to the first rather than replacing it —
        # the board's metadata merge is shallow and would otherwise drop it.
        prior = (pickup.task.metadata or {}).get(METRICS_KEY) or {}
        sink = BoardSink(self.client, self.board_handle, pickup.task.id, token,
                         lane=pickup.lane, metrics=prior)
        try:
            lane, notes, outcome = job(pickup, board, sink)
        except LeaseLost:
            # The lease is gone — expired, or a human cancelled us. We hold
            # no claim, so releasing would fail too. Write nothing.
            logger.info("lease lost on %s; aborting without writing",
                        pickup.task.id)
            return TurnResult(False, "lease lost (cancelled or expired)",
                              task_id=pickup.task.id, job=pickup.job)
        except AgentUnavailable:
            # The pipeline is down, not the task. Stalling would blame a task
            # that is fine, hide the outage behind a green run, and require a
            # human to drag it back once the credential is replaced.
            #
            # So: give the claim back — a claim that outlives the turn idles
            # the whole board until the lease expires — and put the task back
            # in the lane we took it from, which is the pre-claim snapshot on
            # `pickup.task` rather than `pickup.lane`. Restoring it explicitly
            # is load-bearing: an absent lane on release CLEARS the tag, so
            # handing back the plain way would drop an `approved` task into
            # the Inbox and silently convert the human's approval into another
            # planning round.
            #
            # Then re-raise. Nothing below here may swallow it: the run has to
            # exit non-zero so the workflow reports `failed` to
            # /health/api/jobs. A pipeline that cannot run its agent is not a
            # successful sweep, however many boards it read.
            came_from = pickup.task.lane(board.lanes)
            logger.exception("agent unavailable during %s on %s; handing the "
                             "claim back to %s and failing the run",
                             pickup.job, pickup.task.id, came_from or "the inbox")
            sink.abandon(lane=came_from)
            raise
        except Exception as e:
            # Any other failure still has to hand the task back. Stalling
            # with the reason is strictly better than a task pinned in an
            # agent lane with no explanation.
            logger.exception("job %s failed on %s", pickup.job, pickup.task.id)
            lane = selection.LANE_STALLED
            notes = _failure_notes(pickup, e)
            outcome = f"error:{type(e).__name__}"

        try:
            sink.finish(lane, notes=notes, outcome=outcome)
        except RELEASE_ABORTED as e:
            # Both mean "the task is no longer ours to describe", and neither
            # may write. But they differ in the one way that matters here:
            # whether we are still holding a claim that nothing will release.
            #
            # LEASE_LOST — the lease is already gone, so there is no claim to
            # hand back and a release would fail too. Return.
            #
            # LANE_CHANGED — the board moved the task out from under us and
            # refused the write, but OUR TOKEN IS STILL LIVE. Returning here is
            # what pinned the `task` board for 32 minutes on 2026-08-05: the
            # orphaned claim outlived the turn, and `selection.choose` idles a
            # whole board while any claim on it is live, so four consecutive
            # sweeps did nothing to any task. Give it back explicitly instead
            # of waiting out the lease. `abandon()` writes nothing — it only
            # stops the claim being ours.
            handed_back = isinstance(e, LaneChanged) and sink.abandon()
            reason = (f"release aborted ({e.code}); wrote nothing"
                      + (", claim handed back" if handed_back else ""))
            return TurnResult(False, reason,
                              task_id=pickup.task.id, job=pickup.job)
        except TaskBoardError as e:
            # The work happened; only the handback failed. Say so loudly —
            # the task is stuck in an agent lane until the lease expires.
            logger.error("release failed for %s; it will free itself when the "
                         "lease expires: %s", pickup.task.id, e)
            return TurnResult(False, f"release failed: {e}",
                              task_id=pickup.task.id, job=pickup.job)

        return TurnResult(True, pickup.reason, task_id=pickup.task.id,
                          job=pickup.job, released_to=lane, outcome=outcome)


def _failure_notes(pickup: Pickup, exc: Exception) -> str:
    """A stall note a human can act on from a phone.

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
