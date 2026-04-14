"""Workflow tests — Phase 1D.1 + 1D.2.

Uses temporalio.testing.WorkflowEnvironment (in-memory time-skipping
cluster) to drive IssueWorkflow + BatchWorkflow end-to-end with mocked
activities. The activities are replaced with fakes that write evidence
files directly so the gates pass / fail / defer as the test wants.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from temporal.temporal_activities import (
    AgentPhaseInput,
    EligibilityInput,
    EnvironmentInput,
    ForkInput,
    GateInput,
    GateOutcome,
    InboxInput,
    RemediationInput,
    RenderInput,
    ReviewInput,
    SubmitInput,
    TransitionInput,
)
from temporal.workflows import (
    BatchInput,
    BatchWorkflow,
    IssueInput,
    IssueResult,
    IssueWorkflow,
)


# ── Per-test fake activities ──────────────────────────────────────────────


@activity.defn(name="check_eligibility")
async def fake_eligibility(inp: EligibilityInput) -> dict:
    Path(inp.state_root).mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@activity.defn(name="fork_and_scrub_brief")
async def fake_fork(inp: ForkInput) -> dict:
    Path(inp.state_root).mkdir(parents=True, exist_ok=True)
    return {"ok": True, "scrub_count": 0}


@activity.defn(name="setup_environment")
async def fake_environment(inp: EnvironmentInput) -> dict:
    return {"ok": True, "installable": True}


@activity.defn(name="request_repro")
async def fake_repro(inp: AgentPhaseInput) -> dict:
    return {"ok": True}


@activity.defn(name="request_fix")
async def fake_fix(inp: AgentPhaseInput) -> dict:
    return {"ok": True}


@activity.defn(name="request_verify")
async def fake_verify(inp: AgentPhaseInput) -> dict:
    return {"ok": True}


@activity.defn(name="request_remediation")
async def fake_remediation(inp: RemediationInput) -> dict:
    return {"ok": True}


@activity.defn(name="run_review")
async def fake_review(inp: ReviewInput) -> dict:
    return {"ok": True}


@activity.defn(name="render_pr_body")
async def fake_render(inp: RenderInput) -> dict:
    return {"ok": True}


@activity.defn(name="submit_upstream_pr")
async def fake_submit(inp: SubmitInput) -> dict:
    return {
        "ok": True,
        "pr_url": f"https://github.com/{inp.upstream_slug}/pull/9999",
        "pr_number": 9999,
    }


# Module-level switch for run_gates so each test can dictate the verdicts.
# Stored as dicts because that's how the real activity returns them.
_FAKE_GATE_RESULTS: dict[str, list[dict]] = {}


@activity.defn(name="run_gates")
async def fake_run_gates(inp: GateInput) -> list[dict]:
    return list(_FAKE_GATE_RESULTS.get(inp.state, []))


@activity.defn(name="enqueue_for_human_review")
async def fake_enqueue(inp: InboxInput) -> dict:
    return {"ok": True}


@activity.defn(name="record_transition")
async def fake_transition(inp: TransitionInput) -> dict:
    return {"ok": True}


_FAKE_ACTIVITIES = [
    fake_eligibility,
    fake_fork,
    fake_environment,
    fake_repro,
    fake_fix,
    fake_verify,
    fake_remediation,
    fake_review,
    fake_render,
    fake_submit,
    fake_run_gates,
    fake_enqueue,
    fake_transition,
]


def _gate_pass(name: str) -> dict:
    return {"name": name, "verdict": "pass", "reason": "", "score": None, "kind": "mechanical"}


def _gate_fail(name: str, reason: str = "x") -> dict:
    return {"name": name, "verdict": "fail", "reason": reason, "score": None, "kind": "mechanical"}


def _gate_defer(name: str, reason: str = "borderline") -> dict:
    return {"name": name, "verdict": "defer", "reason": reason, "score": 0.55, "kind": "judge"}


def _set_all_gates_pass():
    _FAKE_GATE_RESULTS.clear()
    for state in (
        "eligible", "forked", "environment_ready", "reproduced",
        "fixed", "verified", "remediated", "submittable",
    ):
        _FAKE_GATE_RESULTS[state] = [_gate_pass("ok")]


# ── Test harness ──────────────────────────────────────────────────────────


@pytest.fixture
def issue_input(tmp_path: Path) -> IssueInput:
    return IssueInput(
        upstream_slug="microsoft/markitdown",
        fork_slug="WolffM/markitdown",
        issue_number=183,
        state_root=str(tmp_path / "issue-183"),
        raw_brief_text="fix the merged-cell bug",
        branch_name="fix-merged-cells",
    )


@pytest.fixture(autouse=True)
def _reset_gate_results():
    _FAKE_GATE_RESULTS.clear()
    yield
    _FAKE_GATE_RESULTS.clear()


async def _run_workflow(issue_input: IssueInput) -> IssueResult:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=_FAKE_ACTIVITIES,
        ):
            return await env.client.execute_workflow(
                IssueWorkflow.run,
                issue_input,
                id=f"issue-{issue_input.issue_number}",
                task_queue="test-tq",
            )


# ── 1D.1 — IssueWorkflow tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_workflow_happy_path(issue_input):
    """Every gate passes → workflow reaches `submitted`."""
    _set_all_gates_pass()

    result = await _run_workflow(issue_input)

    assert result.final_state == "submitted"
    assert result.upstream_pr_number == 9999
    assert "9999" in result.upstream_pr_url


@pytest.mark.asyncio
async def test_issue_workflow_aborts_on_gate_failure(issue_input):
    """A failing gate aborts the workflow with a clear reason."""
    _set_all_gates_pass()
    _FAKE_GATE_RESULTS["fixed"] = [_gate_fail("diff_non_empty", "diff is empty")]

    result = await _run_workflow(issue_input)

    assert result.final_state == "aborted"
    assert "diff_non_empty" in result.abort_reason
    assert "diff is empty" in result.abort_reason


@pytest.mark.asyncio
async def test_issue_workflow_defer_then_operator_approve_continues(issue_input):
    """A judge defer pauses the workflow; an `approve` signal resumes it."""
    _set_all_gates_pass()
    _FAKE_GATE_RESULTS["fixed"] = [_gate_defer("relevance", "borderline")]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=_FAKE_ACTIVITIES,
        ):
            handle = await env.client.start_workflow(
                IssueWorkflow.run,
                issue_input,
                id=f"issue-{issue_input.issue_number}-defer",
                task_queue="test-tq",
            )
            # Give the workflow a moment to reach the wait_condition
            await asyncio.sleep(0.1)
            # Now flip the gate so that on the next gate run after approval
            # the workflow can proceed (relevance pass).
            _FAKE_GATE_RESULTS["fixed"] = [_gate_pass("relevance")]
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    assert result.final_state == "submitted"


@pytest.mark.asyncio
async def test_issue_workflow_defer_then_operator_abort_aborts(issue_input):
    """A judge defer + `abort` signal → aborted state."""
    _set_all_gates_pass()
    _FAKE_GATE_RESULTS["submittable"] = [_gate_defer("submission_judge", "thin body")]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=_FAKE_ACTIVITIES,
        ):
            handle = await env.client.start_workflow(
                IssueWorkflow.run,
                issue_input,
                id=f"issue-{issue_input.issue_number}-abort",
                task_queue="test-tq",
            )
            await asyncio.sleep(0.1)
            await handle.signal("submit_human_decision", "abort")
            result = await handle.result()

    assert result.final_state == "aborted"
    assert "operator aborted" in result.abort_reason
    assert result.deferred_at == "submittable"
    assert result.deferred_gate == "submission_judge"


# ── 1D.2 — BatchWorkflow test ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_workflow_fans_out_to_children(tmp_path):
    _set_all_gates_pass()

    issues = [
        IssueInput(
            upstream_slug="microsoft/markitdown",
            fork_slug="WolffM/markitdown",
            issue_number=n,
            state_root=str(tmp_path / f"issue-{n}"),
            raw_brief_text=f"fix bug {n}",
            branch_name=f"fix-{n}",
        )
        for n in (101, 102, 103)
    ]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=_FAKE_ACTIVITIES,
        ):
            result = await env.client.execute_workflow(
                BatchWorkflow.run,
                BatchInput(batch_id="test-batch", issues=issues),
                id="batch-test",
                task_queue="test-tq",
            )

    assert result.batch_id == "test-batch"
    assert result.total == 3
    assert result.submitted == 3
    assert result.aborted == 0
