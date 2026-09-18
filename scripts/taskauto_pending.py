#!/usr/bin/env python3
"""Is there anything a BACKSTOP SWEEP would advance? Exit 0 yes, 10 no.

The gate in front of `taskauto-cron.sh`. Everything about this file follows
from one fact: **work does not arrive here any more.** A human writing a task
fires a `repository_dispatch` from hadoku-task and a run is queued in seconds,
so the cron exists only for the handful of transitions that no human write can
push. Almost always there are none, and the sweep it would have fired is a
runner slot and a row in the fleet's job ledger spent proving a board is still
empty. That accounting is what killed the old 15-minute poll: ~25% of every job
the fleet reported, for boards that are empty nearly all of the time.

So ask first, and dispatch only on a yes. An idle board costs a handful of
board-API calls from the host and produces NO Actions run at all.

WHAT COUNTS AS PENDING — the whole design is in this list.

The question is never "does this board have tasks", it is "is there a
transition that only a sweep can make". Four cases say yes:

  - **`landed`** — the PR is open and will auto-merge on green. `reconcile.py`
    is the only thing that ever notices and archives it, and GitHub does not
    tell us. This is the case the gate exists for; it is also the one that
    makes an events-only pipeline leave the board asserting "waiting on you to
    merge" about work that shipped an hour ago.
  - **An agent lane with no live claim** (`planning`/`working`/`landing`) — a
    crashed run. Recovery fires on the ABSENCE of a heartbeat, which by
    construction nothing can push. See `selection._recoverable`.
  - **A claimable human lane** (`approved`, `replan`) **or the Inbox** — the
    write that put it there already dispatched, so normally a run has been and
    gone. It is still pending here because that dispatch can be LOST: the
    services restart mid-deploy and the wake-up lands nowhere. Then only a
    cron ever looks again.
  - **A live claim** counts too, and deliberately. A run is in flight; the
    concurrency group means our tick queues harmlessly behind it, and the
    alternative — treating "busy" as "nothing to do" — is how a board goes
    quiet at exactly the moment it is doing the most.

Two lanes say no, and only two: **`plan-review`** and **`stalled`**. They are
resting places where a human is expected to act, and that action is a board
write, which dispatches. A task can sit in either for a week; firing a sweep
every hour to re-read a lane whose whole meaning is "waiting for a person"
would rebuild the poll this replaces.

FAILING OPEN IS THE POINT, and is why the exit codes are what they are.

A gate that answers "no work" when it is actually broken does not make the
sweep rarer, it deletes it — silently, which is the failure mode the cron
script's whole header is about. So `10` ("nothing pending") is returned ONLY
by a successful read that found nothing. Every other outcome — an unreadable
board, a missing key, an HTTP error, a bug in here — exits `0` and lets the
sweep fire. A wasted 21-second run is the cheapest thing in this system.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.task_board import BoardSnapshot, TaskBoardClient  # noqa: E402
from temporal.taskauto import selection  # noqa: E402

logger = logging.getLogger("taskauto-pending")

#: Exit code for a CONFIRMED empty sweep — the only code that suppresses a
#: dispatch. Deliberately not 1: `1` is what a traceback, a missing import or
#: an unhandled exception exits with, and those must fire the sweep, not
#: silence it. A distinct number means "I looked, and there is nothing", which
#: is a different claim from "I failed".
EXIT_NOTHING_PENDING = 10

#: Lanes a sweep cannot advance. Both are resting places where a human is
#: expected to act (`selection.CLAIMABLE_HUMAN_LANES` names them as the two it
#: deliberately excludes), and a human acting on one is a board write, which
#: dispatches. Everything not in here is pending — stated that way round on
#: purpose, so a lane added to the schema tomorrow errs toward sweeping.
RESTING_LANES = frozenset({selection.LANE_PLAN_REVIEW, selection.LANE_STALLED})


def pending_tasks(board: BoardSnapshot) -> list[str]:
    """Task ids on `board` that a sweep would advance. Empty ⇒ nothing to do."""
    out = []
    for task in board.active_tasks:
        # A live claim means a run is working right now — pending by
        # definition, whatever lane the task is sitting in.
        if task.claimed or (task.lane(board.lanes) or "") not in RESTING_LANES:
            out.append(task.id)
    return out


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    client = TaskBoardClient()
    boards = client.automation_boards()
    if not boards:
        # No boards at all is ambiguous — an empty fleet and a key that lost
        # its shares look identical from here, and the second one is a real
        # outage. Sweep, and let the run say so.
        logger.warning("no automation boards visible — sweeping rather than "
                       "assuming this is normal")
        return 0

    # `automation_boards()` cannot answer this: it does not populate the
    # per-task `claimed` flag, so it would report every task as unclaimed.
    # Hydrate each board — that is the documented way to ask about claims.
    for board in boards:
        hydrated = client.get_board(board.handle)
        pending = pending_tasks(hydrated)
        if pending:
            logger.info("%s (%s): %d task(s) a sweep would advance: %s",
                        hydrated.handle, hydrated.repo, len(pending),
                        ", ".join(pending))
            return 0
        logger.info("%s (%s): nothing pending", hydrated.handle, hydrated.repo)

    logger.info("%d board(s) read, nothing pending — no sweep needed",
                len(boards))
    return EXIT_NOTHING_PENDING


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        # Fail OPEN, and say why. Suppressing the sweep is the only outcome
        # here that can lose work, so nothing but a clean read is allowed to
        # produce it — a board that will not answer is a reason to look
        # harder, not a reason to stop looking.
        logger.exception("could not determine whether work is pending — "
                         "sweeping anyway")
        code = 0
    # OUTSIDE the try. `sys.exit` raises SystemExit, and catching that here
    # would turn every clean "nothing pending" into a sweep — the gate would
    # look like it worked and never once suppress anything.
    sys.exit(code)
