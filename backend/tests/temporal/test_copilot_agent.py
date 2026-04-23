"""Tests for backend.temporal.agents.copilot — Phase 1B.4.

Mocks the gh runner via the constructor seam so no network calls happen.
Covers:
  - assign() creates the issue, posts the assignee, verifies it stuck
  - assign() retries when the verify fails the first time
  - assign() raises when verify never succeeds
  - poll() returns queued / running / done correctly
  - poll() correlates Copilot PRs by the <issue_title> tag
  - harvest() collects diff + files + commits + agent log
  - harvest() reports no_changes when the PR has no commits/diff
"""

from __future__ import annotations

import json

import pytest

from temporal.agents import IssueRef
from temporal.agents.copilot import COPILOT_ASSIGNEE, CopilotAgent


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/markitdown",
        number=183,
        upstream_slug="microsoft/markitdown",
    )


# ── Fake gh runner ────────────────────────────────────────────────────────


class FakeGh:
    """Records every gh invocation and replays canned responses by argv pattern."""

    def __init__(self):
        self.calls: list[tuple[list[str], str | None]] = []
        self.fork_issue_number = 42
        self.issue_title = "fix the merged-cell xlsx bug"
        self.assignee_present_after = 1  # how many assignee verifies before Copilot appears
        self._assignee_attempts = 0
        # Existing open fork issues assigned to Copilot — used by the
        # idempotent-assign lookup. Tests set this to exercise resume.
        self.existing_fork_issues: list[dict] = []
        # Cross-reference events on fork issue timelines — tests set to
        # exercise B22 timeline-linked correlation. Keyed by fork issue
        # number, value is a list of PR numbers (newest last).
        self.timeline_linked_prs: dict[int, list[int]] = {}
        self.copilot_pr = {
            "number": 9,
            "title": "Fix merged cell handling",
            "headRefName": "fix-merged-cells",
            "body": f"<issue_title>{self.issue_title}</issue_title>\n\nFixed the merged cells.",
            "author": {"login": "copilot-swe-agent[bot]"},
        }
        self.commit_shas = ["abc123", "def456", "789aaa"]
        self.diff_text = "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new\n"
        self.files_touched = ["src/markitdown/xlsx.py"]
        self.head_sha = "deadbeef"
        self.check_run_status = "completed"

    def __call__(self, args, stdin_data=None):
        self.calls.append((list(args), stdin_data))
        joined = " ".join(args)

        # List existing open fork issues assigned to Copilot (idempotent-assign lookup)
        if args[0] == "api" and args[1].startswith("repos/") and "/issues?state=open" in args[1]:
            return {
                "success": True,
                "output": json.dumps(self.existing_fork_issues),
            }

        # Create issue (POST repos/.../issues)
        if args[0] == "api" and args[1].endswith("/issues") and "POST" in args:
            return {
                "success": True,
                "output": json.dumps({"number": self.fork_issue_number}),
            }

        # Assignees POST
        if args[0] == "api" and "/assignees" in args[1] and "POST" in args:
            return {"success": True, "output": "{}"}

        # Issue verify (GET issue, jq assignees)
        if args[0] == "api" and args[1].endswith(f"issues/{self.fork_issue_number}") and "--jq" in args:
            self._assignee_attempts += 1
            if self._assignee_attempts >= self.assignee_present_after:
                return {
                    "success": True,
                    "output": json.dumps([COPILOT_ASSIGNEE]),
                }
            return {"success": True, "output": "[]"}

        # Fork issue timeline — for B22 timeline-based correlation
        if args[0] == "api" and "/timeline" in args[1]:
            # Extract issue number from the URL pattern .../issues/N/timeline
            import re
            m = re.search(r"/issues/(\d+)/timeline", args[1])
            issue_n = int(m.group(1)) if m else 0
            pr_numbers = self.timeline_linked_prs.get(issue_n, [])
            return {"success": True, "output": json.dumps(pr_numbers)}

        # List open PRs
        if args[0] == "api" and "/pulls?state=open" in args[1]:
            return {
                "success": True,
                "output": json.dumps([self.copilot_pr]),
            }

        # PR commits
        if args[0] == "api" and "/commits?per_page=100" in args[1]:
            return {
                "success": True,
                "output": json.dumps(self.commit_shas),
            }

        # PR head SHA
        if args[:2] == ["pr", "view"] and "headRefOid" in args:
            return {"success": True, "output": self.head_sha}

        # check-runs
        if args[0] == "api" and "/check-runs" in args[1]:
            return {"success": True, "output": self.check_run_status}

        # PR diff
        if args[:2] == ["pr", "diff"]:
            return {"success": True, "output": self.diff_text}

        # PR files
        if args[0] == "api" and args[1].endswith("/files") and "filename" in (" ".join(args)):
            return {"success": True, "output": json.dumps(self.files_touched)}

        # PR body for agent log
        if args[0] == "api" and args[1].startswith("repos/") and "/pulls/" in args[1] and ".body" in args:
            return {"success": True, "output": "Copilot session log here"}

        raise AssertionError(f"unexpected gh call: {args}")


@pytest.fixture
def fake_gh() -> FakeGh:
    return FakeGh()


@pytest.fixture
def agent(fake_gh) -> CopilotAgent:
    return CopilotAgent(run_gh=fake_gh, assign_retry_delay_s=0)


# ── assign ────────────────────────────────────────────────────────────────


def test_assign_creates_issue_and_assigns_copilot(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief="fix the merged-cell xlsx bug\n\nDetails here.")

    assert job.agent_kind == "copilot"
    assert job.fork_slug == "WolffM/markitdown"
    assert job.job_id == "42"
    assert job.metadata["upstream_slug"] == "microsoft/markitdown"
    assert job.metadata["upstream_number"] == 183
    assert "issue_title" in job.metadata

    # First call: POST issue
    issue_create_calls = [c for c, _ in fake_gh.calls if c[0] == "api" and c[1].endswith("/issues") and "POST" in c]
    assert len(issue_create_calls) == 1

    # Second call group: assignees POST + verify
    assignee_posts = [c for c, _ in fake_gh.calls if "/assignees" in c[1] and "POST" in c]
    assert len(assignee_posts) == 1


def test_assign_retries_when_verify_fails_first(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 2  # second verify wins
    job = agent.assign(issue, brief="fix something")

    assert job.job_id == "42"
    assignee_posts = [c for c, _ in fake_gh.calls if "/assignees" in c[1] and "POST" in c]
    assert len(assignee_posts) == 2  # retried once


def test_assign_raises_when_assignee_never_sticks(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 999
    with pytest.raises(RuntimeError, match="Copilot was not added"):
        agent.assign(issue, brief="fix something")


def test_assign_adopts_existing_tagged_fork_issue(agent, fake_gh, issue):
    """When a prior assign() already created a fork issue for this title
    (e.g. a heartbeat-timeout abort left it dangling), re-calling assign()
    must return a job pointing at THAT issue rather than creating a
    duplicate. Otherwise every re-dispatch burns another Copilot premium
    request and spawns a duplicate PR."""
    brief = "fix the merged-cell xlsx bug\n\nDetails here."
    # Pre-seed an existing assignment with the same <issue_title> tag
    fake_gh.existing_fork_issues = [
        {
            "number": 17,
            "body": "<issue_title>fix the merged-cell xlsx bug</issue_title>\n\n## Context\n...",
        },
    ]

    job = agent.assign(issue, brief=brief)

    assert job.job_id == "17"
    assert job.metadata.get("adopted") is True
    # No POST to /issues — we reused the existing one
    posts = [c for c, _ in fake_gh.calls if c[0] == "api" and c[1].endswith("/issues") and "POST" in c]
    assert posts == []


def test_assign_creates_fresh_when_existing_issue_tag_does_not_match(agent, fake_gh, issue):
    """An open fork issue for a DIFFERENT title must not be adopted —
    each dispatch needs its own correlation tag."""
    fake_gh.existing_fork_issues = [
        {"number": 17, "body": "<issue_title>an unrelated task</issue_title>\n\n..."},
    ]
    fake_gh.assignee_present_after = 1

    job = agent.assign(issue, brief="fix the merged-cell xlsx bug")

    assert job.job_id == "42"  # fresh issue created, not 17
    assert job.metadata.get("adopted") is not True
    posts = [c for c, _ in fake_gh.calls if c[0] == "api" and c[1].endswith("/issues") and "POST" in c]
    assert len(posts) == 1


def test_assign_raises_when_create_issue_fails(fake_gh, issue):
    def failing_gh(args, stdin_data=None):
        # Idempotent-assign lookup — return no existing issues
        if args[0] == "api" and args[1].startswith("repos/") and "/issues?state=open" in args[1]:
            return {"success": True, "output": "[]"}
        if args[0] == "api" and args[1].endswith("/issues") and "POST" in args:
            return {"success": False, "error": "rate limited"}
        raise AssertionError("should have failed before this")

    bad_agent = CopilotAgent(run_gh=failing_gh, assign_retry_delay_s=0)
    with pytest.raises(RuntimeError, match="failed to create fork issue"):
        bad_agent.assign(issue, brief="x")


def test_assign_passes_brief_into_issue_body(agent, fake_gh, issue):
    brief = "first line is the title\n\nbody text follows"
    agent.assign(issue, brief=brief)

    create_call = next(c for c, _ in fake_gh.calls if c[0] == "api" and c[1].endswith("/issues") and "POST" in c)
    create_idx = fake_gh.calls.index((create_call, json.dumps(json.loads(next(s for c, s in fake_gh.calls if c == create_call)))))  # find stdin
    # simpler: look up the stdin
    stdin = next(s for c, s in fake_gh.calls if c == create_call)
    payload = json.loads(stdin)
    assert "first line is the title" in payload["body"]
    assert "body text follows" in payload["body"]
    assert "<issue_title>" in payload["body"]


# ── poll ──────────────────────────────────────────────────────────────────


def test_poll_returns_done_when_check_completed(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    fake_gh.check_run_status = "completed"
    status = agent.poll(job)
    assert status.state == "done"
    assert status.progress == 1.0


def test_poll_returns_done_via_commit_count_fallback(agent, fake_gh, issue):
    """Check-run absent → 2+ commits is the fallback signal."""
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    fake_gh.check_run_status = ""  # check-run missing
    fake_gh.commit_shas = ["a", "b", "c"]  # > 1 commit
    status = agent.poll(job)
    assert status.state == "done"


def test_poll_returns_running_when_only_one_commit(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    fake_gh.check_run_status = ""
    fake_gh.commit_shas = ["initial-plan-only"]
    status = agent.poll(job)
    assert status.state == "running"


def test_poll_returns_queued_when_no_copilot_pr(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    # Drop the copilot PR — simulate "Copilot hasn't pushed yet"
    fake_gh.copilot_pr = {
        "number": 1, "title": "human PR", "body": "",
        "headRefName": "human", "author": {"login": "human"},
    }
    status = agent.poll(job)
    assert status.state == "queued"


def test_correlate_picks_timeline_linked_pr_over_other_candidates(agent, fake_gh, issue):
    """B22 primary path: GitHub's cross-reference timeline links the
    fork issue to the PR Copilot created for it. That's the strongest
    signal — use it even when multiple Copilot PRs exist."""
    from temporal.agents.copilot import COPILOT_ASSIGNEE

    candidates = [
        {"number": 5, "body": "stale PR from an earlier run",
         "author": {"login": COPILOT_ASSIGNEE}, "commits": [{"sha": "a"}, {"sha": "b"}, {"sha": "c"}]},
        {"number": 9, "body": "current run PR with no tag",
         "author": {"login": COPILOT_ASSIGNEE}, "commits": [{"sha": "x"}]},
    ]
    # Timeline on fork issue #42 points at PR #9 — the current-run PR
    fake_gh.timeline_linked_prs = {42: [9]}

    picked = agent._correlate_pr("WolffM", "markitdown", "42", "some title", candidates)
    assert picked["number"] == 9


def test_correlate_falls_back_to_most_commits_when_no_tag_no_timeline(agent, fake_gh, issue):
    """B22 final fallback: when neither the timeline link nor a tag
    match is available AND there are multiple Copilot PRs (resumes
    accumulating on the fork), pick the one with the most commits.

    Regression for v9 core/pnpm: 3 historical Copilot PRs, none carried
    the <issue_title> tag, previous code returned None and the activity
    timed out after 30 min waiting. Now we pick the most-advanced PR."""
    from temporal.agents.copilot import COPILOT_ASSIGNEE

    candidates = [
        {"number": 4, "body": "no tag here",
         "author": {"login": COPILOT_ASSIGNEE}, "commits": [{"sha": "a"}]},
        {"number": 6, "body": "also no tag",
         "author": {"login": COPILOT_ASSIGNEE},
         "commits": [{"sha": "a"}, {"sha": "b"}, {"sha": "c"}, {"sha": "d"}]},
        {"number": 8, "body": "still no tag",
         "author": {"login": COPILOT_ASSIGNEE}, "commits": [{"sha": "a"}, {"sha": "b"}]},
    ]

    picked = agent._correlate_pr("WolffM", "core", "42", "some title", candidates)
    assert picked["number"] == 6  # 4 commits — the most


def test_correlate_still_picks_tag_match_when_available(agent, fake_gh, issue):
    """The tag-based match remains — if Copilot DID echo the tag,
    prefer the tagged PR over others even if they have more commits."""
    from temporal.agents.copilot import COPILOT_ASSIGNEE

    candidates = [
        {"number": 4, "body": "no tag",
         "author": {"login": COPILOT_ASSIGNEE},
         "commits": [{"sha": "a"}, {"sha": "b"}, {"sha": "c"}]},
        {"number": 7, "body": "<issue_title>the correct title</issue_title>\nbody",
         "author": {"login": COPILOT_ASSIGNEE}, "commits": [{"sha": "x"}]},
    ]

    picked = agent._correlate_pr("WolffM", "x", "42", "the correct title", candidates)
    assert picked["number"] == 7  # tag wins over raw commit count


def test_poll_rejects_foreign_job(agent):
    from temporal.agents import AgentJob
    foreign = AgentJob(job_id="x", agent_kind="noop", fork_slug="x/y", branch_name="b")
    with pytest.raises(ValueError, match="cannot poll"):
        agent.poll(foreign)


# ── harvest ───────────────────────────────────────────────────────────────


def test_harvest_collects_full_result(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    result = agent.harvest(job)
    assert result.exit_reason == "success"
    assert result.commit_shas == ["abc123", "def456", "789aaa"]
    assert result.files_touched == ["src/markitdown/xlsx.py"]
    assert "diff --git" in result.diff_text
    assert result.pr_url == "https://github.com/WolffM/markitdown/pull/9"


def test_harvest_reports_no_changes_when_diff_empty(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    fake_gh.diff_text = ""
    fake_gh.commit_shas = []
    result = agent.harvest(job)
    assert result.exit_reason == "no_changes"
    assert result.diff_text == ""


def test_harvest_reports_error_when_no_pr_found(agent, fake_gh, issue):
    fake_gh.assignee_present_after = 1
    job = agent.assign(issue, brief=fake_gh.issue_title)

    # Simulate the PR vanishing
    fake_gh.copilot_pr = {
        "number": 1, "title": "human PR", "body": "",
        "headRefName": "human", "author": {"login": "human"},
    }
    result = agent.harvest(job)
    assert result.exit_reason == "error"
    assert result.commit_shas == []


def test_harvest_rejects_foreign_job(agent):
    from temporal.agents import AgentJob
    foreign = AgentJob(job_id="x", agent_kind="noop", fork_slug="x/y", branch_name="b")
    with pytest.raises(ValueError, match="cannot harvest"):
        agent.harvest(foreign)
