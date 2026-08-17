"""The scheduler — what turns the pipeline from a tool into automation.

**Why this polls rather than waiting to be pushed.**

Webhooks are the obvious answer and they are not sufficient here, for a
reason that is specific to this pipeline rather than general taste:

1. **Two of our transitions have no board event to push.** A crashed run is
   recovered when its *lease expires* — a timer on hadoku-task's side that
   fires no notification. And an Inbox task becomes eligible once it has sat
   unedited for the settle delay, which is the *absence* of events, not an
   event. Neither can be pushed. A timer is therefore required no matter
   what, and once a timer exists, push only buys latency.

2. **We restart on every deploy, including deploys we cause.** A landing
   triggers a deploy of both pm2 services; a webhook delivered in that window
   is simply lost. The act of working creates the gaps. A missed push means a
   task sits forever with nobody noticing, and silence is the worst failure
   mode this system can have.

3. **The polling is genuinely cheap, now that `/changes` exists.** One GET
   returns deltas across *every* board with a cursor. At the intervals below
   that is on the order of a thousand small requests a day against a 600/min
   budget. Since we serialise to one task per repo, latency-to-start barely
   matters anyway: the work itself takes minutes.

So: **push for latency, poll for correctness.** The poll is the part that
cannot be skipped, so it is what got built first.

**The push half now exists, and it is not a webhook to this process.**
hadoku-task fires a GitHub `repository_dispatch` when a human writes a task
into a `user` lane, which starts the workflow in seconds. Routing the wake
through GitHub rather than an inbound endpoint here is deliberate: an endpoint
that can be poked from outside to make a service that merges to `main` start
working is a security posture change, and this way tenhands still only makes
outbound calls.

It was needed because the cron turned out not to be the thing it claimed.
GitHub deprioritises `schedule`: measured over 63.5h, 78 of 254 runs were
delivered, median gap 46 min, p90 75. Tightening the cron cannot fix that —
the throttle is on delivery, not on the schedule expression.

The push does not change anything below. It only shortens the wait for the
first look, and the reasons in (1) and (2) are why the timer stays.

An untagged Inbox write DOES dispatch, as of 2026-07-31. It used to be
excluded to protect the settle delay, which left a fresh capture — the most
ordinary thing anyone does here — as the one action with no fast path, waiting
on a cron whose *shortest* observed gap was 24 minutes. The settle delay is
still honoured; it is just honoured by waiting a minute inside the woken run
(`taskauto.yml`, "Let a fresh capture settle") rather than by declining to
start one. Policy stayed here, where it belongs, and only the timing moved.

The design that follows from this is two-speed. The change feed is a cheap
hint that something moved; a slower full sweep runs regardless, because
that is the only thing that catches recovery and settle.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from services.task_board import (
    RateLimited,
    TaskBoardClient,
    TaskBoardError,
    TaskBoardUnavailable,
)

from .agent import AgentUnavailable

logger = logging.getLogger(__name__)

#: Gap between polls when something is happening.
ACTIVE_INTERVAL_S = 20
#: Gap when the boards have been quiet. Most of the day is this.
IDLE_INTERVAL_S = 120
#: Ceiling when the board is unreachable and we are backing off.
MAX_BACKOFF_S = 600
#: However quiet things are, sweep every board this often anyway. This is the
#: ONLY thing that recovers a crashed run or picks up a settled Inbox task,
#: because neither produces a change-feed entry at the moment it becomes
#: actionable.
FULL_SWEEP_S = 300


@dataclass
class TickResult:
    acted: bool
    detail: str
    boards_swept: int = 0

    def __str__(self) -> str:
        return f"{'acted' if self.acted else 'idle'}: {self.detail}"


@dataclass
class Scheduler:
    client: TaskBoardClient
    #: Board handles to drive. One repo each.
    boards: list[str]
    #: handle -> something with .turn() -> TurnResult
    runner_for: Callable[[str], object]

    active_interval_s: float = ACTIVE_INTERVAL_S
    idle_interval_s: float = IDLE_INTERVAL_S
    full_sweep_s: float = FULL_SWEEP_S
    max_backoff_s: float = MAX_BACKOFF_S

    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic

    cursor: Optional[str] = None
    #: None until we have actually swept. NOT 0.0: `now` is `time.monotonic`,
    #: whose reference point Python leaves undefined (boot, on Linux), so
    #: `now() - 0.0 >= full_sweep_s` was only *incidentally* true — it holds on
    #: a host with hours of uptime and is false on one rebooted in the last
    #: `full_sweep_s`. That made the first tick of a fresh one-shot process do
    #: nothing at all: no sweep, and a primed cursor reporting no changes. The
    #: guarantee run_taskauto.py rests on ("a fresh process sweeps every board
    #: on its first tick") has to be stated, not inherited from a clock.
    _last_sweep: Optional[float] = field(default=None, init=False)
    _backoff: float = field(default=0.0, init=False)
    _cursor_primed: bool = field(default=False, init=False)

    # ── one pass ──────────────────────────────────────────────────────────

    def tick(self) -> TickResult:
        """Poll once and run at most one turn per board that needs it."""
        due_for_sweep = (
            self._last_sweep is None
            or (self.now() - self._last_sweep) >= self.full_sweep_s)

        try:
            changed = self._changed_boards()
        except RateLimited as e:
            # Backing off is mandatory: three violations gets the key
            # blacklisted, which converts a slow poll into an outage.
            self._backoff = max(self._backoff, float(e.retry_after))
            return TickResult(False, f"rate limited, backing off {self._backoff:.0f}s")
        except TaskBoardUnavailable as e:
            self._bump_backoff()
            return TickResult(False, f"board unreachable ({e}); backoff "
                                     f"{self._backoff:.0f}s")
        except TaskBoardError as e:
            self._bump_backoff()
            return TickResult(False, f"change feed failed: {e}")

        self._backoff = 0.0

        targets = list(self.boards) if due_for_sweep else [
            b for b in self.boards if b in changed]
        if due_for_sweep:
            self._last_sweep = self.now()

        if not targets:
            return TickResult(False, "no changes")

        acted, details = False, []
        for handle in targets:
            try:
                result = self.runner_for(handle).turn()
            except AgentUnavailable:
                # The one failure that is NOT per-board. Every remaining board
                # would fail identically, so carrying on would turn one outage
                # into a row of stalled tasks across every repo — and the
                # `except Exception` below would report each as a detail
                # string on a tick that still counts as a success.
                logger.error("agent unavailable — abandoning this tick; the "
                             "remaining %d board(s) would fail the same way",
                             len(targets) - targets.index(handle) - 1)
                raise
            except TaskBoardError as e:
                # One board being unhappy must not stop the others.
                details.append(f"{handle[:8]}: board error {e}")
                continue
            except Exception as e:
                # A crashing job already routes the task to `stalled` inside
                # the runner; anything reaching here is the runner itself
                # failing, and the loop still has to survive it.
                logger.exception("turn failed on %s", handle)
                details.append(f"{handle[:8]}: {type(e).__name__}: {e}")
                continue
            if getattr(result, "acted", False):
                acted = True
            details.append(f"{handle[:8]}: {result}")

        return TickResult(acted, "; ".join(details), boards_swept=len(targets))

    def _changed_boards(self) -> set[str]:
        """Board ids touched since our cursor, advancing it only on success.

        The first call primes the cursor and reports nothing changed. Without
        that, a fresh scheduler would treat the entire backlog as new and
        immediately claim work a human may have finished with days ago — the
        periodic sweep picks up anything genuinely actionable anyway.
        """
        body = self.client.changes(since=self.cursor, limit=200)
        changes = body.get("changes") or []
        nxt = body.get("cursor")

        if not self._cursor_primed:
            self._cursor_primed = True
            self.cursor = nxt or self.cursor
            return set()

        # Advance only after a successful read, so a failed poll re-reads the
        # same window rather than skipping past changes we never saw.
        if nxt:
            self.cursor = nxt
        return {c.get("boardId") for c in changes if c.get("boardId")}

    # ── the loop ──────────────────────────────────────────────────────────

    def interval_after(self, result: TickResult) -> float:
        """How long to wait next.

        Jittered so that several schedulers, or a scheduler restarted by a
        deploy, don't fall into lockstep and hammer the same second.
        """
        if self._backoff:
            base = min(self._backoff, self.max_backoff_s)
        elif result.acted:
            base = self.active_interval_s
        else:
            base = self.idle_interval_s
        return base * random.uniform(0.85, 1.15)

    def run(self, *, max_ticks: Optional[int] = None,
            on_tick: Optional[Callable[[TickResult], None]] = None) -> int:
        """Poll forever. `max_ticks` bounds it for tests and one-shot runs."""
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            result = self.tick()
            ticks += 1
            if on_tick:
                on_tick(result)
            logger.info("tick %d: %s", ticks, result)
            if max_ticks is not None and ticks >= max_ticks:
                break
            self.sleep(self.interval_after(result))
        return ticks

    def _bump_backoff(self) -> None:
        self._backoff = min(
            self.max_backoff_s,
            self._backoff * 2 if self._backoff else self.idle_interval_s)
