"""Tests for temporal/taskauto/selection.py.

Selection is pure policy, so these are the tests that actually pin the
pipeline's judgement calls: one task in flight per board, work already
started outranks work not started, and the Inbox waits for a human to stop
typing before anyone plans at them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.task_board import BoardSnapshot, BoardTask, Lane
from temporal.taskauto.selection import (
    DEFAULT_SETTLE,
    Idle,
    JOB_IMPLEMENT,
    JOB_PLAN,
    LANE_APPROVED,
    LANE_LANDING,
    LANE_PLANNING,
    LANE_REPLAN,
    LANE_WORKING,
    Pickup,
    choose,
)

NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

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


def task(tid, tag="", *, claimed=False, state="Active", ago_minutes=60,
         title="a task"):
    touched = (NOW - timedelta(minutes=ago_minutes)).isoformat().replace(
        "+00:00", "Z")
    return BoardTask(
        id=tid, title=title, notes="", tag=tag, metadata={},
        claimed=claimed, state=state, created_at=touched, updated_at=touched,
    )


def board(*tasks, lanes=None):
    return BoardSnapshot(
        id="b1", name="n", handle="h", repo="WolffM/tenhands",
        mode="automation", lanes=LANES if lanes is None else lanes,
        tasks=list(tasks), schema_id="autoland", schema_version=1,
        access="contributor", version=1,
    )


def pick(*tasks, **kw):
    return choose(board(*tasks), now=NOW, **kw)


# ── serialisation: one in flight per board ────────────────────────────────


def test_claimed_task_blocks_everything_else():
    """Several tasks on a board routinely touch the same files, and after a
    merge the lock is held through the prod watch window so a red signal can
    be attributed. So a live claim blocks even an approved task."""
    d = pick(task("t1", "working", claimed=True), task("t2", "approved"))
    assert isinstance(d, Idle)
    assert "t1 is in flight" in d.reason


def test_idle_reason_distinguishes_blocked_from_empty():
    """A stuck-looking board needs to say which kind of stuck it is."""
    assert "in flight" in pick(task("t1", "working", claimed=True)).reason
    assert pick().reason == "nothing waiting"


def test_non_automation_board_is_idle():
    d = choose(board(task("t1"), lanes=[]), now=NOW)
    assert isinstance(d, Idle) and "not an automation board" in d.reason


# ── recovery outranks everything ──────────────────────────────────────────


def test_stranded_agent_lane_task_is_recovered_first():
    """A crashed run leaves the task in our lane with an expired claim.
    hadoku-task deliberately never routes it anywhere, so nobody else will
    pick it up."""
    d = pick(task("t1", "approved"), task("t2", "working", claimed=False))
    assert isinstance(d, Pickup)
    assert (d.task.id, d.job, d.lane, d.is_recovery) == (
        "t2", JOB_IMPLEMENT, "working", True)
    assert "crashed" in d.reason


def test_recovery_resumes_in_the_same_lane_not_a_fresh_start():
    d = pick(task("t1", "landing"))
    assert isinstance(d, Pickup)
    assert d.lane == LANE_LANDING and d.is_recovery


def test_recovery_from_planning_runs_the_plan_job():
    d = pick(task("t1", "planning"))
    assert isinstance(d, Pickup)
    assert (d.job, d.lane) == (JOB_PLAN, LANE_PLANNING)


def test_claimed_agent_lane_task_is_in_flight_not_recoverable():
    """The distinction is the claim flag, not the lane — which is exactly
    why we asked hadoku-task for a per-task `claimed` boolean."""
    d = pick(task("t1", "working", claimed=True))
    assert isinstance(d, Idle)


# ── lane priority ─────────────────────────────────────────────────────────


def test_approved_outranks_replan_and_inbox():
    """Drain before filling: the approved task is closest to landing."""
    d = pick(task("t1", ""), task("t2", "replan"), task("t3", "approved"))
    assert isinstance(d, Pickup)
    assert (d.task.id, d.job, d.lane) == ("t3", JOB_IMPLEMENT, LANE_WORKING)


def test_replan_outranks_inbox():
    d = pick(task("t1", ""), task("t2", "replan"))
    assert isinstance(d, Pickup)
    assert (d.task.id, d.job, d.lane) == ("t2", JOB_PLAN, LANE_PLANNING)


def test_inbox_is_planned_when_nothing_else_waits():
    d = pick(task("t1", ""))
    assert isinstance(d, Pickup)
    assert (d.job, d.lane, d.is_recovery) == (JOB_PLAN, LANE_PLANNING, False)


def test_oldest_first_within_a_lane():
    d = pick(task("new", "approved", ago_minutes=5),
             task("old", "approved", ago_minutes=500))
    assert d.task.id == "old"


@pytest.mark.parametrize("lane", ["plan-review", "landed", "stalled"])
def test_human_resting_lanes_are_never_claimed(lane):
    """These mean 'a human is expected to act'. Claiming from them would
    take the decision away from them."""
    d = pick(task("t1", lane))
    assert isinstance(d, Idle) and d.reason == "nothing waiting"


# ── archived tasks ────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", ["Completed", "Deleted"])
def test_archived_tasks_are_never_picked_up(state):
    """`complete: true` on release archives a task, but it still comes back
    in the board read — so an unfiltered runner would re-plan its own
    finished work forever."""
    d = pick(task("t1", "approved", state=state))
    assert isinstance(d, Idle)


def test_archived_task_does_not_count_as_in_flight():
    d = pick(task("gone", "working", claimed=True, state="Deleted"),
             task("t2", "approved"))
    assert isinstance(d, Pickup) and d.task.id == "t2"


# ── settle delay on the Inbox ─────────────────────────────────────────────


def test_freshly_captured_inbox_task_waits():
    """Planning at a sentence still being typed wastes a round trip and
    looks unnervingly eager.

    `ago_minutes=0`, not 1: the settle window is one minute, so a task edited
    a minute ago is settled by definition. This has to be a task touched *now*
    to still be testing anything.
    """
    d = pick(task("t1", "", ago_minutes=0))
    assert isinstance(d, Idle) and "settling" in d.reason


def test_inbox_task_is_picked_up_once_settled():
    d = pick(task("t1", "", ago_minutes=6))
    assert isinstance(d, Pickup) and d.task.id == "t1"


def test_settle_boundary_is_inclusive():
    d = pick(task("t1", "", ago_minutes=int(
        DEFAULT_SETTLE.total_seconds() // 60)))
    assert isinstance(d, Pickup)


def test_settle_window_is_configurable():
    t = task("t1", "", ago_minutes=2)
    assert isinstance(choose(board(t), now=NOW, settle=timedelta(minutes=5)), Idle)
    assert isinstance(choose(board(t), now=NOW, settle=timedelta(minutes=1)), Pickup)


def test_settling_task_does_not_hide_a_ready_one():
    d = pick(task("fresh", "", ago_minutes=1), task("ready", "", ago_minutes=90))
    assert isinstance(d, Pickup) and d.task.id == "ready"


def test_settle_does_not_apply_to_lanes_a_human_moved_it_to():
    """Dragging a task to `approved` IS the human saying go; making them
    then wait five minutes would be nonsense."""
    d = pick(task("t1", "approved", ago_minutes=0))
    assert isinstance(d, Pickup) and d.task.id == "t1"


def test_task_without_timestamps_is_treated_as_settled():
    """Never planning is a worse failure than planning slightly early."""
    t = BoardTask(id="t1", title="x", notes="", tag="", metadata={},
                  claimed=False, state="Active", created_at="", updated_at="")
    assert isinstance(pick(t), Pickup)


def test_unparseable_timestamp_is_treated_as_settled():
    t = BoardTask(id="t1", title="x", notes="", tag="", metadata={},
                  claimed=False, state="Active", created_at="not-a-date",
                  updated_at="")
    assert isinstance(pick(t), Pickup)


def test_updated_at_wins_over_created_at_for_settling():
    """An old task edited seconds ago is being worked on right now."""
    t = BoardTask(
        id="t1", title="x", notes="", tag="", metadata={}, claimed=False,
        state="Active",
        created_at=(NOW - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
        updated_at=(NOW - timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
    )
    assert isinstance(pick(t), Idle)


# ── malformed lanes ───────────────────────────────────────────────────────


def test_task_with_two_lane_tags_is_not_picked_up_but_is_reported():
    """It resolves to no lane at all, and it isn't untagged either, so it is
    invisible to every branch. Reporting "nothing waiting" would be the
    least useful true statement available — it would sit stuck forever."""
    d = pick(task("t1", "approved working"))
    assert isinstance(d, Idle)
    assert "unusable lane tag" in d.reason and "t1" in d.reason


def test_a_stuck_task_does_not_mask_claimable_work():
    d = pick(task("bad", "approved working"), task("good", "approved"))
    assert isinstance(d, Pickup) and d.task.id == "good"


def test_plain_non_lane_tags_are_not_reported_as_malformed():
    """A task tagged only `urgent` is ordinary Inbox capture, not broken."""
    d = pick(task("t1", "urgent", ago_minutes=90))
    assert isinstance(d, Pickup)


def test_extra_non_lane_tags_do_not_block_pickup():
    d = pick(task("t1", "urgent approved"))
    assert isinstance(d, Pickup) and d.task.id == "t1"
