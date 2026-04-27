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
from datetime import timedelta
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
    NotifyHumanCommentsInput,
    RemediationInput,
    RenderInput,
    ReplicateInput,
    ReviewInput,
    SubmitInput,
    TransitionInput,
    WatchPRInput,
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


@activity.defn(name="replicate_fix_as_operator")
async def fake_replicate(inp: ReplicateInput) -> dict:
    return {
        "ok": True,
        "operator_pr_number": 123,
        "operator_pr_url": f"https://github.com/{inp.fork_slug}/pull/123",
        "squashed_commit_sha": "abc1234deadbeef",
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


# Phase 5.1: queue of watch poll results — each test pops the next one,
# defaulting to "merged" once the queue empties so the workflow exits.
_FAKE_WATCH_RESULTS: list[dict] = []
_FAKE_WATCH_DEFAULT: dict = {}


def _watch_poll_default_merged() -> dict:
    return {
        "ok": True,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-04-26T00:00:00Z",
        "merge_sha": "merge_sha_default",
        "closed_at": None,
        "closer": None,
        "closed_unmerged": False,
        "new_blocking_review": False,
        "new_blocking_review_id": None,
        "new_blocking_review_user": None,
        "new_blocking_review_body": None,
        "all_seen_review_ids": [],
        "error": None,
    }


def _watch_poll_no_change() -> dict:
    return {
        "ok": True,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "merge_sha": None,
        "closed_at": None,
        "closer": None,
        "closed_unmerged": False,
        "new_blocking_review": False,
        "new_blocking_review_id": None,
        "new_blocking_review_user": None,
        "new_blocking_review_body": None,
        "all_seen_review_ids": [],
        "error": None,
    }


@activity.defn(name="watch_upstream_pr_state")
async def fake_watch_upstream_pr_state(inp: WatchPRInput) -> dict:
    if _FAKE_WATCH_RESULTS:
        return _FAKE_WATCH_RESULTS.pop(0)
    return _FAKE_WATCH_DEFAULT or _watch_poll_default_merged()


@activity.defn(name="notify_human_comments_for_issue")
async def fake_notify_human_comments(inp: NotifyHumanCommentsInput) -> dict:
    return {"ok": True, "new_count": 0, "seen_ids": list(inp.seen_comment_ids or [])}


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
    fake_replicate,
    fake_submit,
    fake_run_gates,
    fake_enqueue,
    fake_transition,
    fake_watch_upstream_pr_state,
    fake_notify_human_comments,
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
    _FAKE_WATCH_RESULTS.clear()
    global _FAKE_WATCH_DEFAULT
    _FAKE_WATCH_DEFAULT = {}
    yield
    _FAKE_GATE_RESULTS.clear()
    _FAKE_WATCH_RESULTS.clear()
    _FAKE_WATCH_DEFAULT = {}


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
    """Every gate passes + operator signs off + upstream merges →
    workflow reaches `merged` and execution completes.

    With submit_to_upstream=True the workflow pauses at awaiting_signoff;
    the test sends the `approve` signal to unblock submission. The
    Phase 5.1 post-submission loop then polls upstream — the default
    fake watcher returns `merged=True` on the first poll, so the
    workflow exits cleanly.
    """
    _set_all_gates_pass()
    from dataclasses import replace
    issue_input = replace(issue_input, submit_to_upstream=True)

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
                id=f"issue-{issue_input.issue_number}-happy",
                task_queue="test-tq",
            )
            # Give the workflow time to reach the awaiting_signoff wait
            await asyncio.sleep(0.1)
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    assert result.final_state == "merged"
    assert result.upstream_pr_number == 9999
    assert "9999" in result.upstream_pr_url


@pytest.mark.asyncio
async def test_issue_workflow_stops_at_replicated_by_default(issue_input):
    """Default: `submit_to_upstream=False` → workflow terminates cleanly
    after `replicate_fix_as_operator`, leaving the fork-internal preview
    PR for the operator to review before real-upstream shipping."""
    _set_all_gates_pass()

    result = await _run_workflow(issue_input)

    assert result.final_state == "replicated"
    assert result.upstream_pr_url == ""
    assert result.upstream_pr_number is None


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
    """A judge defer pauses the workflow; an `approve` signal resumes it.

    Uses submit_to_upstream=False so the workflow terminates at
    `replicated` without a second signal-wait — keeps this test focused
    on the defer-resume path. The two-wait happy path is covered by
    test_issue_workflow_happy_path.
    """
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
            _FAKE_GATE_RESULTS["fixed"] = [_gate_pass("relevance")]
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    assert result.final_state == "replicated"


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

    # submit_to_upstream omitted (default False) so each child terminates
    # at `replicated` without waiting for an operator-signoff signal —
    # this test is about fan-out shape, not the upstream-submission
    # subset of the state machine.
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
    assert result.aborted == 0
    # All 3 reach `replicated` — fan-out worked end to end without
    # any child crashing or being silently dropped.
    assert all(r.final_state == "replicated" for r in result.results)


@pytest.mark.asyncio
async def test_copilot_activities_route_to_configured_queue(tmp_path):
    """When `copilot_task_queue` is set on the input, the Copilot-bound
    activities (request_repro/fix/verify/remediation) schedule on THAT
    queue, while everything else stays on the workflow's own queue.

    Verified end-to-end: the test runs two Workers — one for the main
    task queue (workflow + non-Copilot activities) and one for a
    separate copilot queue (only Copilot activities). If the routing
    works, the workflow completes to replicated. If it's wrong, it
    hangs because the wrong queue is missing the activity.
    """
    _set_all_gates_pass()

    issues = [
        IssueInput(
            upstream_slug="microsoft/markitdown",
            fork_slug="WolffM/markitdown",
            issue_number=n,
            state_root=str(tmp_path / f"issue-{n}"),
            raw_brief_text=f"fix bug {n}",
            branch_name=f"fix-{n}",
            copilot_task_queue="test-copilot-tq",
            # Default submit_to_upstream=False — terminate at replicated
            # without an operator-signoff signal pause
        )
        for n in (301, 302)
    ]

    main_activities = [
        fake_eligibility, fake_fork, fake_environment,
        fake_review, fake_render, fake_replicate, fake_submit,
        fake_run_gates, fake_enqueue, fake_transition,
    ]
    copilot_activities = [fake_repro, fake_fix, fake_verify, fake_remediation]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=main_activities,
        ), Worker(
            env.client,
            task_queue="test-copilot-tq",
            activities=copilot_activities,
            max_concurrent_activities=2,
        ):
            result = await env.client.execute_workflow(
                BatchWorkflow.run,
                BatchInput(batch_id="routed-batch", issues=issues),
                id="batch-routed",
                task_queue="test-tq",
            )

    assert result.total == 2
    assert result.aborted == 0
    assert all(r.final_state == "replicated" for r in result.results)


# ── Phase 5.1 — Post-submission lifecycle ─────────────────────────────────


def _watch_merged() -> dict:
    return {**_watch_poll_no_change(), "merged": True, "merge_sha": "MERGE_SHA",
            "merged_at": "2026-04-26T12:00:00Z", "state": "closed"}


def _watch_closed_unmerged(closer: str = "maintainer") -> dict:
    return {**_watch_poll_no_change(), "state": "closed", "closed_unmerged": True,
            "closed_at": "2026-04-26T12:00:00Z", "closer": closer}


def _watch_blocking_review(rid: int = 7777, user: str = "maintainer") -> dict:
    r = _watch_poll_no_change()
    r.update({
        "new_blocking_review": True,
        "new_blocking_review_id": rid,
        "new_blocking_review_user": user,
        "new_blocking_review_body": "needs more work",
        "all_seen_review_ids": [rid],
    })
    return r


def _watch_transient_failure() -> dict:
    return {**_watch_poll_no_change(), "ok": False, "error": "transient gh 503"}


@pytest.mark.asyncio
async def test_post_submission_merged_terminates_workflow(issue_input):
    """Acceptance: merged upstream PR transitions to merged + workflow ends."""
    _set_all_gates_pass()
    from dataclasses import replace
    issue_input = replace(issue_input, submit_to_upstream=True)

    _FAKE_WATCH_RESULTS.extend([
        _watch_poll_no_change(),
        _watch_poll_no_change(),
        _watch_merged(),
    ])

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
                id=f"issue-{issue_input.issue_number}-merged",
                task_queue="test-tq",
            )
            await asyncio.sleep(0.1)
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    assert result.final_state == "merged"
    assert result.upstream_pr_number == 9999
    # All scripted polls + the default no-change tail consumed up to merged
    assert _FAKE_WATCH_RESULTS == []


@pytest.mark.asyncio
async def test_post_submission_closed_unmerged_transitions_to_closed_by_upstream(issue_input):
    """Acceptance: closed-without-merge → workflow ends in closed_by_upstream."""
    _set_all_gates_pass()
    from dataclasses import replace
    issue_input = replace(issue_input, submit_to_upstream=True)

    _FAKE_WATCH_RESULTS.extend([
        _watch_poll_no_change(),
        _watch_closed_unmerged(closer="grumpy-maintainer"),
    ])

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
                id=f"issue-{issue_input.issue_number}-closed",
                task_queue="test-tq",
            )
            await asyncio.sleep(0.1)
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    assert result.final_state == "closed_by_upstream"
    assert result.upstream_pr_number == 9999
    assert "closed without merge" in result.abort_reason


@pytest.mark.asyncio
async def test_post_submission_blocking_review_runs_remediation_then_re_signoff(
    issue_input, monkeypatch,
):
    """Acceptance: blocking review → remediation → updated preview PR →
    re-enter awaiting_signoff. Operator approves the remediated content;
    on the next poll the upstream PR merges and the workflow ends."""
    _set_all_gates_pass()
    from dataclasses import replace
    issue_input = replace(issue_input, submit_to_upstream=True)

    # The workflow has TWO awaiting_signoff waits in this scenario (initial
    # submission + post-remediation). Under time-skipping the 14-day
    # wait_condition timeout fires near-instantly between signals — shorten
    # it so the test's signal arrival window is wide enough.
    import temporal.workflows.issue_workflow as ifw
    monkeypatch.setattr(ifw, "_OPERATOR_SIGNOFF_TIMEOUT", timedelta(seconds=30))

    # First poll surfaces a blocking review; after remediation cycle
    # finishes (request_remediation + replicate + new awaiting_signoff +
    # operator approve + re-submit), the next poll finds it merged.
    _FAKE_WATCH_RESULTS.extend([
        _watch_blocking_review(rid=42, user="grumpy-maintainer"),
        _watch_merged(),
    ])

    # Track activity invocations to verify the remediation path fired.
    remediation_calls: list[RemediationInput] = []
    replicate_calls: list[ReplicateInput] = []
    submit_calls: list[SubmitInput] = []

    @activity.defn(name="request_remediation")
    async def tracking_remediation(inp: RemediationInput) -> dict:
        remediation_calls.append(inp)
        return {"ok": True}

    @activity.defn(name="replicate_fix_as_operator")
    async def tracking_replicate(inp: ReplicateInput) -> dict:
        replicate_calls.append(inp)
        return {
            "ok": True,
            "operator_pr_number": 123,
            "operator_pr_url": f"https://github.com/{inp.fork_slug}/pull/123",
            "squashed_commit_sha": f"SHA_{len(replicate_calls)}",
        }

    @activity.defn(name="submit_upstream_pr")
    async def tracking_submit(inp: SubmitInput) -> dict:
        submit_calls.append(inp)
        return {
            "ok": True,
            "pr_url": f"https://github.com/{inp.upstream_slug}/pull/9999",
            "pr_number": 9999,
        }

    activities = [a for a in _FAKE_ACTIVITIES
                  if a.__name__ not in {
                      "fake_remediation", "fake_replicate", "fake_submit",
                  }]
    activities += [tracking_remediation, tracking_replicate, tracking_submit]

    async def signal_approver(handle):
        """Continuously signal `approve` so each awaiting_signoff wait
        completes as soon as the workflow reaches it. Each signal triggers
        a workflow activation which pauses time-skipping; this keeps the
        14-day wait_condition timeout from firing between waits."""
        while True:
            try:
                await handle.signal("submit_human_decision", "approve")
            except Exception:
                return
            await asyncio.sleep(0.05)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-tq",
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=activities,
        ):
            handle = await env.client.start_workflow(
                IssueWorkflow.run,
                issue_input,
                id=f"issue-{issue_input.issue_number}-blocked",
                task_queue="test-tq",
            )
            sig_task = asyncio.create_task(signal_approver(handle))
            try:
                result = await handle.result()
            finally:
                sig_task.cancel()

    assert result.final_state == "merged"
    # Remediation activity ran exactly once
    assert len(remediation_calls) == 1
    # Replicate ran twice — once for the original submission, once after
    # remediation
    assert len(replicate_calls) == 2
    # Submit ran twice — once for the initial open, once for the
    # post-remediation update (which under the real activity becomes
    # `gh pr edit`)
    assert len(submit_calls) == 2


@pytest.mark.asyncio
async def test_post_submission_transient_poll_failure_is_recoverable(issue_input):
    """Acceptance: poll failures (network blip, rate limit) don't abort
    the workflow — the next cycle retries and eventually succeeds."""
    _set_all_gates_pass()
    from dataclasses import replace
    issue_input = replace(issue_input, submit_to_upstream=True)

    _FAKE_WATCH_RESULTS.extend([
        _watch_transient_failure(),
        _watch_transient_failure(),
        _watch_poll_no_change(),
        _watch_merged(),
    ])

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
                id=f"issue-{issue_input.issue_number}-flaky",
                task_queue="test-tq",
            )
            await asyncio.sleep(0.1)
            await handle.signal("submit_human_decision", "approve")
            result = await handle.result()

    # The transient failures didn't abort the workflow — it merged
    # successfully on the fourth poll
    assert result.final_state == "merged"
