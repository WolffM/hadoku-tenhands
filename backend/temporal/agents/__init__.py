"""Agent adapter protocol.

Decouples the orchestrator from the underlying SWE agent. v1 ships with
`CopilotAgent` (decision Q3 — cost optimization). Future agents (Claude,
local model, etc.) implement the same protocol and can be swapped via
config.

Phase 1B.2.

Protocol surface (3 methods, fully decoupled from Temporal):

  assign(job_input)   → AgentJob          # kick off the work, return a handle
  poll(job)           → AgentStatus       # check progress without blocking
  harvest(job)        → AgentResult       # collect the final artifacts

The orchestrator (Temporal `IssueWorkflow`) wraps each method in an
activity. Activities own the timeouts, retries, and error translation.
The Agent itself is pure: no Temporal imports, no semaphores, no global
state. Easy to mock with `NoopAgent` for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


# ── Inputs ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IssueRef:
    """Minimal handle to an issue. The orchestrator passes one of these into
    every Agent call. `slug` and `number` are the FORK's repo, never the
    upstream — by the time we assign, we're working in `WolffM/{repo}`."""

    fork_slug: str          # e.g. "WolffM/markitdown"
    number: int             # the upstream issue number we're addressing
    upstream_slug: str      # the upstream slug (for the agent's awareness)


@dataclass(frozen=True)
class AgentJob:
    """Handle returned by `assign()`. Opaque to the orchestrator beyond the
    fields below — the agent stashes whatever it needs to poll/harvest."""

    job_id: str             # opaque per-agent identifier
    agent_kind: str         # "copilot" | "noop" | etc.
    fork_slug: str
    branch_name: str
    metadata: dict = field(default_factory=dict)


# ── Statuses ──────────────────────────────────────────────────────────────


AgentState = Literal["queued", "running", "done", "failed"]


@dataclass(frozen=True)
class AgentStatus:
    """Snapshot of an in-flight job."""

    state: AgentState
    progress: float                # 0.0..1.0 estimate, or 0.0 if unknown
    last_event: str = ""           # short human-readable line


# ── Results ───────────────────────────────────────────────────────────────


ExitReason = Literal["success", "timeout", "error", "no_changes"]


@dataclass(frozen=True)
class AgentResult:
    """Final output of a finished agent job. The orchestrator writes these
    fields into the evidence store under `05-fixed/`."""

    commit_shas: list[str]
    diff_text: str
    files_touched: list[str]
    agent_log: str                 # session log / equivalent (truncated OK)
    exit_reason: ExitReason
    pr_url: str | None = None      # the agent's draft PR URL, if any


# ── Protocol ──────────────────────────────────────────────────────────────


@runtime_checkable
class Agent(Protocol):
    """Minimal Agent surface. Implementations are pure objects — no Temporal
    imports, no global state. The orchestrator wraps each method in an
    activity with its own retry/timeout policy.

    Implementations MUST NOT raise across the protocol boundary on expected
    failure modes (agent quota, timeout, parse failure). Wrap those into an
    `AgentResult` with `exit_reason != "success"` so the orchestrator can
    turn them into evidence + a gate failure rather than a workflow crash.
    Genuine programming errors (TypeError, ValueError on bad inputs) MAY
    propagate.
    """

    def assign(
        self,
        issue: IssueRef,
        brief: str,
        instruction: str = "",
    ) -> AgentJob: ...

    def poll(self, job: AgentJob) -> AgentStatus: ...

    def harvest(self, job: AgentJob) -> AgentResult: ...
