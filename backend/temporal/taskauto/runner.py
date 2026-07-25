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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from services.task_board import (
    RELEASE_ABORTED,
    BoardSnapshot,
    ClaimHeld,
    LeaseLost,
    TaskBoardClient,
    TaskBoardError,
)

from . import plan_notes, selection
from .progress import BoardSink
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

    def __str__(self) -> str:
        if not self.acted:
            return f"idle: {self.reason}"
        return (f"{self.job} on {self.task_id} → {self.released_to}"
                f" ({self.reason})")


#: A job takes (pickup, board, sink) and returns (destination_lane, notes,
#: outcome). Raising is allowed — the runner routes the failure to `stalled`
#: rather than leaving the task claimed.
Job = Callable[..., tuple]


class Runner:
    def __init__(self, client: TaskBoardClient, board_handle: str, *,
                 jobs: Optional[dict[str, Job]] = None,
                 settle: timedelta = selection.DEFAULT_SETTLE,
                 now: Optional[Callable[[], datetime]] = None) -> None:
        self.client = client
        self.board_handle = board_handle
        self.jobs = jobs or {}
        self.settle = settle
        self._now = now or (lambda: datetime.now(timezone.utc))

    def turn(self) -> TurnResult:
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

        try:
            token = self.client.claim(
                self.board_handle, decision.task.id,
                lane=decision.lane, lease_seconds=CLAIM_LEASE_SECONDS)
        except ClaimHeld as e:
            # Someone claimed it between our read and our write. Normal.
            return TurnResult(False, f"raced: held by {e.holder or 'another worker'}",
                              task_id=decision.task.id)

        return self._run_claimed(decision, board, token, job)

    def _run_claimed(self, pickup: Pickup, board: BoardSnapshot,
                     token: str, job: Job) -> TurnResult:
        sink = BoardSink(self.client, self.board_handle, pickup.task.id, token)
        try:
            lane, notes, outcome = job(pickup, board, sink)
        except LeaseLost:
            # The lease is gone — expired, or a human cancelled us. We hold
            # no claim, so releasing would fail too. Write nothing.
            logger.info("lease lost on %s; aborting without writing",
                        pickup.task.id)
            return TurnResult(False, "lease lost (cancelled or expired)",
                              task_id=pickup.task.id, job=pickup.job)
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
            # LEASE_LOST: someone else owns the task now. LANE_CHANGED: a
            # human retagged it mid-claim and the release wrote nothing.
            # Different causes, identical consequence — the task is no longer
            # ours and anything further would trample whoever it belongs to.
            return TurnResult(False, f"release aborted ({e.code}); wrote nothing",
                              task_id=pickup.task.id, job=pickup.job)
        except TaskBoardError as e:
            # The work happened; only the handback failed. Say so loudly —
            # the task is stuck in an agent lane until the lease expires.
            logger.error("release failed for %s; it will free itself when the "
                         "lease expires: %s", pickup.task.id, e)
            return TurnResult(False, f"release failed: {e}",
                              task_id=pickup.task.id, job=pickup.job)

        return TurnResult(True, pickup.reason, task_id=pickup.task.id,
                          job=pickup.job, released_to=lane)


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
