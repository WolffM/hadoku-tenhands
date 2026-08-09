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
from temporal.taskauto.agent import AgentError, AgentUnavailable
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
        # Kept off the tuple so the exact-match assertions above stay readable.
        self.last_release = {"lane": lane, "if_current_lane": if_current_lane}
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


def test_the_log_line_says_what_the_job_decided_not_just_where_it_went():
    """Two very different conclusions release to the same lane.

    `plan:no-op` ("this looks already done") and `plan:unverifiable` ("I could
    not state an acceptance check") both land in plan-review with no plan, and
    a card that then gets approved bounces identically. Without the outcome in
    the log line the two are indistinguishable after the fact — the notes are
    rewritten each pass, so the evidence is gone. That cost a real debugging
    round.
    """
    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": lambda *a: ("plan-review", None, "implement:no-plan")}).turn()
    assert r.outcome == "implement:no-plan"
    assert "[implement:no-plan]" in str(r)
    assert "→ plan-review" in str(r)


def test_an_idle_turn_has_no_outcome_to_report():
    c = FakeClient(snapshot())
    r = runner(c, {"implement": lambda *a: ("landed", None, "ok")}).turn()
    assert str(r).startswith("idle:") and "[" not in str(r)


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


def test_release_asserts_the_lane_it_believes_the_task_is_in():
    """End to end: the `ifCurrentLane` guard has to reach the client.

    It's the only thing stopping the pipeline from overwriting a task a human
    dragged out mid-claim — hadoku-task allows that drag and doesn't check for
    a live claim (`board-contract.md` §2, `test_progress.py`).
    """
    def job(pickup, board, sink):
        sink.lane("landing")
        return "landed", None, "merged"

    c = FakeClient(snapshot(task()))
    runner(c, {"implement": job}).turn()
    assert c.last_release == {"lane": "landed", "if_current_lane": "landing"}


def test_release_guard_falls_back_to_the_claim_lane():
    """A job that never moves lanes still asserts where the claim put it."""
    c = FakeClient(snapshot(task()))
    runner(c, {"implement": lambda *a: ("landed", None, "merged")}).turn()
    assert c.last_release == {"lane": "landed", "if_current_lane": "working"}


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
    assert r.acted is False
    assert "LEASE_LOST" in r.reason and "wrote nothing" in r.reason


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


def test_a_lane_changed_release_aborts_like_a_lost_lease():
    """A human retagged the task mid-claim, so the release wrote nothing.
    Different cause from LEASE_LOST, identical consequence — the task is no
    longer ours to write to.

    This only happens in production because `finish` sends `ifCurrentLane`
    (`test_release_asserts_the_lane_it_believes_the_task_is_in`). Until it did,
    the board had no way to raise this and the release quietly moved the task
    back — the handler was right, the guard that reaches it was missing."""
    from services.task_board import LaneChanged

    class C(FakeClient):
        def release(self, *a, **k):
            raise LaneChanged("retagged", code="LANE_CHANGED", status=409)

    r = runner(C(snapshot(task())), {"implement": lambda *a: ("landed", None, "")}).turn()
    assert r.acted is False
    assert "LANE_CHANGED" in r.reason and "wrote nothing" in r.reason


def _guarded_release_client(attempts):
    """Production's actual shape: the board refuses the *guarded* release and
    accepts an unguarded one.

    The older test made every release raise, which cannot tell "we let go of
    the claim" apart from "we walked away still holding it" — the whole point
    of the fix below. `attempts` records EVERY call including refused ones;
    `FakeClient.calls` only sees the ones that get through.
    """
    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            attempts.append(kw)
            if kw.get("if_current_lane") is not None:
                from services.task_board import LaneChanged
                raise LaneChanged("retagged", code="LANE_CHANGED", status=409)
            return super().release(board, task_id, token, **kw)
    return C


def test_lane_changed_hands_the_claim_back_instead_of_stranding_it():
    """The 2026-08-05 outage in one test.

    A refused release leaves the claim OURS, and `selection.choose` idles an
    entire board while any claim on it is live. Returning without handing it
    back blocked the `task` board for 32 minutes across four sweeps, on a task
    the agent had barely touched.
    """
    attempts = []
    c = _guarded_release_client(attempts)(snapshot(task()))
    r = runner(c, {"implement": lambda *a: ("landed", None, "")}).turn()

    assert r.acted is False
    assert "LANE_CHANGED" in r.reason and "wrote nothing" in r.reason
    assert "claim handed back" in r.reason

    assert len(attempts) == 2, "the guarded release, then the handback"
    assert attempts[0]["if_current_lane"] is not None, "the guarded one first"
    assert attempts[1].get("if_current_lane") is None, (
        "the handback must not re-send the guard that just refused us")


def test_the_handback_writes_nothing_at_all():
    """It is a surrender, not an update. The board just told us our idea of
    this task is stale, so asserting a lane or overwriting notes is exactly
    the trampling `ifCurrentLane` exists to prevent."""
    attempts = []
    c = _guarded_release_client(attempts)(snapshot(task()))
    runner(c, {"implement": lambda *a: ("landed", "notes!", "out")}).turn()

    handback = attempts[-1]
    assert handback.get("lane") is None
    assert handback.get("notes") is None
    assert handback.get("metadata") is None
    assert not handback.get("complete")


def test_lease_lost_on_release_does_not_attempt_a_handback():
    """Nothing to hand back — the lease is already gone, and the release would
    fail too. Only LANE_CHANGED leaves us holding a live token."""
    from services.task_board import LeaseLost

    attempts = []

    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            attempts.append(kw)
            raise LeaseLost("gone", code="LEASE_LOST", status=409)

    r = runner(C(snapshot(task())), {"implement": lambda *a: ("landed", None, "")}).turn()
    assert "LEASE_LOST" in r.reason and "wrote nothing" in r.reason
    assert "claim handed back" not in r.reason
    assert len(attempts) == 1, "must not retry a dead token"


def test_a_failed_handback_is_reported_honestly_not_claimed_as_success():
    """If the handback itself fails the board really is blocked until the
    lease expires. Saying otherwise would hide the outage."""
    from services.task_board import LaneChanged, TaskBoardError

    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            if kw.get("if_current_lane") is not None:
                raise LaneChanged("retagged", code="LANE_CHANGED", status=409)
            raise TaskBoardError("board unreachable")

    r = runner(C(snapshot(task())), {"implement": lambda *a: ("landed", None, "")}).turn()
    assert r.acted is False
    assert "wrote nothing" in r.reason
    assert "claim handed back" not in r.reason, "the claim is still stranded"


# ── the checkout lock ─────────────────────────────────────────────────────


class FakeLock:
    """Stands in for CheckoutManager.lock. Records order of operations."""

    def __init__(self, *, available=True):
        self.available = available
        self.events: list[str] = []
        self.repos: list[str] = []

    def __call__(self, repo):
        self.repos.append(repo)
        return self

    def __enter__(self):
        self.events.append("acquire")
        return self.available

    def __exit__(self, *exc):
        self.events.append("release")
        return False


def test_a_busy_checkout_means_we_never_claim():
    """The lock is taken BEFORE the claim on purpose. Claim first and this
    same contention would strand a task in an agent lane until its lease
    expired, with no human able to see why."""
    lock = FakeLock(available=False)
    c = FakeClient(snapshot(task()))
    r = Runner(c, "H", jobs={"implement": lambda *a: ("landed", None, "ok")},
               now=lambda: NOW, lock=lock).turn()
    assert r.acted is False
    assert "held by another process" in r.reason
    assert c.named("claim") == [], "a lost checkout race must cost no claim"
    assert c.named("release") == []
    assert lock.events == ["acquire", "release"]


def test_the_lock_is_keyed_on_the_boards_repo():
    lock = FakeLock()
    c = FakeClient(snapshot(task()))
    Runner(c, "H", jobs={"implement": lambda *a: ("landed", None, "ok")},
           now=lambda: NOW, lock=lock).turn()
    assert lock.repos == ["WolffM/tenhands"]


def test_a_normal_turn_takes_the_lock_and_gives_it_back():
    lock = FakeLock()
    c = FakeClient(snapshot(task()))
    r = Runner(c, "H", jobs={"implement": lambda *a: ("landed", None, "ok")},
               now=lambda: NOW, lock=lock).turn()
    assert r.acted is True
    assert lock.events == ["acquire", "release"]
    assert c.named("claim"), "the happy path still claims"


def test_the_lock_is_released_even_when_the_job_explodes():
    """The runner swallows a job failure into `stalled`; the lock must not
    outlive the turn regardless."""
    lock = FakeLock()
    c = FakeClient(snapshot(task()))

    def boom(*a):
        raise RuntimeError("kaboom")

    r = Runner(c, "H", jobs={"implement": boom}, now=lambda: NOW,
               lock=lock).turn()
    assert r.acted is True and r.released_to == selection.LANE_STALLED
    assert lock.events == ["acquire", "release"]


def test_nothing_waiting_does_not_touch_the_lock():
    """An idle board is decided from the snapshot alone. Taking a filesystem
    lock to conclude there is no work would serialise every poll across
    processes for no reason."""
    lock = FakeLock()
    c = FakeClient(snapshot())
    Runner(c, "H", jobs={"implement": lambda *a: ("landed", None, "ok")},
           now=lambda: NOW, lock=lock).turn()
    assert lock.events == []


# ── an unusable agent is an outage, not a stall ───────────────────────────


def test_an_unavailable_agent_does_not_stall_the_task():
    """Stalling would blame a task that is fine for a credential nobody
    replaced, and — because a stall is a normal, successful outcome — hide
    the outage behind a green run. 2026-08-08: that is exactly what happened.
    """
    def boom(*a):
        raise AgentUnavailable("claude exited non-zero")

    c = FakeClient(snapshot(task()))
    with pytest.raises(AgentUnavailable):
        runner(c, {"implement": boom}).turn()
    assert not [r for r in c.named("release") if r[2] == "stalled"]


def test_the_claim_is_handed_back_before_the_run_dies():
    """A claim that outlives the turn idles the whole board until the lease
    expires — 32 minutes, measured, on 2026-08-05. Failing the run must not
    reintroduce that."""
    def boom(*a):
        raise AgentUnavailable("claude exited non-zero")

    c = FakeClient(snapshot(task()))
    with pytest.raises(AgentUnavailable):
        runner(c, {"implement": boom}).turn()
    handback = c.named("release")
    assert handback, "the claim was never given back"
    # No lane, no notes, no outcome: we assert nothing about a task we never
    # touched, so the next sweep re-reads it and plans it again.
    assert handback[0][2] is None and handback[0][3] is None


def test_an_ordinary_agent_error_still_stalls_just_that_task():
    """The whole point of the split — one bad task must not stop the sweep."""
    def boom(*a):
        raise AgentError("the reply had no sections in it")

    c = FakeClient(snapshot(task()))
    r = runner(c, {"implement": boom}).turn()
    assert r.released_to == "stalled" and r.outcome == "error:AgentError"
