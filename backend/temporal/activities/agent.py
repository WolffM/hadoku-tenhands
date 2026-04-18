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

import asyncio
import json
from typing import Any, Callable, Optional

from ..agents import Agent, AgentJob, AgentResult, IssueRef


async def request_repro(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
    heartbeat: Optional[Callable[[str], None]] = None,
) -> dict:
    """Tell the agent to reproduce the bug. Polls until done, writes evidence."""
    job = await asyncio.to_thread(
        agent.assign, issue, brief=scrubbed_brief, instruction=instruction or _REPRO_INSTRUCTION,
    )
    result = await _wait_and_harvest(agent, job, heartbeat=heartbeat)

    evidence.write_json("04-reproduced/agent_result.json", _result_to_dict(result))
    await asyncio.to_thread(_download_agent_files, agent, issue, result, "04-reproduced", evidence)
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


async def request_fix(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
    heartbeat: Optional[Callable[[str], None]] = None,
) -> dict:
    """Tell the agent to produce a fix. Writes diff + commits + files into evidence."""
    job = await asyncio.to_thread(
        agent.assign, issue, brief=scrubbed_brief, instruction=instruction or _FIX_INSTRUCTION,
    )
    result = await _wait_and_harvest(agent, job, heartbeat=heartbeat)

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
    evidence.write_json(
        "05-fixed/commits.json",
        [{"sha": sha, "message": ""} for sha in result.commit_shas],
    )
    await asyncio.to_thread(_download_agent_files, agent, issue, result, "05-fixed", evidence)
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


async def request_verify(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    evidence,
    *,
    instruction: str = "",
    heartbeat: Optional[Callable[[str], None]] = None,
) -> dict:
    """Tell the agent to verify the fix. Writes test_output.txt or after.png."""
    job = await asyncio.to_thread(
        agent.assign, issue, brief=scrubbed_brief, instruction=instruction or _VERIFY_INSTRUCTION,
    )
    result = await _wait_and_harvest(agent, job, heartbeat=heartbeat)

    evidence.write_json("06-verified/agent_result.json", _result_to_dict(result))
    await asyncio.to_thread(_download_agent_files, agent, issue, result, "06-verified", evidence)
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


async def request_remediation(
    agent: Agent,
    issue: IssueRef,
    scrubbed_brief: str,
    review_comments_path: str,
    evidence,
    *,
    instruction: str = "",
    heartbeat: Optional[Callable[[str], None]] = None,
) -> dict:
    """Tell the agent to remediate review comments."""
    comments_text = ""
    if evidence.exists(review_comments_path):
        comments = evidence.read_json(review_comments_path)
        comments_text = "\n".join(
            f"- [{c.get('severity', '?')}] {c.get('body', '')}"
            for c in (comments if isinstance(comments, list) else [])
        )

    augmented = f"{scrubbed_brief}\n\n## Review comments to address\n\n{comments_text}"

    job = await asyncio.to_thread(
        agent.assign, issue, brief=augmented, instruction=instruction or _REMEDIATION_INSTRUCTION,
    )
    result = await _wait_and_harvest(agent, job, heartbeat=heartbeat)

    evidence.write_text("08-remediated/diff.patch", result.diff_text)
    evidence.write_json("08-remediated/agent_result.json", _result_to_dict(result))
    return {"ok": result.exit_reason == "success", "exit_reason": result.exit_reason}


# ── helpers ───────────────────────────────────────────────────────────────


def _download_agent_files(
    agent: Agent,
    issue: IssueRef,
    result: AgentResult,
    evidence_subdir: str,
    evidence,
) -> None:
    """Download files the agent created on the PR branch into the evidence store.

    CopilotAgent commits files to a remote branch — they don't exist locally.
    This fetches each touched file via the GitHub API and writes it into the
    evidence directory so gates can read them.
    """
    if not result.files_touched or not result.pr_url:
        return

    # Best-effort: don't let download failures block the pipeline.
    try:
        from services.github_api import run_gh_command  # type: ignore
    except ImportError:
        return

    owner, repo = issue.fork_slug.split("/", 1)

    # Get the PR branch name from the PR URL
    pr_number = result.pr_url.rstrip("/").rsplit("/", 1)[-1]
    branch_call = run_gh_command([
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}",
        "--jq", ".head.ref",
    ])
    branch = (branch_call.get("output", "").strip()) if branch_call.get("success") else ""
    if not branch:
        return

    for filepath in result.files_touched:
        try:
            content_call = run_gh_command([
                "api", f"repos/{owner}/{repo}/contents/{filepath}",
                "-H", "Accept: application/vnd.github.raw+json",
                "--method", "GET",
                "-f", f"ref={branch}",
            ])
            if content_call.get("success") and content_call.get("output"):
                # Use just the filename, not the full path from the repo
                filename = filepath.rsplit("/", 1)[-1]
                evidence.write_text(f"{evidence_subdir}/{filename}", content_call["output"])
        except Exception:
            continue  # best-effort


async def _wait_and_harvest(
    agent: Agent,
    job: AgentJob,
    max_polls: int = 90,
    poll_interval_s: float = 20.0,
    *,
    heartbeat: Optional[Callable[[str], None]] = None,
) -> AgentResult:
    """Poll the agent until done (or fail), then harvest.

    The blocking gh subprocess calls run in a thread via asyncio.to_thread
    so they don't starve the worker event loop while other activities run.
    `heartbeat` is called each iteration so Temporal knows the activity is
    still alive even during long waits.

    Default bound: 90 polls × 20s = 30 min wall clock per phase.
    """
    for i in range(max_polls):
        if heartbeat is not None:
            try:
                heartbeat(f"poll {i + 1}/{max_polls}")
            except Exception:
                pass  # heartbeat failure must never break the loop

        status = await asyncio.to_thread(agent.poll, job)
        if status.state == "done":
            return await asyncio.to_thread(agent.harvest, job)
        if status.state == "failed":
            return AgentResult(
                commit_shas=[],
                diff_text="",
                files_touched=[],
                agent_log=f"agent reported failed: {status.last_event}",
                exit_reason="error",
            )
        await asyncio.sleep(poll_interval_s)

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
