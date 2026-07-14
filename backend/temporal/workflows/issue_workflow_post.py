"""Post-submission flow — runs after IssueWorkflow reaches `submitted`.

Three free functions, each taking the workflow instance as `wf`:

- `post_submission_loop` — polls the upstream PR until merged / closed /
  stale; on a new blocking review, branches into `do_remediation_cycle`
  and loops back.
- `do_remediation_cycle` — agent re-fix → re-replicate → operator
  re-signoff → push update. Returns None on success (caller resumes
  polling) or an `IssueResult` if the cycle terminates the workflow.
- `terminate_stale` — finalize the workflow at `closed_by_upstream` when
  no upstream activity has occurred for `_POST_SUBMISSION_STALE_DAYS`.

Free-function shape (vs methods on `IssueWorkflow`) is deliberate: it
splits the 1200-line workflow file in half without paying the cost of a
multi-inheritance mixin. The functions access `wf.state` /
`wf.human_decision` / `wf._run_state_gates_or_defer(...)` by duck typing
— Temporal's determinism contract is satisfied as long as every
external touch goes through `workflow.execute_activity`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..temporal_activities import (
        InboxInput,
        NotifyHumanCommentsInput,
        RemediationInput,
        RenderInput,
        ReplicateInput,
        RunTestInput,
        ScreenshotInput,
        SubmitInput,
        TransitionInput,
        WatchPRInput,
    )

from .issue_workflow_types import (
    IssueInput,
    IssueResult,
    _LONG_ACTIVITY_TIMEOUT,
    _MAX_REMEDIATION_CYCLES,
    _OperatorAborted,
    _OPERATOR_SIGNOFF_TIMEOUT,
    _POLL_CADENCE_AFTER_ACTIVITY,
    _POLL_CADENCE_DEFAULT,
    _POST_SUBMISSION_STALE_DAYS,
    _SHORT_ACTIVITY_TIMEOUT,
)


async def post_submission_loop(
    wf,
    inp: IssueInput,
    upstream_pr_number: Optional[int],
    upstream_pr_url: str,
) -> IssueResult:
    """Watch the upstream PR until it merges, closes, or goes stale.

    On a new blocking review, branch into the remediation cycle (which
    re-uses request_remediation + replicate_fix_as_operator + the
    submittable gates + a fresh awaiting_signoff wait) and loop back
    in here on operator approve.

    Transient poll failures (network blip, rate limit) do NOT abort —
    the workflow sleeps the next cadence and retries.
    """
    if not upstream_pr_number:
        # No PR number means submit_upstream_pr didn't surface one. We
        # can't watch what we can't address; treat as already-submitted
        # terminal state so the workflow doesn't spin forever.
        return IssueResult(
            final_state="submitted",
            upstream_pr_url=upstream_pr_url,
            upstream_pr_number=None,
        )

    seen_review_ids: list[int] = []
    seen_comment_ids: list[int] = []
    last_activity_at = workflow.now()
    cadence = _POLL_CADENCE_DEFAULT
    remediation_cycles = 0

    while True:
        await workflow.sleep(cadence)

        # Comments first — fires Discord but doesn't drive transitions.
        try:
            comments_poll = await workflow.execute_activity(
                "notify_human_comments_for_issue",
                NotifyHumanCommentsInput(
                    upstream_slug=inp.upstream_slug,
                    pr_number=upstream_pr_number,
                    state_root=inp.state_root,
                    seen_comment_ids=seen_comment_ids,
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            comments_poll = {"ok": False}
        if isinstance(comments_poll, dict) and comments_poll.get("ok"):
            seen_comment_ids = comments_poll.get("seen_ids", seen_comment_ids)
            if comments_poll.get("new_count", 0) > 0:
                last_activity_at = workflow.now()

        # State + reviews — drives transitions.
        try:
            poll = await workflow.execute_activity(
                "watch_upstream_pr_state",
                WatchPRInput(
                    upstream_slug=inp.upstream_slug,
                    pr_number=upstream_pr_number,
                    state_root=inp.state_root,
                    seen_review_ids=seen_review_ids,
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            poll = {"ok": False}

        if not isinstance(poll, dict) or not poll.get("ok"):
            # Transient. Don't update last_activity_at — the upstream
            # may genuinely be quiet. Stale check still applies.
            if (workflow.now() - last_activity_at) > timedelta(days=_POST_SUBMISSION_STALE_DAYS):
                return await terminate_stale(
                    wf, inp, upstream_pr_number, upstream_pr_url,
                )
            cadence = _POLL_CADENCE_DEFAULT
            continue

        seen_review_ids = poll.get("all_seen_review_ids", seen_review_ids)

        if poll.get("merged"):
            await workflow.execute_activity(
                "record_transition",
                TransitionInput(
                    state_root=inp.state_root,
                    from_state=wf.state,
                    to_state="merged",
                    reason=f"upstream PR merged: {poll.get('merge_sha') or ''}",
                    decided_by="system:watcher",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
            wf.state = "merged"
            return IssueResult(
                final_state="merged",
                upstream_pr_url=upstream_pr_url,
                upstream_pr_number=upstream_pr_number,
            )

        if poll.get("closed_unmerged"):
            await workflow.execute_activity(
                "record_transition",
                TransitionInput(
                    state_root=inp.state_root,
                    from_state=wf.state,
                    to_state="closed_by_upstream",
                    reason=f"upstream PR closed without merge by {poll.get('closer') or 'unknown'}",
                    decided_by="system:watcher",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
            wf.state = "closed_by_upstream"
            return IssueResult(
                final_state="closed_by_upstream",
                upstream_pr_url=upstream_pr_url,
                upstream_pr_number=upstream_pr_number,
                abort_reason="upstream closed without merge",
            )

        if poll.get("new_blocking_review"):
            last_activity_at = workflow.now()
            cadence = _POLL_CADENCE_AFTER_ACTIVITY
            if remediation_cycles >= _MAX_REMEDIATION_CYCLES:
                wf.state = "aborted"
                return IssueResult(
                    final_state="aborted",
                    upstream_pr_url=upstream_pr_url,
                    upstream_pr_number=upstream_pr_number,
                    abort_reason=(
                        f"hit MAX_REMEDIATION_CYCLES={_MAX_REMEDIATION_CYCLES} "
                        f"on upstream PR #{upstream_pr_number}"
                    ),
                )
            remediation_cycles += 1
            outcome = await do_remediation_cycle(
                wf=wf,
                inp=inp,
                upstream_pr_number=upstream_pr_number,
                upstream_pr_url=upstream_pr_url,
                blocking_review_user=poll.get("new_blocking_review_user") or "",
            )
            if outcome is not None:
                return outcome
            # On success the workflow is back in `submitted`; resume polling.
            continue

        # No new info this cycle. Stale check + cadence relax.
        if (workflow.now() - last_activity_at) > timedelta(days=_POST_SUBMISSION_STALE_DAYS):
            return await terminate_stale(
                wf, inp, upstream_pr_number, upstream_pr_url,
            )
        cadence = _POLL_CADENCE_DEFAULT


async def do_remediation_cycle(
    wf,
    inp: IssueInput,
    upstream_pr_number: int,
    upstream_pr_url: str,
    blocking_review_user: str,
) -> Optional[IssueResult]:
    """Run one remediation cycle: agent re-fix → re-replicate → re-signoff.

    Returns None on success (workflow is back in `submitted` and the
    outer loop should resume polling). Returns an IssueResult only if
    the cycle terminates the workflow (operator abort, max cycles, etc.).
    """
    await workflow.execute_activity(
        "record_transition",
        TransitionInput(
            state_root=inp.state_root,
            from_state=wf.state,
            to_state="remediating_upstream",
            reason=(
                f"new blocking review from {blocking_review_user or 'maintainer'} "
                f"on upstream PR #{upstream_pr_number}"
            ),
            decided_by="system:watcher",
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
    )
    wf.state = "remediating_upstream"

    # Agent picks up the maintainer's comments and pushes more commits.
    # Routed to copilot-tq the same way request_fix etc. are routed.
    remediation_kwargs: dict = {
        "start_to_close_timeout": _LONG_ACTIVITY_TIMEOUT,
        "heartbeat_timeout": timedelta(minutes=2),
        "retry_policy": RetryPolicy(maximum_attempts=1),
    }
    if inp.copilot_task_queue:
        remediation_kwargs["task_queue"] = inp.copilot_task_queue
    await workflow.execute_activity(
        "request_remediation",
        RemediationInput(
            upstream_slug=inp.upstream_slug,
            fork_slug=inp.fork_slug,
            issue_number=inp.issue_number,
            state_root=inp.state_root,
        ),
        **remediation_kwargs,
    )

    # Re-render the PR title/body before replicate so the squashed
    # commit message reflects any post-remediation reframing. Same
    # dependency as the main path: replicate reads pr_title.txt.
    await workflow.execute_activity(
        "render_pr_body",
        RenderInput(
            upstream_slug=inp.upstream_slug,
            issue_number=inp.issue_number,
            state_root=inp.state_root,
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    # Re-replicate so the operator branch reflects the
    # post-remediation fix. Then test against that fresh branch and
    # render the body again with the fresh verification screenshot.
    # Same ordering reason as the main path: run_test_command needs
    # the operator branch to actually exist on the fork remote with
    # the latest commits — putting replicate after the test means
    # we'd be testing stale pre-remediation code.
    await workflow.execute_activity(
        "replicate_fix_as_operator",
        ReplicateInput(
            upstream_slug=inp.upstream_slug,
            fork_slug=inp.fork_slug,
            branch_name=inp.branch_name,
            state_root=inp.state_root,
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=2),
    )

    # Re-run the verify against the just-pushed operator branch so
    # the screenshot/body reflect the post-remediation fix, not
    # whatever was tested in the pre-remediation pass.
    await workflow.execute_activity(
        "run_test_command",
        RunTestInput(
            fork_slug=inp.fork_slug,
            branch_name=inp.branch_name,
            state_root=inp.state_root,
        ),
        start_to_close_timeout=_LONG_ACTIVITY_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    await workflow.execute_activity(
        "render_test_output_screenshot",
        ScreenshotInput(
            fork_slug=inp.fork_slug,
            issue_number=inp.issue_number,
            state_root=inp.state_root,
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=2),
    )
    await workflow.execute_activity(
        "render_pr_body",
        RenderInput(
            upstream_slug=inp.upstream_slug,
            issue_number=inp.issue_number,
            state_root=inp.state_root,
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=3),
    )

    await workflow.execute_activity(
        "record_transition",
        TransitionInput(
            state_root=inp.state_root,
            from_state=wf.state,
            to_state="submittable_v2",
            reason="remediation pushed; preview PR refreshed",
            decided_by="system:workflow",
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
    )
    wf.state = "submittable_v2"

    # Re-run the same submittable gate set (no_upstream_refs,
    # pr_template_compliance, submission_judge). A failure or operator
    # abort during defer terminates the workflow; that's the desired
    # behavior — we don't want to ship an updated PR that fails our
    # own gates.
    await wf._run_state_gates_or_defer("submittable", inp)

    # Re-enter awaiting_signoff with the same submission-failure
    # safety net as the initial signoff loop in IssueWorkflow.run:
    # if the upstream `gh pr edit` fails (e.g. PR closed by upstream
    # while we were remediating), loop back to the operator inbox
    # with the error rather than aborting the workflow.
    submission_error: str | None = None
    first_entry = True
    while True:
        base_reason = (
            f"remediation cycle complete; preview PR refreshed in response to "
            f"upstream review on PR #{upstream_pr_number}"
        )
        inbox_reason = (
            base_reason
            if submission_error is None
            else f"previous upstream-update attempt failed: {submission_error}. "
                 f"Edit the fork PR / fix root cause, then approve again, "
                 f"or signal abort."
        )
        await workflow.execute_activity(
            "enqueue_for_human_review",
            InboxInput(
                state="awaiting_signoff",
                gate_name="operator_signoff",
                reason=inbox_reason,
                score=None,
                upstream_slug=inp.upstream_slug,
                issue_number=inp.issue_number,
                state_root=inp.state_root,
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        if first_entry:
            await workflow.execute_activity(
                "record_transition",
                TransitionInput(
                    state_root=inp.state_root,
                    from_state=wf.state,
                    to_state="awaiting_signoff",
                    reason="awaiting operator signoff on remediated preview PR",
                    decided_by="system:workflow",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
            wf.state = "awaiting_signoff"
            first_entry = False

        await workflow.wait_condition(
            lambda: wf.human_decision is not None,
            timeout=_OPERATOR_SIGNOFF_TIMEOUT,
        )
        decision = wf.human_decision
        wf.human_decision = None
        if decision == "abort":
            raise _OperatorAborted(
                state="awaiting_signoff",
                gate_name="operator_signoff",
                reason=(
                    "operator declined remediated upstream submission"
                    if submission_error is None
                    else f"operator abandoned remediation after submission failure: {submission_error}"
                ),
            )

        # Approve / retry → push the updated content upstream. Because
        # 10-submitted/upstream_pr_number is recorded, submit_upstream_pr
        # uses `gh pr edit` instead of `gh pr create`, so the existing
        # upstream PR's title + body get updated. The branch was
        # force-pushed during replicate; the diff auto-updates.
        try:
            await workflow.execute_activity(
                "submit_upstream_pr",
                SubmitInput(
                    upstream_slug=inp.upstream_slug,
                    fork_slug=inp.fork_slug,
                    branch_name=inp.branch_name,
                    base_branch=inp.base_branch,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            # Success — exit loop
            break
        except Exception as e:
            submission_error = f"{type(e).__name__}: {str(e)[:300]}"
            try:
                await workflow.execute_activity(
                    "record_transition",
                    TransitionInput(
                        state_root=inp.state_root,
                        from_state="awaiting_signoff",
                        to_state="awaiting_signoff",
                        reason=f"submit_upstream_pr (remediation update) failed: {submission_error}",
                        decided_by="system:workflow",
                    ),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                )
            except Exception:
                pass
            # Loop back to operator inbox
            continue
    await workflow.execute_activity(
        "record_transition",
        TransitionInput(
            state_root=inp.state_root,
            from_state=wf.state,
            to_state="submitted",
            reason="remediated content pushed to upstream PR",
            decided_by="system:workflow",
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
    )
    wf.state = "submitted"
    return None


async def terminate_stale(
    wf,
    inp: IssueInput,
    upstream_pr_number: int,
    upstream_pr_url: str,
) -> IssueResult:
    await workflow.execute_activity(
        "record_transition",
        TransitionInput(
            state_root=inp.state_root,
            from_state=wf.state,
            to_state="closed_by_upstream",
            reason=f"stale: no upstream activity for {_POST_SUBMISSION_STALE_DAYS} days",
            decided_by="system:watcher",
        ),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
    )
    wf.state = "closed_by_upstream"
    return IssueResult(
        final_state="closed_by_upstream",
        upstream_pr_url=upstream_pr_url,
        upstream_pr_number=upstream_pr_number,
        abort_reason=f"stale: {_POST_SUBMISSION_STALE_DAYS}d no upstream activity",
    )
