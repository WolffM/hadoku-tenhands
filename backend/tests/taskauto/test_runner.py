"""Tests for temporal/taskauto/runner.py.

The claim is the boundary of responsibility, so most of these are about what
happens *after* it: every path out must release the task. A task left pinned
in an agent lane is invisible to the human and blocks the whole board, since
we serialise to one task per repo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.task_board import (
    BoardSnapshot,
    BoardTask,
    ClaimHeld,
    Lane,
    LeaseLost,
    TaskBoardUnavailable,
)
from temporal.taskauto import selection
from temporal.taskauto.runner import Runner, TurnResult

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)

LANES = [
    Lane("planning", "Planning", 0, "agent"),
    Lane("plan-review", "Plan Review", 0, "user"),
    Lane("replan", "Re-plan", 1, "user"),
    Lane("approved", "Approved", 2, "user"),
    Lane("working", "Working", 3, "agent"),
    Lane("landing", "Landing", 4, "agent"),
    Lane("landed", "Landed", 5, "user"),
    Lane("stalled", "Stalled", 6, "user"),
]


def task(tid="t1", tag="approved", *, claimed=False, ago=60):
    ts = (NOW - timedelta(minutes=ago)).isoformat().replace("+00:00", "Z")
    return BoardTask(id=tid, title="make coffee theme default", notes="",
                     tag=tag, metadata={}, claimed=claimed, state="Active",
                     created_at=ts, updated_at=ts)


def snapshot(*tasks):
    return BoardSnapshot(id="b", name="tenhands", handle="H",
                         repo="WolffM/tenhands", mode="automation",
                         lanes=LANES, tasks=list(tasks), schema_id="autoland",
                         schema_version=1, access="contributor", version=1)


class FakeClient:
    def __init__(self, board, *, claim_raises=None):
        self.board = board
        self.claim_raises = claim_raises
        self.calls: list[tuple] = []
        self.token = "tok-1"

    def get_board(self, handle):
        self.calls.append(("get_board", handle))
        return self.board

    def claim(self, board, task_id, *, lane=None, lease_seconds=None,
              agent_id=None):
        self.calls.append(("claim", task_id, lane, lease_seconds))
        if self.claim_raises:
            raise self.claim_raises
        return self.token

    def set_lane(self, board, task_id, token, lane):
        self.calls.append(("set_lane", task_id, lane))
        return {}

    def heartbeat(self, board, task_id, token, *, lease_seconds=None):
        self.calls.append(("heartbeat", task_id))
        return {}

    def release(self, board, task_id, token, *, lane=None, notes=None,
                outcome=None, metadata=None, complete=False,
                if_current_lane=None):
        self.calls.append(("release", task_id, lane, outcome, complete))
        return {}

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def runner(client, jobs):
    return Runner(client, "H", jobs=jobs, now=lambda: NOW)


# ── no-ops ────────────────────────────────────────────────────────────────


def test_empty_board_does_nothing():
    c = FakeClient(snapshot())
    r = runner(c, {"implement": lambda *a: ("landed", None, "ok")}).turn()
    assert r.acted is False and r.reason == "nothing waiting"
    assert c.named("claim") == []


def test_no_handler_means_no_claim():
    """Claiming work we can't run would pin the board behind a task nothing
    will ever finish."""
    c = FakeClient(snapshot(task()))
    r = runner(c, {}).turn()
    assert r.acted is False and "no handler" in r.reason
    assert c.named("claim") == []


def test_losing_the_claim_race_is_not_an_error():
    """Two runners polling one board is the case the atomic claim exists
    for; the loser should shrug and move on."""
    c = FakeClient(snapshot(task()),
                   claim_raises=ClaimHeld("held", code="CLAIM_HELD",
                                          status=409,
                                          body={"holder": "agent-9"}))
    r = runner(c, {"implement": lambda *a: ("landed", None, "ok")}).turn()
    assert r.acted is False and "agent-9" in r.reason
    assert c.named("release") == []


# ── the happy path ────────────────────────────────────────────────────────


def test_claims_into_the_lane_selection_chose_and_releases():
    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": lambda *a: ("landed", "done", "merged")}).turn()
    assert r.acted is True
    assert ("claim", "t1", "working", 900) in c.calls
    assert ("release", "t1", "landed", "merged", False) in c.calls
    assert r.released_to == "landed"


def test_the_job_can_move_lanes_mid_run():
    def job(pickup, board, sink):
        sink.lane("landing")
        return "landed", None, "merged"

    c = FakeClient(snapshot(task()))
    runner(c, {"implement": job}).turn()
    assert ("set_lane", "t1", "landing") in c.calls


def test_plan_job_runs_for_an_inbox_task():
    c = FakeClient(snapshot(task(tag="", ago=90)))
    r = runner(c, {"plan": lambda *a: ("plan-review", "a plan", "asked")}).turn()
    assert r.acted and r.job == "plan"
    assert ("claim", "t1", "planning", 900) in c.calls
    assert ("release", "t1", "plan-review", "asked", False) in c.calls


# ── failure always hands the task back ────────────────────────────────────


def test_a_crashing_job_stalls_the_task_rather_than_pinning_it():
    """A task left claimed in an agent lane is invisible and blocks the
    board. Stalling with a reason is strictly better."""
    def boom(*a):
        raise RuntimeError("the agent exploded")

    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": boom}).turn()
    rel = c.named("release")[0]
    assert rel[2] == "stalled"
    assert rel[3] == "error:RuntimeError"
    assert r.acted and r.released_to == "stalled"


def test_the_stall_note_names_the_failure():
    def boom(*a):
        raise ValueError("could not find the theme file")

    captured = {}

    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            captured.update(kw)
            return super().release(board, task_id, token, **kw)

    r = runner(C(snapshot(task())), {"implement": boom}).turn()
    assert "could not find the theme file" in captured["notes"]
    assert r.released_to == "stalled"


def test_a_job_failing_on_an_unavailable_board_still_stalls():
    def boom(*a):
        raise TaskBoardUnavailable("network")

    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": boom}).turn()
    assert r.released_to == "stalled"


# ── lease loss is not a failure to route ──────────────────────────────────


def test_lease_lost_aborts_without_writing():
    """A human cancelled us, or the lease expired. We no longer hold the
    claim, so anything we wrote would be trampling whoever does."""
    def cancelled(*a):
        raise LeaseLost("gone", code="LEASE_LOST", status=409)

    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": cancelled}).turn()
    assert r.acted is False and "lease lost" in r.reason
    assert c.named("release") == [], "must not write after losing the lease"


def test_lease_lost_during_release_is_reported_not_swallowed():
    class C(FakeClient):
        def release(self, *a, **k):
            raise LeaseLost("gone", code="LEASE_LOST", status=409)

    r = runner(C(snapshot(task())), {"implement": lambda *a: ("landed", None, "")}).turn()
    assert r.acted is False and "lease lost" in r.reason


def test_release_failure_is_surfaced_loudly():
    """The work happened; only the handback failed. The task is stuck until
    the lease expires and the operator needs to know."""
    class C(FakeClient):
        def release(self, *a, **k):
            raise TaskBoardUnavailable("500")

    r = runner(C(snapshot(task())), {"implement": lambda *a: ("landed", None, "")}).turn()
    assert r.acted is False and "release failed" in r.reason


# ── serialisation holds through the runner ────────────────────────────────


def test_a_live_claim_elsewhere_blocks_this_turn():
    c = FakeClient(snapshot(task("busy", "working", claimed=True), task("t2")))
    r = runner(c, {"implement": lambda *a: ("landed", None, "")}).turn()
    assert r.acted is False and "in flight" in r.reason
    assert c.named("claim") == []
