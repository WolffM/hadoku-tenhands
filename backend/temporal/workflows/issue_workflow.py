"""IssueWorkflow: per-issue state machine.

Drives one upstream issue through the crimson-kitty pipeline. Each state
transition runs a sequence: stage activity → evidence write → gate run.
On gate Defer, the workflow pauses on a signal; the operator resolves via
the Pipeline Inbox UI.

See docs/crimson-kitty/state-machine.md for the state list and transitions.

Not yet implemented. Pseudocode:

    from datetime import timedelta
    from temporalio import workflow
    from temporalio.common import RetryPolicy

    from ..activities import (
        check_eligibility, fork_and_scrub_brief, setup_environment,
        agent_reproduce, agent_fix, agent_verify, run_review,
        agent_remediate, submit_upstream_pr,
    )
    from ..gates import run_gates
    from ..evidence import EvidenceStore

    @workflow.defn
    class IssueWorkflow:
        def __init__(self) -> None:
            self.state: str = "candidate"
            self.human_decision: HumanDecision | None = None

        @workflow.run
        async def run(self, issue_ref: IssueRef) -> IssueResult:
            ev = EvidenceStore(issue_ref)

            await self._transition("eligible", check_eligibility, ev, issue_ref)
            await self._transition("forked",   fork_and_scrub_brief, ev, issue_ref)
            await self._transition("environment_ready", setup_environment, ev, issue_ref)
            await self._transition("reproduced", agent_reproduce, ev, issue_ref)
            await self._transition("fixed",      agent_fix, ev, issue_ref)
            await self._transition("verified",   agent_verify, ev, issue_ref)
            await self._transition("reviewed",   run_review, ev, issue_ref)
            if self._has_blockers(ev):
                await self._transition("remediated", agent_remediate, ev, issue_ref)
            await self._transition("submitted",  submit_upstream_pr, ev, issue_ref)

            return await self._watch_until_terminal(ev, issue_ref)

        async def _transition(self, target_state, activity, ev, issue_ref):
            await workflow.execute_activity(
                activity,
                args=[issue_ref, ev.path],
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            gate_results = await workflow.execute_activity(
                run_gates,
                args=[target_state, ev.path],
                start_to_close_timeout=timedelta(minutes=10),
            )
            for gr in gate_results:
                if gr.verdict == "fail":
                    raise workflow.ApplicationError(f"gate {gr.name} failed: {gr.reason}")
                if gr.verdict == "defer":
                    await self._await_human_decision(target_state, gr)
            self.state = target_state

        async def _await_human_decision(self, state, gate_result):
            await workflow.execute_activity(enqueue_for_human_review, ...)
            await workflow.wait_condition(
                lambda: self.human_decision is not None,
                timeout=timedelta(days=7),
            )
            decision = self.human_decision
            self.human_decision = None
            if decision == "abort":
                raise workflow.ApplicationError("operator aborted")
            if decision == "retry":
                ...

        @workflow.signal
        def submit_human_decision(self, decision: str) -> None:
            self.human_decision = decision
"""
