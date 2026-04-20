"""BatchWorkflow — fans out to many IssueWorkflows.

The operator dispatches a batch of N issues; the BatchWorkflow spawns one
child IssueWorkflow per issue and collects the results.

Concurrency is capped by `max_concurrency` (default 2) to stay under the
Copilot coding-agent per-user concurrent-session limit — firing 8 at once
resulted in all 8 accepting the PR stub but only the first 2-3 actually
getting a coding-VM slot; the rest timed out with no work done. A
semaphore held across the child's full lifecycle (repro → fix → verify)
means each slot is released only when its issue completes or aborts.

Phase 1D.2.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .issue_workflow import IssueInput, IssueResult, IssueWorkflow


@dataclass
class BatchInput:
    batch_id: str                 # e.g. "crimson-kitty-2026-04-14"
    issues: list[IssueInput]
    max_concurrency: int = 2


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
        sem = asyncio.Semaphore(max(1, inp.max_concurrency))

        async def _run_one(issue: IssueInput) -> IssueResult:
            async with sem:
                try:
                    return await workflow.execute_child_workflow(
                        IssueWorkflow.run,
                        issue,
                        id=f"{inp.batch_id}-{issue.upstream_slug.replace('/', '__')}-{issue.issue_number}",
                    )
                except Exception as e:
                    return IssueResult(
                        final_state="aborted",
                        abort_reason=f"child workflow crashed: {type(e).__name__}: {e}",
                    )

        results = await asyncio.gather(*[_run_one(i) for i in inp.issues])

        submitted = sum(1 for r in results if r.final_state == "submitted")
        aborted = sum(1 for r in results if r.final_state == "aborted")

        return BatchResult(
            batch_id=inp.batch_id,
            total=len(results),
            submitted=submitted,
            aborted=aborted,
            results=results,
        )
