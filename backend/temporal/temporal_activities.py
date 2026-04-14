"""Temporal-decorated activity wrappers.

The pure activity functions in `temporal.activities.*` take live Python
objects (EvidenceStore, Agent) which can't be passed across the Temporal
workflow boundary. This module defines top-level `@activity.defn`
functions that take serializable inputs (paths, slugs, ints) and
rehydrate the Python objects internally.

The workflow calls these via `workflow.execute_activity()`. Workers
register them via `worker.register_activities()`.

The agent kind is selected at activity-call time via the
`CRIMSON_AGENT_KIND` env var (`noop` for tests, `copilot` for prod).
This is the seam test workflows use to stay hermetic.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from temporalio import activity

from .agents import IssueRef
from .agents.copilot import CopilotAgent
from .agents.noop import NoopAgent
from .evidence.store import EvidenceStore


def _evidence_for(state_root: str) -> EvidenceStore:
    return EvidenceStore(Path(state_root))


def _agent():
    kind = os.environ.get("CRIMSON_AGENT_KIND", "noop").lower()
    if kind == "copilot":
        return CopilotAgent()
    return NoopAgent()


def _issue_ref(upstream_slug: str, fork_slug: str, number: int) -> IssueRef:
    return IssueRef(fork_slug=fork_slug, number=number, upstream_slug=upstream_slug)


# ── Eligibility ───────────────────────────────────────────────────────────


@dataclass
class EligibilityInput:
    upstream_slug: str
    issue_number: int
    state_root: str


@activity.defn(name="check_eligibility")
async def act_check_eligibility(inp: EligibilityInput) -> dict:
    from .activities.eligibility import check_eligibility

    ev = _evidence_for(inp.state_root)
    return check_eligibility(inp.upstream_slug, inp.issue_number, ev)


# ── Fork + scrub ──────────────────────────────────────────────────────────


@dataclass
class ForkInput:
    upstream_slug: str
    fork_slug: str
    issue_number: int
    raw_brief_text: str
    branch_name: str
    state_root: str


@activity.defn(name="fork_and_scrub_brief")
async def act_fork_and_scrub_brief(inp: ForkInput) -> dict:
    from .activities.fork import fork_and_scrub_brief

    ev = _evidence_for(inp.state_root)
    return fork_and_scrub_brief(
        upstream_slug=inp.upstream_slug,
        issue_number=inp.issue_number,
        raw_brief_text=inp.raw_brief_text,
        branch_name=inp.branch_name,
        evidence=ev,
        fork_owner=inp.fork_slug.split("/", 1)[0],
    )


# ── Environment ───────────────────────────────────────────────────────────


@dataclass
class EnvironmentInput:
    fork_slug: str
    branch_name: str
    workdir: str
    install_cmd: list[str]
    state_root: str
    dev_server_cmd: list[str] | None = None


@activity.defn(name="setup_environment")
async def act_setup_environment(inp: EnvironmentInput) -> dict:
    from .activities.environment import setup_environment

    ev = _evidence_for(inp.state_root)
    return setup_environment(
        fork_slug=inp.fork_slug,
        branch_name=inp.branch_name,
        workdir=inp.workdir,
        install_cmd=inp.install_cmd,
        evidence=ev,
        dev_server_cmd=inp.dev_server_cmd,
    )


# ── Agent-driven phases ───────────────────────────────────────────────────


@dataclass
class AgentPhaseInput:
    upstream_slug: str
    fork_slug: str
    issue_number: int
    state_root: str
    instruction: str = ""


def _load_scrubbed_brief(ev: EvidenceStore) -> str:
    return ev.read_text("02-forked/scrubbed_brief.md", default="")


@activity.defn(name="request_repro")
async def act_request_repro(inp: AgentPhaseInput) -> dict:
    from .activities.agent import request_repro

    ev = _evidence_for(inp.state_root)
    issue = _issue_ref(inp.upstream_slug, inp.fork_slug, inp.issue_number)
    return request_repro(_agent(), issue, _load_scrubbed_brief(ev), ev, instruction=inp.instruction)


@activity.defn(name="request_fix")
async def act_request_fix(inp: AgentPhaseInput) -> dict:
    from .activities.agent import request_fix

    ev = _evidence_for(inp.state_root)
    issue = _issue_ref(inp.upstream_slug, inp.fork_slug, inp.issue_number)
    return request_fix(_agent(), issue, _load_scrubbed_brief(ev), ev, instruction=inp.instruction)


@activity.defn(name="request_verify")
async def act_request_verify(inp: AgentPhaseInput) -> dict:
    from .activities.agent import request_verify

    ev = _evidence_for(inp.state_root)
    issue = _issue_ref(inp.upstream_slug, inp.fork_slug, inp.issue_number)
    return request_verify(_agent(), issue, _load_scrubbed_brief(ev), ev, instruction=inp.instruction)


@dataclass
class RemediationInput:
    upstream_slug: str
    fork_slug: str
    issue_number: int
    state_root: str


@activity.defn(name="request_remediation")
async def act_request_remediation(inp: RemediationInput) -> dict:
    from .activities.agent import request_remediation

    ev = _evidence_for(inp.state_root)
    issue = _issue_ref(inp.upstream_slug, inp.fork_slug, inp.issue_number)
    return request_remediation(
        _agent(), issue, _load_scrubbed_brief(ev),
        review_comments_path="07-reviewed/comments.json",
        evidence=ev,
    )


# ── Review ────────────────────────────────────────────────────────────────


@dataclass
class ReviewInput:
    fork_slug: str
    pr_number: int
    state_root: str


@activity.defn(name="run_review")
async def act_run_review(inp: ReviewInput) -> dict:
    from .activities.review import run_review

    ev = _evidence_for(inp.state_root)
    return run_review(inp.fork_slug, inp.pr_number, ev)


# ── Submission ────────────────────────────────────────────────────────────


@dataclass
class RenderInput:
    upstream_slug: str
    issue_number: int
    state_root: str


@activity.defn(name="render_pr_body")
async def act_render_pr_body(inp: RenderInput) -> dict:
    from .activities.submission import render_pr_body

    ev = _evidence_for(inp.state_root)
    return render_pr_body(inp.upstream_slug, inp.issue_number, ev)


@dataclass
class SubmitInput:
    upstream_slug: str
    fork_slug: str
    branch_name: str
    base_branch: str
    state_root: str


@activity.defn(name="submit_upstream_pr")
async def act_submit_upstream_pr(inp: SubmitInput) -> dict:
    from .activities.submission import submit_upstream_pr

    ev = _evidence_for(inp.state_root)
    return submit_upstream_pr(
        upstream_slug=inp.upstream_slug,
        fork_slug=inp.fork_slug,
        branch_name=inp.branch_name,
        base_branch=inp.base_branch,
        evidence=ev,
    )


# ── Gate runner ───────────────────────────────────────────────────────────


@dataclass
class GateInput:
    state: str
    upstream_slug: str
    fork_slug: str
    issue_number: int
    state_root: str


@dataclass
class GateOutcome:
    name: str
    verdict: str
    reason: str
    score: float | None
    kind: str


@activity.defn(name="run_gates")
async def act_run_gates(inp: GateInput) -> list[dict]:
    """Returns gate results as plain dicts.

    Temporal's default JSON data converter doesn't round-trip dataclasses
    cleanly across the workflow boundary, so we serialize to dict here and
    the workflow accesses by key. Tests can use the GateOutcome helper to
    construct fake results that match this shape.
    """
    from .gates import IssueRef as GateIssueRef, run_gates
    # Import gate modules so their @gate decorators populate the registry.
    from .gates import (  # noqa: F401
        eligibility,
        environment,
        fix,
        input_context_clean,
        remediation,
        repro,
        submission,
        verify,
    )

    ev = _evidence_for(inp.state_root)
    issue = GateIssueRef(
        fork_slug=inp.fork_slug,
        upstream_slug=inp.upstream_slug,
        upstream_number=inp.issue_number,
    )
    results = run_gates(inp.state, issue, ev)
    return [
        {
            "name": r.name,
            "verdict": r.verdict,
            "reason": r.reason,
            "score": r.score,
            "kind": r.kind,
        }
        for r in results
    ]


# ── Inbox enqueue ─────────────────────────────────────────────────────────


@dataclass
class InboxInput:
    state: str
    gate_name: str
    reason: str
    score: float | None
    upstream_slug: str
    issue_number: int
    state_root: str


@activity.defn(name="enqueue_for_human_review")
async def act_enqueue_for_human_review(inp: InboxInput) -> dict:
    from .activities.inbox import enqueue_for_human_review

    ev = _evidence_for(inp.state_root)
    return enqueue_for_human_review(
        state=inp.state,
        gate_name=inp.gate_name,
        reason=inp.reason,
        score=inp.score,
        upstream_slug=inp.upstream_slug,
        issue_number=inp.issue_number,
        evidence=ev,
    )


# ── Transition recorder ───────────────────────────────────────────────────


@dataclass
class TransitionInput:
    state_root: str
    from_state: str
    to_state: str
    reason: str
    decided_by: str


@activity.defn(name="record_transition")
async def act_record_transition(inp: TransitionInput) -> dict:
    ev = _evidence_for(inp.state_root)
    ev.record_transition(inp.from_state, inp.to_state, inp.reason, inp.decided_by)
    return {"ok": True}


ALL_ACTIVITIES = [
    act_check_eligibility,
    act_fork_and_scrub_brief,
    act_setup_environment,
    act_request_repro,
    act_request_fix,
    act_request_verify,
    act_request_remediation,
    act_run_review,
    act_render_pr_body,
    act_submit_upstream_pr,
    act_run_gates,
    act_enqueue_for_human_review,
    act_record_transition,
]
