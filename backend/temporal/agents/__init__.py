"""Agent adapter protocol.

Decouples the orchestrator from the underlying SWE agent. v1 ships with
CopilotAgent (cost optimization, decision Q3). Future agents (Claude,
local model, etc.) implement the same protocol and can be swapped via
config.

Protocol:

    from typing import Protocol
    from dataclasses import dataclass

    @dataclass
    class AgentJob:
        job_id: str
        agent_kind: str

    @dataclass
    class AgentStatus:
        state: Literal["queued", "running", "done", "failed"]
        progress: float        # 0.0 - 1.0 estimate
        last_event: str        # human-readable

    @dataclass
    class AgentResult:
        commit_shas: list[str]
        diff_text: str
        files_touched: list[str]
        agent_log: str         # Copilot session log or equivalent
        exit_reason: Literal["success", "timeout", "error"]

    class Agent(Protocol):
        def assign(self,
                   issue_ref: IssueRef,
                   brief: str,
                   evidence_dir: str,
                   instruction: AgentInstruction) -> AgentJob: ...

        def poll(self, job: AgentJob) -> AgentStatus: ...

        def harvest(self, job: AgentJob) -> AgentResult: ...

Implementations:
    copilot.py — CopilotAgent (Phase 1 default)
    noop.py    — NoopAgent for tests
"""
