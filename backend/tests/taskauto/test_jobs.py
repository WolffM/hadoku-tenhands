"""Tests for temporal/taskauto/jobs.py — the plan and implement jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.task_board import BoardSnapshot, BoardTask, Lane
from temporal.taskauto import plan_notes, selection
from temporal.taskauto.agent import AgentOutcome
from temporal.taskauto.jobs import make_implement_job, make_plan_job
from temporal.taskauto.landing import LandingRefused, LandResult
from temporal.taskauto.selection import Pickup

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
LANES = [Lane("planning", "P", 0, "agent"), Lane("plan-review", "PR", 0, "user"),
         Lane("replan", "R", 1, "user"), Lane("approved", "A", 2, "user"),
         Lane("working", "W", 3, "agent"), Lane("landing", "L", 4, "agent"),
         Lane("landed", "D", 5, "user"), Lane("stalled", "S", 6, "user")]


def board():
    return BoardSnapshot(id="b", name="n", handle="H", repo="WolffM/tenhands",
                         mode="automation", lanes=LANES, tasks=[],
                         schema_id="autoland", schema_version=1,
                         access="contributor", version=1)


def pickup(title="make coffee theme default", notes="", job="plan"):
    t = BoardTask(id="t1", title=title, notes=notes, tag="", metadata={},
                  claimed=False, state="Active",
                  created_at=NOW.isoformat(), updated_at=NOW.isoformat())
    return Pickup(task=t, job=job, lane="planning", reason="test")


class FakeSink:
    def __init__(self): self.lanes, self.beats = [], 0
    def lane(self, lane): self.lanes.append(lane)
    def heartbeat(self): self.beats += 1
    def finish(self, *a, **k): pass


class FakeAgent:
    def __init__(self, answer="", outcome=None):
        self.answer, self.outcome = answer, outcome
        self.asked, self.worked = [], []

    def ask(self, checkout, prompt, timeout_s=None):
        self.asked.append(prompt)
        return self.answer

    def work(self, checkout, prompt):
        self.worked.append(prompt)
        return self.outcome or AgentOutcome()


class FakeCheckouts:
    def __init__(self): self.calls = []
    def reset_to(self, repo, base): self.calls.append((repo, base)); return Path("/co")


class FakeLander:
    def __init__(self, result=None, raises=None):
        self.result, self.raises = result, raises
        self.calls = []

    def land(self, checkout, task, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        return self.result or LandResult(True, "abc12345", "b", "landed",
                                         ["suite green"])


GOOD_PLAN = """\
## What I think you want

Coffee should be the default theme.

## Plan

1. Change the default in the theme config

## Questions

_No open questions._

## How we'll know it worked

- the default theme resolves to coffee

## Blast radius

- src/themes.ts
"""


# ── plan job ──────────────────────────────────────────────────────────────


def test_a_clean_plan_goes_to_plan_review_for_a_human():
    agent = FakeAgent(answer=GOOD_PLAN)
    job = make_plan_job(agent, FakeCheckouts())
    lane, notes, outcome = job(pickup(), board(), FakeSink())
    assert lane == selection.LANE_PLAN_REVIEW and outcome == "plan:ready"
    assert "coffee" in notes.lower()


def test_open_questions_go_to_plan_review():
    agent = FakeAgent(answer=GOOD_PLAN.replace(
        "_No open questions._", "1. Which shade of coffee?"))
    lane, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup(), board(), FakeSink())
    assert lane == selection.LANE_PLAN_REVIEW and outcome == "plan:questions"
    assert "Which shade" in notes


def test_a_plan_without_an_acceptance_check_asks_how_wed_know():
    """G2. Without one there is nothing to verify and 'lands on green' would
    be an empty phrase."""
    agent = FakeAgent(answer=GOOD_PLAN.replace(
        "- the default theme resolves to coffee", "_none_"))
    lane, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup("too much wooshing"), board(), FakeSink())
    assert outcome == "plan:unverifiable"
    assert "how would you tell me" in notes.lower()


def test_already_done_is_reported_never_concluded():
    """The pipeline may never decide a task is garbage on its own."""
    agent = FakeAgent(answer=(
        "## What I think you want\n\nThis is already done.\n\n"
        "## Plan\n\n_none_\n\n## Questions\n\n_No open questions._\n"))
    lane, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup(), board(), FakeSink())
    assert lane == selection.LANE_PLAN_REVIEW
    assert outcome == "plan:no-action-proposed"


def test_the_pass_cap_stalls_rather_than_asking_again():
    prior = plan_notes.render(plan_notes.PlanDoc(
        plan=["x"], questions=["again?"],
        pass_number=plan_notes.MAX_PASSES))
    lane, notes, outcome = make_plan_job(FakeAgent(answer=GOOD_PLAN),
                                         FakeCheckouts())(
        pickup(notes=prior), board(), FakeSink())
    assert lane == selection.LANE_STALLED and outcome == "plan:cap-reached"
    assert "laptop" in notes


def test_a_first_plan_is_pass_one():
    """Raw capture parses to pass_number 1, so incrementing unconditionally
    labelled the first plan 'pass 2' and burned a round off the cap before
    the conversation had even started."""
    _, notes, _ = make_plan_job(FakeAgent(answer=GOOD_PLAN), FakeCheckouts())(
        pickup(notes=""), board(), FakeSink())
    assert plan_notes.parse(notes).pass_number == 1


def test_the_pass_number_increments_and_settled_answers_survive():
    prior = plan_notes.render(plan_notes.PlanDoc(
        plan=["x"], settled=[("Which repo?", "tenhands")], pass_number=1))
    _, notes, _ = make_plan_job(FakeAgent(answer=GOOD_PLAN), FakeCheckouts())(
        pickup(notes=prior), board(), FakeSink())
    doc = plan_notes.parse(notes)
    assert doc.pass_number == 2
    assert ("Which repo?", "tenhands") in doc.settled


def test_the_humans_reply_is_shown_to_the_planner():
    agent = FakeAgent(answer=GOOD_PLAN)
    make_plan_job(agent, FakeCheckouts())(
        pickup(notes="actually use mocha not coffee"), board(), FakeSink())
    assert "actually use mocha not coffee" in agent.asked[0]


def test_a_bug_is_described_to_the_planner_as_a_bug():
    agent = FakeAgent(answer=GOOD_PLAN)
    make_plan_job(agent, FakeCheckouts())(
        pickup("bug-wooshing starts early"), board(), FakeSink())
    assert "claims something is broken" in agent.asked[0]


def test_planning_resets_the_checkout_first():
    co = FakeCheckouts()
    make_plan_job(FakeAgent(answer=GOOD_PLAN), co)(pickup(), board(), FakeSink())
    assert co.calls == [("WolffM/tenhands", "main")]


# ── implement job ─────────────────────────────────────────────────────────


def approved(notes=GOOD_PLAN):
    return pickup(notes=notes, job="implement")


def test_a_successful_landing_reports_landed_with_the_sha():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["src/themes.ts"]))
    lane, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert lane == selection.LANE_LANDED
    assert outcome == "landed:abc12345"


def test_a_dry_run_parks_in_plan_review_rather_than_claiming_success():
    lander = FakeLander(LandResult(False, "abc12345", "b", "dry run", ["ok"]))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    lane, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), lander)(approved(), board(), FakeSink())
    assert lane == selection.LANE_PLAN_REVIEW and outcome == "dry-run"
    assert "NOT pushed" in notes


def test_an_agent_that_changed_nothing_stalls_with_what_it_said():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[], log="I declined."))
    lane, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert lane == selection.LANE_STALLED and outcome == "implement:no-changes"
    assert "I declined." in notes


def test_a_refused_landing_stalls_with_the_gate_reason():
    lander = FakeLander(raises=LandingRefused("suite failed on the merge result"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    lane, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), lander)(approved(), board(), FakeSink())
    assert lane == selection.LANE_STALLED and outcome == "land:refused"
    assert "suite failed" in notes


def test_implementing_without_a_plan_goes_back_to_the_human():
    lane, _, outcome = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a"])),
        FakeCheckouts(), FakeLander())(
        approved(notes="just a raw thought"), board(), FakeSink())
    assert lane == selection.LANE_PLAN_REVIEW and outcome == "implement:no-plan"


def test_the_task_is_moved_to_landing_before_the_push():
    sink = FakeSink()
    make_implement_job(FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
                       FakeCheckouts(), FakeLander())(approved(), board(), sink)
    assert selection.LANE_LANDING in sink.lanes


def test_the_test_command_is_passed_through_to_the_lander():
    lander = FakeLander()
    make_implement_job(FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
                       FakeCheckouts(), lander,
                       test_command=["pytest", "-q"])(
        approved(), board(), FakeSink())
    assert lander.calls[0]["test_command"] == ["pytest", "-q"]


def test_the_agent_is_told_not_to_touch_git():
    """The pipeline owns committing; an agent that commits or pushes would
    bypass every landing gate."""
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    make_implement_job(agent, FakeCheckouts(), FakeLander())(
        approved(), board(), FakeSink())
    assert "Do NOT commit" in agent.worked[0]


def test_heartbeats_happen_around_the_long_agent_call():
    """The heartbeat is the only channel a human cancel arrives through."""
    sink = FakeSink()
    make_implement_job(FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
                       FakeCheckouts(), FakeLander())(approved(), board(), sink)
    assert sink.beats >= 2


# ── the prod watcher, wired into landing ──────────────────────────────────


class FakeWatcher:
    def __init__(self, healthy=True, reason="ok"):
        from temporal.taskauto.watch import WatchResult
        self.result = WatchResult(healthy, reason)
        self.calls = []

    def watch(self, repo, sha, **kw):
        self.calls.append((repo, sha, kw))
        return self.result


class FakeReverter:
    def __init__(self, raises=None):
        self.raises, self.calls = raises, []

    def revert(self, checkout, sha, base="main"):
        self.calls.append(sha)
        if self.raises:
            raise self.raises
        return "revert99abc"


def _implement(**kw):
    return make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
        FakeCheckouts(), FakeLander(), health_url="http://h", **kw)


def test_a_healthy_landing_reports_landed():
    job = _implement(watcher=FakeWatcher(True, "deploy success, health ok"))
    lane, notes, outcome = job(approved(), board(), FakeSink())
    assert lane == selection.LANE_LANDED and outcome.startswith("landed:")
    assert "stayed healthy" in notes


def test_a_red_prod_is_reverted_and_stalled():
    """The property that makes unreviewed landing acceptable at all."""
    rev = FakeReverter()
    job = _implement(watcher=FakeWatcher(False, "deploy concluded failure"),
                     reverter=rev)
    lane, notes, outcome = job(approved(), board(), FakeSink())
    assert lane == selection.LANE_STALLED
    assert outcome.startswith("reverted:")
    assert rev.calls == ["abc12345"]
    assert "REVERTED as revert99" in notes


def test_the_revert_reason_is_carried_back_to_the_human():
    job = _implement(watcher=FakeWatcher(False, "health check failed: HTTP 502"),
                     reverter=FakeReverter())
    _, notes, _ = job(approved(), board(), FakeSink())
    assert "HTTP 502" in notes


def test_red_prod_with_no_reverter_says_so_very_loudly():
    """Silence here would report a landing as fine while prod is down."""
    job = _implement(watcher=FakeWatcher(False, "deploy concluded failure"))
    lane, notes, outcome = job(approved(), board(), FakeSink())
    assert lane == selection.LANE_STALLED
    assert outcome == "landed:unwatched-red"
    assert "NOT taken back" in notes


def test_landing_with_no_watcher_at_all_is_recorded():
    lane, notes, outcome = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
        FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert lane == selection.LANE_LANDED
    assert "NO PROD WATCHER" in notes


def test_a_dry_run_never_watches_or_reverts():
    w, rev = FakeWatcher(False), FakeReverter()
    job = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
        FakeCheckouts(),
        FakeLander(LandResult(False, "abc", "b", "dry run", ["ok"])),
        watcher=w, reverter=rev, health_url="http://h")
    lane, _, outcome = job(approved(), board(), FakeSink())
    assert outcome == "dry-run" and w.calls == [] and rev.calls == []


# ── recovery after a crash between push and release ───────────────────────


class GitCheckouts(FakeCheckouts):
    """A checkout manager whose `run` answers `git log --grep`."""

    def __init__(self, landed_subject=None, sha="cafe1234"):
        super().__init__()
        self.landed_subject, self.sha = landed_subject, sha
        self.log_calls = []

    def run(self, args, timeout=60):
        self.log_calls.append(args)

        class R:
            ok = True
            out = (f"{self.sha}\x00{self.landed_subject}\n"
                   if self.landed_subject else "")
        return R()


def test_a_task_already_on_main_is_recovered_not_rebuilt():
    """Observed for real: the runner was killed mid-watch, the commit was
    already on main, and the task sat in `landing`. A naive re-run would
    rebuild shipped work and then stall on 'no changes'."""
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    co = GitCheckouts(landed_subject="make coffee theme default")
    lane, notes, outcome = make_implement_job(agent, co, FakeLander())(
        approved(), board(), FakeSink())
    assert lane == selection.LANE_LANDED
    assert outcome == "recovered:cafe1234"
    assert agent.worked == [], "must not run the agent again"


def test_a_task_not_on_main_proceeds_normally():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    co = GitCheckouts(landed_subject=None)
    lane, _, outcome = make_implement_job(agent, co, FakeLander())(
        approved(), board(), FakeSink())
    assert outcome.startswith("landed:") and agent.worked


def test_a_merely_similar_commit_does_not_count_as_landed():
    """Subject must match exactly — a task title appearing inside some other
    commit's message must not read as already shipped."""
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    co = GitCheckouts(landed_subject="revert: make coffee theme default")
    _, _, outcome = make_implement_job(agent, co, FakeLander())(
        approved(), board(), FakeSink())
    assert outcome.startswith("landed:"), "should have proceeded, not recovered"
