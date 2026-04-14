"""BatchWorkflow — fans out to many IssueWorkflows.

The operator dispatches a batch of N issues; the BatchWorkflow spawns one
child IssueWorkflow per issue and collects the results. Children run in
parallel up to the worker's task queue concurrency limit.

Phase 1D.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .issue_workflow import IssueInput, IssueResult, IssueWorkflow


@dataclass
class BatchInput:
    batch_id: str                 # e.g. "crimson-kitty-2026-04-14"
    issues: list[IssueInput]


@dataclass
class BatchResult:
    batch_id: str
    total: int
    submitted: int
    aborted: int
    results: list[IssueResult] = field(default_factory=list)


@workflow.defn(name="BatchWorkflow")
class BatchWorkflow:
    @workflow.run
    async def run(self, inp: BatchInput) -> BatchResult:
        # Spawn child workflows in parallel via execute_child_workflow.
        # Each child has its own state_root so they don't fight.
        coros = [
            workflow.execute_child_workflow(
                IssueWorkflow.run,
                issue,
                id=f"{inp.batch_id}-{issue.upstream_slug.replace('/', '__')}-{issue.issue_number}",
                # Children inherit the parent's task queue by default.
            )
            for issue in inp.issues
        ]

        # Gather. Failed children surface as exceptions, which we catch
        # so one bad issue doesn't blow up the whole batch.
        results: list[IssueResult] = []
        for coro in coros:
            try:
                r = await coro
                results.append(r)
            except Exception as e:
                results.append(IssueResult(
                    final_state="aborted",
                    abort_reason=f"child workflow crashed: {type(e).__name__}: {e}",
                ))

        submitted = sum(1 for r in results if r.final_state == "submitted")
        aborted = sum(1 for r in results if r.final_state == "aborted")

        return BatchResult(
            batch_id=inp.batch_id,
            total=len(results),
            submitted=submitted,
            aborted=aborted,
            results=results,
        )
