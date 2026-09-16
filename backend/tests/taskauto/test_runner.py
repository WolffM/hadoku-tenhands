"""Tests for temporal/taskauto/runner.py.

The claim is the boundary of responsibility, so most of these are about what
happens *after* it: every path out must release the task. A task left claimed
is invisible to the human and blocks its whole repo, since we serialise to one
task in flight per repo lane.

Every scenario below survived the v2 → v3 rewrite unchanged in substance —
they encode outages that happened, and turning the board axis did not make any
of them stop being possible. What changed is the vocabulary: a job returns a
STATUS rather than a destination lane, and the task stays in its repo lane
from claim to release.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.task_board import (
    BoardSnapshot,
    BoardTask,
    ClaimHeld,
    Lane,
    LaneChanged,
    LeaseLost,
    NotesChanged,
    TaskBoardError,
    TaskBoardUnavailable,
    notes_hash,
)
from temporal.taskauto import plan_notes, selection
from temporal.taskauto.agent import AgentError, AgentUnavailable
from temporal.taskauto.plan_notes import APPROVAL_ITEM, PlanDoc
from temporal.taskauto.runner import BoardRunner, LaneRunner, TurnResult

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

CONJURE = "hadoku-conjure"
AGGREGATOR = "hadoku-aggregator"

LANES = [
    Lane(CONJURE, "Conjure", 0, "user", repo="WolffM/hadoku-conjure"),
    Lane(AGGREGATOR, "Aggregator", 1, "user", repo="WolffM/hadoku-aggregator"),
]

SIGNED_OFF = plan_notes.render(PlanDoc(
    understanding="Cache it.", plan=["Add a TTL."],
    acceptance=["Second call hits."], needs_approval=True)).replace(
        APPROVAL_ITEM, "- [x] Approve this plan")

LANDED = selection.done("landed as abc12345")
WAITING = selection.waiting("plan ready — sign it off")


#: `status=None` has to mean "no chip at all" — an untouched task — so the
#: default cannot be spelled `None` or the helper would swallow the one case
#: that gets a task planned.
_UNSET = object()


def task(tid="t1", tag=CONJURE, *, claimed=False, ago=60, notes=SIGNED_OFF,
         status=_UNSET):
    ts = (NOW - timedelta(minutes=ago)).isoformat().replace("+00:00", "Z")
    return BoardTask(id=tid, title="make coffee theme default", notes=notes,
                     tag=tag, metadata={}, claimed=claimed, state="Active",
                     created_at=ts, updated_at=ts,
                     status=(selection.waiting("sign it off")
                             if status is _UNSET else status))


def inbox_task(tid="t1", *, ago=90):
    ts = (NOW - timedelta(minutes=ago)).isoformat().replace("+00:00", "Z")
    return BoardTask(id=tid, title="fix the cache", notes="", tag="",
                     metadata={}, claimed=False, state="Active",
                     created_at=ts, updated_at=ts)


def snapshot(*tasks, lanes=None):
    return BoardSnapshot(id="b", name="hadoku", handle="H", repo="",
                         mode="automation",
                         lanes=LANES if lanes is None else lanes,
                         tasks=list(tasks), schema_id="autoland",
                         schema_version=3, access="contributor", version=1)


class FakeClient:
    def __init__(self, board, *, claim_raises=None):
        self.board = board
        self.claim_raises = claim_raises
        self.calls: list[tuple] = []
        self.token = "tok-1"
        self.boards_read = 0

    def get_board(self, handle):
        self.boards_read += 1
        self.calls.append(("get_board", handle))
        return self.board

    def claim(self, board, task_id, *, lane=None, lease_seconds=None,
              agent_id=None):
        self.calls.append(("claim", task_id, lane, lease_seconds))
        if self.claim_raises:
            raise self.claim_raises
        return self.token

    def set_lane(self, board, task_id, token, lane, *, status=None):
        self.calls.append(("set_lane", task_id, lane,
                           status.kind if status else None))
        return {}

    def heartbeat(self, board, task_id, token, *, lease_seconds=None):
        self.calls.append(("heartbeat", task_id))
        return {}

    def release(self, board, task_id, token, *, lane=None, notes=None,
                outcome=None, metadata=None, complete=False, status=None,
                if_current_lane=None, if_notes_hash=None):
        self.calls.append(("release", task_id, lane, outcome, complete,
                           status.kind if status else None))
        # Kept off the tuple so the exact-match assertions stay readable.
        self.last_release = {"lane": lane, "if_current_lane": if_current_lane,
                             "if_notes_hash": if_notes_hash}
        return {}

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def runner(client, jobs, *, lane=CONJURE, lock=None):
    return LaneRunner(client, "H", lane, jobs=jobs, now=lambda: NOW, lock=lock)


def turn(client, jobs, *, lane=CONJURE, lock=None):
    return runner(client, jobs, lane=lane, lock=lock).turn(client.board)


# ── no-ops ────────────────────────────────────────────────────────────────


def test_empty_lane_does_nothing():
    c = FakeClient(snapshot())
    r = turn(c, {"implement": lambda *a: (LANDED, None, "ok")})
    assert r.acted is False and "nothing waiting" in r.reason
    assert c.named("claim") == []


def test_no_handler_means_no_claim():
    """Claiming work we can't run would pin the repo behind a task nothing
    will ever finish."""
    c = FakeClient(snapshot(task()))
    r = turn(c, {})
    assert r.acted is False and "no handler" in r.reason
    assert c.named("claim") == []


def test_losing_the_claim_race_is_not_an_error():
    """Two runners polling one board is the case the atomic claim exists for;
    the loser should shrug and move on."""
    c = FakeClient(snapshot(task()),
                   claim_raises=ClaimHeld("held", code="CLAIM_HELD",
                                          status=409,
                                          body={"holder": "agent-9"}))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "ok")})
    assert r.acted is False and "agent-9" in r.reason
    assert c.named("release") == []


# ── the happy path ────────────────────────────────────────────────────────


def test_the_log_line_says_what_the_job_decided_not_just_its_status():
    """Two very different conclusions publish the same chip.

    `plan:no-action-proposed` ("this looks already done") and
    `plan:unverifiable` ("I could not state an acceptance check") both leave a
    `waiting` chip with no plan. Without the outcome in the log line the two
    are indistinguishable after the fact — the notes are rewritten each pass,
    so the evidence is gone. That cost a real debugging round."""
    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": lambda *a: (WAITING, None, "implement:no-plan")})
    assert r.outcome == "implement:no-plan"
    assert "[implement:no-plan]" in str(r)
    assert "→ waiting" in str(r)


def test_an_idle_turn_has_no_outcome_to_report():
    c = FakeClient(snapshot())
    r = turn(c, {"implement": lambda *a: (LANDED, None, "ok")})
    assert str(r).startswith("idle:") and "[" not in str(r)


def test_claims_into_the_repo_lane_and_releases_there():
    """The claim names the lane the task is ALREADY in. Under v2 this moved
    the card into an agent lane; under v3 the card never moves, so the lane on
    both calls is the repo — and a release that named anything else would be
    re-filing the task behind the human's back."""
    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": lambda *a: (LANDED, "done", "merged")})
    assert r.acted is True
    assert ("claim", "t1", CONJURE, 900) in c.calls
    assert ("release", "t1", CONJURE, "merged", False, "done") in c.calls
    assert r.status == "done" and r.repo == "WolffM/hadoku-conjure"


def test_a_job_can_publish_progress_without_releasing():
    """Releasing to report progress would drop the lease in between — the
    exact window another runner would take the task in."""
    def job(pickup, board, sink):
        sink.status(selection.working("landing"))
        return LANDED, None, "merged"

    c = FakeClient(snapshot(task()))
    turn(c, {"implement": job})
    assert ("set_lane", "t1", CONJURE, "working") in c.calls


def test_release_asserts_both_guards():
    """End to end: `ifCurrentLane` AND `ifNotesHash` have to reach the client.

    Between them they are the only thing stopping the pipeline overwriting a
    human who moved the card to another repo, or edited the plan, mid-claim.
    hadoku-task allows both and checks for no live claim first."""
    notes = SIGNED_OFF
    c = FakeClient(snapshot(task(notes=notes)))
    turn(c, {"implement": lambda *a: (LANDED, "new notes", "merged")})
    assert c.last_release == {
        "lane": CONJURE,
        "if_current_lane": CONJURE,
        # The digest of what we PLANNED AGAINST, not of what we are writing.
        "if_notes_hash": notes_hash(notes),
    }


def test_the_notes_guard_is_the_claim_time_snapshot():
    """Hashing the outgoing notes instead would make the guard vacuous — it
    would only ever compare our own write against itself."""
    original = SIGNED_OFF + "\n<!-- distinct -->\n"
    c = FakeClient(snapshot(task(notes=original)))
    turn(c, {"implement": lambda *a: (LANDED, "rewritten", "merged")})
    assert c.last_release["if_notes_hash"] == notes_hash(original)
    assert c.last_release["if_notes_hash"] != notes_hash("rewritten")


def test_plan_job_runs_for_an_unplanned_task_in_a_repo_lane():
    c = FakeClient(snapshot(task(notes="", status=None, ago=90)))
    r = turn(c, {"plan": lambda *a: (WAITING, "a plan", "asked")})
    assert r.acted and r.job == "plan"
    assert ("claim", "t1", CONJURE, 900) in c.calls
    assert ("release", "t1", CONJURE, "asked", False, "waiting") in c.calls


# ── failure always hands the task back ────────────────────────────────────


def test_a_crashing_job_blocks_the_task_rather_than_pinning_it():
    """A task left claimed is invisible and blocks its repo. Publishing
    `blocked` with a reason is strictly better."""
    def boom(*a):
        raise RuntimeError("the agent exploded")

    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": boom})
    rel = c.named("release")[0]
    assert rel[5] == "blocked"
    assert rel[3] == "error:RuntimeError"
    assert r.acted and r.status == "blocked"


def test_the_failure_note_names_the_failure():
    def boom(*a):
        raise ValueError("could not find the theme file")

    captured = {}

    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            captured.update(kw)
            return super().release(board, task_id, token, **kw)

    r = turn(C(snapshot(task())), {"implement": boom})
    assert "could not find the theme file" in captured["notes"]
    assert r.status == "blocked"


def test_a_job_failing_on_an_unavailable_board_still_blocks():
    def boom(*a):
        raise TaskBoardUnavailable("network")

    c = FakeClient(snapshot(task()))
    assert turn(c, {"implement": boom}).status == "blocked"


# ── lease loss is not a failure to route ──────────────────────────────────


def test_lease_lost_aborts_without_writing():
    """A human cancelled us, or the lease expired. We no longer hold the
    claim, so anything we wrote would be trampling whoever does."""
    def cancelled(*a):
        raise LeaseLost("gone", code="LEASE_LOST", status=409)

    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": cancelled})
    assert r.acted is False and "lease lost" in r.reason
    assert c.named("release") == [], "must not write after losing the lease"


def test_lease_lost_during_release_is_reported_not_swallowed():
    class C(FakeClient):
        def release(self, *a, **k):
            raise LeaseLost("gone", code="LEASE_LOST", status=409)

    r = turn(C(snapshot(task())), {"implement": lambda *a: (LANDED, None, "")})
    assert r.acted is False
    assert "LEASE_LOST" in r.reason and "wrote nothing" in r.reason


def test_release_failure_is_surfaced_loudly():
    """The work happened; only the handback failed. The task is stuck until
    the lease expires and the operator needs to know."""
    class C(FakeClient):
        def release(self, *a, **k):
            raise TaskBoardUnavailable("500")

    r = turn(C(snapshot(task())), {"implement": lambda *a: (LANDED, None, "")})
    assert r.acted is False and "release failed" in r.reason


# ── serialisation holds through the runner ────────────────────────────────


def test_a_live_claim_in_this_repo_blocks_the_turn():
    c = FakeClient(snapshot(task("busy", claimed=True), task("t2")))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "")})
    assert r.acted is False and "in flight" in r.reason
    assert c.named("claim") == []


def test_a_live_claim_in_another_repo_does_not():
    c = FakeClient(snapshot(task("busy", AGGREGATOR, claimed=True),
                            task("t2", CONJURE)))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "")})
    assert r.acted is True and r.task_id == "t2"


# ── a refused release must not strand the claim ───────────────────────────


@pytest.mark.parametrize("exc,code", [
    (LaneChanged("retagged", code="LANE_CHANGED", status=409), "LANE_CHANGED"),
    (NotesChanged("edited", code="NOTES_CHANGED", status=409), "NOTES_CHANGED"),
])
def test_a_refused_release_aborts_like_a_lost_lease(exc, code):
    """A human moved the card or edited the plan mid-claim, so the release
    wrote nothing. Different causes from LEASE_LOST, identical consequence for
    the write — the task is no longer ours to describe."""
    class C(FakeClient):
        def release(self, *a, **k):
            raise exc

    r = turn(C(snapshot(task())), {"implement": lambda *a: (LANDED, None, "")})
    assert r.acted is False
    assert code in r.reason and "wrote nothing" in r.reason


def _guarded_release_client(attempts, exc):
    """Production's actual shape: the board refuses the *guarded* release and
    accepts an unguarded one.

    Making every release raise cannot tell "we let go of the claim" apart from
    "we walked away still holding it" — the whole point of the fix below.
    `attempts` records EVERY call including refused ones; `FakeClient.calls`
    only sees the ones that get through.
    """
    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            attempts.append(kw)
            if (kw.get("if_current_lane") is not None
                    or kw.get("if_notes_hash") is not None):
                raise exc
            return super().release(board, task_id, token, **kw)
    return C


@pytest.mark.parametrize("exc,code", [
    (LaneChanged("retagged", code="LANE_CHANGED", status=409), "LANE_CHANGED"),
    (NotesChanged("edited", code="NOTES_CHANGED", status=409), "NOTES_CHANGED"),
])
def test_a_refused_release_hands_the_claim_back(exc, code):
    """The 2026-08-05 outage in one test, now covering both guards.

    A refused release leaves the claim OURS, and selection idles an entire
    repo while any claim on it is live. Returning without handing it back
    blocked the `task` board for 32 minutes across four sweeps, on a task the
    agent had barely touched. `NOTES_CHANGED` is new in v3 and has exactly the
    same shape, which is why it is parametrised alongside rather than trusted
    to be covered by the older case.
    """
    attempts = []
    c = _guarded_release_client(attempts, exc)(snapshot(task()))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "")})

    assert r.acted is False
    assert code in r.reason and "wrote nothing" in r.reason
    assert "claim handed back" in r.reason

    assert len(attempts) == 2, "the guarded release, then the handback"
    assert attempts[1].get("if_current_lane") is None, (
        "the handback must not re-send the guard that just refused us")
    assert attempts[1].get("if_notes_hash") is None


def test_the_handback_writes_nothing_but_the_lane():
    """It is a surrender, not an update. The board just told us our idea of
    this task is stale, so overwriting notes is exactly the trampling the
    guards exist to prevent. The lane IS sent, because an absent lane clears
    the tag and would drop the task out of its repo into the Inbox."""
    attempts = []
    c = _guarded_release_client(
        attempts, LaneChanged("x", code="LANE_CHANGED", status=409))(
            snapshot(task()))
    turn(c, {"implement": lambda *a: (LANDED, "notes!", "out")})
    handback = attempts[-1]
    assert handback.get("lane") == CONJURE
    assert handback.get("notes") is None
    assert handback.get("metadata") is None
    assert handback.get("status") is None
    assert not handback.get("complete")


def test_lease_lost_on_release_does_not_attempt_a_handback():
    """Nothing to hand back — the lease is already gone, and the release would
    fail too. Only the other two leave us holding a live token."""
    attempts = []

    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            attempts.append(kw)
            raise LeaseLost("gone", code="LEASE_LOST", status=409)

    r = turn(C(snapshot(task())), {"implement": lambda *a: (LANDED, None, "")})
    assert "LEASE_LOST" in r.reason and "wrote nothing" in r.reason
    assert "claim handed back" not in r.reason
    assert len(attempts) == 1, "must not retry a dead token"


def test_a_failed_handback_is_reported_honestly_not_claimed_as_success():
    """If the handback itself fails the repo really is blocked until the lease
    expires. Saying otherwise would hide the outage."""
    class C(FakeClient):
        def release(self, board, task_id, token, **kw):
            if kw.get("if_current_lane") is not None:
                raise LaneChanged("retagged", code="LANE_CHANGED", status=409)
            raise TaskBoardError("board unreachable")

    r = turn(C(snapshot(task())), {"implement": lambda *a: (LANDED, None, "")})
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
    same contention would strand a task until its lease expired, with no human
    able to see why."""
    lock = FakeLock(available=False)
    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "ok")}, lock=lock)
    assert r.acted is False
    assert "held by another process" in r.reason
    assert c.named("claim") == [], "a lost checkout race must cost no claim"
    assert c.named("release") == []
    assert lock.events == ["acquire", "release"]


def test_the_lock_is_keyed_on_the_lanes_repo():
    """v2 keyed it on the board's single repo. The board has many now, so the
    key comes from the lane — get this wrong and two repos serialise against
    each other, or worse, one repo doesn't serialise against itself."""
    lock = FakeLock()
    c = FakeClient(snapshot(task("t1", AGGREGATOR)))
    turn(c, {"implement": lambda *a: (LANDED, None, "ok")},
         lane=AGGREGATOR, lock=lock)
    assert lock.repos == ["WolffM/hadoku-aggregator"]


def test_a_normal_turn_takes_the_lock_and_gives_it_back():
    lock = FakeLock()
    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": lambda *a: (LANDED, None, "ok")}, lock=lock)
    assert r.acted is True
    assert lock.events == ["acquire", "release"]
    assert c.named("claim"), "the happy path still claims"


def test_the_lock_is_released_even_when_the_job_explodes():
    lock = FakeLock()
    c = FakeClient(snapshot(task()))

    def boom(*a):
        raise RuntimeError("kaboom")

    r = turn(c, {"implement": boom}, lock=lock)
    assert r.acted is True and r.status == selection.STATUS_BLOCKED
    assert lock.events == ["acquire", "release"]


def test_nothing_waiting_does_not_touch_the_lock():
    """An idle repo is decided from the snapshot alone. Taking a filesystem
    lock to conclude there is no work would serialise every poll across
    processes for no reason."""
    lock = FakeLock()
    c = FakeClient(snapshot())
    turn(c, {"implement": lambda *a: (LANDED, None, "ok")}, lock=lock)
    assert lock.events == []


# ── an unusable agent is an outage, not a stall ───────────────────────────


def test_an_unavailable_agent_does_not_block_the_task():
    """Blocking would blame a task that is fine for a credential nobody
    replaced, and — because `blocked` is a normal, successful outcome — hide
    the outage behind a green run. 2026-08-08: that is exactly what happened.
    """
    def boom(*a):
        raise AgentUnavailable("claude exited non-zero")

    c = FakeClient(snapshot(task()))
    with pytest.raises(AgentUnavailable):
        turn(c, {"implement": boom})
    assert not [r for r in c.named("release") if r[5] == "blocked"]


def test_the_claim_is_handed_back_before_the_run_dies():
    """A claim that outlives the turn idles the whole repo until the lease
    expires — 32 minutes, measured, on 2026-08-05."""
    def boom(*a):
        raise AgentUnavailable("claude exited non-zero")

    c = FakeClient(snapshot(task()))
    with pytest.raises(AgentUnavailable):
        turn(c, {"implement": boom})
    handback = c.named("release")
    assert handback, "the claim was never given back"
    # No notes and no outcome — we assert nothing about a task we never
    # touched, so the next sweep re-reads it and picks it up again.
    assert handback[0][3] is None


def test_the_task_stays_in_its_repo_when_the_agent_dies():
    """An absent lane on release CLEARS the tag, which under v3 would drop the
    task out of its repo and back into the Inbox — losing the routing decision
    and, if it was signed off, the approval with it. Measured against the live
    board 2026-08-08, when the same hazard cost a human's approval."""
    def boom(*a):
        raise AgentUnavailable("claude exited non-zero")

    c = FakeClient(snapshot(task(tag=CONJURE)))
    with pytest.raises(AgentUnavailable):
        turn(c, {"implement": boom})
    assert c.named("release")[0][2] == CONJURE


def test_an_ordinary_agent_error_still_blocks_just_that_task():
    """The whole point of the split — one bad task must not stop the sweep."""
    def boom(*a):
        raise AgentError("the reply had no sections in it")

    c = FakeClient(snapshot(task()))
    r = turn(c, {"implement": boom})
    assert r.status == "blocked" and r.outcome == "error:AgentError"


# ── BoardRunner: one read, then every repo ────────────────────────────────


def board_runner(client, *, jobs=None, route_job=None, pr_lookup=None):
    jobs = jobs or {}
    return BoardRunner(
        client, "H", now=lambda: NOW, route_job=route_job,
        pr_lookup=pr_lookup,
        lane_runner_for=lambda tag: LaneRunner(client, "H", tag, jobs=jobs,
                                               now=lambda: NOW))


def test_the_board_is_read_once_for_every_repo_on_it():
    """N lane runners each calling `get_board` would be N identical round
    trips per tick. Hoisting the read is what makes one board with N repos
    cheaper than N boards rather than merely tidier."""
    c = FakeClient(snapshot(task("t1", CONJURE), task("t2", AGGREGATOR)))
    board_runner(c, jobs={"implement": lambda *a: (LANDED, None, "ok")}).turn()
    assert c.boards_read == 1


def test_every_repo_lane_gets_a_turn():
    c = FakeClient(snapshot(task("t1", CONJURE), task("t2", AGGREGATOR)))
    r = board_runner(
        c, jobs={"implement": lambda *a: (LANDED, None, "ok")}).turn()
    assert r.acted
    assert {rel[1] for rel in c.named("release")} == {"t1", "t2"}


def test_one_repo_erroring_does_not_stop_the_others():
    calls = []

    class C(FakeClient):
        def claim(self, board, task_id, **kw):
            calls.append(task_id)
            if task_id == "t1":
                raise TaskBoardError("board unhappy")
            return super().claim(board, task_id, **kw)

    c = C(snapshot(task("t1", CONJURE), task("t2", AGGREGATOR)))
    r = board_runner(
        c, jobs={"implement": lambda *a: (LANDED, None, "ok")}).turn()
    assert calls == ["t1", "t2"]
    assert r.acted, "the second repo still got its turn"


def test_an_unavailable_agent_abandons_the_whole_board():
    """Every remaining repo would fail identically, so carrying on would turn
    one outage into a row of blocked tasks across the fleet."""
    def boom(*a):
        raise AgentUnavailable("claude is down")

    c = FakeClient(snapshot(task("t1", CONJURE), task("t2", AGGREGATOR)))
    with pytest.raises(AgentUnavailable):
        board_runner(c, jobs={"implement": boom}).turn()


def test_a_v2_board_is_declined_rather_than_misread():
    v2 = [Lane("planning", "Planning", 0, "agent")]
    c = FakeClient(snapshot(task("t1", "planning"), lanes=v2))
    r = board_runner(c, jobs={"implement": lambda *a: (LANDED, None, "ok")}).turn()
    assert r.acted is False and "not a v3 board" in str(r)
    assert c.named("claim") == []


def test_malformed_tasks_are_reported_on_the_board_line():
    c = FakeClient(snapshot(task("t1", f"{CONJURE} {AGGREGATOR}")))
    r = board_runner(c, jobs={}).turn()
    assert "unusable lane tag" in str(r)


# ── BoardRunner: routing ──────────────────────────────────────────────────


def test_routing_files_an_inbox_task_and_takes_no_checkout_lock():
    """No lock is available to take — an Inbox task's repo is unknown until it
    has been read. That is the whole reason routing is its own job."""
    def route(pickup, board, sink):
        return selection.working(f"filed under {CONJURE}"), None, "route", CONJURE

    c = FakeClient(snapshot(inbox_task()))
    r = board_runner(c, route_job=route).turn()
    assert r.acted
    rel = c.named("release")[0]
    assert rel[1] == "t1" and rel[2] == CONJURE


def test_routing_takes_a_short_lease():
    """A crashed router must not pin an Inbox task for a quarter of an hour
    over work that is a single classification call."""
    def route(pickup, board, sink):
        return selection.working("filed"), None, "route", CONJURE

    c = FakeClient(snapshot(inbox_task()))
    board_runner(c, route_job=route).turn()
    assert c.named("claim")[0][3] == 120


def test_routing_guards_the_release_on_the_task_still_being_untagged():
    """"" is a real lane value meaning untagged, and sending it guards against
    a human filing the card themselves while the router was thinking. None
    would send no guard at all."""
    def route(pickup, board, sink):
        return selection.working("filed"), None, "route", CONJURE

    c = FakeClient(snapshot(inbox_task()))
    board_runner(c, route_job=route).turn()
    assert c.last_release["if_current_lane"] == ""


def test_a_routed_task_is_claimable_in_the_same_tick():
    """Re-reading after a successful route is what gets a fresh capture
    planned in one sweep instead of two."""
    def route(pickup, board, sink):
        return selection.working("filed"), None, "route", CONJURE

    c = FakeClient(snapshot(inbox_task()))
    board_runner(c, route_job=route,
                 jobs={"plan": lambda *a: (WAITING, "p", "planned")}).turn()
    assert c.boards_read == 2, "one read, then a re-read after the route"


def test_an_empty_inbox_does_not_claim():
    def route(pickup, board, sink):  # pragma: no cover - must not run
        raise AssertionError("routing ran on an empty inbox")

    c = FakeClient(snapshot(task("t1", CONJURE)))
    board_runner(c, route_job=route).turn()
    assert [x for x in c.named("claim") if x[1] == "t1"] == []


def test_no_route_job_means_the_inbox_is_simply_not_touched():
    c = FakeClient(snapshot(inbox_task()))
    r = board_runner(c).turn()
    assert c.named("claim") == []
    assert "route" not in str(r)


# ── BoardRunner: reconciliation runs first ────────────────────────────────


def test_reconcile_runs_before_selection_and_forces_a_re_read():
    seen = []

    def lookup(ref):
        seen.append(ref.number)
        return None  # no verdict — leave it alone

    notes = "Opened https://github.com/WolffM/hadoku-conjure/pull/42"
    c = FakeClient(snapshot(task("t1", CONJURE, notes=notes,
                                 status=selection.waiting("PR #42"))))
    board_runner(c, pr_lookup=lookup).turn()
    assert seen == [42], "the open PR was checked"
    assert c.boards_read == 1, "no verdict means no correction and no re-read"
