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
