"""Tests for G2 — verification_possible.

The gate that makes "lands on green" mean something, and the one whose
first draft was wrong: it demanded a reproduction from every task, which
would have stalled `make coffee theme default` forever.
"""

from __future__ import annotations

import pytest

from temporal.gates import TASK_AUTOMATION, registry_snapshot, run_gates
from temporal.gates.taskauto.verification import PLAN_PATH, verification_possible
from temporal.taskauto.plan_notes import PlanDoc, render
from temporal.taskauto.refs import TaskRef


class Ev:
    def __init__(self, plan_text="", *, explode=False):
        self.plan_text = plan_text
        self.explode = explode

    def read_text(self, path):
        assert path == PLAN_PATH
        if self.explode:
            raise FileNotFoundError(path)
        return self.plan_text

    def write_json(self, *a, **k):
        pass


def ref(title):
    return TaskRef(repo_slug="WolffM/hadoku_site", board="h1",
                   task_id="t1", title=title)


def check(title, doc):
    return verification_possible(ref(title), Ev(render(doc)))


def plan(**kw):
    kw.setdefault("plan", ["do the thing"])
    kw.setdefault("pass_number", 1)
    return PlanDoc(**kw)


# ── change requests ───────────────────────────────────────────────────────


def test_change_request_with_an_acceptance_check_passes():
    r = check("make coffee theme default",
              plan(acceptance=["the default theme resolves to coffee"]))
    assert r.verdict == "pass"
    assert r.evidence_data["kind"] == "change"


def test_change_request_without_an_acceptance_check_fails():
    r = check("make coffee theme default", plan())
    assert r.verdict == "fail"
    assert "acceptance check" in r.reason


def test_a_change_request_is_never_asked_for_a_reproduction():
    """The category error the first draft made. Nothing is claimed broken,
    so there is no red state to reach."""
    r = check("make coffee theme default",
              plan(acceptance=["default theme is coffee"]))
    assert r.verdict == "pass"
    assert "reproduc" not in r.reason.lower()


@pytest.mark.parametrize("title", [
    "hide 'generating with GLM-5'",
    "need a cancel button",
    "reorganize categories, interesting stuff front and center",
])
def test_real_change_requests_pass_with_an_acceptance_check(title):
    assert check(title, plan(acceptance=["it is so"])).verdict == "pass"


# ── bugs ──────────────────────────────────────────────────────────────────


def test_bug_with_a_reproduction_passes():
    r = check("bug-wooshing starts before music starts",
              plan(acceptance=["wooshing audio starts after music begins"]))
    assert r.verdict == "pass"
    assert r.evidence_data["kind"] == "bug"


def test_bug_without_a_reproduction_fails_and_says_why():
    r = check("bug-animations get stuck and lag", plan())
    assert r.verdict == "fail"
    assert "reproduction" in r.reason
    assert "proves nothing" in r.reason


def test_the_bug_prefix_is_what_switches_the_standard():
    """Same plan, same missing acceptance — but the failure reason differs,
    and so does what the human is being asked for."""
    bug = check("bug-x", plan())
    change = check("x", plan())
    assert bug.verdict == change.verdict == "fail"
    assert "reproduction" in bug.reason
    assert "acceptance check" in change.reason


# ── the unverifiable case ─────────────────────────────────────────────────


def test_a_subjective_task_fails_and_asks_the_right_question():
    """`too much wooshing` has nothing to reproduce AND no statable end
    condition. The gate must send back the one question that unblocks it —
    the same question a human would have to answer before they could review
    the diff themselves."""
    r = check("too much wooshing", plan())
    assert r.verdict == "fail"
    assert "how they would" in r.reason and "fixed" in r.reason
    assert r.evidence_data["kind"] == "change"


# ── open questions are a different failure ────────────────────────────────


def test_open_questions_fail_distinctly_from_unverifiability():
    """'I still have questions' and 'there is no way to check this' send the
    human to different places; one reason for both would be useless."""
    r = check("make coffee theme default",
              plan(questions=["which coffee?"], acceptance=["it is coffee"]))
    assert r.verdict == "fail"
    assert "question" in r.reason
    assert "acceptance" not in r.reason


def test_open_questions_outrank_a_missing_acceptance_check():
    r = check("make coffee theme default", plan(questions=["which?"]))
    assert "question" in r.reason


# ── failure modes ─────────────────────────────────────────────────────────


def test_missing_plan_fails_closed():
    r = verification_possible(ref("x"), Ev(explode=True))
    assert r.verdict == "fail" and "could not read" in r.reason


def test_empty_plan_fails_rather_than_passing_vacuously():
    r = verification_possible(ref("make coffee theme default"), Ev(""))
    assert r.verdict == "fail"


# ── registration ──────────────────────────────────────────────────────────


def test_registered_under_task_automation_after_planned():
    entries = [(p, after) for p, after, _, name in registry_snapshot()
               if name == "verification_possible"]
    assert entries == [(TASK_AUTOMATION, "planned")]


def test_runs_via_the_registry_and_not_for_crimson_kitty():
    ev = Ev(render(plan(acceptance=["ok"])))
    got = run_gates("planned", ref("x"), ev, pipeline=TASK_AUTOMATION)
    assert [r.name for r in got] == ["verification_possible"]
    assert run_gates("planned", ref("x"), ev, pipeline="crimson-kitty") == []
