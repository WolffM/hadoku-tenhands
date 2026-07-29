"""Tests for temporal/taskauto/scheduler.py.

The load-bearing property is that the loop **cannot get stuck**. A change
feed that misses something, a board that goes away, a runner that throws, a
rate limit — none of them may leave work sitting forever with nobody
noticing, because silence is this system's worst failure mode.
"""

from __future__ import annotations

import pytest

from services.task_board import (
    RateLimited,
    TaskBoardUnavailable,
    VersionConflict,
)
from temporal.taskauto.scheduler import Scheduler


class FakeClient:
    def __init__(self, *pages, raises=None):
        self.pages = list(pages)
        self.raises = raises
        self.calls = []

    def changes(self, since=None, limit=100):
        self.calls.append(since)
        if self.raises:
            raise self.raises
        return self.pages.pop(0) if self.pages else {"changes": [], "cursor": since}


class FakeRunner:
    def __init__(self, acted=True, raises=None):
        self.acted, self.raises = acted, raises
        self.turns = 0

    def turn(self):
        self.turns += 1
        if self.raises:
            raise self.raises

        class R:
            pass
        R.acted = self.acted
        R.__str__ = lambda s: "did a thing" if self.acted else "idle: nothing"
        return R()


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def now(self):
        return self.t


def page(*board_ids, cursor="c1"):
    return {"changes": [{"boardId": b} for b in board_ids], "cursor": cursor}


def sched(client, runners, **kw):
    clock = Clock()
    s = Scheduler(client=client, boards=list(runners),
                  runner_for=lambda h: runners[h],
                  sleep=clock.sleep, now=clock.now, **kw)
    s.clock = clock
    return s


def steady(client, runners, **kw):
    """A scheduler past its cold start.

    Every scheduler's first tick sweeps every board and primes the cursor — see
    `test_a_fresh_scheduler_sweeps_every_board_on_its_first_tick`. Tests about
    change *routing* want the steady state after that, so this consumes the
    first tick and zeroes the turn counters. Keeping the cold start out of them
    is what lets each one assert the small number it actually cares about.
    """
    s = sched(client, runners, **kw)
    s.tick()
    for r in runners.values():
        r.turns = 0
    return s


# ── the cold start ────────────────────────────────────────────────────────


def test_a_fresh_scheduler_sweeps_every_board_on_its_first_tick():
    """run_taskauto.py's one-shot shape rests entirely on this: a fresh process
    misses nothing by not having been running, because its first tick looks at
    everything. The sweep does not need to have been watching, only to look.

    Regression: `_last_sweep` defaulted to 0.0 and was compared against
    `time.monotonic()`, whose reference point Python leaves undefined (boot, on
    Linux). So this held on a host with hours of uptime and silently failed on
    one rebooted within `full_sweep_s` — the first tick swept nothing, the
    freshly primed cursor reported no changes, and a one-shot run exited having
    done nothing at all. Hence the clock pinned to zero below.
    """
    a, b = FakeRunner(), FakeRunner()
    s = sched(FakeClient(), {"a": a, "b": b}, full_sweep_s=1_000_000)
    s.clock.t = 0.0                     # a host that booted a moment ago
    result = s.tick()
    assert (a.turns, b.turns) == (1, 1)
    assert result.boards_swept == 2


def test_the_first_poll_primes_the_cursor_and_reports_no_changes():
    """A fresh scheduler must not treat the whole change-feed backlog as new.

    Asserted on `_changed_boards` rather than through `tick`, because the
    first-tick sweep above legitimately does act: priming protects against
    replaying the *feed*, and the sweep finds what is genuinely actionable by
    applying the lane and settle rules the raw feed knows nothing about.
    """
    s = sched(FakeClient(page("b1", cursor="c9")), {"b1": FakeRunner()})
    assert s._changed_boards() == set()
    assert s.cursor == "c9"


def test_changes_after_priming_do_trigger_a_turn():
    r = FakeRunner()
    s = steady(FakeClient(page(cursor="c0"), page("b1", cursor="c1")), {"b1": r})
    assert s.tick().acted is True
    assert r.turns == 1


# ── change routing ────────────────────────────────────────────────────────


def test_only_boards_that_changed_are_touched():
    a, b = FakeRunner(), FakeRunner()
    s = steady(FakeClient(page(cursor="c0"), page("a", cursor="c1")),
               {"a": a, "b": b})
    s.tick()
    assert (a.turns, b.turns) == (1, 0)


def test_changes_on_boards_we_do_not_drive_are_ignored():
    a = FakeRunner()
    s = steady(FakeClient(page(cursor="c0"), page("someone-elses", cursor="c1")),
               {"a": a})
    assert s.tick().acted is False
    assert a.turns == 0


# ── the full sweep is what catches recovery and settle ────────────────────


def test_a_full_sweep_runs_even_with_no_changes():
    """The only thing that recovers a crashed run or picks up a settled
    Inbox task — neither produces a change-feed entry at the moment it
    becomes actionable."""
    r = FakeRunner()
    s = steady(FakeClient(), {"b1": r}, full_sweep_s=100)
    s.clock.t = 500               # well past the sweep interval
    s.tick()
    assert r.turns == 1, "a quiet board must still be swept"


def test_between_sweeps_a_quiet_board_is_left_alone():
    r = FakeRunner()
    s = steady(FakeClient(), {"b1": r}, full_sweep_s=1000)
    s.clock.t = 10
    assert s.tick().acted is False
    assert r.turns == 0


def test_the_sweep_covers_every_board_not_just_changed_ones():
    a, b = FakeRunner(acted=False), FakeRunner(acted=False)
    s = steady(FakeClient(), {"a": a, "b": b}, full_sweep_s=100)
    s.clock.t = 500
    s.tick()
    assert (a.turns, b.turns) == (1, 1)


# ── the loop must survive everything ──────────────────────────────────────


def test_a_throwing_runner_does_not_stop_the_others():
    bad = FakeRunner(raises=RuntimeError("kaboom"))
    good = FakeRunner()
    s = sched(FakeClient(), {"bad": bad, "good": good}, full_sweep_s=0)
    result = s.tick()
    assert good.turns == 1
    assert "kaboom" in result.detail


def test_a_board_error_on_one_board_does_not_stop_the_others():
    bad = FakeRunner(raises=VersionConflict("stale", code="VERSION_CONFLICT"))
    good = FakeRunner()
    s = sched(FakeClient(), {"bad": bad, "good": good}, full_sweep_s=0)
    s.tick()
    assert good.turns == 1


def test_an_unreachable_board_backs_off_instead_of_spinning():
    s = sched(FakeClient(raises=TaskBoardUnavailable("down")), {"b": FakeRunner()})
    first = s.tick()
    assert first.acted is False and "unreachable" in first.detail
    assert s.interval_after(first) > s.active_interval_s


def test_backoff_grows_then_resets_on_recovery():
    client = FakeClient(raises=TaskBoardUnavailable("down"))
    s = sched(client, {"b": FakeRunner()}, idle_interval_s=10, max_backoff_s=100)
    s.tick(); first = s._backoff
    s.tick(); second = s._backoff
    assert second > first
    client.raises = None
    s.tick()
    assert s._backoff == 0.0, "a successful poll must clear the backoff"


def test_backoff_is_capped():
    s = sched(FakeClient(raises=TaskBoardUnavailable("down")), {"b": FakeRunner()},
              idle_interval_s=10, max_backoff_s=50)
    for _ in range(12):
        s.tick()
    assert s._backoff <= 50


def test_rate_limiting_honours_retry_after():
    """Three violations blacklists the key, turning a slow poll into an
    outage — so this backoff is mandatory, not advisory."""
    s = sched(FakeClient(raises=RateLimited(
        "slow down", code="RATE_LIMITED", body={"retryAfter": 240})),
        {"b": FakeRunner()})
    result = s.tick()
    assert "rate limited" in result.detail
    assert s.interval_after(result) >= 240 * 0.85


# ── cursor safety ─────────────────────────────────────────────────────────


def test_a_failed_poll_does_not_advance_the_cursor():
    """Otherwise the changes in that window are skipped and never seen."""
    client = FakeClient(page(cursor="c1"))
    s = sched(client, {"b": FakeRunner()})
    s.tick()
    assert s.cursor == "c1"
    client.raises = TaskBoardUnavailable("down")
    s.tick()
    assert s.cursor == "c1", "cursor must not move past unread changes"


def test_the_cursor_is_sent_on_the_next_poll():
    client = FakeClient(page(cursor="c1"), page("b", cursor="c2"))
    s = sched(client, {"b": FakeRunner()})
    s.tick(); s.tick()
    assert client.calls == [None, "c1"]


# ── pacing ────────────────────────────────────────────────────────────────


def test_it_polls_faster_while_work_is_flowing():
    s = sched(FakeClient(), {"b": FakeRunner()}, active_interval_s=5,
              idle_interval_s=100)

    class R:
        acted = True
    assert s.interval_after(R()) < 100


def test_it_slows_down_when_idle():
    s = sched(FakeClient(), {"b": FakeRunner()}, active_interval_s=5,
              idle_interval_s=100)

    class R:
        acted = False
    assert s.interval_after(R()) > 5


def test_intervals_are_jittered():
    """Several schedulers, or one restarted by a deploy, must not fall into
    lockstep and hammer the same second."""
    s = sched(FakeClient(), {"b": FakeRunner()}, idle_interval_s=100)

    class R:
        acted = False
    seen = {round(s.interval_after(R()), 4) for _ in range(20)}
    assert len(seen) > 1


def test_run_stops_after_max_ticks_and_does_not_sleep_at_the_end():
    r = FakeRunner()
    s = sched(FakeClient(), {"b": r}, full_sweep_s=0)
    assert s.run(max_ticks=3) == 3
    assert len(s.clock.slept) == 2, "no pointless sleep after the final tick"


def test_run_reports_every_tick():
    seen = []
    s = sched(FakeClient(), {"b": FakeRunner()}, full_sweep_s=0)
    s.run(max_ticks=2, on_tick=seen.append)
    assert len(seen) == 2
