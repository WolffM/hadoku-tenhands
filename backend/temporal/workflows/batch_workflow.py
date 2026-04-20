"""BatchWorkflow — fans out to many IssueWorkflows.

Spawns one child IssueWorkflow per issue and collects the results.
Children run fully in parallel at the workflow layer; concurrency is
enforced per-activity by routing Copilot-bound activities to a
dedicated, capped task queue (see `backend/temporal/worker.py`). That
way a child in human-review wait isn't holding a slot — only children
actively running a Copilot activity consume the ceiling.

Phase 1D.2.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .issue_workflow import IssueInput, IssueResult, IssueWorkflow


@dataclass
class BatchInput:
    batch_id: str
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
        coros = [
            workflow.execute_child_workflow(
                IssueWorkflow.run,
                issue,
                id=f"{inp.batch_id}-{issue.upstream_slug.replace('/', '__')}-{issue.issue_number}",
            )
            for issue in inp.issues
        ]

        raw = await asyncio.gather(*coros, return_exceptions=True)
        results: list[IssueResult] = []
        for r in raw:
            if isinstance(r, IssueResult):
                results.append(r)
            elif isinstance(r, Exception):
                results.append(IssueResult(
                    final_state="aborted",
                    abort_reason=f"child workflow crashed: {type(r).__name__}: {r}",
                ))
            else:
                results.append(IssueResult(
                    final_state="aborted",
                    abort_reason=f"unexpected child result: {type(r).__name__}",
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
