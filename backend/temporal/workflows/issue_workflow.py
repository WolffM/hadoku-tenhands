"""IssueWorkflow — per-issue state machine.

Drives one upstream issue through the crimson-kitty pipeline. Each state
transition runs `activity → record_transition → run_gates`. Gate failure
aborts. Gate defer (only judge gates) pauses on a signal — the operator
resolves via the Pipeline Inbox UI.

The workflow is deterministic: it only touches the outside world via
`workflow.execute_activity()`. The activities themselves do all the I/O.

See docs/crimson-kitty/state-machine.md for the state list and the
canonical transition list.

Phase 1D.1; post-submission lifecycle (Phase 5.1) extends the workflow
to keep watching the upstream PR after it's opened — driving merged /
closed_by_upstream / remediating_upstream → submittable_v2 → submitted
loops based on what maintainers do.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..gates import CRIMSON_KITTY
    from ..temporal_activities import (
        AgentPhaseInput,
        EligibilityInput,
        EnvironmentInput,
        ForkInput,
        GateInput,
        GateOutcome,
        InboxInput,
        ReadReviewSummaryInput,
        RemediationInput,
        RenderInput,
        ScreenshotInput,
        RunTestInput,
        ReplicateInput,
        ReviewInput,
        SubmitInput,
        TransitionInput,
    )

# Post-submission flow lives in its own module so this file stays under
# ~800 lines. The free functions take the workflow instance as `wf` and
# share types/constants via `issue_workflow_types`. Re-export IssueInput
# and IssueResult so tests / callers that import them from this module
# keep working.
from .issue_workflow_post import (
    do_remediation_cycle,  # noqa: F401  (re-export for tests + callers)
    post_submission_loop,
    terminate_stale,  # noqa: F401  (re-export for tests + callers)
)
from .issue_workflow_types import (
    IssueInput,
    IssueResult,
    _GateFailed,
    _LONG_ACTIVITY_TIMEOUT,
    _MAX_LOCAL_REMEDIATION_ITERATIONS,
    _OperatorAborted,
    _OPERATOR_SIGNOFF_TIMEOUT,
    _SHORT_ACTIVITY_TIMEOUT,
)


# ── Workflow ──────────────────────────────────────────────────────────────


@workflow.defn(name="IssueWorkflow")
class IssueWorkflow:
    def __init__(self) -> None:
        self.state: str = "candidate"
        self.human_decision: Optional[str] = None  # "approve" | "abort" | "retry"

    # ── Signals (operator resolves a deferred workflow) ───────────────────

    @workflow.signal
    def submit_human_decision(self, decision: str) -> None:
        self.human_decision = decision

    @workflow.query
    def current_state(self) -> str:
        return self.state

    # ── Run ────────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, inp: IssueInput) -> IssueResult:
        try:
            await self._transition(
                target="eligible",
                activity_name="check_eligibility",
                arg=EligibilityInput(
                    upstream_slug=inp.upstream_slug,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                inp=inp,
            )

            await self._transition(
                target="forked",
                activity_name="fork_and_scrub_brief",
                arg=ForkInput(
                    upstream_slug=inp.upstream_slug,
                    fork_slug=inp.fork_slug,
                    issue_number=inp.issue_number,
                    raw_brief_text=inp.raw_brief_text,
                    branch_name=inp.branch_name,
                    state_root=inp.state_root,
                ),
                inp=inp,
            )

            await self._transition(
                target="environment_ready",
                activity_name="setup_environment",
                arg=EnvironmentInput(
                    fork_slug=inp.fork_slug,
                    branch_name=inp.branch_name,
                    workdir=inp.workdir,
                    install_cmd=inp.install_cmd,
                    state_root=inp.state_root,
                ),
                inp=inp,
            )

            await self._transition(
                target="reproduced",
                activity_name="request_repro",
                arg=AgentPhaseInput(
                    upstream_slug=inp.upstream_slug,
                    fork_slug=inp.fork_slug,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                inp=inp,
                long=True,
            )

            await self._transition(
                target="fixed",
                activity_name="request_fix",
                arg=AgentPhaseInput(
                    upstream_slug=inp.upstream_slug,
                    fork_slug=inp.fork_slug,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                inp=inp,
                long=True,
            )

            await self._transition(
                target="verified",
                activity_name="request_verify",
                arg=AgentPhaseInput(
                    upstream_slug=inp.upstream_slug,
                    fork_slug=inp.fork_slug,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                inp=inp,
                long=True,
            )

            # The reviewed → remediated/submittable branching depends on
            # whether there are blocker comments. We optimistically run
            # the review and check the gate output for blockers via the
            # severity_summary file (read by an activity helper).
            await self._transition(
                target="reviewed",
                activity_name="run_review",
                arg=ReviewInput(
                    fork_slug=inp.fork_slug,
                    pr_number=inp.pr_number_for_review or 0,
                    state_root=inp.state_root,
                ),
                inp=inp,
                run_gates_after=False,  # no gates after reviewed in the registry
            )

            # Phase 5.2: local Copilot Review remediation loop. If the
            # review surfaced blocking comments, route the PR back through
            # request_remediation and re-run review. Capped at
            # _MAX_LOCAL_REMEDIATION_ITERATIONS so a stuck agent can't
            # loop forever — abort with a clear reason on cap.
            #
            # Iteration count: up to N+1 read_review_summary calls
            # (initial + after each of N remediations) and up to N
            # remediations. If the post-remediation read on iteration N
            # still shows blockers, abort.
            for iteration in range(_MAX_LOCAL_REMEDIATION_ITERATIONS + 1):
                summary = await workflow.execute_activity(
                    "read_review_summary",
                    ReadReviewSummaryInput(state_root=inp.state_root),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                blocking = int(summary.get("blocking", 0))
                if blocking == 0:
                    break
                if iteration >= _MAX_LOCAL_REMEDIATION_ITERATIONS:
                    raise _GateFailed(
                        gate_name="local_remediation_cap",
                        reason=(
                            f"hit MAX_LOCAL_REMEDIATION_ITERATIONS="
                            f"{_MAX_LOCAL_REMEDIATION_ITERATIONS} with "
                            f"{blocking} blocking comment(s) still present"
                        ),
                    )

                # Route to copilot-tq the same way request_fix etc. are
                # routed. Skip gates after `remediated` — the registered
                # `remediation_complete` gate expects an explicit
                # per-comment resolution map that the Copilot agent
                # doesn't produce; the loop's re-run of run_review is
                # the actual blocker-resolution check.
                remediation_kwargs = {
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
                await workflow.execute_activity(
                    "record_transition",
                    TransitionInput(
                        state_root=inp.state_root,
                        from_state=self.state,
                        to_state="remediated",
                        reason=f"local remediation iteration {iteration + 1}: {blocking} blocking comment(s)",
                        decided_by="system:workflow",
                    ),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                )
                self.state = "remediated"

                # Re-run review against the remediated branch. Skip gates
                # again — `reviewed` has none registered.
                await self._transition(
                    target="reviewed",
                    activity_name="run_review",
                    arg=ReviewInput(
                        fork_slug=inp.fork_slug,
                        pr_number=inp.pr_number_for_review or 0,
                        state_root=inp.state_root,
                    ),
                    inp=inp,
                    run_gates_after=False,
                )

            # Render the PR title + body BEFORE replicate, because
            # replicate reads `09-submittable/pr_title.txt` and
            # `09-submittable/pr_body.md` to build the squashed commit
            # message. We re-render below after verify so the body picks
            # up the test-output screenshot URL.
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

            # Sever the agent-attribution lineage: squash the agent's fix
            # into a single operator-authored commit on branch_name, open a
            # fork-internal preview PR, and close the agent's draft. After
            # this step, 05-fixed/commits.json reflects the new single
            # commit so downstream gates scan the real submission-bound
            # history.
            #
            # IMPORTANT: replicate MUST run before run_test_command. The
            # cktest sandbox clones `inp.branch_name` (the crimson-kitty-N
            # operator branch), and that branch doesn't exist on the fork
            # remote until replicate force-pushes it here. Putting
            # run_test_command first meant claw-3 was clone-failing 100%
            # of the time because the ref it wanted was created seconds
            # later by replicate. See docker/compose#13772 verify run
            # (2026-05-13 18:51): 5 retry attempts spanning 31s all
            # missed because the branch authored time was 18:51:45.
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

            # Run the agent-supplied test command in the cktest sandbox
            # runner against the now-existing operator branch and capture
            # stdout+stderr to 06-verified/test_output.txt. Phase 5.6
            # split: Copilot commits 05-fixed/test_command.txt (one
            # shell line); the pipeline runs it in a clean sandbox
            # rather than asking Copilot to do shell ops. Non-fatal: if
            # the agent didn't commit a command or the runner is
            # unavailable, the screenshot stage downstream no-ops
            # gracefully and verification falls back to text-only.
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

            # Render a terminal-styled screenshot of the verification
            # test output and upload it to the fork's release assets.
            # The body re-render below reads the resulting URL from
            # `06-verified/after_url.txt` and embeds it inline at the
            # top of the Verification section. Non-fatal: if there's no
            # test output to render, chromium isn't available, or the
            # upload fails, the activity returns ok=False and the body
            # falls back to text-only verification.
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

            # Re-render the PR body now that the verify screenshot URL
            # exists on disk — idempotent w.r.t. the earlier call but
            # produces the final body that the preview PR ships with.
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
                    from_state=self.state,
                    to_state="replicated",
                    reason="fix re-authored under operator identity; preview PR opened on fork",
                    decided_by="system:workflow",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
            self.state = "replicated"

            # The submittable state has 3 gates (no_upstream_refs,
            # pr_template_compliance, submission_judge). Run them by
            # calling run_gates with state="submittable".
            await self._run_state_gates_or_defer("submittable", inp)

            # Every run that clears the submittable gates routes through
            # the operator_signoff inbox defer — the operator is the
            # single ship-or-stop authority.

            # Operator signoff loop. Submittable gates have passed, the
            # preview PR is on the fork. Each iteration:
            #   1. Enqueue inbox (with last error context on retries)
            #   2. Wait for operator signal (approve / retry / abort)
            #   3. On abort → raise _OperatorAborted (caught below)
            #   4. On approve/retry → try submit_upstream_pr
            #   5. On submit success → break out of loop
            #   6. On submit failure → record + loop back with error
            #
            # Looping (instead of letting a submit failure bubble to the
            # catch-all and abort the workflow) is the 2026-05-27 fix
            # after argoproj/argo-cd#27872 crashed at submit because
            # base_branch=main against a master repo. The original
            # mistake was hardcoded "main" in dispatch — now fixed in
            # _resolve_default_branch — but the workflow's "park and
            # wait for operator to fix it" path is the safety net.
            submission_error: str | None = None
            submit_result: dict | None = None
            while True:
                inbox_reason = (
                    "preview PR ready on fork; edit if needed, then approve to ship upstream"
                    if submission_error is None
                    else f"previous submission attempt failed: {submission_error}. "
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
                # Only record the awaiting_signoff transition on first entry —
                # subsequent loops re-enter the same state without a new
                # transition event.
                if submission_error is None:
                    await workflow.execute_activity(
                        "record_transition",
                        TransitionInput(
                            state_root=inp.state_root,
                            from_state=self.state,
                            to_state="awaiting_signoff",
                            reason="awaiting operator signoff on preview PR",
                            decided_by="system:workflow",
                        ),
                        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                    )
                    self.state = "awaiting_signoff"
                await workflow.wait_condition(
                    lambda: self.human_decision is not None,
                    timeout=_OPERATOR_SIGNOFF_TIMEOUT,
                )
                decision = self.human_decision
                self.human_decision = None
                if decision == "abort":
                    raise _OperatorAborted(
                        state="awaiting_signoff",
                        gate_name="operator_signoff",
                        reason=(
                            "operator declined upstream submission"
                            if submission_error is None
                            else f"operator abandoned after submission failure: {submission_error}"
                        ),
                    )
                # approve / retry both fall through to submit
                try:
                    submit_result = await workflow.execute_activity(
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
                    # Success — record + exit loop
                    break
                except Exception as e:
                    submission_error = f"{type(e).__name__}: {str(e)[:300]}"
                    # Best-effort: log the failure to the events stream so
                    # the inbox UI surfaces context. Not raising — we want
                    # to loop back to the operator inbox.
                    try:
                        await workflow.execute_activity(
                            "record_transition",
                            TransitionInput(
                                state_root=inp.state_root,
                                from_state="awaiting_signoff",
                                to_state="awaiting_signoff",
                                reason=f"submit_upstream_pr failed: {submission_error}",
                                decided_by="system:workflow",
                            ),
                            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                        )
                    except Exception:
                        pass  # Don't mask the real failure with a logging issue
                    # loop back to operator inbox
                    continue

            # submit_result is guaranteed non-None here (loop only exits via break on success)
            assert submit_result is not None

            await workflow.execute_activity(
                "record_transition",
                TransitionInput(
                    state_root=inp.state_root,
                    from_state=self.state,
                    to_state="submitted",
                    reason="upstream PR opened",
                    decided_by="system:workflow",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
            self.state = "submitted"

            upstream_pr_number = submit_result.get("pr_number")
            upstream_pr_url = submit_result.get("pr_url", "")

            return await post_submission_loop(
                wf=self,
                inp=inp,
                upstream_pr_number=upstream_pr_number,
                upstream_pr_url=upstream_pr_url,
            )

        except _GateFailed as gf:
            reason = f"gate {gf.gate_name} failed: {gf.reason}"
            await self._record_abort(inp, self.state, reason)
            self.state = "aborted"
            return IssueResult(final_state="aborted", abort_reason=reason)
        except _OperatorAborted as oa:
            reason = f"operator aborted at {oa.state}/{oa.gate_name}: {oa.reason}"
            await self._record_abort(inp, self.state, reason)
            self.state = "aborted"
            return IssueResult(
                final_state="aborted",
                abort_reason=reason,
                deferred_at=oa.state,
                deferred_gate=oa.gate_name,
            )
        except Exception as e:
            # Any uncaught exception from an activity (aggregator errors, gh
            # API failures, timeouts, etc.) gets turned into a clean abort
            # rather than a WorkflowExecutionFailed. Operator can see the
            # reason via the existing retro view / inbox surfaces instead
            # of having to dig through Temporal event history.
            crashed_at = self.state
            reason = (
                f"activity crashed at state={crashed_at}: "
                f"{type(e).__name__}: {str(e)[:400]}"
            )
            await self._record_abort(inp, crashed_at, reason)
            self.state = "aborted"
            return IssueResult(final_state="aborted", abort_reason=reason)

    async def _record_abort(self, inp: IssueInput, from_state: str, reason: str) -> None:
        """Persist the abort to the evidence store.

        Without this the workflow only set `self.state = "aborted"` in memory
        and returned an IssueResult — nothing on disk recorded the abort, so
        `transitions.jsonl` froze at the crash point and the UI showed the
        run stuck mid-pipeline (e.g. `eligible`) with no failed gate to
        explain it. Writing the `→ aborted` transition makes `current_state`
        resolve to `aborted` and carries the reason for the operator.

        Best-effort: a failure here must not mask the original abort.
        """
        try:
            await workflow.execute_activity(
                "record_transition",
                TransitionInput(
                    state_root=inp.state_root,
                    from_state=from_state,
                    to_state="aborted",
                    reason=reason,
                    decided_by="system:workflow",
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception:
            pass

    # ── helpers ───────────────────────────────────────────────────────────

    async def _transition(
        self,
        target: str,
        activity_name: str,
        arg: object,
        inp: IssueInput,
        *,
        long: bool = False,
        run_gates_after: bool = True,
    ) -> None:
        """Run one transition: activity → record_transition → run_gates."""
        timeout = _LONG_ACTIVITY_TIMEOUT if long else _SHORT_ACTIVITY_TIMEOUT
        # Long activities (agent polling) heartbeat every ~20s. Require one
        # every 2 minutes or Temporal treats the activity as dead and retries.
        heartbeat_timeout = timedelta(minutes=2) if long else None
        # Copilot-bound activities (`long=True`) run on a dedicated,
        # concurrency-capped task queue when one is configured — this
        # is how the 2-session Copilot ceiling is honored without
        # blocking the batch while another issue sits in human review.
        activity_kwargs = {
            "start_to_close_timeout": timeout,
            "heartbeat_timeout": heartbeat_timeout,
            "retry_policy": RetryPolicy(maximum_attempts=1 if long else 3),
        }
        if long and inp.copilot_task_queue:
            activity_kwargs["task_queue"] = inp.copilot_task_queue
        # Instrumentation: log the workflow-side view of each transition so
        # we can correlate workflow timing with activity timing on the worker
        # side. `workflow.now()` is replay-safe (deterministic). Elapsed
        # measures the activity's wall-clock from schedule to result —
        # bridges the "did the activity hang?" vs "did orchestration drop?"
        # gap when an activity reports timed-out.
        start_ns = workflow.now()
        workflow.logger.info(
            "transition start: from=%s to=%s activity=%s long=%s",
            self.state, target, activity_name, long,
        )
        try:
            await workflow.execute_activity(
                activity_name,
                arg,
                **activity_kwargs,
            )
            elapsed = (workflow.now() - start_ns).total_seconds()
            workflow.logger.info(
                "transition activity ok: %s elapsed_s=%.1f",
                activity_name, elapsed,
            )
        except Exception:
            elapsed = (workflow.now() - start_ns).total_seconds()
            workflow.logger.warning(
                "transition activity fail: %s elapsed_s=%.1f",
                activity_name, elapsed,
            )
            raise

        await workflow.execute_activity(
            "record_transition",
            TransitionInput(
                state_root=inp.state_root,
                from_state=self.state,
                to_state=target,
                reason=f"activity {activity_name} succeeded",
                decided_by="system:workflow",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = target

        if run_gates_after:
            await self._run_state_gates_or_defer(target, inp)

    async def _run_state_gates_or_defer(self, state: str, inp: IssueInput) -> None:
        """Run all gates registered for `state`, react to the verdicts.

        Gate results come back as plain dicts (Temporal's default JSON
        converter doesn't round-trip dataclasses), so we access by key.
        """
        results: list[dict] = await workflow.execute_activity(
            "run_gates",
            GateInput(
                state=state,
                upstream_slug=inp.upstream_slug,
                fork_slug=inp.fork_slug,
                issue_number=inp.issue_number,
                state_root=inp.state_root,
                pipeline=CRIMSON_KITTY,
            ),
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        for r in results:
            verdict = r["verdict"]
            name = r["name"]
            reason = r["reason"]
            score = r.get("score")

            if verdict == "fail":
                raise _GateFailed(gate_name=name, reason=reason)
            if verdict == "defer":
                # Enqueue + wait for human signal
                await workflow.execute_activity(
                    "enqueue_for_human_review",
                    InboxInput(
                        state=state,
                        gate_name=name,
                        reason=reason,
                        score=score,
                        upstream_slug=inp.upstream_slug,
                        issue_number=inp.issue_number,
                        state_root=inp.state_root,
                    ),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                )
                await workflow.wait_condition(
                    lambda: self.human_decision is not None,
                    timeout=timedelta(days=7),
                )
                decision = self.human_decision
                self.human_decision = None
                if decision == "abort":
                    raise _OperatorAborted(state=state, gate_name=name, reason=reason)
                # `approve` and `retry` both fall through; the workflow
                # continues from the next state. (Phase 1: no in-place
                # retry — the operator approves and we move on.)

