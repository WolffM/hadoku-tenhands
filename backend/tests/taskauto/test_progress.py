"""`BoardSink` — the board projection, and the guard on handing a task back.

The interesting property here is not that the sink publishes; it's what it
asserts when it stops. hadoku-task lets a human drag a task *out* of an agent
lane and does **not** check whether a claim is live first — we asked for that
escape hatch and called it sufficient (`board-contract.md` §2). So the only
thing standing between "a human took this task back" and "the pipeline
overwrote their notes" is `ifCurrentLane` on release.

These tests pin what the sink believes the board says, because that belief is
what gets asserted.
"""

import pytest

from services.task_board import LaneChanged, LeaseLost, TaskBoardError
from temporal.taskauto.progress import BoardSink, NullSink


class FakeClient:
    """Records calls; `set_lane` can be made to fail on demand."""

    def __init__(self, set_lane_raises=None, release_raises=None):
        self.calls = []
        self.releases = []
        self.set_lane_raises = set_lane_raises
        self.release_raises = release_raises

    def set_lane(self, board, task_id, token, lane):
        self.calls.append(("set_lane", lane))
        if self.set_lane_raises:
            raise self.set_lane_raises
        return {}

    def heartbeat(self, board, task_id, token, *, lease_seconds=None):
        self.calls.append(("heartbeat",))
        return {}

    def release(self, board, task_id, token, *, lane=None, notes=None,
                outcome=None, metadata=None, complete=False,
                if_current_lane=None):
        self.releases.append({"lane": lane, "notes": notes, "outcome": outcome,
                              "complete": complete, "metadata": metadata,
                              "if_current_lane": if_current_lane})
        if self.release_raises:
            raise self.release_raises
        return {}


def sink(client, lane="working"):
    return BoardSink(client, "H", "t1", "tok", lane=lane)


# ---- What the release asserts ---------------------------------------------


def test_release_guards_on_the_lane_the_claim_put_it_in():
    """No `set_lane` happened, so the claim's lane is still the truth."""
    c = FakeClient()
    sink(c, lane="planning").finish("plan-review", notes="n", outcome="asked")
    assert c.releases[0]["if_current_lane"] == "planning"


def test_release_guards_on_the_last_lane_we_set():
    c = FakeClient()
    s = sink(c, lane="approved")
    s.lane("working")
    s.lane("landing")
    s.finish("landed", outcome="merged")
    assert c.releases[0]["if_current_lane"] == "landing"


def test_a_failed_set_lane_does_not_advance_the_belief():
    """The projection write failed, so the task never moved.

    Asserting the lane we *wanted* would 409 on a lane nobody touched, and
    the run would abandon a completed job for a network blip.
    """
    c = FakeClient(set_lane_raises=TaskBoardError("502 from the board"))
    s = sink(c, lane="approved")
    s.lane("working")
    s.finish("stalled", outcome="error")
    assert c.releases[0]["if_current_lane"] == "approved"


def test_no_known_lane_sends_no_guard():
    """Degrades to the old unguarded behaviour rather than inventing a lane."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok").finish("landed")
    assert c.releases[0]["if_current_lane"] is None


def test_lane_changed_reaches_the_caller():
    """A human retagged mid-claim: the release wrote nothing and must not be
    swallowed, or the run would report success over work it didn't hand back."""
    c = FakeClient(release_raises=LaneChanged("lane changed"))
    with pytest.raises(LaneChanged):
        sink(c).finish("landed")


# ---- Timings ---------------------------------------------------------------


def test_metrics_ride_out_on_the_release():
    c = FakeClient()
    s = sink(c)
    s.record(plan_s=12.5, plan_passes=1)
    s.finish("plan-review", outcome="asked")
    md = c.releases[0]["metadata"]["taskauto"]
    assert md["plan_s"] == 12.5 and md["plan_passes"] == 1


def test_a_second_pass_adds_to_the_first():
    """The board merges metadata shallowly, so the running total has to be
    carried in and added to — otherwise pass two erases pass one and every
    task reports only its last visit."""
    c = FakeClient()
    s = BoardSink(c, "H", "t1", "tok", lane="planning",
                  metrics={"plan_s": 30.0, "plan_passes": 1})
    s.record(plan_s=12.0, plan_passes=1)
    s.finish("plan-review")
    md = c.releases[0]["metadata"]["taskauto"]
    assert md["plan_s"] == 42.0 and md["plan_passes"] == 2


def test_only_a_terminal_lane_gets_an_end_to_end_total():
    """A task still mid-conversation has no total yet. Stamping one every pass
    would make `agent_s` mean 'until last touched' rather than 'to done'."""
    c = FakeClient()
    s = sink(c)
    s.record(plan_s=10.0)
    s.finish("plan-review")
    assert "agent_s" not in c.releases[0]["metadata"]["taskauto"]

    c2 = FakeClient()
    s2 = BoardSink(c2, "H", "t1", "tok", lane="landing",
                   metrics={"plan_s": 30.0, "implement_s": 120.0})
    s2.finish("landed", outcome="landed:abc")
    md = c2.releases[0]["metadata"]["taskauto"]
    assert md["agent_s"] == 150.0 and md["finished_lane"] == "landed"


def test_a_stalled_task_still_gets_a_total():
    """Stalling is an ending too, and 'how long did we spend before giving up'
    is the number that makes a stall worth reading."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok", metrics={"plan_s": 9.0}).finish("stalled")
    assert c.releases[0]["metadata"]["taskauto"]["agent_s"] == 9.0


def test_counts_are_not_summed_into_agent_seconds():
    """Only `_s` fields are time. A pass counter added into the total would
    silently inflate it."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok",
              metrics={"plan_s": 10.0, "plan_passes": 3}).finish("landed")
    assert c.releases[0]["metadata"]["taskauto"]["agent_s"] == 10.0


def test_no_metrics_means_no_metadata():
    """crimson-kitty and any path that records nothing must not start writing
    an empty object onto tasks."""
    c = FakeClient()
    sink(c).finish("landed")
    assert c.releases[0]["metadata"] is None


# ---- The projection itself -------------------------------------------------


def test_set_lane_failures_are_swallowed():
    """A projection write must never fail the work."""
    c = FakeClient(set_lane_raises=TaskBoardError("boom"))
    sink(c).lane("landing")  # does not raise


def test_lease_lost_on_set_lane_propagates():
    """Not a projection failure — the claim is gone and the run must abort."""
    c = FakeClient(set_lane_raises=LeaseLost("gone"))
    with pytest.raises(LeaseLost):
        sink(c).lane("landing")


def test_finish_is_idempotent():
    c = FakeClient()
    s = sink(c)
    s.finish("landed")
    s.finish("landed")
    assert len(c.releases) == 1


def test_null_sink_accepts_the_same_calls():
    """crimson-kitty's sink, and every test that doesn't hold a claim."""
    n = NullSink()
    n.lane("working")
    n.heartbeat()
    n.finish("landed", notes="n", outcome="ok", complete=True)
