"""NoopAgent — deterministic Agent implementation for tests.

Returns canned responses with no side effects. Used by:
  - workflow tests in Phase 1D
  - end-to-end pipeline tests in Phase 1E
  - any test that needs a real Agent shape but doesn't want to talk to Copilot

Phase 1B.3.

Configurable via constructor args so tests can simulate different scenarios:
  - happy path with a non-empty diff (default)
  - empty diff to exercise the diff_non_empty gate
  - failure exit_reason to exercise the gate failure path
  - timeout-style poll that takes N polls to reach 'done'
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import (
    Agent,
    AgentJob,
    AgentResult,
    AgentStatus,
    ExitReason,
    IssueRef,
)


_DEFAULT_DIFF = """\
diff --git a/src/example.py b/src/example.py
index 1234567..abcdefg 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,3 +1,4 @@
 def example():
+    # noop agent canned fix
     return 42
"""


@dataclass
class NoopAgent:
    """Deterministic agent. Every method is pure (no I/O, no subprocess)."""

    diff_text: str = _DEFAULT_DIFF
    files_touched: list[str] = field(default_factory=lambda: ["src/example.py"])
    commit_shas: list[str] = field(default_factory=lambda: ["a1b2c3d4e5"])
    agent_log: str = "noop agent — canned response"
    exit_reason: ExitReason = "success"
    pr_url: str | None = None
    polls_until_done: int = 1
    _poll_counts: dict[str, int] = field(default_factory=dict)

    # ── Agent protocol ────────────────────────────────────────────────────

    def assign(
        self,
        issue: IssueRef,
        brief: str,
        instruction: str = "",
        *,
        batch_id: str = "",
    ) -> AgentJob:
        job_id = f"noop-{uuid.uuid4().hex[:8]}"
        self._poll_counts[job_id] = 0
        return AgentJob(
            job_id=job_id,
            agent_kind="noop",
            fork_slug=issue.fork_slug,
            branch_name=f"fix-issue-{issue.number}",
            metadata={
                "brief_chars": len(brief),
                "instruction_chars": len(instruction),
                "batch_id": batch_id,
            },
        )

    def poll(self, job: AgentJob) -> AgentStatus:
        if job.agent_kind != "noop":
            raise ValueError(f"NoopAgent cannot poll {job.agent_kind!r} job")

        self._poll_counts[job.job_id] = self._poll_counts.get(job.job_id, 0) + 1
        n = self._poll_counts[job.job_id]

        if n >= self.polls_until_done:
            return AgentStatus(state="done", progress=1.0, last_event="noop done")
        return AgentStatus(
            state="running",
            progress=min(0.99, n / max(self.polls_until_done, 1)),
            last_event=f"noop poll {n}/{self.polls_until_done}",
        )

    def harvest(self, job: AgentJob) -> AgentResult:
        if job.agent_kind != "noop":
            raise ValueError(f"NoopAgent cannot harvest {job.agent_kind!r} job")

        return AgentResult(
            commit_shas=list(self.commit_shas),
            diff_text=self.diff_text,
            files_touched=list(self.files_touched),
            agent_log=self.agent_log,
            exit_reason=self.exit_reason,
            pr_url=self.pr_url,
        )


# Type-check that NoopAgent satisfies the Agent protocol.
_check: Agent = NoopAgent()  # noqa: F841
