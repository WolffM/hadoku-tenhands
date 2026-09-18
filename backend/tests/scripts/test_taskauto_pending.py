"""Tests for the backstop gate (scripts/taskauto_pending.py).

The gate decides whether the hourly cron fires a sweep at all, so there are
exactly two things worth testing and they are not symmetric:

- **What counts as pending.** Get this wrong in the permissive direction and
  the cron is a little noisier than it needs to be. Get it wrong in the
  restrictive direction and a task silently never advances.
- **That it fails OPEN.** Every failure path must exit 0 and let the sweep
  fire. A gate that answers "nothing to do" whenever it is broken has deleted
  the backstop rather than made it cheaper, and it would look healthy doing it.

The second one is why the exit codes are tested directly rather than through
the helper: `10` is a verdict and `0` is everything else, and the only way to
be sure a traceback does not read as a verdict is to raise one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from services.task_board import BoardSnapshot, BoardTask, Lane

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GATE_PATH = _REPO_ROOT / "scripts" / "taskauto_pending.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("taskauto_pending", _GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gate():
    return _load_gate()


LANES = [
    Lane(tag="planning", label="Planning", order=0, editable_by="agent"),
    Lane(tag="plan-review", label="Plan review", order=1, editable_by="user"),
    Lane(tag="replan", label="Replan", order=2, editable_by="user"),
    Lane(tag="approved", label="Approved", order=3, editable_by="user"),
    Lane(tag="working", label="Working", order=4, editable_by="agent"),
    Lane(tag="landing", label="Landing", order=5, editable_by="agent"),
    Lane(tag="landed", label="Landed", order=6, editable_by="user"),
    Lane(tag="stalled", label="Stalled", order=7, editable_by="user"),
]


def task(task_id: str, tag: str, *, claimed: bool = False,
         state: str = "Active") -> BoardTask:
    return BoardTask(id=task_id, title=task_id, notes="", tag=tag,
                     metadata={}, claimed=claimed, state=state)


def board(*tasks: BoardTask) -> BoardSnapshot:
    return BoardSnapshot(
        id="b1", name="board", handle="H1", repo="WolffM/x", mode="automation",
        lanes=LANES, tasks=list(tasks), schema_id="autoland-v1",
        schema_version=1, access="contributor", version=1)


# ── what counts as pending ────────────────────────────────────────────────


def test_an_empty_board_is_not_pending(gate):
    """The case the gate exists for: nearly every hour, on nearly every board."""
    assert gate.pending_tasks(board()) == []


def test_landed_is_pending(gate):
    """The whole reason a backstop still exists. The PR auto-merges on green
    and only `reconcile.py` ever notices — GitHub does not tell us, and no
    human write is coming to push it."""
    assert gate.pending_tasks(board(task("t1", "landed"))) == ["t1"]


def test_an_agent_lane_with_no_live_claim_is_pending(gate):
    """A crashed run. Recovery fires on the ABSENCE of a heartbeat, which by
    construction nothing can push — see `selection._recoverable`."""
    for lane in ("planning", "working", "landing"):
        assert gate.pending_tasks(board(task("t1", lane))) == ["t1"], lane


def test_a_claimable_human_lane_is_pending(gate):
    """The write that put it here already dispatched, so normally a run has
    been and gone. It still counts, because that dispatch can be LOST when the
    services restart mid-deploy — and then only a cron looks again."""
    for lane in ("approved", "replan"):
        assert gate.pending_tasks(board(task("t1", lane))) == ["t1"], lane


def test_the_inbox_is_pending(gate):
    """An untagged task is claimable (it starts planning), so a lost dispatch
    strands it exactly like any other."""
    assert gate.pending_tasks(board(task("t1", ""))) == ["t1"]


def test_plan_review_and_stalled_are_not_pending(gate):
    """The only two lanes that suppress. Both are resting places where a human
    is expected to act, and that action is a board write, which dispatches. A
    task can sit in either for a week; sweeping hourly to re-read a lane whose
    meaning is "waiting for a person" would rebuild the poll this replaces."""
    assert gate.pending_tasks(
        board(task("t1", "plan-review"), task("t2", "stalled"))) == []


def test_a_live_claim_is_pending_even_in_a_resting_lane(gate):
    """A run is working right now. The concurrency group means our tick queues
    harmlessly behind it; treating "busy" as "nothing to do" is how a board
    goes quiet at exactly the moment it is doing the most."""
    assert gate.pending_tasks(
        board(task("t1", "plan-review", claimed=True))) == ["t1"]


def test_archived_tasks_are_not_pending(gate):
    """Completed and Deleted tasks still come back in a board read. A board
    with a thousand archived tasks and nothing live must still be quiet."""
    assert gate.pending_tasks(board(
        task("t1", "landed", state="Completed"),
        task("t2", "landed", state="Deleted"))) == []


def test_an_unknown_lane_is_pending(gate):
    """RESTING_LANES is an allowlist of things that suppress, not a denylist of
    things that fire. A lane added to the schema tomorrow must err toward
    sweeping — the cost of being wrong that way is one 21-second run."""
    assert gate.pending_tasks(board(task("t1", "some-new-lane"))) == ["t1"]


# ── failing open ──────────────────────────────────────────────────────────


def test_no_visible_boards_sweeps(gate, monkeypatch):
    """An empty fleet and a key that lost its board shares look identical from
    here, and the second is a real outage. Sweep, and let the run say so."""
    monkeypatch.setattr(gate, "TaskBoardClient",
                        lambda *a, **k: _FakeClient(boards=[]))
    assert gate.main() == 0


def test_a_clean_read_finding_nothing_is_the_only_suppressing_answer(gate,
                                                                    monkeypatch):
    monkeypatch.setattr(gate, "TaskBoardClient",
                        lambda *a, **k: _FakeClient(boards=[board()]))
    assert gate.main() == gate.EXIT_NOTHING_PENDING


def test_a_pending_board_sweeps(gate, monkeypatch):
    monkeypatch.setattr(
        gate, "TaskBoardClient",
        lambda *a, **k: _FakeClient(boards=[board(task("t1", "landed"))]))
    assert gate.main() == 0


def test_an_unreadable_board_raises_rather_than_answering(gate, monkeypatch):
    """`main` must not swallow this itself — the module's `__main__` guard
    turns it into exit 0. Silently returning "nothing pending" from a failed
    read is the one outcome that can lose work."""
    monkeypatch.setattr(gate, "TaskBoardClient",
                        lambda *a, **k: _FakeClient(boom=RuntimeError("502")))
    with pytest.raises(RuntimeError):
        gate.main()


def test_the_suppressing_code_is_not_one(gate):
    """`1` is what a traceback, a missing import and an unhandled exception all
    exit with. If the gate used it for "nothing pending", every crash would
    silence the backstop and look like a verdict."""
    assert gate.EXIT_NOTHING_PENDING != 1
    assert gate.EXIT_NOTHING_PENDING != 0


def test_a_clean_exit_is_not_swallowed_by_the_fail_open_handler():
    """The `__main__` guard catches `Exception` and NOT `BaseException`, and
    calls `sys.exit` outside the try. Catching `SystemExit` there would turn
    every "nothing pending" into a sweep — the gate would look like it worked
    and never once suppress anything."""
    src = _GATE_PATH.read_text()
    assert "except BaseException" not in src
    guard = src.split('if __name__ == "__main__":')[1]
    assert "except Exception:" in guard
    # The exit call must sit at the guard's top level, not inside the try.
    assert "\n    sys.exit(code)" in guard


class _FakeClient:
    def __init__(self, boards=None, boom=None):
        self._boards = boards or []
        self._boom = boom

    def automation_boards(self):
        if self._boom:
            raise self._boom
        return self._boards

    def get_board(self, handle):
        if self._boom:
            raise self._boom
        return next(b for b in self._boards if b.handle == handle)
