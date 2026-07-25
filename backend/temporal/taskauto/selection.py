"""What the runner should pick up next from a board.

Pure policy over a `BoardSnapshot` — no I/O, no clock of its own, no board
writes. The runner reads a board, asks this what to do, and does it. Keeping
it pure is what makes the interesting decisions testable, because every one
of them is a judgement call rather than a mechanism:

  - only one task in flight per board, and why that has to include recovery
  - work already started outranks work not yet started
  - the Inbox waits for a task to stop being edited before anyone plans it

hadoku-task deliberately holds none of this ("there is no /agent/eligible" —
deciding what's ready means knowing which lane feeds which job, which is
pipeline knowledge). This module is that knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from services.task_board import BoardSnapshot, BoardTask


# ── Lanes, as this pipeline uses them ─────────────────────────────────────
# Must match docs/hadoku-task-automation/schemas/autoland-v1.json.

LANE_PLANNING = "planning"
LANE_PLAN_REVIEW = "plan-review"
LANE_REPLAN = "replan"
LANE_APPROVED = "approved"
LANE_WORKING = "working"
LANE_LANDING = "landing"
LANE_LANDED = "landed"
LANE_STALLED = "stalled"

#: Lanes we own. A task resting in one of these with no live claim is a
#: crashed run, never idle work — see `_recoverable`.
AGENT_LANES = (LANE_PLANNING, LANE_WORKING, LANE_LANDING)

#: How long a task must sit untouched in the Inbox before we plan it.
#: The Inbox is where half-formed thoughts land; planning at one the instant
#: it appears means planning against a sentence still being typed.
DEFAULT_SETTLE = timedelta(minutes=5)


# ── Jobs ──────────────────────────────────────────────────────────────────

JOB_PLAN = "plan"
JOB_IMPLEMENT = "implement"


@dataclass(frozen=True)
class Pickup:
    """A decision to claim one task and run one job."""

    task: BoardTask
    job: str
    #: Lane to move the task into as part of the claim.
    lane: str
    #: Why this one — carried into logs and the claim outcome so a board
    #: that did something surprising can be explained after the fact.
    reason: str
    #: True when resuming a crashed run rather than starting fresh.
    is_recovery: bool = False


@dataclass(frozen=True)
class Idle:
    """Nothing to do, and the reason — which is the useful part.

    "Idle" and "blocked behind an in-flight task" look identical from
    outside and mean very different things when a board looks stuck.
    """

    reason: str


Decision = object  # Pickup | Idle


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _recoverable(board: BoardSnapshot) -> list[BoardTask]:
    """Tasks stranded in one of our lanes with no live claim.

    This is the crashed-runner case: the worker died, the lease expired, and
    hadoku-task deliberately left the task exactly where it was rather than
    routing it anywhere. Nobody else will pick it up, so if we don't, it sits
    there forever.
    """
    return [
        t for t in board.active_tasks
        if not t.claimed and t.lane(board.lanes) in AGENT_LANES
    ]


def _settled(task: BoardTask, now: datetime, settle: timedelta) -> bool:
    touched = _parse_iso(task.last_touched)
    if touched is None:
        # No usable timestamp. Treat as settled rather than stranding the
        # task forever — the cost of planning slightly early is a question
        # on someone's phone; the cost of never planning is silence.
        return True
    return now - touched >= settle


def choose(
    board: BoardSnapshot,
    *,
    now: datetime,
    settle: timedelta = DEFAULT_SETTLE,
) -> Decision:
    """Pick the next task to claim on this board, or explain why not.

    Priority, highest first:

    1. **Recovery** — a task stranded in one of our lanes by a crashed run.
       It outranks everything because the work is already part-done and its
       evidence is on disk; starting something new first would leave it
       stale for longer and risk two half-finished tasks on one repo.
    2. **`approved`** — the human has signed off; this is the closest task
       to landing. Draining before filling keeps work-in-progress at one and
       gets value to production sooner.
    3. **`replan`** — the human answered our questions. Cheap and it
       unblocks a conversation they're waiting on.
    4. **Inbox** — brand new work, oldest first, once settled.

    `plan-review`, `landed` and `stalled` are terminal for us: they're
    resting places where a human is expected to act, and claiming from them
    would take the decision away from them.
    """
    if not board.is_automation:
        return Idle("board has no lanes — not an automation board")

    # One task in flight per board. Several tasks routinely touch the same
    # files, so concurrent diffs would collide; and after a merge the lock
    # has to be held through the prod watch window anyway, or a red health
    # signal can't be attributed to a specific change.
    #
    # This is checked against the server's per-task `claimed` flag rather
    # than lane membership, because a task can sit in an agent lane with an
    # expired claim — which is precisely the recovery case below, not
    # in-flight work.
    in_flight = [t for t in board.active_tasks if t.claimed]
    if in_flight:
        return Idle(
            f"{in_flight[0].id} is in flight "
            f"(lane={in_flight[0].lane(board.lanes)})"
        )

    recoverable = _recoverable(board)
    if recoverable:
        task = min(recoverable, key=lambda t: t.last_touched or "")
        lane = task.lane(board.lanes) or LANE_PLANNING
        return Pickup(
            task=task,
            job=JOB_PLAN if lane == LANE_PLANNING else JOB_IMPLEMENT,
            lane=lane,
            reason=f"resuming crashed run stranded in {lane}",
            is_recovery=True,
        )

    for lane_tag, job, target, why in (
        (LANE_APPROVED, JOB_IMPLEMENT, LANE_WORKING, "approved by human"),
        (LANE_REPLAN, JOB_PLAN, LANE_PLANNING, "human answered, re-planning"),
    ):
        candidates = board.tasks_in(lane_tag)
        if candidates:
            task = min(candidates, key=lambda t: t.last_touched or "")
            return Pickup(task=task, job=job, lane=target, reason=why)

    inbox = board.untagged()
    if inbox:
        ready = [t for t in inbox if _settled(t, now, settle)]
        if not ready:
            return Idle(
                f"{len(inbox)} inbox task(s) still settling "
                f"(< {int(settle.total_seconds())}s since last edit)"
            )
        task = min(ready, key=lambda t: t.last_touched or "")
        return Pickup(
            task=task, job=JOB_PLAN, lane=LANE_PLANNING,
            reason="new capture, settled",
        )

    # Nothing claimable. Before reporting a quiet board, account for tasks
    # that are stuck rather than absent: a task carrying two lane tags
    # resolves to no lane, isn't untagged either, and so is invisible to
    # every branch above. It would sit there indefinitely while the board
    # reported "nothing waiting", which is the least useful true statement
    # available. A write would fail LANE_INVALID anyway — a human has to
    # repair it — so say so.
    malformed = board.malformed()
    if malformed:
        ids = ", ".join(t.id for t in malformed[:3])
        return Idle(
            f"nothing claimable; {len(malformed)} task(s) carry an "
            f"unusable lane tag and need repair ({ids})"
        )

    return Idle("nothing waiting")
