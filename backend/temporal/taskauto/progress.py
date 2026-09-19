"""`ProgressSink` — publishing pipeline state onto the board.

The board is a **projection**, not the source of truth. Temporal and the
evidence store remain authoritative for where a task is; this mirrors that
somewhere a human can watch and steer from a phone.

That distinction decides the error policy: **a failure to publish must never
fail the work.** If the board is unreachable mid-task, the right outcome is
that the run completes and the board catches up on the next transition — not
that we abandon a half-finished merge because a projection write 500'd.

The one exception is `LEASE_LOST`, which is not a publishing failure at all.
It means the claim is gone — the lease expired, or a human cancelled us via
`POST /agent/cancel`. That has to reach the caller so the run aborts without
writing anything, so it propagates while everything else is swallowed.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

from services.task_board import (
    LeaseLost,
    TaskBoardClient,
    TaskBoardError,
    TaskStatus,
    notes_hash,
)

logger = logging.getLogger(__name__)

#: Where per-task timings live on the board. `notes` is rewritten every pass,
#: so it cannot hold a running total; `metadata` merges and survives.
METRICS_KEY = "taskauto"

#: Status kinds that end the pipeline's involvement. Reaching one is what
#: makes an end-to-end total meaningful.
#:
#: v2 listed lanes here (`landed`, `stalled`). The lanes are repos now and a
#: task never leaves the one it is in, so "finished" is a property of the
#: status rather than of where the card sits. `waiting` is deliberately absent
#: — a plan awaiting sign-off is mid-conversation, and stamping a total on it
#: each pass would make "how long did this take" mean "how long until someone
#: last looked at it".
TERMINAL_KINDS = ("blocked", "done")


class ProgressSink(Protocol):
    """Where a pipeline reports what it's doing."""

    def status(self, status: TaskStatus) -> None: ...
    def heartbeat(self) -> None: ...
    def record(self, **fields: float) -> None: ...
    def finish(self, status: TaskStatus, *, notes: Optional[str] = None,
               outcome: str = "", complete: bool = False) -> None: ...


class NullSink:
    """Reports nowhere.

    crimson-kitty's sink. Also what tests use, and what a taskauto run uses
    before it holds a claim.
    """

    def status(self, status: TaskStatus) -> None:
        pass

    def heartbeat(self) -> None:
        pass

    def record(self, **fields: float) -> None:
        pass

    def finish(self, status: TaskStatus, *, notes=None, outcome="",
               complete=False) -> None:
        pass


class BoardSink:
    """Publishes onto a hadoku-task board while holding its claim."""

    def __init__(self, client: TaskBoardClient, board: str, task_id: str,
                 token: str, *, lane: Optional[str] = None,
                 metrics: Optional[dict] = None,
                 notes_at_claim: Optional[str] = None) -> None:
        self.client = client
        self.board = board
        self.task_id = task_id
        self.token = token
        self.released = False
        #: Timings so far, read off the task at claim time and added to as this
        #: turn runs. `notes` is rewritten every pass and cannot carry a running
        #: total; `metadata` survives, which is why the numbers live there.
        self._metrics: dict = dict(metrics or {})
        #: Where we believe the board currently has this task. Under v3 that
        #: is the repo lane it was claimed in and never leaves; a routing job
        #: starts with None, because deciding this IS its job.
        #: Sent as `ifCurrentLane` on release — see `finish`.
        self._current_lane = lane
        #: Digest of the notes as they stood when we claimed. Sent as
        #: `ifNotesHash` on release, so the guard compares against what we
        #: PLANNED AGAINST rather than what we are about to write.
        self._notes_at_claim = notes_hash(notes_at_claim)

    def _swallow(self, what: str, exc: Exception) -> None:
        logger.warning("board projection failed (%s): %s: %s",
                       what, type(exc).__name__, exc)

    def status(self, status: TaskStatus) -> None:
        """Publish the chip mid-job. Best-effort.

        Rides on `set-lane` with the task's CURRENT lane, which is a lane move
        that moves nothing: under v3 the lane is the repo and the task stays
        in it from claim to release. The endpoint is what accepts a status
        without releasing, and releasing to report progress would drop the
        lease in between — the exact window another runner would take the task
        in.

        Swallowing a failure is right here for the same reason as everywhere
        else in this class: the chip is a projection, and a run must not die
        because a projection write 500'd.
        """
        if not self._current_lane:
            # Nothing to address the write at. Only reachable for a routing
            # job, which holds a claim on an Inbox task that is in no lane yet
            # — and which has nothing worth reporting mid-flight anyway.
            return
        try:
            self.client.set_lane(self.board, self.task_id, self.token,
                                 self._current_lane, status=status)
        except LeaseLost:
            raise
        except TaskBoardError as e:
            self._swallow(f"status {status.kind}", e)

    def record(self, **fields: float) -> None:
        """Add to this task's running totals. Numbers accumulate, so a task
        planned three times reports the sum of three planning passes rather
        than only the last one."""
        for k, v in fields.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                self._metrics[k] = round(self._metrics.get(k, 0) + v, 3)
            else:
                self._metrics[k] = v

    def heartbeat(self) -> None:
        """Hold the lease, and learn if a human cancelled us.

        This is the only channel through which a cancel reaches a running
        job, so it must be called during long waits rather than only at
        transitions — otherwise "stop" takes effect at the end of a
        30-minute agent run, which is not stopping.
        """
        try:
            self.client.heartbeat(self.board, self.task_id, self.token)
        except LeaseLost:
            raise
        except TaskBoardError as e:
            self._swallow("heartbeat", e)

    def finish(self, status: TaskStatus, *, notes: Optional[str] = None,
               outcome: str = "", complete: bool = False,
               lane: Optional[str] = None) -> None:
        """Release the claim, publishing the final status. Idempotent here.

        `lane` is the ONE case where the pipeline moves a card: a routing job
        naming the repo it decided on. Everything else leaves it out and the
        task stays where it is, which is what `_current_lane` defaults to.

        Unlike the others this is allowed to raise: releasing is how the task
        stops being ours, and a silent failure would leave it claimed until the
        lease expired — invisible, and blocking its whole repo under
        one-task-in-flight-per-repo.

        **Two guards, covering the two ways a human can act mid-claim.**

        `ifCurrentLane` catches a retag. Under v3 that means *moving the task
        to another repo*, which is a rarer act than v2's drag-out-of-a-lane but
        a far more consequential one: releasing over it would drag the task
        back to a repo the human just decided it did not belong in.

        `ifNotesHash` catches an edit to the plan, and it is new because v3
        needed it to exist. In v2 the notes were safe by construction — we only
        wrote them while the task sat in an `agent` lane a human could not
        write. With every lane `editableBy: user` that guarantee is gone, and
        without this guard a twenty-minute job ends by overwriting whatever
        they typed while it ran. There is no recovery from that; the previous
        text was never stored anywhere.

        `_notes_at_claim` is the digest we planned against, so the comparison
        is against what we READ rather than what we are about to write. Both
        guards refuse by writing nothing, and both leave our token live — which
        is why the runner has to hand the claim back rather than return.

        The trade is deliberate and unchanged: a lost response to a successful
        `set-lane` makes our belief stale and aborts a release nobody
        contested. That costs a lease, which recovery then resumes —
        recoverable, unlike an overwrite.
        """
        if self.released:
            return
        metadata = None
        if self._metrics:
            metrics = dict(self._metrics)
            # Only a terminal lane gets a total: a task still mid-conversation
            # has no end-to-end number yet, and stamping one every pass would
            # make "how long did this take" mean "how long until it was last
            # touched".
            if status.kind in TERMINAL_KINDS or complete:
                metrics["agent_s"] = round(
                    sum(v for k, v in metrics.items()
                        if k.endswith("_s") and isinstance(v, (int, float))), 3)
                metrics["finished_kind"] = status.kind
            metadata = {METRICS_KEY: metrics}
        self.client.release(self.board, self.task_id, self.token,
                            lane=lane or self._current_lane, notes=notes,
                            outcome=outcome or None, status=status,
                            complete=complete, metadata=metadata,
                            if_current_lane=self._current_lane,
                            if_notes_hash=self._notes_at_claim)
        self.released = True

    def abandon(self, *, lane: Optional[str] = None) -> bool:
        """Give the claim back, writing nothing but `lane`. Never raises.

        **`lane=None` does not mean "leave it where it is".** The board reads
        an absent `lane` on release as *clear the tag*, which drops the task
        into the Inbox — measured against the live board on 2026-08-08, not
        inferred. That is correct for the LANE_CHANGED case this was written
        for, where the whole point is to assert nothing, but it is silently
        destructive anywhere else: an `approved` task handed back this way
        loses the approval and gets re-planned instead of implemented, and
        nothing anywhere says so.

        So callers who know where the task came from pass it. The claim moved
        the task into an agent lane, so "where it came from" is
        `pickup.task.lane(board.lanes)` — the pre-claim snapshot — and NOT
        `pickup.lane`, which is the agent lane we moved it to.

        The counterpart to `finish`'s `ifCurrentLane` guard. When that guard
        trips the release is refused and *the claim stays ours* — which is the
        dangerous half, because `selection.choose` serialises one task in
        flight per board off the server's `claimed` flag. A claim nobody will
        ever release blocks every task on that board until its lease runs out,
        including tasks the agent has never touched.

        That is not hypothetical. On 2026-08-05 task `MSGNHPC1B11K` was claimed
        out of the inbox, its lane write did not stick, the release came back
        `409 LANE_CHANGED`, and the runner returned holding a live token. The
        `task` board reported `is in flight (lane=None)` to every sweep for the
        next 32 minutes — four runs did nothing — until the lease expired at
        22:53:06. The very next sweep planned the task in seconds. Nothing was
        wrong except that the claim outlived the turn.

        Still no notes, no metadata, no `ifCurrentLane`, in either case. Each
        is a write, and this runs when our idea of the task is either stale or
        irrelevant. `ifCurrentLane` stays off deliberately even when restoring
        a lane: the guard trips by refusing the release, and a refused release
        is the pinned claim above — worth more than the few seconds of race it
        would close.

        Returns whether the claim is actually gone, because the caller reports
        two different things. Never raises: this runs on an error path, and an
        exception here would replace a precise diagnosis with a worse one.
        """
        if self.released:
            return True
        try:
            self.client.release(self.board, self.task_id, self.token, lane=lane)
        except Exception as e:
            # Worth a warning rather than a swallow: failing here means the
            # board stays blocked for the rest of the lease, which is the
            # exact outage this method exists to prevent.
            logger.warning("could not hand back the claim on %s; the board "
                           "stays blocked until the lease expires: %s: %s",
                           self.task_id, type(e).__name__, e)
            return False
        self.released = True
        return True
