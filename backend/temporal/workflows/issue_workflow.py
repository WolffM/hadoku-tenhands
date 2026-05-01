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

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ..temporal_activities import (
        AgentPhaseInput,
        EligibilityInput,
        EnvironmentInput,
        ForkInput,
        GateInput,
        GateOutcome,
        InboxInput,
        NotifyHumanCommentsInput,
        ReadReviewSummaryInput,
        RemediationInput,
        RenderInput,
        ScreenshotInput,
        ReplicateInput,
        ReviewInput,
        SubmitInput,
        TransitionInput,
        WatchPRInput,
    )


# ── Inputs / Results ──────────────────────────────────────────────────────


@dataclass
class IssueInput:
    upstream_slug: str          # e.g. "microsoft/markitdown"
    fork_slug: str              # e.g. "WolffM/markitdown"
    issue_number: int
    state_root: str             # path to evidence dir for this issue
    raw_brief_text: str         # the unscrubbed brief text from the operator
    branch_name: str            # operator-readable branch (e.g. "fix-merged-cells")
    base_branch: str = "main"
    install_cmd: list[str] = field(default_factory=lambda: ["python", "-c", "0"])
    workdir: str = "."
    pr_number_for_review: int | None = None  # set after fix/agent PR is identified
    # Routes the Copilot-bound activities (request_repro/fix/verify/
    # remediation) to a separate, capped task queue so those slots are
    # NOT held while the workflow sits in human-review wait. Empty
    # string means "schedule on the workflow's own task queue" — tests
    # rely on that default so they don't need a second worker.
    copilot_task_queue: str = ""
    # Phase-4.5 flag: when false, the workflow stops at the fork-internal
    # operator preview PR produced by `replicate_fix_as_operator` — a
    # human reviews it before the real upstream submission. When true,
    # `submit_upstream_pr` runs next and opens a PR on the actual
    # upstream repo. Default false during the bring-up; flip after the
    # operator PR has been validated.
    submit_to_upstream: bool = False


@dataclass
class IssueResult:
    final_state: str
    upstream_pr_url: str = ""
    upstream_pr_number: int | None = None
    abort_reason: str = ""
    deferred_at: str = ""
    deferred_gate: str = ""


# ── Workflow ──────────────────────────────────────────────────────────────


# How long an activity has to complete before Temporal cancels it. The
# Copilot-driven activities can take 30–180 minutes so we set this high.
_LONG_ACTIVITY_TIMEOUT = timedelta(hours=4)
_SHORT_ACTIVITY_TIMEOUT = timedelta(minutes=10)

# ── Phase 5.1 post-submission tunables ────────────────────────────────────
#
# Polling cadence (open question A in phase-5-plan.md): default 30 min;
# when the prior poll surfaced a NEW blocking review or human comment,
# tighten to 5 min for the next poll so we react quickly during active
# review. After a quiet poll the cadence relaxes back to 30 min. Math
# at the conservative end: 30 min × 24h = 48 polls/day per workflow,
# well inside the 5000/hr per-token gh budget for any plausible batch.
_POLL_CADENCE_DEFAULT = timedelta(minutes=30)
_POLL_CADENCE_AFTER_ACTIVITY = timedelta(minutes=5)

# Termination condition (open question B): if no upstream activity for
# this many days we stop watching and transition to closed_by_upstream
# with reason="stale". Maintainer never engaged — treat as a soft loss.
_POST_SUBMISSION_STALE_DAYS = 30

# Cap on how many times a single workflow loops through the
# remediation → re-signoff cycle. Without this an adversarial reviewer
# could keep us in the loop indefinitely; in practice operators should
# step in well before this fires.
_MAX_REMEDIATION_CYCLES = 3

# Phase 5.2 — local Copilot Review remediation loop. After the workflow
# runs the fork-internal code review, if blocking comments exist we
# branch into request_remediation and re-run review. Capped at 3 to
# prevent the agent from looping on its own bad output.
_MAX_LOCAL_REMEDIATION_ITERATIONS = 3

# How long the workflow waits at awaiting_signoff for the operator's
# `submit_human_decision` signal before timing out. Module-level so
# tests can patch a short timeout for the time-skipping environment.
_OPERATOR_SIGNOFF_TIMEOUT = timedelta(days=14)


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

            # Render a terminal-styled screenshot of the verification
            # test output and upload it to the fork's release assets.
            # The body renderer below reads the resulting URL from
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

            # Render the PR body before the replicate/gate steps — those
            # read pr_title.txt / pr_body.md.
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

            # Phase-4.5: hold real-upstream submission behind the
            # operator flag. When false, stop at the fork-internal
            # preview PR — the operator reviews, flips the flag for the
            # next dispatch when satisfied.
            if not inp.submit_to_upstream:
                return IssueResult(
                    final_state="replicated",
                    upstream_pr_url="",
                    upstream_pr_number=None,
                )

            # Operator signoff gate. Submittable gates have passed,
            # the preview PR is on the fork. Pause here so the operator
            # can edit the preview PR (add screenshots, expand prose)
            # before the upstream submission. submit_upstream_pr will
            # read the LIVE preview content on resume.
            await workflow.execute_activity(
                "enqueue_for_human_review",
                InboxInput(
                    state="awaiting_signoff",
                    gate_name="operator_signoff",
                    reason="preview PR ready on fork; edit if needed, then approve to ship upstream",
                    score=None,
                    upstream_slug=inp.upstream_slug,
                    issue_number=inp.issue_number,
                    state_root=inp.state_root,
                ),
                start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
            )
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
                    reason="operator declined upstream submission",
                )
            # approve / retry both fall through to submit

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

            return await self._post_submission_loop(
                inp=inp,
                upstream_pr_number=upstream_pr_number,
                upstream_pr_url=upstream_pr_url,
            )

        except _GateFailed as gf:
            self.state = "aborted"
            return IssueResult(
                final_state="aborted",
                abort_reason=f"gate {gf.gate_name} failed: {gf.reason}",
            )
        except _OperatorAborted as oa:
            self.state = "aborted"
            return IssueResult(
                final_state="aborted",
                abort_reason=f"operator aborted at {oa.state}/{oa.gate_name}: {oa.reason}",
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
            self.state = "aborted"
            reason = f"{type(e).__name__}: {str(e)[:400]}"
            return IssueResult(
                final_state="aborted",
                abort_reason=f"activity crashed at state={crashed_at}: {reason}",
            )

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
        await workflow.execute_activity(
            activity_name,
            arg,
            **activity_kwargs,
        )

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


    # ── Phase 5.1: post-submission lifecycle ──────────────────────────────

    async def _post_submission_loop(
        self,
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
                    return await self._terminate_stale(
                        inp, upstream_pr_number, upstream_pr_url,
                    )
                cadence = _POLL_CADENCE_DEFAULT
                continue

            seen_review_ids = poll.get("all_seen_review_ids", seen_review_ids)

            if poll.get("merged"):
                await workflow.execute_activity(
                    "record_transition",
                    TransitionInput(
                        state_root=inp.state_root,
                        from_state=self.state,
                        to_state="merged",
                        reason=f"upstream PR merged: {poll.get('merge_sha') or ''}",
                        decided_by="system:watcher",
                    ),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                )
                self.state = "merged"
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
                        from_state=self.state,
                        to_state="closed_by_upstream",
                        reason=f"upstream PR closed without merge by {poll.get('closer') or 'unknown'}",
                        decided_by="system:watcher",
                    ),
                    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
                )
                self.state = "closed_by_upstream"
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
                    self.state = "aborted"
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
                outcome = await self._do_remediation_cycle(
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
                return await self._terminate_stale(
                    inp, upstream_pr_number, upstream_pr_url,
                )
            cadence = _POLL_CADENCE_DEFAULT

    async def _do_remediation_cycle(
        self,
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
                from_state=self.state,
                to_state="remediating_upstream",
                reason=(
                    f"new blocking review from {blocking_review_user or 'maintainer'} "
                    f"on upstream PR #{upstream_pr_number}"
                ),
                decided_by="system:watcher",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = "remediating_upstream"

        # Agent picks up the maintainer's comments and pushes more commits.
        # Routed to copilot-tq the same way request_fix etc. are routed.
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

        # Re-render + re-replicate. replicate_fix_as_operator detects the
        # existing operator preview PR and PATCHes its title/body instead
        # of opening a new one; the fork branch is force-updated so the
        # upstream PR's diff auto-refreshes via GitHub's branch tracking.
        # Re-render the test-output screenshot too — the remediation may
        # have updated the test output and we want the embedded image
        # to reflect the latest run, not the pre-remediation one.
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

        await workflow.execute_activity(
            "record_transition",
            TransitionInput(
                state_root=inp.state_root,
                from_state=self.state,
                to_state="submittable_v2",
                reason="remediation pushed; preview PR refreshed",
                decided_by="system:workflow",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = "submittable_v2"

        # Re-run the same submittable gate set (no_upstream_refs,
        # pr_template_compliance, submission_judge). A failure or operator
        # abort during defer terminates the workflow; that's the desired
        # behavior — we don't want to ship an updated PR that fails our
        # own gates.
        await self._run_state_gates_or_defer("submittable", inp)

        # Re-enter awaiting_signoff. The operator's signal here governs
        # whether we ship the updated content upstream.
        await workflow.execute_activity(
            "enqueue_for_human_review",
            InboxInput(
                state="awaiting_signoff",
                gate_name="operator_signoff",
                reason=(
                    f"remediation cycle complete; preview PR refreshed in response to "
                    f"upstream review on PR #{upstream_pr_number}"
                ),
                score=None,
                upstream_slug=inp.upstream_slug,
                issue_number=inp.issue_number,
                state_root=inp.state_root,
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        await workflow.execute_activity(
            "record_transition",
            TransitionInput(
                state_root=inp.state_root,
                from_state=self.state,
                to_state="awaiting_signoff",
                reason="awaiting operator signoff on remediated preview PR",
                decided_by="system:workflow",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = "awaiting_signoff"

        await workflow.wait_condition(
            lambda: self.human_decision is not None,
            timeout=timedelta(days=14),
        )
        decision = self.human_decision
        self.human_decision = None
        if decision == "abort":
            raise _OperatorAborted(
                state="awaiting_signoff",
                gate_name="operator_signoff",
                reason="operator declined remediated upstream submission",
            )

        # Approve / retry → push the updated content upstream. Because
        # 10-submitted/upstream_pr_number is recorded, submit_upstream_pr
        # uses `gh pr edit` instead of `gh pr create`, so the existing
        # upstream PR's title + body get updated. The branch was
        # force-pushed during replicate; the diff auto-updates.
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
        await workflow.execute_activity(
            "record_transition",
            TransitionInput(
                state_root=inp.state_root,
                from_state=self.state,
                to_state="submitted",
                reason="remediated content pushed to upstream PR",
                decided_by="system:workflow",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = "submitted"
        return None

    async def _terminate_stale(
        self,
        inp: IssueInput,
        upstream_pr_number: int,
        upstream_pr_url: str,
    ) -> IssueResult:
        await workflow.execute_activity(
            "record_transition",
            TransitionInput(
                state_root=inp.state_root,
                from_state=self.state,
                to_state="closed_by_upstream",
                reason=f"stale: no upstream activity for {_POST_SUBMISSION_STALE_DAYS} days",
                decided_by="system:watcher",
            ),
            start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
        )
        self.state = "closed_by_upstream"
        return IssueResult(
            final_state="closed_by_upstream",
            upstream_pr_url=upstream_pr_url,
            upstream_pr_number=upstream_pr_number,
            abort_reason=f"stale: {_POST_SUBMISSION_STALE_DAYS}d no upstream activity",
        )


# ── Internal control-flow exceptions ──────────────────────────────────────


class _GateFailed(Exception):
    def __init__(self, gate_name: str, reason: str) -> None:
        super().__init__(f"gate {gate_name} failed: {reason}")
        self.gate_name = gate_name
        self.reason = reason


class _OperatorAborted(Exception):
    def __init__(self, state: str, gate_name: str, reason: str) -> None:
        super().__init__(f"operator aborted at {state}/{gate_name}")
        self.state = state
        self.gate_name = gate_name
        self.reason = reason
