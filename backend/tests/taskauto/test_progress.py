"""`BoardSink` — the board projection, and the guards on handing a task back.

The interesting property here is not that the sink publishes; it's what it
asserts when it stops. hadoku-task lets a human act on a task mid-claim and
does **not** check for a live claim first — we asked for that escape hatch and
called it sufficient (`board-contract.md` §2). Two guards stand between that
and the pipeline trampling them:

  `ifCurrentLane`  they moved the card to another repo
  `ifNotesHash`    they edited the plan

The second is new in autoland v3 and had to be. In v2 the notes were safe by
construction — we only wrote them while the task sat in an `agent` lane a
human could not write. Every lane is `editableBy: user` now, so that
guarantee is gone.

These tests pin what the sink believes the board says, because that belief is
what gets asserted.
"""

import pytest

from services.task_board import (
    LaneChanged,
    LeaseLost,
    NotesChanged,
    TaskBoardError,
    notes_hash,
)
from temporal.taskauto import selection
from temporal.taskauto.progress import BoardSink, NullSink

WAITING = selection.waiting("sign it off")
DONE = selection.done("merged")
BLOCKED = selection.blocked("a gate said no")
CONJURE = "hadoku-conjure"


class FakeClient:
    """Records calls; `set_lane` can be made to fail on demand."""

    def __init__(self, set_lane_raises=None, release_raises=None):
        self.calls = []
        self.releases = []
        self.set_lane_raises = set_lane_raises
        self.release_raises = release_raises

    def set_lane(self, board, task_id, token, lane, *, status=None):
        self.calls.append(("set_lane", lane, status.kind if status else None))
        if self.set_lane_raises:
            raise self.set_lane_raises
        return {}

    def heartbeat(self, board, task_id, token, *, lease_seconds=None):
        self.calls.append(("heartbeat",))
        return {}

    def release(self, board, task_id, token, *, lane=None, notes=None,
                outcome=None, metadata=None, complete=False, status=None,
                if_current_lane=None, if_notes_hash=None):
        self.releases.append({"lane": lane, "notes": notes, "outcome": outcome,
                              "complete": complete, "metadata": metadata,
                              "status": status,
                              "if_current_lane": if_current_lane,
                              "if_notes_hash": if_notes_hash})
        if self.release_raises:
            raise self.release_raises
        return {}


def sink(client, lane=CONJURE, notes_at_claim=None):
    return BoardSink(client, "H", "t1", "tok", lane=lane,
                     notes_at_claim=notes_at_claim)


# ---- What the release asserts ---------------------------------------------


def test_release_guards_on_the_repo_lane_the_task_is_in():
    """The card does not move, so the guard is the repo lane throughout —
    and the release names that same lane, because an ABSENT lane clears the
    tag and would drop the task out of its repo into the Inbox."""
    c = FakeClient()
    sink(c).finish(WAITING, notes="n", outcome="asked")
    assert c.releases[0]["if_current_lane"] == CONJURE
    assert c.releases[0]["lane"] == CONJURE


def test_publishing_progress_does_not_move_the_card():
    """`status()` rides on set-lane with the CURRENT lane: a lane move that
    moves nothing. The endpoint is what accepts a chip without releasing."""
    c = FakeClient()
    s = sink(c)
    s.status(selection.working("landing"))
    s.finish(DONE, outcome="merged")
    assert ("set_lane", CONJURE, "working") in c.calls
    assert c.releases[0]["if_current_lane"] == CONJURE


def test_the_notes_guard_is_the_claim_time_digest():
    """Hashing the outgoing notes would make the guard compare our own write
    against itself, which is no guard at all."""
    c = FakeClient()
    sink(c, notes_at_claim="the plan they read").finish(
        WAITING, notes="a rewritten plan")
    assert c.releases[0]["if_notes_hash"] == notes_hash("the plan they read")


def test_an_empty_notes_field_still_guards():
    """Absent notes hash as the EMPTY STRING rather than as no hash, which is
    what lets a runner guard "this task had no plan when I claimed it"."""
    c = FakeClient()
    sink(c).finish(WAITING, notes="a first plan")
    assert c.releases[0]["if_notes_hash"] == notes_hash("")


def test_a_routing_sink_guards_on_being_untagged():
    """"" is a real lane value meaning untagged, and it guards against a human
    filing the card while the router was thinking."""
    c = FakeClient()
    s = BoardSink(c, "H", "t1", "tok", lane="")
    s.finish(selection.working("filed"), lane=CONJURE)
    assert c.releases[0]["if_current_lane"] == ""
    assert c.releases[0]["lane"] == CONJURE, "the one case that moves a card"


def test_a_routing_sink_has_nowhere_to_publish_progress():
    """No lane to address a set-lane at, and nothing worth reporting anyway."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok", lane="").status(selection.working("x"))
    assert c.calls == []


def test_no_known_lane_sends_no_guard():
    """Degrades to the old unguarded behaviour rather than inventing a lane."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok").finish(DONE)
    assert c.releases[0]["if_current_lane"] is None


@pytest.mark.parametrize("exc", [LaneChanged("moved"), NotesChanged("edited")])
def test_a_refused_release_reaches_the_caller(exc):
    """The release wrote nothing and must not be swallowed, or the run would
    report success over work it never handed back."""
    c = FakeClient(release_raises=exc)
    with pytest.raises(type(exc)):
        sink(c).finish(DONE)


# ---- Timings ---------------------------------------------------------------


def test_metrics_ride_out_on_the_release():
    c = FakeClient()
    s = sink(c)
    s.record(plan_s=12.5, plan_passes=1)
    s.finish(WAITING, outcome="asked")
    md = c.releases[0]["metadata"]["taskauto"]
    assert md["plan_s"] == 12.5 and md["plan_passes"] == 1


def test_a_second_pass_adds_to_the_first():
    """The board merges metadata shallowly, so the running total has to be
    carried in and added to — otherwise pass two erases pass one and every
    task reports only its last visit."""
    c = FakeClient()
    s = BoardSink(c, "H", "t1", "tok", lane=CONJURE,
                  metrics={"plan_s": 30.0, "plan_passes": 1})
    s.record(plan_s=12.0, plan_passes=1)
    s.finish(WAITING)
    md = c.releases[0]["metadata"]["taskauto"]
    assert md["plan_s"] == 42.0 and md["plan_passes"] == 2


def test_only_a_terminal_status_gets_an_end_to_end_total():
    """A task still mid-conversation has no total yet. Stamping one every pass
    would make `agent_s` mean 'until last touched' rather than 'to done'.

    `waiting` is the one that changed meaning: v2 keyed this on the LANE, and
    a plan awaiting sign-off is `waiting`, which is mid-conversation."""
    c = FakeClient()
    s = sink(c)
    s.record(plan_s=10.0)
    s.finish(WAITING)
    assert "agent_s" not in c.releases[0]["metadata"]["taskauto"]

    c2 = FakeClient()
    s2 = BoardSink(c2, "H", "t1", "tok", lane=CONJURE,
                   metrics={"plan_s": 30.0, "implement_s": 120.0})
    s2.finish(DONE, outcome="landed:abc")
    md = c2.releases[0]["metadata"]["taskauto"]
    assert md["agent_s"] == 150.0 and md["finished_kind"] == "done"


def test_a_blocked_task_still_gets_a_total():
    """Getting stuck is an ending too, and 'how long did we spend before
    giving up' is the number that makes it worth reading."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok", metrics={"plan_s": 9.0}).finish(BLOCKED)
    assert c.releases[0]["metadata"]["taskauto"]["agent_s"] == 9.0


def test_counts_are_not_summed_into_agent_seconds():
    """Only `_s` fields are time. A pass counter added into the total would
    silently inflate it."""
    c = FakeClient()
    BoardSink(c, "H", "t1", "tok",
              metrics={"plan_s": 10.0, "plan_passes": 3}).finish(DONE)
    assert c.releases[0]["metadata"]["taskauto"]["agent_s"] == 10.0


def test_no_metrics_means_no_metadata():
    """crimson-kitty and any path that records nothing must not start writing
    an empty object onto tasks."""
    c = FakeClient()
    sink(c).finish(DONE)
    assert c.releases[0]["metadata"] is None


# ---- The projection itself -------------------------------------------------


def test_status_failures_are_swallowed():
    """A projection write must never fail the work."""
    c = FakeClient(set_lane_raises=TaskBoardError("boom"))
    sink(c).status(selection.working("landing"))  # does not raise


def test_lease_lost_on_a_status_write_propagates():
    """Not a projection failure — the claim is gone and the run must abort."""
    c = FakeClient(set_lane_raises=LeaseLost("gone"))
    with pytest.raises(LeaseLost):
        sink(c).status(selection.working("landing"))


def test_finish_is_idempotent():
    c = FakeClient()
    s = sink(c)
    s.finish(DONE)
    s.finish(DONE)
    assert len(c.releases) == 1


def test_null_sink_accepts_the_same_calls():
    """crimson-kitty's sink, and every test that doesn't hold a claim."""
    n = NullSink()
    n.status(selection.working("x"))
    n.heartbeat()
    n.finish(DONE, notes="n", outcome="ok", complete=True)
