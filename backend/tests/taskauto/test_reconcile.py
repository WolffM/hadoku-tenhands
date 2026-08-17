"""Reconciling `landed` tasks against what really happened to their PR.

The bug this module exists for was not subtle and was invisible for days:
`landed` promised "the PR is open and waiting on you to merge" and nothing
ever checked. 13 of 14 live tasks disagreed with their pull request — ten
merged and still nagging, three CLOSED WITHOUT MERGING and still presented as
work waiting to be accepted.

So the tests that matter most here are the ones about NOT acting: a lookup
that fails, a PR still open, a human who grabbed the task first. Acting on a
guess is how you complete work nobody accepted.
"""

from __future__ import annotations

import pytest

from services.task_board import (
    BoardSnapshot,
    BoardTask,
    ClaimHeld,
    LaneChanged,
    Lane,
    LeaseLost,
    TaskBoardError,
)
from temporal.taskauto import plan_notes, reconcile, selection
from temporal.taskauto.plan_notes import PlanDoc
from temporal.taskauto.reconcile import PRRef, PRState

PR_URL = "https://github.com/WolffM/hadoku-pygmalion/pull/8"

LANES = [
    Lane(tag="replan", label="Replan", order=1, editable_by="user"),
    Lane(tag="approved", label="Approved", order=2, editable_by="user"),
    Lane(tag="working", label="Working", order=3, editable_by="agent"),
    Lane(tag="landed", label="Landed", order=4, editable_by="user"),
]


def task(tid="t1", tag="landed", notes=f"see {PR_URL}") -> BoardTask:
    return BoardTask(id=tid, title="a task", notes=notes, tag=tag,
                     metadata={}, claimed=False, state="Active",
                     created_at="2026-08-01T00:00:00Z",
                     updated_at="2026-08-01T00:00:00Z")


def board(*tasks: BoardTask) -> BoardSnapshot:
    return BoardSnapshot(id="b", name="b", handle="b", repo="WolffM/x",
                         mode="automation", schema_id="autoland",
                         schema_version=2, access="contributor", version=1,
                         lanes=list(LANES), tasks=list(tasks))


class FakeClient:
    """Records claim/release instead of performing them."""

    def __init__(self, claim_error=None, release_error=None):
        self.claims: list[str] = []
        self.releases: list[dict] = []
        self._claim_error = claim_error
        self._release_error = release_error

    def claim(self, board_handle, task_id, *, lease_seconds=None, **kw):
        if self._claim_error:
            raise self._claim_error
        self.claims.append(task_id)
        return "tok"

    def release(self, board_handle, task_id, token, **kw):
        if self._release_error:
            raise self._release_error
        self.releases.append({"task_id": task_id, **kw})
        return {}


def lookup_of(state: PRState | None):
    return lambda pr: state


# ── finding the PR ────────────────────────────────────────────────────────


def test_pr_ref_reads_the_url_the_pipeline_writes():
    ref = reconcile.pr_ref(f"Implemented and pushed.\n\n{PR_URL}\n\nMerge it.")
    assert ref == PRRef(repo="WolffM/hadoku-pygmalion", number=8)


def test_pr_ref_is_none_when_there_is_no_pr():
    assert reconcile.pr_ref("no link here") is None
    assert reconcile.pr_ref("") is None


def test_pr_ref_ignores_a_non_pr_github_url():
    """An issue link is not a pull request, and completing a task because
    someone closed a linked issue would be its own bug."""
    assert reconcile.pr_ref("https://github.com/WolffM/x/issues/4") is None


def test_pr_ref_takes_ours_when_a_human_pastes_another_below():
    notes = f"{PR_URL}\n\nrelated: https://github.com/WolffM/other/pull/99"
    assert reconcile.pr_ref(notes).number == 8


# ── the decision table ────────────────────────────────────────────────────


def test_merged_completes_the_task():
    v = reconcile.decide(task(), PRRef("WolffM/x", 8),
                         PRState(state="MERGED", merged=True))
    assert v.complete is True
    assert v.outcome == "pr-merged:8"


def test_merged_by_timestamp_alone_still_counts():
    """Older `gh` reports state=CLOSED with a mergedAt. Reading only `state`
    would file a merged PR as a rejection and re-plan shipped work."""
    v = reconcile.decide(task(), PRRef("WolffM/x", 8),
                         PRState(state="CLOSED", merged=True))
    assert v.complete is True
    assert v.outcome == "pr-merged:8"


def test_closed_unmerged_goes_back_to_replan():
    v = reconcile.decide(task(), PRRef("WolffM/x", 8),
                         PRState(state="CLOSED", merged=False))
    assert v.lane == selection.LANE_REPLAN
    assert v.complete is False
    assert v.outcome == "pr-rejected:8"


def test_open_is_left_alone():
    assert reconcile.decide(task(), PRRef("WolffM/x", 8),
                            PRState(state="OPEN", merged=False)) is None


def test_a_failed_lookup_is_left_alone():
    """`None` means "we could not find out", and that must be indistinguishable
    from "still open" in its consequences. Never act on ignorance."""
    assert reconcile.decide(task(), PRRef("WolffM/x", 8), None) is None


# ── what the human and the planner end up reading ─────────────────────────


def test_rejection_reaches_the_planner_as_human_text():
    """The rejection has to survive a render/parse round trip as `human_text`
    — the same channel a human's typed reply uses. `render()` drops
    `human_text`, so writing it INTO the doc would silently lose it."""
    v = reconcile.decide(task(), PRRef("WolffM/x", 8),
                         PRState(state="CLOSED", merged=False))
    parsed = plan_notes.parse(v.notes)
    assert "CLOSED WITHOUT MERGING" in parsed.human_text
    assert "https://github.com/WolffM/x/pull/8" in parsed.human_text


def test_replan_keeps_the_prior_plan_and_acceptance():
    prior = plan_notes.render(PlanDoc(
        understanding="u", plan=["step one"], acceptance=["it works"],
        pass_number=1))
    v = reconcile.decide(task(notes=prior + f"\n\n{PR_URL}"),
                         PRRef("WolffM/x", 8),
                         PRState(state="CLOSED", merged=False))
    doc = plan_notes.parse(v.notes)
    assert doc.plan == ["step one"]
    assert doc.acceptance == ["it works"]


def test_replan_resets_to_pass_one_so_a_retry_cannot_start_at_the_cap():
    prior = plan_notes.render(PlanDoc(understanding="u",
                                      pass_number=plan_notes.MAX_PASSES))
    v = reconcile.decide(task(notes=prior + f"\n\n{PR_URL}"),
                         PRRef("WolffM/x", 8),
                         PRState(state="CLOSED", merged=False))
    doc = plan_notes.parse(v.notes)
    assert doc.pass_number == 1
    assert not doc.at_pass_cap


def test_merged_notes_record_the_merge_under_outcome_and_summarise_files():
    # By landing time the plan section holds the execution log, not the plan —
    # blast_radius holds the files that actually changed.
    prior = plan_notes.render(PlanDoc(
        understanding="u",
        plan=["committed on taskauto/abc", "opened pull request"],
        blast_radius=["src/a.py", "src/b.py"]))
    pr = PRRef("WolffM/x", 8)
    v = reconcile.decide(task(notes=prior + f"\n\n{PR_URL}"),
                         pr,
                         PRState(state="MERGED", merged=True))
    doc = plan_notes.parse(v.notes)
    # The merge is the headline, under Outcome — never mislabelled as the want.
    assert "Merged via" in doc.outcome
    assert pr.url in doc.outcome
    assert "2 file(s) changed" in doc.outcome
    assert doc.understanding == ""
    # The execution log is dropped; the changed files remain as the summary.
    assert doc.plan == []
    assert doc.blast_radius == ["src/a.py", "src/b.py"]


# ── the sweep-level behaviour ─────────────────────────────────────────────


def test_reconcile_claims_and_releases_a_rejected_task():
    c = FakeClient()
    acted = reconcile.reconcile(board(task()), c, "bh",
                                lookup=lookup_of(PRState("CLOSED", False)))
    assert acted and c.claims == ["t1"]
    rel = c.releases[0]
    assert rel["lane"] == selection.LANE_REPLAN
    assert rel["complete"] is False


def test_release_is_guarded_on_the_lane_it_read():
    """Without `if_current_lane`, a human retagging between our read and our
    write gets dragged back into a lane they just moved away from."""
    c = FakeClient()
    reconcile.reconcile(board(task()), c, "bh",
                        lookup=lookup_of(PRState("MERGED", True)))
    assert c.releases[0]["if_current_lane"] == selection.LANE_LANDED


def test_only_landed_tasks_are_touched():
    c = FakeClient()
    tasks = [task("a", tag="approved"), task("w", tag="working"),
             task("r", tag="replan")]
    reconcile.reconcile(board(*tasks), c, "bh",
                        lookup=lookup_of(PRState("CLOSED", False)))
    assert c.claims == []


def test_a_landed_task_with_no_pr_link_is_left_alone():
    c = FakeClient()
    reconcile.reconcile(board(task(notes="no link")), c, "bh",
                        lookup=lookup_of(PRState("CLOSED", False)))
    assert c.claims == []


def test_a_task_someone_else_is_working_is_skipped():
    c = FakeClient(claim_error=ClaimHeld("held", code="CLAIM_HELD"))
    acted = reconcile.reconcile(board(task()), c, "bh",
                                lookup=lookup_of(PRState("CLOSED", False)))
    assert acted == [] and c.releases == []


def test_a_lane_change_under_us_writes_nothing():
    c = FakeClient(release_error=LaneChanged("moved", code="LANE_CHANGED"))
    acted = reconcile.reconcile(board(task()), c, "bh",
                                lookup=lookup_of(PRState("CLOSED", False)))
    assert acted == []


def test_a_lost_lease_writes_nothing():
    c = FakeClient(release_error=LeaseLost("gone", code="LEASE_LOST"))
    assert reconcile.reconcile(board(task()), c, "bh",
                               lookup=lookup_of(PRState("CLOSED", False))) == []


def test_a_raising_lookup_never_breaks_the_sweep():
    """One unreachable repo must not stop every other board being corrected."""
    def boom(pr):
        raise RuntimeError("network gone")

    c = FakeClient()
    assert reconcile.reconcile(board(task()), c, "bh", lookup=boom) == []
    assert c.claims == []


def test_a_release_failure_is_reported_not_raised():
    c = FakeClient(release_error=TaskBoardError("boom"))
    assert reconcile.reconcile(board(task()), c, "bh",
                               lookup=lookup_of(PRState("MERGED", True))) == []


def test_several_tasks_are_each_handled_on_their_own_verdict():
    c = FakeClient()
    merged = task("m", notes="https://github.com/WolffM/x/pull/1")
    rejected = task("r", notes="https://github.com/WolffM/x/pull/2")
    open_pr = task("o", notes="https://github.com/WolffM/x/pull/3")
    states = {1: PRState("MERGED", True), 2: PRState("CLOSED", False),
              3: PRState("OPEN", False)}
    reconcile.reconcile(board(merged, rejected, open_pr), c, "bh",
                        lookup=lambda pr: states[pr.number])
    assert sorted(c.claims) == ["m", "r"]
    by_task = {r["task_id"]: r for r in c.releases}
    assert by_task["m"]["complete"] is True
    assert by_task["r"]["lane"] == selection.LANE_REPLAN


# ── the gh seam ───────────────────────────────────────────────────────────


def test_gh_lookup_parses_a_merged_pr():
    look = reconcile.gh_lookup(
        lambda argv: (True, '{"state":"MERGED","mergedAt":"2026-08-01T00:00:00Z"}'))
    assert look(PRRef("WolffM/x", 8)).is_merged


def test_gh_lookup_parses_a_rejection():
    look = reconcile.gh_lookup(
        lambda argv: (True, '{"state":"CLOSED","mergedAt":null}'))
    assert look(PRRef("WolffM/x", 8)).is_rejected


def test_gh_lookup_returns_none_when_gh_fails():
    look = reconcile.gh_lookup(lambda argv: (False, ""))
    assert look(PRRef("WolffM/x", 8)) is None


def test_gh_lookup_returns_none_on_garbage():
    look = reconcile.gh_lookup(lambda argv: (True, "not json"))
    assert look(PRRef("WolffM/x", 8)) is None


def test_gh_lookup_asks_about_the_right_pr():
    seen = {}

    def run(argv):
        seen["argv"] = argv
        return True, '{"state":"OPEN","mergedAt":null}'

    reconcile.gh_lookup(run)(PRRef("WolffM/hadoku-pygmalion", 8))
    assert "--repo" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--repo") + 1] == "WolffM/hadoku-pygmalion"
    assert "8" in seen["argv"]
