"""Agent-driven activities — Phase 1C.4 + 1C.5 + 1C.6 + 1C.7.

The agent (NoopAgent in tests, CopilotAgent in prod) does multiple distinct
jobs across the pipeline lifecycle:

  reproduce   →  04-reproduced/test.* + notes.md
  fix         →  05-fixed/diff.patch + commit_shas.txt + files_touched.txt
  verify      →  06-verified/test_output.txt + diff_from_repro.json
  remediate   →  08-remediated/diff.patch + resolved_comments.json

Rather than 4 nearly-identical activity files, this single module exposes
4 thin wrapper functions over a common `_run_agent_phase` helper. Each
wrapper reads the agent's harvested result and writes the
phase-appropriate evidence files.
"""

from __future__ import annotations

import json
from typing import Any

from ..agents import Agent, AgentJob, AgentResult, IssueRef


def request_repro(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
) -> dict:
    """Tell the agent to reproduce the bug. Polls until done, writes evidence."""
    job = agent.assign(issue, brief=scrubbed_brief, instruction=instruction or _REPRO_INSTRUCTION)
    result = _wait_and_harvest(agent, job)

    # The agent is responsible for writing test.* / before.png / notes.md
    # into the working directory. The orchestrator is expected to copy
    # those files into 04-reproduced/ before this activity returns. For
    # the activity itself, we just record the agent's structured output.
    evidence.write_json("04-reproduced/agent_result.json", _result_to_dict(result))
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


def request_fix(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
) -> dict:
    """Tell the agent to produce a fix. Writes diff + commits + files into evidence."""
    job = agent.assign(issue, brief=scrubbed_brief, instruction=instruction or _FIX_INSTRUCTION)
    result = _wait_and_harvest(agent, job)

    evidence.write_text("05-fixed/diff.patch", result.diff_text)
    evidence.write_text(
        "05-fixed/commit_shas.txt",
        "\n".join(result.commit_shas) + ("\n" if result.commit_shas else ""),
    )
    evidence.write_text(
        "05-fixed/files_touched.txt",
        "\n".join(result.files_touched) + ("\n" if result.files_touched else ""),
    )
    evidence.write_json("05-fixed/agent_result.json", _result_to_dict(result))
    # commits.json: structured form for the no_upstream_refs scanner
    evidence.write_json(
        "05-fixed/commits.json",
        [{"sha": sha, "message": ""} for sha in result.commit_shas],
    )
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


def request_verify(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
) -> dict:
    """Tell the agent to verify the fix. Writes test_output.txt or after.png."""
    job = agent.assign(issue, brief=scrubbed_brief, instruction=instruction or _VERIFY_INSTRUCTION)
    result = _wait_and_harvest(agent, job)

    evidence.write_json("06-verified/agent_result.json", _result_to_dict(result))
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


def request_remediation(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    review_comments_path: str,
    evidence,
    *,
    instruction: str = "",
) -> dict:
    """Tell the agent to remediate review comments."""
    # The brief gets the review comments appended so the agent has
    # context. The base brief is still scrubbed.
    comments_text = ""
    if evidence.exists(review_comments_path):
        comments = evidence.read_json(review_comments_path)
        comments_text = "\n".join(
            f"- [{c.get('severity', '?')}] {c.get('body', '')}"
            for c in (comments if isinstance(comments, list) else [])
        )

    augmented = f"{scrubbed_brief}\n\n## Review comments to address\n\n{comments_text}"

    job = agent.assign(issue, brief=augmented, instruction=instruction or _REMEDIATION_INSTRUCTION)
    result = _wait_and_harvest(agent, job)

    evidence.write_text("08-remediated/diff.patch", result.diff_text)
    evidence.write_json("08-remediated/agent_result.json", _result_to_dict(result))
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


# ── helpers ───────────────────────────────────────────────────────────────


def _wait_and_harvest(agent: Agent, job: AgentJob, max_polls: int = 1000) -> AgentResult:
    """Poll the agent until done (or fail), then harvest.

    The orchestrator wraps each call in a Temporal activity with its own
    long timeout, so this loop is bounded by `max_polls` as a safety net
    against a misbehaving agent that never reports done.
    """
    for _ in range(max_polls):
        status = agent.poll(job)
        if status.state == "done":
            return agent.harvest(job)
        if status.state == "failed":
            return AgentResult(
                commit_shas=[],
                diff_text="",
                files_touched=[],
                agent_log=f"agent reported failed: {status.last_event}",
                exit_reason="error",
            )
    return AgentResult(
        commit_shas=[],
        diff_text="",
        files_touched=[],
        agent_log=f"polled {max_polls} times without done",
        exit_reason="timeout",
    )


def _result_to_dict(result: AgentResult) -> dict:
    return {
        "commit_shas": result.commit_shas,
        "files_touched": result.files_touched,
        "diff_bytes": len(result.diff_text),
        "agent_log_excerpt": result.agent_log[:1000],
        "exit_reason": result.exit_reason,
        "pr_url": result.pr_url,
    }


# ── canned instructions ────────────────────────────────────────────────────

_REPRO_INSTRUCTION = (
    "Reproduce the issue. Produce a failing test, screenshot, or trace that "
    "demonstrates the bug. Write notes.md with the required sections: "
    "Steps to reproduce, Observed, Expected. notes.md must be at least 50 words."
)

_FIX_INSTRUCTION = (
    "Fix the bug. Make commits that touch only the files necessary to fix "
    "the bug. Do not include unrelated cleanup, import reordering, or formatting "
    "changes. The fix will be reviewed for relevance and scope."
)

_VERIFY_INSTRUCTION = (
    "Verify your fix works. Run the test you wrote in the repro phase and "
    "confirm it now passes, OR produce an after.png that is visibly different "
    "from before.png. Write the test output or screenshot to the working tree."
)

_REMEDIATION_INSTRUCTION = (
    "Address the review comments listed below. For each blocking comment, "
    "make the requested change in a new commit. Do not introduce unrelated "
    "changes."
)
