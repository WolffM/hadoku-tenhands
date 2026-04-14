"""Tests for backend.temporal.agents — Phase 1B.2 + 1B.3.

Covers:
  - Agent protocol satisfaction (NoopAgent type-checks as Agent)
  - NoopAgent assign/poll/harvest happy path
  - NoopAgent configurable scenarios (empty diff, failure, multi-poll)
"""

from __future__ import annotations

import pytest

from temporal.agents import (
    Agent,
    AgentJob,
    AgentResult,
    AgentStatus,
    IssueRef,
)
from temporal.agents.noop import NoopAgent


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/markitdown",
        number=183,
        upstream_slug="microsoft/markitdown",
    )


# ── Agent protocol ────────────────────────────────────────────────────────


def test_noop_agent_satisfies_agent_protocol():
    """Runtime-check that NoopAgent has the Agent surface."""
    agent = NoopAgent()
    assert isinstance(agent, Agent)


def test_noop_agent_has_all_three_methods():
    agent = NoopAgent()
    assert callable(agent.assign)
    assert callable(agent.poll)
    assert callable(agent.harvest)


# ── NoopAgent.assign ──────────────────────────────────────────────────────


def test_assign_returns_job_with_unique_id(issue):
    agent = NoopAgent()
    j1 = agent.assign(issue, brief="brief 1")
    j2 = agent.assign(issue, brief="brief 2")
    assert j1.job_id != j2.job_id
    assert j1.agent_kind == "noop"
    assert j1.fork_slug == "WolffM/markitdown"
    assert j1.branch_name == "fix-issue-183"


def test_assign_records_brief_size_in_metadata(issue):
    agent = NoopAgent()
    job = agent.assign(issue, brief="hello world", instruction="be careful")
    assert job.metadata["brief_chars"] == len("hello world")
    assert job.metadata["instruction_chars"] == len("be careful")


# ── NoopAgent.poll ────────────────────────────────────────────────────────


def test_poll_returns_done_immediately_by_default(issue):
    agent = NoopAgent()
    job = agent.assign(issue, brief="x")
    status = agent.poll(job)
    assert isinstance(status, AgentStatus)
    assert status.state == "done"
    assert status.progress == 1.0


def test_poll_takes_n_polls_when_configured(issue):
    agent = NoopAgent(polls_until_done=3)
    job = agent.assign(issue, brief="x")

    s1 = agent.poll(job)
    s2 = agent.poll(job)
    s3 = agent.poll(job)

    assert s1.state == "running"
    assert s2.state == "running"
    assert s3.state == "done"
    assert 0.0 < s1.progress < 1.0


def test_poll_rejects_foreign_job(issue):
    agent = NoopAgent()
    foreign_job = AgentJob(
        job_id="x", agent_kind="copilot",
        fork_slug="x/y", branch_name="b",
    )
    with pytest.raises(ValueError, match="cannot poll"):
        agent.poll(foreign_job)


# ── NoopAgent.harvest ─────────────────────────────────────────────────────


def test_harvest_returns_canned_default_result(issue):
    agent = NoopAgent()
    job = agent.assign(issue, brief="x")
    result = agent.harvest(job)

    assert isinstance(result, AgentResult)
    assert result.exit_reason == "success"
    assert result.commit_shas == ["a1b2c3d4e5"]
    assert result.files_touched == ["src/example.py"]
    assert "noop agent canned fix" in result.diff_text
    assert result.agent_log


def test_harvest_returns_configured_empty_diff(issue):
    """Used to exercise the diff_non_empty gate failure path."""
    agent = NoopAgent(diff_text="", files_touched=[], commit_shas=[])
    job = agent.assign(issue, brief="x")
    result = agent.harvest(job)
    assert result.diff_text == ""
    assert result.commit_shas == []


def test_harvest_returns_configured_failure(issue):
    """Used to exercise the 'agent reported failure' path."""
    agent = NoopAgent(exit_reason="error", agent_log="canned failure")
    job = agent.assign(issue, brief="x")
    result = agent.harvest(job)
    assert result.exit_reason == "error"
    assert result.agent_log == "canned failure"


def test_harvest_returns_configured_pr_url(issue):
    agent = NoopAgent(pr_url="https://github.com/WolffM/markitdown/pull/9")
    job = agent.assign(issue, brief="x")
    result = agent.harvest(job)
    assert result.pr_url == "https://github.com/WolffM/markitdown/pull/9"


def test_harvest_rejects_foreign_job(issue):
    agent = NoopAgent()
    foreign_job = AgentJob(
        job_id="x", agent_kind="copilot",
        fork_slug="x/y", branch_name="b",
    )
    with pytest.raises(ValueError, match="cannot harvest"):
        agent.harvest(foreign_job)


# ── full lifecycle ────────────────────────────────────────────────────────


def test_full_assign_poll_harvest_lifecycle(issue):
    agent = NoopAgent(polls_until_done=2)
    job = agent.assign(issue, brief="reproduce + fix the bug")

    # Poll until done
    statuses = []
    for _ in range(5):
        s = agent.poll(job)
        statuses.append(s.state)
        if s.state == "done":
            break

    assert statuses == ["running", "done"]
    result = agent.harvest(job)
    assert result.exit_reason == "success"
