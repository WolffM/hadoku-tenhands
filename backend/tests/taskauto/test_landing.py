"""Tests for temporal/taskauto/landing.py.

This is the component that pushes to a branch people depend on, unattended.
Every test here is about a reason NOT to push — that's the whole job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temporal.taskauto.landing import CmdResult, Lander, LandingRefused
from temporal.taskauto.refs import RepoPolicy, TaskRef


class FakeShell:
    def __init__(self, *, fail=(), outputs=None):
        self.fail = fail
        self.outputs = outputs or {}
        self.calls: list[list[str]] = []

    def __call__(self, args, cwd, timeout=1800):
        args = list(args)
        self.calls.append(args)
        joined = " ".join(args)
        for pat in self.fail:
            if pat in joined:
                return CmdResult(False, "", f"simulated failure: {pat}")
        for pat, out in self.outputs.items():
            if pat in joined:
                return CmdResult(True, out)
        return CmdResult(True, "")

    def ran(self, pat):
        return [c for c in self.calls if pat in " ".join(c)]


def ref(title="make coffee theme default", notes="", policy=None):
    return TaskRef(repo_slug="WolffM/tenhands", board="H", task_id="t1",
                   title=title, notes_at_claim=notes,
                   policy=policy or RepoPolicy())


def lander(shell, dry_run=True):
    return Lander(run=shell, dry_run=dry_run)


SHA = {"rev-parse HEAD": "abc1234def5678\n"}


# ── preflight refusals ────────────────────────────────────────────────────


def test_nothing_changed_is_refused():
    """An agent that reported a fix without making one is the most common
    failure there is."""
    with pytest.raises(LandingRefused, match="nothing changed"):
        lander(FakeShell()).preflight(ref(), [])


def test_blast_radius_cap_is_enforced():
    files = [f"src/f{i}.ts" for i in range(25)]
    with pytest.raises(LandingRefused, match="blast radius"):
        lander(FakeShell()).preflight(ref(), files)


def test_protected_path_without_authorisation_is_refused():
    with pytest.raises(LandingRefused, match="protected paths"):
        lander(FakeShell()).preflight(ref(), [".github/workflows/deploy.yml"])


def test_protected_path_with_authorisation_passes():
    checks = lander(FakeShell()).preflight(
        ref(title="fix ci allow-protected: .github/workflows/deploy.yml"),
        [".github/workflows/deploy.yml"])
    assert any("protected_paths" in c for c in checks)


def test_the_agent_cannot_authorise_itself_at_landing_time_either():
    """`notes_at_claim` is the pre-claim snapshot. Whatever the agent wrote
    into live notes never reaches this call."""
    with pytest.raises(LandingRefused, match="protected paths"):
        lander(FakeShell()).preflight(
            ref(notes="human text, no directive"),
            ["backend/temporal/judge.py"])


def test_an_ordinary_change_passes_preflight():
    checks = lander(FakeShell()).preflight(ref(), ["backend/app.py"])
    assert any("diff_non_empty" in c for c in checks)


# ── verification is against current main ──────────────────────────────────


def test_the_suite_runs_on_the_merge_result_not_the_bare_branch():
    """A branch cut an hour ago passes against the main it remembers, not
    the one it is about to become part of."""
    sh = FakeShell(outputs=SHA)
    lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                    changed_files=["a.py"], test_command=["pytest", "-q"])
    order = [" ".join(c) for c in sh.calls]
    merged = next(i for i, c in enumerate(order) if "merge --no-edit origin/main" in c)
    tested = next(i for i, c in enumerate(order) if c.startswith("pytest"))
    assert merged < tested, "must merge main in BEFORE running the suite"


def test_a_failing_suite_refuses_to_push():
    sh = FakeShell(fail=("pytest",), outputs=SHA)
    with pytest.raises(LandingRefused, match="suite failed"):
        lander(sh, dry_run=False).land(
            Path("/co"), ref(), branch="b", message="m",
            changed_files=["a.py"], test_command=["pytest", "-q"])
    assert sh.ran("push") == [], "nothing may be pushed after a red suite"


def test_the_failure_message_carries_the_test_output():
    sh = FakeShell(fail=("pytest",), outputs=SHA)
    with pytest.raises(LandingRefused) as ei:
        lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                        changed_files=["a.py"], test_command=["pytest", "-q"])
    assert "simulated failure" in str(ei.value)


def test_a_conflict_with_main_aborts_the_merge_and_refuses():
    """An unattended agent resolving conflicts is not something anyone
    wants."""
    sh = FakeShell(fail=("merge --no-edit",), outputs=SHA)
    with pytest.raises(LandingRefused, match="conflicts"):
        lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                        changed_files=["a.py"])
    assert sh.ran("merge --abort"), "a half-merged tree must not be left behind"


def test_missing_test_command_is_loudly_recorded_not_silently_ok():
    """Without a suite, 'lands on green' is an empty phrase."""
    res = lander(FakeShell(outputs=SHA)).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert any("NO TEST COMMAND" in c for c in res.checks)


# ── dry run is the default posture ────────────────────────────────────────


def test_dry_run_does_everything_except_push():
    sh = FakeShell(outputs=SHA)
    res = lander(sh, dry_run=True).land(
        Path("/co"), ref(), branch="b", message="m",
        changed_files=["a.py"], test_command=["pytest", "-q"])
    assert res.pushed is False
    assert res.commit_sha.startswith("abc1234")
    assert sh.ran("commit") and sh.ran("pytest")
    assert sh.ran("push") == []


def test_default_is_dry_run():
    assert Lander().dry_run is True


# ── the push itself ───────────────────────────────────────────────────────


def test_push_uses_an_explicit_refspec():
    """A bare `git push origin main` pushes the local main ref regardless of
    which branch we are standing on — it silently no-ops while the commit
    sits somewhere else."""
    sh = FakeShell(outputs=SHA)
    res = lander(sh, dry_run=False).land(
        Path("/co"), ref(), branch="b", message="m",
        changed_files=["a.py"], test_command=["pytest", "-q"])
    assert res.pushed is True
    assert sh.ran("push origin HEAD:main"), "must be an explicit refspec"


def test_a_rejected_push_is_refused_not_forced():
    sh = FakeShell(fail=("push",), outputs=SHA)
    with pytest.raises(LandingRefused, match="push rejected"):
        lander(sh, dry_run=False).land(
            Path("/co"), ref(), branch="b", message="m",
            changed_files=["a.py"], test_command=["pytest", "-q"])
    assert sh.ran("push --force") == []


def test_a_failed_commit_stops_before_any_verification():
    sh = FakeShell(fail=("commit",))
    with pytest.raises(LandingRefused, match="commit failed"):
        lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                        changed_files=["a.py"], test_command=["pytest"])
    assert sh.ran("pytest") == []


def test_checks_read_as_an_audit_trail():
    res = lander(FakeShell(outputs=SHA), dry_run=False).land(
        Path("/co"), ref(), branch="b", message="m",
        changed_files=["a.py"], test_command=["pytest", "-q"])
    joined = " | ".join(res.checks)
    for expected in ("diff_non_empty", "blast_radius", "protected_paths",
                     "committed", "merged current origin/main", "suite green",
                     "pushed"):
        assert expected in joined


# ── pr mode ───────────────────────────────────────────────────────────────
#
# The mode that matters going forward: the agent opens a pull request and a
# human merges it. Every test here is about the promise that `main` is not
# touched, and that a branch which is already pushed never gets stranded.


PR_OUT = dict(SHA, **{"pr create": "https://github.com/WolffM/tenhands/pull/99\n"})

#: A base branch WITH required checks. `branches/main` is the protection read;
#: the jq in the lander reduces it to a count, so the fake returns the count.
PROTECTED = dict(PR_OUT, **{"api repos/WolffM/tenhands/branches/main": "3\n"})

#: A base branch with none — GitHub returns 0, not an error.
UNPROTECTED = dict(PR_OUT, **{"api repos/WolffM/tenhands/branches/main": "0\n"})


def pr_lander(shell, auto_merge=False):
    return Lander(run=shell, dry_run=False, mode="pr", auto_merge=auto_merge)


def test_pr_mode_never_pushes_to_base():
    sh = FakeShell(outputs=PR_OUT)
    res = pr_lander(sh).land(Path("/co"), ref(), branch="taskauto/t1",
                             message="fix the thing", changed_files=["a.py"])
    assert res.pushed is False, "pushed must stay False — nothing reached main"
    assert sh.ran("HEAD:main") == [], "pr mode must never push to base"
    assert sh.ran("HEAD:refs/heads/taskauto/t1"), "the branch should be pushed"


def test_pr_mode_returns_the_pull_request_url():
    res = pr_lander(FakeShell(outputs=PR_OUT)).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert res.pr_url == "https://github.com/WolffM/tenhands/pull/99"
    assert "human merges it" in res.reason


def test_pr_mode_does_not_run_the_suite():
    # CI is the gate. Running it here too would burn the expensive half of
    # the job twice on one runner to learn the same thing.
    sh = FakeShell(outputs=PR_OUT)
    res = pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                             changed_files=["a.py"], test_command=["pytest"])
    assert sh.ran("pytest") == []
    assert any("gate" in c for c in res.checks)


def test_pr_mode_still_refuses_protected_paths():
    # A human reviewing later is not a reason to relax the preflight; the
    # branch is pushed to a shared remote either way.
    sh = FakeShell(outputs=PR_OUT)
    with pytest.raises(LandingRefused, match="protected paths"):
        pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                           changed_files=[".github/workflows/deploy.yml"])
    assert sh.ran("push") == []


def test_pr_mode_still_refuses_a_conflict_with_main():
    sh = FakeShell(fail=("merge --no-edit",), outputs=PR_OUT)
    with pytest.raises(LandingRefused, match="conflicts with current"):
        pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                           changed_files=["a.py"])
    assert sh.ran("push") == []


def test_an_existing_pull_request_is_reused_not_treated_as_failure():
    # The normal state on a retry after a crash. The branch is pushed by then,
    # so raising here would strand real work over a duplicate-create.
    sh = FakeShell(fail=("pr create",),
                   outputs=dict(SHA, **{"pr view": "https://example/pull/7\n"}))
    res = pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                             changed_files=["a.py"])
    assert res.pr_url == "https://example/pull/7"
    assert any("already open" in c for c in res.checks)


def test_a_pushed_branch_with_no_pull_request_is_refused_loudly():
    sh = FakeShell(fail=("pr create", "pr view"), outputs=SHA)
    with pytest.raises(LandingRefused, match="is pushed but opening"):
        pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                           changed_files=["a.py"])


def test_pr_push_uses_force_with_lease_so_retries_are_not_wedged():
    sh = FakeShell(outputs=PR_OUT)
    pr_lander(sh).land(Path("/co"), ref(), branch="b", message="m",
                       changed_files=["a.py"])
    assert sh.ran("--force-with-lease"), "a retry must be able to update its own branch"


def test_pr_title_comes_from_the_first_line_of_the_commit_message():
    sh = FakeShell(outputs=PR_OUT)
    pr_lander(sh).land(Path("/co"), ref(), branch="b",
                       message="drop the unused import\n\nlonger body here",
                       changed_files=["a.py"])
    created = sh.ran("pr create")[0]
    assert created[created.index("--title") + 1] == "drop the unused import"


def test_dry_run_in_pr_mode_opens_nothing():
    sh = FakeShell(outputs=PR_OUT)
    res = Lander(run=sh, dry_run=True, mode="pr").land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert res.pr_url == ""
    assert sh.ran("push") == [] and sh.ran("pr create") == []
    assert sh.ran("pr merge") == [], "a dry run must not arm auto-merge either"


# ── auto-merge ────────────────────────────────────────────────────────────
#
# The whole safety property is one distinction: `--auto` waits for *required*
# checks and nothing else, so on a branch with none it merges IMMEDIATELY
# rather than on green. Every test here is about reading the base branch's
# protection instead of the pull request's own check rollup.


def test_auto_merge_is_on_by_default():
    # The velocity decision, pinned: PRs land themselves unless the repo
    # gives us a reason not to. `dry_run` is still the safe default separately.
    assert Lander().auto_merge is True


def test_auto_merge_is_armed_when_the_base_branch_requires_checks():
    sh = FakeShell(outputs=PROTECTED)
    res = pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="taskauto/t1", message="m",
        changed_files=["a.py"])
    assert res.auto_merge_armed is True
    merge = sh.ran("pr merge")
    assert merge, "auto-merge should have been armed"
    assert "--auto" in merge[0] and "--squash" in merge[0]
    assert "--delete-branch" in merge[0]
    assert res.pushed is False, "arming auto-merge is not landing it"


def test_auto_merge_holds_when_the_base_branch_has_no_required_checks():
    # The load-bearing case. `--auto` here would merge on the spot, unreviewed.
    sh = FakeShell(outputs=UNPROTECTED)
    res = pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="taskauto/t1", message="m",
        changed_files=["a.py"])
    assert res.auto_merge_armed is False
    assert sh.ran("pr merge") == [], "must not arm --auto on an unprotected base"
    assert any("HELD" in c for c in res.checks)
    assert "a human merges it" in res.reason


def test_unreadable_protection_holds_rather_than_arming():
    # Fails closed: not knowing is exactly when merging unattended is worst.
    sh = FakeShell(fail=("api repos/WolffM/tenhands/branches/main",),
                   outputs=PR_OUT)
    res = pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert res.auto_merge_armed is False
    assert sh.ran("pr merge") == []


def test_a_non_numeric_protection_payload_holds_rather_than_arming():
    sh = FakeShell(outputs=dict(
        PR_OUT, **{"api repos/WolffM/tenhands/branches/main": "null\n"}))
    res = pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert res.auto_merge_armed is False
    assert sh.ran("pr merge") == []


def test_protection_is_read_from_the_base_branch_not_the_pull_request():
    # If this ever starts reading `statusCheckRollup`, the guard is worthless:
    # a PR covered in green NON-required checks looks identical from there.
    sh = FakeShell(outputs=PROTECTED)
    pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert sh.ran("branches/main"), "must read the base branch's protection"
    assert not any("statusCheckRollup" in " ".join(c) for c in sh.calls)


def test_a_failure_to_arm_leaves_the_pull_request_open_rather_than_raising():
    # The branch is pushed and the PR exists by then. Raising would strand
    # real work over the merge scheduling, which a human can still do.
    sh = FakeShell(fail=("pr merge",), outputs=PROTECTED)
    res = pr_lander(sh, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert res.pr_url == "https://github.com/WolffM/tenhands/pull/99"
    assert res.auto_merge_armed is False
    assert any("could not be armed" in c for c in res.checks)


def test_auto_merge_never_arms_in_push_mode():
    # push mode has no pull request to schedule.
    sh = FakeShell(outputs=SHA)
    Lander(run=sh, dry_run=False, mode="push", auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    assert sh.ran("pr merge") == []


def test_the_pr_body_states_which_of_the_two_it_got():
    armed = FakeShell(outputs=PROTECTED)
    pr_lander(armed, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    created = armed.ran("pr create")[0]
    assert "Auto-merge is armed" in created[created.index("--body") + 1]

    held = FakeShell(outputs=UNPROTECTED)
    pr_lander(held, auto_merge=True).land(
        Path("/co"), ref(), branch="b", message="m", changed_files=["a.py"])
    created = held.ran("pr create")[0]
    body = created[created.index("--body") + 1]
    assert "no required status checks" in body
    assert "Merge it by hand" in body


def test_preflight_still_gates_before_anything_is_armed():
    # Auto-merge is downstream of every refusal, not a way around one.
    sh = FakeShell(outputs=PROTECTED)
    with pytest.raises(LandingRefused, match="protected paths"):
        pr_lander(sh, auto_merge=True).land(
            Path("/co"), ref(), branch="b", message="m",
            changed_files=[".github/workflows/deploy.yml"])
    assert sh.ran("pr merge") == [] and sh.ran("pr create") == []
