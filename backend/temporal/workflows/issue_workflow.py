"""IssueWorkflow — per-issue state machine.

Drives one upstream issue through the crimson-kitty pipeline. Each state
transition runs `activity → record_transition → run_gates`. Gate failure
aborts. Gate defer (only judge gates) pauses on a signal — the operator
resolves via the Pipeline Inbox UI.

The workflow is deterministic: it only touches the outside world via
`workflow.execute_activity()`. The activities themselves do all the I/O.

See docs/crimson-kitty/state-machine.md for the state list and the
canonical transition list.

Phase 1D.1.
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
        RemediationInput,
        RenderInput,
        ReviewInput,
        SubmitInput,
        TransitionInput,
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

            # Render the PR body before the submission gates run — those
            # gates read pr_title.txt / pr_body.md
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

            # The submittable state has 3 gates (no_upstream_refs,
            # pr_template_compliance, submission_judge). Run them by
            # calling run_gates with state="submittable".
            await self._run_state_gates_or_defer("submittable", inp)

            # Open the upstream PR
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

            return IssueResult(
                final_state="submitted",
                upstream_pr_url=submit_result.get("pr_url", ""),
                upstream_pr_number=submit_result.get("pr_number"),
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
        await workflow.execute_activity(
            activity_name,
            arg,
            start_to_close_timeout=timeout,
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(maximum_attempts=1 if long else 3),
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
