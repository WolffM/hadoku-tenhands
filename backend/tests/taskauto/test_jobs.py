"""Tests for temporal/taskauto/jobs.py — the plan and implement jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.task_board import BoardSnapshot, BoardTask, Lane
from temporal.taskauto import plan_notes, selection
from temporal.taskauto.agent import AgentError, AgentOutcome
from temporal.taskauto.jobs import make_implement_job, make_plan_job
from temporal.taskauto.landing import LandingRefused, LandResult
from temporal.taskauto.selection import Pickup

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
REPO = "WolffM/hadoku-tenhands"
LANE = "hadoku-tenhands"

#: A v3 lane set: one lane, and it names a repo. The jobs read the repo off
#: the PICKUP rather than the board now, because a board has several.
LANES = [Lane(LANE, "TenHands", 0, "user", repo=REPO)]


def board():
    return BoardSnapshot(id="b", name="n", handle="H", repo="",
                         mode="automation", lanes=LANES, tasks=[],
                         schema_id="autoland", schema_version=3,
                         access="contributor", version=1)


def pickup(title="make coffee theme default", notes="", job="plan"):
    t = BoardTask(id="t1", title=title, notes=notes, tag=LANE, metadata={},
                  claimed=False, state="Active",
                  created_at=NOW.isoformat(), updated_at=NOW.isoformat())
    return Pickup(task=t, job=job, lane=LANE, repo=REPO, reason="test")


class FakeSink:
    def __init__(self): self.chips, self.beats, self.metrics = [], 0, {}
    def status(self, status): self.chips.append(status.kind)
    def heartbeat(self): self.beats += 1
    def record(self, **f):
        for k, v in f.items():
            self.metrics[k] = self.metrics.get(k, 0) + v
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
    status, notes, outcome = job(pickup(), board(), FakeSink())
    assert status.kind == "waiting" and outcome == "plan:ready"
    assert "coffee" in notes.lower()


def test_the_seeded_github_item_reaches_the_planning_prompt():
    """The whole fix. Planning holds no `gh` and no token by design, so the
    item it was seeded from has to be fetched by the parent and handed over —
    otherwise all it ever sees is the board's 280-character preview."""
    agent = FakeAgent(answer=GOOD_PLAN)
    job = make_plan_job(agent, FakeCheckouts(),
                        hydrate=lambda repo, title: f"ITEM({repo}/{title})")
    job(pickup("Address PR #21"), board(), FakeSink())
    assert f"ITEM({REPO}/Address PR #21)" in agent.asked[0]


def test_a_task_with_no_github_item_gets_no_item_block():
    agent = FakeAgent(answer=GOOD_PLAN)
    job = make_plan_job(agent, FakeCheckouts(), hydrate=lambda repo, title: "")
    job(pickup(), board(), FakeSink())
    assert "SEEDED FROM" not in agent.asked[0]


def test_planning_is_told_not_to_invent_a_reason_for_the_task():
    """A bare `Address PR #21` states no intent, and an agent handed a bare
    imperative supplies one — it wrote plan steps against a review backlog
    that did not exist."""
    agent = FakeAgent(answer=GOOD_PLAN)
    make_plan_job(agent, FakeCheckouts(), hydrate=lambda r, t: "")(
        pickup("Address PR #21"), board(), FakeSink())
    assert "Do not invent a reason" in agent.asked[0]
    assert "paste back what is already in front of you" in agent.asked[0]


def test_open_questions_go_to_plan_review():
    agent = FakeAgent(answer=GOOD_PLAN.replace(
        "_No open questions._", "1. Which shade of coffee?"))
    status, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup(), board(), FakeSink())
    assert status.kind == "waiting" and outcome == "plan:questions"
    assert "Which shade" in notes


def test_a_plan_without_an_acceptance_check_asks_how_wed_know():
    """G2. Without one there is nothing to verify and 'lands on green' would
    be an empty phrase."""
    agent = FakeAgent(answer=GOOD_PLAN.replace(
        "- the default theme resolves to coffee", "_none_"))
    status, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup("too much wooshing"), board(), FakeSink())
    assert outcome == "plan:unverifiable"
    assert "how would you tell me" in notes.lower()


def test_already_done_is_reported_never_concluded():
    """The pipeline may never decide a task is garbage on its own."""
    agent = FakeAgent(answer=(
        "## What I think you want\n\nThis is already done.\n\n"
        "## Plan\n\n_none_\n\n## Questions\n\n_No open questions._\n"))
    status, notes, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup(), board(), FakeSink())
    assert status.kind == "waiting"
    assert outcome == "plan:no-action-proposed"


def test_an_unreadable_reply_is_not_a_verdict_of_already_done():
    """`parse` never raises, so a reply that is not one of our documents came
    back as an empty PlanDoc and fell into `no-action-proposed` — telling a
    human "this looks already done" on the strength of output we could not
    read. That is how a revoked credential's 401 reached a board on
    2026-08-08. Refuse to conclude anything instead."""
    agent = FakeAgent(answer="Failed to authenticate. API Error: 401 OAuth "
                             "access token has been revoked.")
    with pytest.raises(AgentError):
        make_plan_job(agent, FakeCheckouts())(pickup(), board(), FakeSink())


def test_prose_with_no_headings_is_rejected_even_when_it_sounds_fine():
    """Not just error strings — anything that ignored the output contract."""
    agent = FakeAgent(answer="Sure! I had a look and it all seems done already.")
    with pytest.raises(AgentError):
        make_plan_job(agent, FakeCheckouts())(pickup(), board(), FakeSink())


def test_one_recognised_heading_is_enough_to_be_read_as_a_document():
    """The check is "did the agent answer in our format", not "is the answer
    complete" — a document proposing nothing is still a document, and
    `no-action-proposed` remains the honest outcome for it."""
    agent = FakeAgent(answer="## What I think you want\n\nNothing to do here.\n")
    status, _, outcome = make_plan_job(agent, FakeCheckouts())(
        pickup(), board(), FakeSink())
    assert status.kind == "waiting"
    assert outcome == "plan:no-action-proposed"


# ── a stall must not destroy the plan it stalled on ───────────────────────
#
# Both stall paths built a FRESH PlanDoc, so the approved plan vanished from
# `notes` — the only place it lives. `implement_job` opens with
# `if not doc.plan: -> LANE_REPLAN`, so re-approving a stalled task silently
# restarted the whole planning conversation. On the `meet` task that would
# have discarded 266s of planning across three passes over one refused file.


def _approved(plan=("step one", "step two")):
    doc = plan_notes.PlanDoc(understanding="u", plan=list(plan),
                             acceptance=["it works"], pass_number=3)
    return pickup(notes=plan_notes.render(doc), job="implement")


def test_a_refused_landing_keeps_the_plan():
    lander = FakeLander(raises=LandingRefused(
                              "protected paths touched without "
                              "`allow-protected:` authorisation: .devvault.json"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[".devvault.json"]))
    status, notes, outcome = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "land:refused"
    assert plan_notes.parse(notes).plan == ["step one", "step two"]


def test_re_approving_a_refused_task_rebuilds_instead_of_replanning():
    """The whole point: the obvious human gesture has to work."""
    lander = FakeLander(raises=LandingRefused(
                              "protected paths touched without "
                              "`allow-protected:` authorisation: .devvault.json"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[".devvault.json"]))
    _, notes, _ = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())

    # The human drags it back to `approved` unchanged. It must implement, not
    # bounce to `replan` for a fresh planning conversation.
    status2, _, outcome2 = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.py"])),
        FakeCheckouts(), FakeLander())(
        pickup(notes=notes, job="implement"), board(), FakeSink())
    assert outcome2 != "implement:no-plan"
    assert status2.kind != "waiting"


def test_a_refusal_explains_itself_without_naming_an_incantation():
    """The override needs an exact string in the task title, months after you
    last read about it. Advertising it made the note longer and no more
    actionable. Say what the refusal MEANS instead."""
    lander = FakeLander(raises=LandingRefused(
        "protected paths touched: .devvault.json"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[".devvault.json"]))
    _, notes, _ = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())
    assert "allow-protected" not in notes
    assert "cannot be undone by a revert" in notes
    assert "needs a human" in notes


def test_the_gate_itself_does_not_advertise_the_override():
    """The refusal string is user-facing; it reaches the board verbatim."""
    from temporal.taskauto.landing import Lander
    from temporal.taskauto.refs import RepoPolicy, TaskRef
    task = TaskRef(repo_slug="WolffM/x", board="b", task_id="t",
                   title="add a thing", notes_at_claim="", policy=RepoPolicy())
    with pytest.raises(LandingRefused) as e:
        Lander(dry_run=True).preflight(task, [".github/workflows/deploy.yml"])
    assert "allow-protected" not in str(e.value)
    assert ".github/workflows/deploy.yml" in str(e.value)


def test_the_plan_leads_and_the_refusal_trails():
    """A task whose plan was fine must not read as though the plan were the
    problem — the failure is a fact ABOUT the document, not the document."""
    lander = FakeLander(raises=LandingRefused("protected paths touched: x"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["x"]))
    _, notes, _ = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())
    assert notes.index("## Plan") < notes.index("NOT LANDED")
    # ...and the footer still ends the document.
    assert notes.rstrip().endswith("— pass 3")


def test_a_refusal_carries_the_agents_own_account():
    lander = FakeLander(raises=LandingRefused("blast radius: 40 files changed, cap is 20"))
    agent = FakeAgent(outcome=AgentOutcome(
        changed_files=["a.py"], log="I rewrote the whole module."))
    _, notes, _ = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())
    assert "I rewrote the whole module." in notes
    assert "max_files_changed" in notes  # the remedy for THIS refusal


def test_no_changes_also_keeps_the_plan_and_the_agents_words():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[],
                                           log="Nothing to do; already done."))
    status, notes, outcome = make_implement_job(agent, FakeCheckouts(), FakeLander())(
        _approved(), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "implement:no-changes"
    assert plan_notes.parse(notes).plan == ["step one", "step two"]
    assert "Nothing to do; already done." in notes


def test_the_stall_note_does_not_reset_the_pass_number():
    """`pass 1` on a third-pass task reads as a fresh conversation and would
    hand the planning loop two extra rounds if it ever went back."""
    lander = FakeLander(raises=LandingRefused("nope"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.py"]))
    _, notes, _ = make_implement_job(agent, FakeCheckouts(), lander)(
        _approved(), board(), FakeSink())
    assert plan_notes.parse(notes).pass_number == 3


def test_the_pass_cap_stalls_rather_than_asking_again():
    prior = plan_notes.render(plan_notes.PlanDoc(
        plan=["x"], questions=["again?"],
        pass_number=plan_notes.MAX_PASSES))
    status, notes, outcome = make_plan_job(FakeAgent(answer=GOOD_PLAN),
                                         FakeCheckouts())(
        pickup(notes=prior), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "plan:cap-reached"
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
    assert co.calls == [(REPO, "main")]


# ── implement job ─────────────────────────────────────────────────────────


def approved(notes=GOOD_PLAN):
    return pickup(notes=notes, job="implement")


def test_a_successful_landing_reports_landed_with_the_sha():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["src/themes.ts"]))
    status, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert status.kind == "done"
    assert outcome == "landed:abc12345"


def test_a_dry_run_blocks_rather_than_claiming_success():
    """`blocked`, not `waiting`, and the difference is load-bearing.

    Nothing is wrong with the change — but nothing a human writes in the notes
    can advance it either; only arming TASKAUTO_LIVE can. A `waiting` chip on
    an already-signed-off plan is re-read as "approved, go" on the very next
    sweep, so a dry run would rebuild the same change forever."""
    lander = FakeLander(LandResult(False, "abc12345", "b", "dry run", ["ok"]))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    status, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), lander)(approved(), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "dry-run"
    assert "NOT pushed" in notes


def test_an_agent_that_changed_nothing_stalls_with_what_it_said():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=[], log="I declined."))
    status, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "implement:no-changes"
    assert "I declined." in notes


def test_a_refused_landing_stalls_with_the_gate_reason():
    lander = FakeLander(raises=LandingRefused("suite failed on the merge result"))
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    status, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), lander)(approved(), board(), FakeSink())
    assert status.kind == "blocked" and outcome == "land:refused"
    assert "suite failed" in notes


def test_what_the_human_added_reaches_the_implementer():
    """Answering a question and dragging straight to `approved` — skipping
    `replan` — must not lose the answer.

    `render` emits only the sections the pipeline controls, so a plan is
    re-rendered without the human's own words. The planning path was never
    exposed to this (it forwards raw notes), which is exactly why the approve
    path could drop them unnoticed: a human writes an instruction, watches the
    agent implement the plan without it, and has no way to tell that their
    sentence was never read.
    """
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    amended = GOOD_PLAN + "\n\nalso update the tooltip, and do NOT touch Bar.tsx"
    make_implement_job(agent, FakeCheckouts(), FakeLander())(
        approved(notes=amended), board(), FakeSink())
    assert "also update the tooltip" in agent.worked[0]
    assert "do NOT touch Bar.tsx" in agent.worked[0]
    assert "amending the plan" in agent.worked[0], \
        "it has to be labelled, or the agent reads it as part of its own plan"


def test_an_unamended_plan_adds_no_human_block():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    make_implement_job(agent, FakeCheckouts(), FakeLander())(
        approved(), board(), FakeSink())
    assert "WHAT THE HUMAN WROTE" not in agent.worked[0]


def test_implementing_without_a_plan_routes_where_it_will_be_planned():
    """Approved before it was planned — a task dragged straight from the Inbox.

    v2 put it in `replan`, a lane the pipeline claims from. There are no
    state lanes now, so the same job is done by the SHAPE of the note: a
    `waiting` chip plus text below the document, which `plan_notes.parse`
    surfaces as `human_text` and `selection.human_verdict` reads as "they
    answered, plan it again".

    It used to go to `plan-review`, which the pipeline never touched, and ask
    "should this go back through planning?" — a question that could not be
    answered by answering it, on a task nothing would ever pick up again. The
    assertion below is the guard against regressing to that: whatever the note
    says, selection has to be willing to pick the task up.
    """
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a"]))
    status, notes, outcome = make_implement_job(
        agent, FakeCheckouts(), FakeLander())(
        approved(notes="just a raw thought"), board(), FakeSink())
    assert status.kind == "waiting" and outcome == "implement:no-plan"

    parked = BoardTask(id="t1", title="t", notes=notes, tag=LANE, metadata={},
                       claimed=False, state="Active", status=status)
    assert selection.human_verdict(parked) == selection.JOB_PLAN, \
        "selection has to be willing to plan the task this note produces"
    assert "Nothing is needed from you" in notes
    assert "?" not in notes.split("## Questions")[-1] or "_No open questions._" in notes
    assert agent.worked == [], "must not run the agent when there is no plan"


def test_the_task_is_moved_to_landing_before_the_push():
    sink = FakeSink()
    make_implement_job(FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
                       FakeCheckouts(), FakeLander())(approved(), board(), sink)
    assert "working" in sink.chips


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
    status, notes, outcome = job(approved(), board(), FakeSink())
    assert status.kind == "done" and outcome.startswith("landed:")
    assert "stayed healthy" in notes


def test_a_red_prod_is_reverted_and_stalled():
    """The property that makes unreviewed landing acceptable at all."""
    rev = FakeReverter()
    job = _implement(watcher=FakeWatcher(False, "deploy concluded failure"),
                     reverter=rev)
    status, notes, outcome = job(approved(), board(), FakeSink())
    assert status.kind == "blocked"
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
    status, notes, outcome = job(approved(), board(), FakeSink())
    assert status.kind == "blocked"
    assert outcome == "landed:unwatched-red"
    assert "NOT taken back" in notes


def test_landing_with_no_watcher_at_all_is_recorded():
    status, notes, outcome = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
        FakeCheckouts(), FakeLander())(approved(), board(), FakeSink())
    assert status.kind == "done"
    assert "NO PROD WATCHER" in notes


def test_a_dry_run_never_watches_or_reverts():
    w, rev = FakeWatcher(False), FakeReverter()
    job = make_implement_job(
        FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"])),
        FakeCheckouts(),
        FakeLander(LandResult(False, "abc", "b", "dry run", ["ok"])),
        watcher=w, reverter=rev, health_url="http://h")
    status, _, outcome = job(approved(), board(), FakeSink())
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
    status, notes, outcome = make_implement_job(agent, co, FakeLander())(
        approved(), board(), FakeSink())
    assert status.kind == "done"
    assert outcome == "recovered:cafe1234"
    assert agent.worked == [], "must not run the agent again"


def test_a_task_not_on_main_proceeds_normally():
    agent = FakeAgent(outcome=AgentOutcome(changed_files=["a.ts"]))
    co = GitCheckouts(landed_subject=None)
    status, _, outcome = make_implement_job(agent, co, FakeLander())(
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
