"""End-to-end pipeline test with NoopAgent — Phase 1E.1.

Walks a fake issue through every state of the IssueWorkflow using:
  - real EvidenceStore (writes real files)
  - real sanitizer (real scrub_brief + scan_outputs)
  - real mechanical gates (registered via the @gate decorator)
  - NoopAgent for all agent phases
  - mocked aggregator HTTP (no network)
  - mocked gh runner (no GitHub)
  - mocked claude CLI for judge gates (deterministic pass)

Verifies the issue reaches `submitted` and the evidence directory
contains every artifact the state machine schema expects.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from temporal.activities.eligibility import check_eligibility
from temporal.activities.environment import setup_environment
from temporal.activities.fork import fork_and_scrub_brief
from temporal.activities.review import run_review
from temporal.activities.submission import render_pr_body, submit_upstream_pr
from temporal.agents import IssueRef
from temporal.agents.noop import NoopAgent
from temporal.evidence.store import EvidenceStore
from temporal.judge import JudgeResult
from temporal.temporal_activities import (
    AgentPhaseInput,
    EligibilityInput,
    EnvironmentInput,
    ForkInput,
    GateInput,
    InboxInput,
    NotifyHumanCommentsInput,
    ReadReviewSummaryInput,
    RemediationInput,
    RenderInput,
    ReplicateInput,
    ReviewInput,
    SubmitInput,
    TransitionInput,
    WatchPRInput,
)
from temporal.workflows import IssueInput, IssueResult, IssueWorkflow


# ── Fake external services ────────────────────────────────────────────────


def _fake_aggregator_get(endpoint: str):
    """Return canned aggregator envelopes for every endpoint."""
    if "health" in endpoint:
        return {"success": True, "data": {"maintainerHealthScore": 80}}
    if "dossier" in endpoint:
        return {"success": True, "data": {
            "sections": [],
            "slug": "microsoft/markitdown",
        }}
    if "issue-brief" in endpoint:
        return {"success": True, "data": {
            "issue": {
                "title": "Fix the merged-cell bug",
                "body": "When loading merged.xlsx the converter returns empty cells for merged-range anchors.",
                "state": "open",
                "assignee": None,
            },
        }}
    if "contributing" in endpoint:
        return {"success": True, "data": {
            "ai_policy": "unknown",
            "dco_required": False,
            "license_check_required": False,
        }}
    if "pr-template" in endpoint:
        return {"success": True, "data": {
            "path": None, "raw_text": None, "sections": [], "front_matter": None,
        }}
    raise AssertionError(f"unexpected aggregator endpoint: {endpoint}")


def _fake_gh(args, stdin_data=None):
    """Pretend the fork already exists; pretend gh pr create succeeds."""
    if args[:2] == ["pr", "create"]:
        return {"success": True, "output": "https://github.com/microsoft/markitdown/pull/8888\n"}
    # submit_upstream_pr reads the fork preview PR's live title+body
    # via `gh api repos/{fork}/pulls/{N}`. Return a clean stub so the
    # post-signoff sanitizer + gh pr create both succeed.
    if (
        len(args) > 1 and args[0] == "api"
        and "/pulls/" in args[1] and "--jq" in args
    ):
        return {
            "success": True,
            "output": '{"title":"Fix the merged-cell bug","body":"## Summary\\n\\nClean operator-edited body.\\n"}',
        }
    return {"success": True, "output": "{}"}


def _fake_judge_score(rubric: str, payload: str) -> JudgeResult:
    return JudgeResult(
        verdict="pass", score=0.92,
        reasoning="e2e fake judge: passing",
        raw={"verdict": "pass", "score": 0.92},
    )


def _ev(state_root: str) -> EvidenceStore:
    return EvidenceStore(Path(state_root))


_NOTES_BODY = (
    "## Steps to reproduce\n\n"
    "1. Open the merged.xlsx fixture in the converter\n"
    "2. Look at cell A2 in the merged-range section of the workbook\n"
    "3. Compare the converter output to the expected text\n"
    "4. Note the empty string instead of the header label\n\n"
    "## Observed\n\n"
    "The xlsx converter returns an empty string for cells that are part of a merged range "
    "but are not the anchor cell of the merge.\n\n"
    "## Expected\n\n"
    "The converter should resolve the merged-range anchor and return the header text from "
    "the anchor cell when reading any cell in the merged range.\n"
)


# ── Module-level Temporal activity definitions ────────────────────────────
# Defined at module level so type hints resolve correctly when Temporal
# inspects them at registration time.


@activity.defn(name="check_eligibility")
async def real_eligibility(inp: EligibilityInput) -> dict:
    return check_eligibility(
        inp.upstream_slug, inp.issue_number, _ev(inp.state_root),
        aggregator_get=_fake_aggregator_get,
    )


@activity.defn(name="fork_and_scrub_brief")
async def real_fork(inp: ForkInput) -> dict:
    return fork_and_scrub_brief(
        upstream_slug=inp.upstream_slug,
        issue_number=inp.issue_number,
        raw_brief_text=inp.raw_brief_text,
        branch_name=inp.branch_name,
        evidence=_ev(inp.state_root),
        run_gh=_fake_gh,
    )


@activity.defn(name="setup_environment")
async def real_environment(inp: EnvironmentInput) -> dict:
    return setup_environment(
        fork_slug=inp.fork_slug,
        branch_name=inp.branch_name,
        workdir=inp.workdir,
        install_cmd=inp.install_cmd,
        evidence=_ev(inp.state_root),
        runner=lambda cmd, cwd, timeout: {"success": True, "output": "ok", "error": "", "returncode": 0},
    )


@activity.defn(name="request_repro")
async def real_repro(inp: AgentPhaseInput) -> dict:
    from temporal.activities.agent import request_repro
    ev = _ev(inp.state_root)
    result = await request_repro(
        NoopAgent(),
        IssueRef(fork_slug=inp.fork_slug, number=inp.issue_number, upstream_slug=inp.upstream_slug),
        ev.read_text("02-forked/scrubbed_brief.md", default=""),
        ev,
    )
    # Seed evidence files the gate expects (NoopAgent doesn't touch the disk
    # for the repro artifact files; we stand in for that here)
    ev.write_text("04-reproduced/test.py", "def test_x():\n    assert False\n")
    ev.write_text("04-reproduced/notes.md", _NOTES_BODY)
    return result


@activity.defn(name="request_fix")
async def real_fix(inp: AgentPhaseInput) -> dict:
    from temporal.activities.agent import request_fix
    ev = _ev(inp.state_root)
    return await request_fix(
        NoopAgent(),
        IssueRef(fork_slug=inp.fork_slug, number=inp.issue_number, upstream_slug=inp.upstream_slug),
        ev.read_text("02-forked/scrubbed_brief.md", default=""),
        ev,
    )


@activity.defn(name="request_verify")
async def real_verify(inp: AgentPhaseInput) -> dict:
    from temporal.activities.agent import request_verify
    ev = _ev(inp.state_root)
    result = await request_verify(
        NoopAgent(),
        IssueRef(fork_slug=inp.fork_slug, number=inp.issue_number, upstream_slug=inp.upstream_slug),
        ev.read_text("02-forked/scrubbed_brief.md", default=""),
        ev,
    )
    ev.write_text("06-verified/test_output.txt", "1 passed in 0.5s")
    return result


@activity.defn(name="request_remediation")
async def real_remediation(inp: RemediationInput) -> dict:
    return {"ok": True}  # not exercised in the happy path


@activity.defn(name="run_review")
async def real_review(inp: ReviewInput) -> dict:
    return run_review(
        inp.fork_slug, inp.pr_number, _ev(inp.state_root),
        review_runner=lambda fs, pr: {"comments": []},
    )


@activity.defn(name="render_pr_body")
async def real_render(inp: RenderInput) -> dict:
    return render_pr_body(
        inp.upstream_slug, inp.issue_number, _ev(inp.state_root),
        aggregator_get=_fake_aggregator_get,
    )


@activity.defn(name="render_test_output_screenshot")
async def real_screenshot(inp) -> dict:
    """E2E stub: skip the chromium dance. Real coverage lives in
    test_screenshot.py; the e2e flow just needs the activity to
    return a dict so the workflow proceeds. NoopAgent doesn't produce
    test_output.txt anyway, so the real renderer would no-op too."""
    return {"ok": False, "reason": "noop e2e — screenshot stub"}


@activity.defn(name="run_test_command")
async def real_run_test_command(inp) -> dict:
    """E2E stub: skip the cktest sandbox dispatch. Real coverage lives
    in test_test_runner.py; the e2e flow just needs the activity to
    return a dict so the workflow proceeds. NoopAgent doesn't produce
    a test_command.txt anyway."""
    return {"ok": False, "reason": "noop e2e — test runner stub"}


@activity.defn(name="submit_upstream_pr")
async def real_submit(inp: SubmitInput) -> dict:
    return submit_upstream_pr(
        upstream_slug=inp.upstream_slug,
        fork_slug=inp.fork_slug,
        branch_name=inp.branch_name,
        base_branch=inp.base_branch,
        evidence=_ev(inp.state_root),
        issue_number=inp.issue_number,
        run_gh=_fake_gh,
    )


@activity.defn(name="replicate_fix_as_operator")
async def real_replicate(inp: ReplicateInput) -> dict:
    """E2E stub: pretend the squash + fork-preview-PR + draft close all
    succeeded. Rewrites 05-fixed/commits.json to the new single commit
    so downstream no_upstream_refs gate scans the right thing. A full
    real test of `replicate_fix_as_operator` lives in
    test_activities_replicate.py
    with a fully-scripted fake_gh."""
    ev = _ev(inp.state_root)
    if ev.exists("05-fixed/commits.json"):
        ev.write_json("05-fixed/agent_original_commits.json", ev.read_json("05-fixed/commits.json"))
    ev.write_json(
        "05-fixed/commits.json",
        [{"sha": "operator1234", "message": "fake squashed operator commit"}],
    )
    ev.write_json(
        "09-submittable/squashed_commit.json",
        {"sha": "operator1234", "message": "fake", "tree": "tree123", "parent": "base123"},
    )
    ev.write_text("09-submittable/operator_pr_url", f"https://github.com/{inp.fork_slug}/pull/42")
    ev.write_text("09-submittable/operator_pr_number", "42")
    return {
        "ok": True,
        "operator_pr_number": 42,
        "operator_pr_url": f"https://github.com/{inp.fork_slug}/pull/42",
        "squashed_commit_sha": "operator1234",
    }


@activity.defn(name="run_gates")
async def real_run_gates(inp: GateInput) -> list[dict]:
    """Run the real gate registry with judge calls patched out."""
    with patch("temporal.gates.fix.judge_score", _fake_judge_score), \
         patch("temporal.gates.submission.judge_score", _fake_judge_score):
        from temporal.gates import IssueRef as GateIssueRef
        from temporal.gates import run_gates as run_gates_fn
        from temporal.gates import (  # noqa: F401  — populates the registry
            eligibility,
            environment,
            fix,
            input_context_clean,
            remediation,
            repro,
            submission,
            verify,
        )
        ev = _ev(inp.state_root)
        issue = GateIssueRef(
            fork_slug=inp.fork_slug,
            upstream_slug=inp.upstream_slug,
            upstream_number=inp.issue_number,
        )
        results = run_gates_fn(inp.state, issue, ev, pipeline=inp.pipeline)
        for r in results:
            ev.record_gate(
                gate_name=r.name,
                verdict=r.verdict,
                reason=r.reason,
                evidence_data=r.evidence_data,
            )
        return [
            {"name": r.name, "verdict": r.verdict, "reason": r.reason, "score": r.score, "kind": r.kind}
            for r in results
        ]


@activity.defn(name="enqueue_for_human_review")
async def real_enqueue(inp: InboxInput) -> dict:
    from temporal.activities.inbox import enqueue_for_human_review
    return enqueue_for_human_review(
        state=inp.state,
        gate_name=inp.gate_name,
        reason=inp.reason,
        score=inp.score,
        upstream_slug=inp.upstream_slug,
        issue_number=inp.issue_number,
        evidence=_ev(inp.state_root),
        notify=lambda m, **kw: None,
    )


@activity.defn(name="record_transition")
async def real_transition(inp: TransitionInput) -> dict:
    ev = _ev(inp.state_root)
    ev.record_transition(inp.from_state, inp.to_state, inp.reason, inp.decided_by)
    return {"ok": True}


@activity.defn(name="read_review_summary")
async def real_read_review_summary(inp: ReadReviewSummaryInput) -> dict:
    from temporal.activities.review import read_review_summary
    return read_review_summary(_ev(inp.state_root))


@activity.defn(name="watch_upstream_pr_state")
async def real_watch_upstream_pr_state(inp: WatchPRInput) -> dict:
    """E2E: pretend the upstream PR merged on the first poll so the
    Phase 5.1 post-submission loop exits cleanly without hitting
    networked gh calls."""
    ev = _ev(inp.state_root)
    ev.write_json("11-merged/merge_info.json", {
        "merge_sha": "e2e_merge_sha", "merged_at": "2026-04-26T12:00:00Z",
        "merged_by": "e2e_maintainer", "upstream_slug": inp.upstream_slug,
        "pr_number": inp.pr_number,
    })
    ev.write_text("11-merged/merge_sha", "e2e_merge_sha")
    return {
        "ok": True,
        "state": "closed", "merged": True,
        "merged_at": "2026-04-26T12:00:00Z",
        "merge_sha": "e2e_merge_sha",
        "closed_at": None, "closer": None,
        "closed_unmerged": False,
        "new_blocking_review": False,
        "new_blocking_review_id": None,
        "new_blocking_review_user": None,
        "new_blocking_review_body": None,
        "all_seen_review_ids": list(inp.seen_review_ids or []),
        "error": None,
    }


@activity.defn(name="notify_human_comments_for_issue")
async def real_notify_human_comments(inp: NotifyHumanCommentsInput) -> dict:
    return {"ok": True, "new_count": 0, "seen_ids": list(inp.seen_comment_ids or [])}


_REAL_ACTIVITIES = [
    real_eligibility,
    real_fork,
    real_environment,
    real_repro,
    real_fix,
    real_verify,
    real_remediation,
    real_review,
    real_read_review_summary,
    real_run_test_command,
    real_screenshot,
    real_render,
    real_replicate,
    real_submit,
    real_run_gates,
    real_enqueue,
    real_transition,
    real_watch_upstream_pr_state,
    real_notify_human_comments,
]


# ── Test ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_noop_agent_full_pipeline(tmp_path):
    state_root = tmp_path / "issue-183"

    issue_input = IssueInput(
        upstream_slug="microsoft/markitdown",
        fork_slug="WolffM/markitdown",
        issue_number=183,
        state_root=str(state_root),
        raw_brief_text="Fix the merged-cell bug — see https://github.com/microsoft/markitdown/issues/183",
        branch_name="fix-merged-cells",
        install_cmd=["true"],
        workdir=str(tmp_path),
        pr_number_for_review=999,
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="e2e-tq",
            workflows=[IssueWorkflow],
            activities=_REAL_ACTIVITIES,
        ):
            handle = await env.client.start_workflow(
                IssueWorkflow.run,
                issue_input,
                id="e2e-issue-183",
                task_queue="e2e-tq",
            )
            # Phase 4.5: workflow pauses at awaiting_signoff because
            # submit_to_upstream=True. Sign off so the upstream
            # submission step runs.
            import asyncio as _asyncio
            await _asyncio.sleep(0.2)
            await handle.signal("submit_human_decision", "approve")
            result: IssueResult = await handle.result()

    # Workflow completed successfully — print the gate trail on failure.
    # Phase 5.1: the post-submission loop polls the watcher, sees an
    # immediate merged result, and ends in `merged` (not `submitted`).
    if result.final_state != "merged":
        ev_diag = EvidenceStore(state_root)
        gates_log = ev_diag.read_jsonl("gates.jsonl")
        transitions_log = ev_diag.read_jsonl("transitions.jsonl")
        msg = (
            f"workflow aborted: {result.abort_reason}\n"
            f"transitions: {[(t.get('from'), t.get('to')) for t in transitions_log]}\n"
            f"gates: {[(g.get('gate'), g.get('verdict'), g.get('reason')) for g in gates_log]}"
        )
        raise AssertionError(msg)

    assert result.upstream_pr_number == 8888

    # Evidence directory has every expected artifact
    ev = EvidenceStore(state_root)
    assert ev.exists("01-eligible/dossier.json")
    assert ev.exists("01-eligible/issue_brief.json")
    assert ev.exists("01-eligible/contributing_check.json")

    assert ev.exists("02-forked/fork_url")
    assert ev.exists("02-forked/branch_name")
    assert ev.exists("02-forked/scrubbed_brief.md")
    assert ev.exists("02-forked/scrub_report.json")

    # The scrubbed brief must not contain the upstream URL/short-ref/slug
    scrubbed = ev.read_text("02-forked/scrubbed_brief.md")
    assert "microsoft/markitdown" not in scrubbed
    assert "github.com" not in scrubbed
    report = ev.read_json("02-forked/scrub_report.json")
    assert report["count"] >= 1

    assert ev.exists("03-environment/health.json")
    assert ev.read_json("03-environment/health.json")["installable"] is True

    assert ev.exists("04-reproduced/test.py")
    assert ev.exists("04-reproduced/notes.md")

    assert ev.exists("05-fixed/diff.patch")
    assert ev.exists("05-fixed/commit_shas.txt")
    assert ev.exists("05-fixed/files_touched.txt")

    assert ev.exists("06-verified/test_output.txt")

    assert ev.exists("07-reviewed/comments.json")
    assert ev.exists("07-reviewed/severity_summary.json")

    assert ev.exists("09-submittable/pr_title.txt")
    assert ev.exists("09-submittable/pr_body.md")
    assert ev.exists("09-submittable/sanitizer_scan.json")

    assert ev.exists("10-submitted/upstream_pr_url")

    # The transitions log captured every state
    transitions = ev.read_jsonl("transitions.jsonl")
    states_visited = [t["to"] for t in transitions]
    assert "eligible" in states_visited
    assert "forked" in states_visited
    assert "fixed" in states_visited
    assert "submitted" in states_visited

    # gates.jsonl has at least one entry per gate-bearing state
    gates = ev.read_jsonl("gates.jsonl")
    gate_names = {g["gate"] for g in gates}
    assert "eligibility" in gate_names
    assert "input_context_clean" in gate_names
    assert "diff_non_empty" in gate_names
    assert "no_upstream_refs" in gate_names
