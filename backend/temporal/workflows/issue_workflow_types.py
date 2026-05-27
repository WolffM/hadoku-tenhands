"""Types + tunables shared between `issue_workflow.py` and
`issue_workflow_post.py`.

Pure data — no `workflow.execute_activity` calls, no Temporal imports.
Lives in its own module to break the circular dependency between the
main workflow file (which holds the `IssueWorkflow` class) and the
post-submission module (which holds the polling / remediation
free-functions called from inside the workflow).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta


# ── Inputs / Results ──────────────────────────────────────────────────────


@dataclass
class IssueInput:
    upstream_slug: str          # e.g. "microsoft/markitdown"
    fork_slug: str              # e.g. "WolffM/markitdown"
    issue_number: int
    state_root: str             # path to evidence dir for this issue
    raw_brief_text: str         # the unscrubbed brief text from the operator
    branch_name: str            # operator-readable branch (e.g. "fix-merged-cells")
    # No default for base_branch — the dispatch endpoint MUST resolve it
    # from the upstream's actual default_branch before constructing
    # IssueInput. A default of "main" silently produced PR-submission
    # crashes against repos that use master/develop (argoproj/argo-cd
    # 2026-05-27). Required field.
    base_branch: str = ""
    install_cmd: list[str] = field(default_factory=lambda: ["python", "-c", "0"])
    workdir: str = "."
    pr_number_for_review: int | None = None  # set after fix/agent PR is identified
    # Routes the Copilot-bound activities (request_repro/fix/verify/
    # remediation) to a separate, capped task queue so those slots are
    # NOT held while the workflow sits in human-review wait. Empty
    # string means "schedule on the workflow's own task queue" — tests
    # rely on that default so they don't need a second worker.
    copilot_task_queue: str = ""


@dataclass
class IssueResult:
    final_state: str
    upstream_pr_url: str = ""
    upstream_pr_number: int | None = None
    abort_reason: str = ""
    deferred_at: str = ""
    deferred_gate: str = ""


# ── Workflow-level tunables ────────────────────────────────────────────────


# How long an activity has to complete before Temporal cancels it. The
# Copilot-driven activities can take 30–180 minutes so we set this high.
_LONG_ACTIVITY_TIMEOUT = timedelta(hours=4)
_SHORT_ACTIVITY_TIMEOUT = timedelta(minutes=10)

# Phase 5.1 post-submission tunables.
#
# Polling cadence: default 30 min; when the prior poll surfaced a NEW
# blocking review or human comment, tighten to 5 min for the next poll
# so we react quickly during active review. After a quiet poll the
# cadence relaxes back to 30 min. Math at the conservative end: 30 min
# × 24h = 48 polls/day per workflow, well inside the 5000/hr per-token
# gh budget for any plausible batch.
_POLL_CADENCE_DEFAULT = timedelta(minutes=30)
_POLL_CADENCE_AFTER_ACTIVITY = timedelta(minutes=5)

# Termination condition: if no upstream activity for this many days we
# stop watching and transition to closed_by_upstream with reason="stale".
# Maintainer never engaged — treat as a soft loss.
_POST_SUBMISSION_STALE_DAYS = 30

# Cap on how many times a single workflow loops through the
# remediation → re-signoff cycle. Without this an adversarial reviewer
# could keep us in the loop indefinitely; in practice operators should
# step in well before this fires.
_MAX_REMEDIATION_CYCLES = 3

# Phase 5.2 — local Copilot Review remediation loop. After the workflow
# runs the fork-internal code review, if blocking comments exist we
# branch into request_remediation and re-run review. Capped at 3 to
# prevent the agent from looping on its own bad output.
_MAX_LOCAL_REMEDIATION_ITERATIONS = 3

# How long the workflow waits at awaiting_signoff for the operator's
# `submit_human_decision` signal before timing out. Module-level so
# tests can patch a short timeout for the time-skipping environment.
_OPERATOR_SIGNOFF_TIMEOUT = timedelta(days=14)


# ── Internal control-flow exceptions ──────────────────────────────────────


class _GateFailed(Exception):
    def __init__(self, gate_name: str, reason: str) -> None:
        super().__init__(f"gate {gate_name} failed: {reason}")
        self.gate_name = gate_name
        self.reason = reason


class _OperatorAborted(Exception):
    def __init__(self, state: str, gate_name: str, reason: str) -> None:
        super().__init__(f"operator aborted at {state}/{gate_name}")
        self.state = state
        self.gate_name = gate_name
        self.reason = reason
