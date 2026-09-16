"""Tests for temporal/taskauto/selection.py.

Selection is pure policy, so these are the tests that actually pin the
pipeline's judgement calls. Under autoland v3 those are: one task in flight
per REPO rather than per board, a crashed run outranks new work, an approval
tick is the only thing that authorises implementing, and the Inbox waits for
someone to stop typing before anyone reads at them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.task_board import BoardSnapshot, BoardTask, Lane, TaskStatus
from temporal.taskauto import plan_notes
from temporal.taskauto.plan_notes import APPROVAL_ITEM, PlanDoc
from temporal.taskauto.selection import (
    DEFAULT_SETTLE,
    Idle,
    JOB_IMPLEMENT,
    JOB_PLAN,
    JOB_ROUTE,
    Pickup,
    blocked,
    choose,
    choose_unrouted,
    done,
    human_verdict,
    malformed_note,
    waiting,
    working,
)

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

CONJURE = "hadoku-conjure"
AGGREGATOR = "hadoku-aggregator"

LANES = [
    Lane(CONJURE, "Conjure", 0, "user", repo="WolffM/hadoku-conjure"),
    Lane(AGGREGATOR, "Aggregator", 1, "user", repo="WolffM/hadoku-aggregator"),
]

#: A v2 lane set — states, no repos. Used to pin that v3 code declines to
#: drive one rather than misreading `planning` as a repo.
V2_LANES = [
    Lane("planning", "Planning", 0, "agent"),
    Lane("approved", "Approved", 1, "user"),
]


def task(tid, tag="", *, claimed=False, state="Active", ago_minutes=60,
         title="a task", notes="", status=None):
    touched = (NOW - timedelta(minutes=ago_minutes)).isoformat().replace(
        "+00:00", "Z")
    return BoardTask(
        id=tid, title=title, notes=notes, tag=tag, metadata={},
        claimed=claimed, state=state, created_at=touched, updated_at=touched,
        status=status,
    )


def board(*tasks, lanes=None):
    return BoardSnapshot(
        id="b1", name="n", handle="h", repo="", mode="automation",
        lanes=LANES if lanes is None else lanes, tasks=list(tasks),
        schema_id="autoland", schema_version=3, access="contributor",
        version=1)


def pick(*tasks, lane=CONJURE, **kw):
    return choose(board(*tasks), lane, now=NOW, **kw)


# Notes shaped the way the plan job actually renders them, so these tests
# exercise the real documents rather than a convenient approximation.
PLAN_AWAITING_SIGNOFF = plan_notes.render(PlanDoc(
    understanding="Cache the lookups.", plan=["Add a TTL."],
    acceptance=["The second call is a hit."], needs_approval=True))
PLAN_SIGNED_OFF = PLAN_AWAITING_SIGNOFF.replace(
    APPROVAL_ITEM, "- [x] Approve this plan")
PLAN_WITH_QUESTIONS = plan_notes.render(PlanDoc(
    understanding="Cache the lookups.", questions=["Negative lookups too?"]))
PLAN_ANSWERED = PLAN_WITH_QUESTIONS.replace(
    "— pass 1", "Yes, those too.\n\n— pass 1")


# ── serialisation: one in flight per REPO ─────────────────────────────────


def test_a_live_claim_blocks_the_rest_of_its_repo():
    """Several tasks in one repo routinely touch the same files, so concurrent
    diffs collide. A live claim blocks even a signed-off plan."""
    d = pick(task("t1", CONJURE, claimed=True),
             task("t2", CONJURE, notes=PLAN_SIGNED_OFF, status=waiting("x")))
    assert isinstance(d, Idle)
    assert "t1 is in flight" in d.reason


def test_a_claim_in_one_repo_does_not_block_another():
    """The whole point of the axis turning. Two repos never share a checkout,
    so serialising across them would be throughput thrown away for nothing."""
    b = board(task("t1", CONJURE, claimed=True),
              task("t2", AGGREGATOR, notes=PLAN_SIGNED_OFF,
                   status=waiting("x")))
    assert isinstance(choose(b, CONJURE, now=NOW), Idle)
    d = choose(b, AGGREGATOR, now=NOW)
    assert isinstance(d, Pickup) and d.task.id == "t2"
    assert d.repo == "WolffM/hadoku-aggregator"


def test_an_unknown_lane_is_not_a_repo_lane():
    assert isinstance(choose(board(), "nope", now=NOW), Idle)


def test_a_v2_lane_set_drives_nothing():
    """`planning` is a lane, not a repo. Reading it as one would claim tasks
    into a checkout that does not exist."""
    b = board(task("t1", "planning"), lanes=V2_LANES)
    assert b.repo_lanes == []
    assert isinstance(choose(b, "planning", now=NOW), Idle)


# ── recovery ──────────────────────────────────────────────────────────────


def test_a_working_task_with_no_claim_is_a_crashed_run():
    d = pick(task("t1", CONJURE, status=working("implementing")))
    assert isinstance(d, Pickup)
    assert d.is_recovery and "crashed" in d.reason


def test_recovery_outranks_new_work():
    d = pick(task("new", CONJURE, ago_minutes=90),
             task("crashed", CONJURE, status=working("planning")))
    assert isinstance(d, Pickup) and d.task.id == "crashed"


def test_a_crashed_implementation_resumes_as_an_implementation():
    """Re-planning would throw away an approval the human already gave."""
    d = pick(task("t1", CONJURE, notes=PLAN_SIGNED_OFF,
                  status=working("implementing")))
    assert isinstance(d, Pickup) and d.job == JOB_IMPLEMENT


def test_a_crashed_planning_pass_resumes_as_planning():
    d = pick(task("t1", CONJURE, notes=PLAN_AWAITING_SIGNOFF,
                  status=working("planning")))
    assert isinstance(d, Pickup) and d.job == JOB_PLAN


# ── what the human did ────────────────────────────────────────────────────


def test_a_ticked_approval_authorises_implementing():
    d = pick(task("t1", CONJURE, notes=PLAN_SIGNED_OFF,
                  status=waiting("plan ready — sign it off")))
    assert isinstance(d, Pickup)
    assert d.job == JOB_IMPLEMENT and d.reason == "approved by human"


def test_an_untouched_plan_waits():
    d = pick(task("t1", CONJURE, notes=PLAN_AWAITING_SIGNOFF,
                  status=waiting("plan ready — sign it off")))
    assert isinstance(d, Idle)


def test_answering_without_ticking_sends_it_back_for_another_pass():
    """The case that must not be read off `questions_answered` alone: they
    replied but did not sign off, so the answer feeds planning — implementing
    here would build a plan nobody approved."""
    replied = PLAN_AWAITING_SIGNOFF.replace(
        "— pass 1", "Actually use a 5 minute TTL.\n\n— pass 1")
    assert plan_notes.questions_answered(replied) is False
    d = pick(task("t1", CONJURE, notes=replied, status=waiting("...")))
    assert isinstance(d, Pickup)
    assert d.job == JOB_PLAN and d.reason == "human answered, re-planning"


def test_answering_a_question_only_plan_re_plans():
    d = pick(task("t1", CONJURE, notes=PLAN_ANSWERED, status=waiting("1 q")))
    assert isinstance(d, Pickup) and d.job == JOB_PLAN


def test_a_plan_that_never_asked_for_approval_is_not_approved():
    """`pending_approval` is None both when it was ticked and when it was
    never asked. Conflating them would implement every plan on sight."""
    assert plan_notes.pending_approval(PLAN_WITH_QUESTIONS) is None
    assert human_verdict(task("t1", CONJURE, notes=PLAN_WITH_QUESTIONS)) is None


# ── terminal states ───────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [
    blocked("a gate said no"),
    done("merged in #42"),
])
def test_terminal_statuses_are_left_for_the_human(status):
    d = pick(task("t1", CONJURE, notes=PLAN_SIGNED_OFF, status=status))
    assert isinstance(d, Idle)


def test_a_task_waiting_on_a_pull_request_is_reconciles_business():
    notes = plan_notes.render(PlanDoc(
        outcome="Opened https://github.com/WolffM/hadoku-conjure/pull/42",
        pass_number=1))
    d = pick(task("t1", CONJURE, notes=notes,
                  status=waiting("PR #42 — yours to merge")))
    assert isinstance(d, Idle)


# ── new work ──────────────────────────────────────────────────────────────


def test_an_unplanned_task_in_a_repo_lane_gets_planned():
    d = pick(task("t1", CONJURE, title="fix the cache"))
    assert isinstance(d, Pickup)
    assert d.job == JOB_PLAN and d.lane == CONJURE
    assert d.repo == "WolffM/hadoku-conjure"


def test_a_freshly_edited_task_settles_first():
    d = pick(task("t1", CONJURE, ago_minutes=0))
    assert isinstance(d, Idle) and "settling" in d.reason


def test_oldest_unplanned_first():
    d = pick(task("new", CONJURE, ago_minutes=5),
             task("old", CONJURE, ago_minutes=500))
    assert isinstance(d, Pickup) and d.task.id == "old"


def test_completed_tasks_are_invisible():
    d = pick(task("t1", CONJURE, state="Completed"))
    assert isinstance(d, Idle)


# ── the Inbox ─────────────────────────────────────────────────────────────


def test_an_untagged_task_is_routed():
    d = choose_unrouted(board(task("t1", title="fix the aggregator")), now=NOW)
    assert isinstance(d, Pickup)
    assert d.job == JOB_ROUTE and d.lane == "" and d.repo == ""


def test_a_tagged_task_is_not_in_the_inbox():
    assert isinstance(choose_unrouted(board(task("t1", CONJURE)), now=NOW), Idle)


def test_the_inbox_settles_too():
    d = choose_unrouted(board(task("t1", ago_minutes=0)), now=NOW)
    assert isinstance(d, Idle) and "settling" in d.reason


def test_a_claimed_inbox_task_is_left_alone():
    d = choose_unrouted(board(task("t1", claimed=True)), now=NOW)
    assert isinstance(d, Idle) and "in flight" in d.reason


def test_routing_needs_repo_lanes():
    b = board(task("t1"), lanes=V2_LANES)
    assert isinstance(choose_unrouted(b, now=NOW), Idle)


def test_settle_is_configurable():
    t = task("t1", ago_minutes=3)
    assert isinstance(choose_unrouted(board(t), now=NOW,
                                      settle=timedelta(minutes=10)), Idle)
    assert isinstance(choose_unrouted(board(t), now=NOW,
                                      settle=timedelta(minutes=1)), Pickup)


# ── the tasks nothing else can see ────────────────────────────────────────


def test_a_task_with_two_lane_tags_is_reported_rather_than_ignored():
    """It resolves to no lane and isn't untagged either, so both `choose` and
    `choose_unrouted` are blind to it. Saying nothing would leave every repo
    reporting 'nothing waiting' while a task sits there forever."""
    b = board(task("t1", f"{CONJURE} {AGGREGATOR}"))
    assert isinstance(choose(b, CONJURE, now=NOW), Idle)
    assert isinstance(choose_unrouted(b, now=NOW), Idle)
    assert "t1" in malformed_note(b)


def test_a_healthy_board_has_no_malformed_note():
    assert malformed_note(board(task("t1", CONJURE))) == ""


def test_a_hand_labelled_tag_is_not_a_lane_tag():
    """A user tag alongside a lane tag is refused by the board on an
    automation board, but a task carrying ONLY a non-lane tag is just Inbox
    capture someone labelled — it must not vanish."""
    b = board(task("t1", "urgent"))
    assert malformed_note(b) == ""
    assert isinstance(choose_unrouted(b, now=NOW), Pickup)


# ── the chip factories ────────────────────────────────────────────────────


def test_every_factory_produces_a_status_the_board_would_accept():
    for status in (working("a"), waiting("b"), blocked("c"), done("d")):
        assert isinstance(status, TaskStatus)
        assert status.to_payload()["kind"] == status.kind


def test_an_href_survives_to_the_payload():
    s = waiting("PR #42", href="https://github.com/o/r/pull/42")
    assert s.to_payload()["href"].endswith("/pull/42")


def test_default_settle_matches_the_dispatch_sleep():
    """`taskauto.yml`'s "Let a fresh capture settle" step waits this long
    before sweeping. Two values that must agree, in two repos."""
    assert DEFAULT_SETTLE == timedelta(minutes=1)
