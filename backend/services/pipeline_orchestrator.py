"""
Pipeline Orchestrator — sequences Stage 4 sub-stages (4a → 4b → 4c → 4d → 4.5).

The orchestrator is a state machine that advances assignments through
the pipeline one step at a time. It delegates actual work to dispatchers
(pluggable backends) and tracks state in assignment records.

State transitions:
    swe_agent_working → swe_agent_done
    swe_agent_done → static_analysis_running
    static_analysis_running → static_analysis_done
    static_analysis_done → review_in_progress
    review_in_progress → review_complete
    review_complete → remediation_running | remediation_done (skip)
    remediation_running → remediation_done
    remediation_done → retrospective_complete
"""

import json
import logging
import time

from .dispatchers import create_default_registry
from .github_api import run_gh_command
from .pipeline_session_analysis import (
    fetch_workflow_analysis as _fetch_workflow_analysis_fn,
    fetch_session_log as _fetch_session_log_fn,
    fetch_fork_diff as _fetch_fork_diff_fn,
)
from .pipeline_context_builders import (
    build_remediation_context as _build_remediation_context_fn,
    build_review_context as _build_review_context_fn,
)
from .pipeline_retrospective import (
    collect_retrospective as _collect_retrospective_fn,
)

logger = logging.getLogger(__name__)


# Valid pipeline states in order
PIPELINE_STATES = [
    "swe_agent_working",
    "swe_agent_done",
    "static_analysis_running",
    "static_analysis_done",
    "review_in_progress",
    "review_complete",
    "remediation_running",
    "remediation_done",
    "retrospective_complete",
]


class PipelineOrchestrator:
    """Advances assignments through the Stage 4 pipeline.

    Each call to advance() moves an assignment forward at most one step.
    The orchestrator is idempotent — calling advance() repeatedly on a
    completed assignment is a no-op.
    """

    def __init__(self, dispatchers=None, oss_service=None):
        """
        Args:
            dispatchers: Dict mapping job types to StageDispatcher instances.
                         Defaults to create_default_registry().
            oss_service: OSSService instance for state persistence and
                         context building. If None, must be provided per-call.
        """
        self.dispatchers = dispatchers or create_default_registry()
        self.svc = oss_service

    def advance(self, assignment, context):
        """Advance one assignment one step through the pipeline.

        Args:
            assignment: The assignment dict from assignments.json
            context: Dict with {my_user, ...} — runtime context
        Returns:
            Dict with {success, status, advanced: bool, ...details}
        """
        status = assignment.get("stage4_status", "swe_agent_working")

        # Merge assignment into context for dispatchers
        ctx = {**context, **assignment}

        if status == "swe_agent_working":
            return self._check_swe_completion(assignment, ctx)
        elif status == "swe_agent_done":
            return self._dispatch_static_analysis(assignment, ctx)
        elif status == "static_analysis_running":
            return self._check_static_analysis(assignment, ctx)
        elif status == "static_analysis_done":
            return self._dispatch_review(assignment, ctx)
        elif status == "review_in_progress":
            return self._check_review(assignment, ctx)
        elif status == "review_complete":
            return self._dispatch_remediation(assignment, ctx)
        elif status == "remediation_running":
            return self._check_remediation(assignment, ctx)
        elif status == "remediation_done":
            return self._log_retrospective(assignment, ctx)
        elif status == "retrospective_complete":
            return {"success": True, "status": "retrospective_complete",
                    "advanced": False, "message": "Pipeline complete"}

        return {"success": False, "status": status,
                "error": f"Unknown pipeline state: {status}"}

    def _check_swe_completion(self, assignment, ctx):
        """Check if the SWE agent (4a) has finished."""
        dispatcher = self.dispatchers["swe"]
        job_id = str(assignment.get("fork_issue_number", ""))
        result = dispatcher.check_status(job_id, ctx)

        if result.get("done"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "swe_agent_done",
                "stage4_pr_number": result.get("pr_number"),
                "stage4_pr_branch": result.get("pr_branch"),
                "stage4_swe_done_at": now,
            }
            self._update_assignment(assignment, updates)

            # Close any other open Copilot PRs on this fork that are stale
            # (Copilot creates a new branch+PR each time it retries)
            my_user = ctx.get("my_user", "")
            repo = assignment.get("repo", "")
            pr_num = result.get("pr_number")
            if pr_num and my_user and repo:
                self._close_stale_copilot_prs(my_user, repo, pr_num)

            return {"success": True, "status": "swe_agent_done",
                    "advanced": True, "details": result}

        return {"success": True, "status": "swe_agent_working",
                "advanced": False, "details": result}

    def _close_stale_copilot_prs(self, my_user, repo, keep_pr_number):
        """Close open Copilot PRs on the fork that are not the active one.

        Copilot creates a new branch+PR each time it retries. When we detect
        the active PR, close all other open Copilot PRs to avoid accumulation.
        """
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/pulls?state=open&per_page=100",
            "--jq",
            '[.[] | select(.user.login | ascii_downcase | contains("copilot")) | .number]',
        ])
        if not result["success"]:
            return
        try:
            open_copilot_prs = json.loads(result["output"])
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(open_copilot_prs, list):
            return
        for pr_num in open_copilot_prs:
            if pr_num == keep_pr_number:
                continue
            close_result = run_gh_command([
                "pr", "close", str(pr_num), "-R", f"{my_user}/{repo}",
                "--comment", f"Superseded by #{keep_pr_number}. Closing stale Copilot attempt.",
            ])
            if close_result["success"]:
                logger.info("Closed stale Copilot PR #%s on %s/%s", pr_num, my_user, repo)
            else:
                logger.warning("Failed to close stale PR #%s on %s/%s: %s",
                               pr_num, my_user, repo, close_result.get("error", ""))

    def _dispatch_static_analysis(self, assignment, ctx):
        """Dispatch static analysis (4b) against the SWE agent's branch."""
        dispatcher = self.dispatchers["static_analysis"]

        job_spec = {
            "type": "static_analysis",
            "branch": assignment.get("stage4_pr_branch", "main"),
            "language": assignment.get("language"),
            "toolchain": assignment.get("toolchain_profile"),
        }

        result = dispatcher.dispatch(job_spec, ctx)
        if result.get("success"):
            updates = {"stage4_status": "static_analysis_running"}
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "static_analysis_running",
                    "advanced": True, "details": result}

        return {"success": False, "status": "swe_agent_done",
                "advanced": False, "error": result.get("error", "Dispatch failed")}

    def _check_static_analysis(self, assignment, ctx):
        """Check if static analysis (4b) has completed."""
        dispatcher = self.dispatchers["static_analysis"]
        job_id = f"{ctx['my_user']}/{ctx['repo']}:static-analysis.yml"
        result = dispatcher.check_status(job_id, ctx)

        if result.get("done"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "static_analysis_done",
                "stage4_sa_run_id": result.get("run_id"),
                "stage4_sa_conclusion": result.get("conclusion"),
                "stage4_sa_done_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "static_analysis_done",
                    "advanced": True, "details": result}

        # If the run is queued (not in_progress), the runner may be down.
        # Attempt to restart it — _ensure_self_hosted_runner is idempotent.
        if result.get("status") == "queued":
            my_user = ctx["my_user"]
            repo = ctx["repo"]
            origin_owner = assignment.get("origin_owner", "")
            logger.warning(
                "SA run queued with no runner for %s/%s — attempting runner restart",
                my_user, repo
            )
            try:
                from .oss_fork import OSSForkMixin
                fork_mixin = OSSForkMixin()
                fork_mixin._ensure_self_hosted_runner(my_user, repo)
            except Exception as e:
                logger.error("Runner restart failed for %s/%s: %s", my_user, repo, e)

        return {"success": True, "status": "static_analysis_running",
                "advanced": False, "details": result}

    def _dispatch_review(self, assignment, ctx):
        """Dispatch the review agent (4c)."""
        dispatcher = self.dispatchers["review"]

        # Build review context from available data
        review_context = self._build_review_context(assignment, ctx)

        job_spec = {
            "type": "review",
            "pr_number": assignment.get("stage4_pr_number"),
            "review_context": review_context,
        }

        result = dispatcher.dispatch(job_spec, ctx)
        if result.get("success"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "review_in_progress",
                "stage4_review_requested": True,
                "stage4_review_dispatched_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "review_in_progress",
                    "advanced": True, "details": result}

        return {"success": False, "status": "static_analysis_done",
                "advanced": False, "error": result.get("error", "Dispatch failed")}

    def _check_review(self, assignment, ctx):
        """Check if the review agent (4c) has posted its review."""
        dispatcher = self.dispatchers["review"]
        job_id = f"{ctx['my_user']}/{ctx['repo']}#{assignment.get('stage4_pr_number')}"
        result = dispatcher.check_status(job_id, ctx)

        if result.get("done"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "review_complete",
                "stage4_review_done_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "review_complete",
                    "advanced": True, "details": result}

        # Check timeout — 10 minutes since review was requested
        dispatched_at = assignment.get("stage4_review_dispatched_at")
        if dispatched_at:
            import datetime
            try:
                dt = datetime.datetime.fromisoformat(
                    dispatched_at.replace("Z", "+00:00"))
                elapsed = time.time() - dt.timestamp()
                if elapsed > 600:  # 10 minutes
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    updates = {
                        "stage4_status": "review_complete",
                        "stage4_review_done_at": now,
                        "stage4_review_timed_out": True,
                    }
                    self._update_assignment(assignment, updates)
                    return {
                        "success": True, "status": "review_complete",
                        "advanced": True,
                        "details": {"status": "timeout",
                                    "message": "No Copilot review after 10 minutes"},
                    }
            except (ValueError, TypeError) as e:
                logger.error(
                    "Review timeout check failed for %s #%s — dispatched_at=%r error: %s",
                    assignment.get("origin_slug"), assignment.get("issue_number"),
                    dispatched_at, e
                )

        return {"success": True, "status": "review_in_progress",
                "advanced": False, "details": result}

    # ---- Stage 4d: Remediation ----

    def _dispatch_remediation(self, assignment, ctx):
        """Dispatch remediation (4d) or skip if review has no actionable comments."""
        inline_comments = self._count_inline_comments(assignment, ctx)

        if inline_comments == 0:
            # No actionable feedback — skip 4d
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "remediation_done",
                "stage4d_skipped": True,
                "stage4d_done_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "remediation_done",
                    "advanced": True, "skipped": True,
                    "message": "No actionable review comments — skipped remediation"}

        # Build remediation context and dispatch
        remediation_body = self._build_remediation_context(assignment, ctx)
        dispatcher = self.dispatchers["remediation"]
        job_spec = {
            "type": "remediation",
            "pr_number": assignment.get("stage4_pr_number"),
            "remediation_body": remediation_body,
        }
        result = dispatcher.dispatch(job_spec, ctx)
        if result.get("success"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "remediation_running",
                "stage4d_pre_commit_count": result.get("pre_commit_count"),
                "stage4d_skipped": False,
                "stage4d_dispatched_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "remediation_running",
                    "advanced": True, "details": result}

        return {"success": False, "status": "review_complete",
                "advanced": False,
                "error": result.get("error", "Remediation dispatch failed")}

    def _check_remediation(self, assignment, ctx):
        """Check if remediation (4d) is complete."""
        dispatcher = self.dispatchers["remediation"]
        job_id = str(assignment.get("stage4_pr_number", ""))
        result = dispatcher.check_status(job_id, ctx)

        if result.get("done"):
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            updates = {
                "stage4_status": "remediation_done",
                "stage4d_done_at": now,
            }
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "remediation_done",
                    "advanced": True, "details": result}

        return {"success": True, "status": "remediation_running",
                "advanced": False, "details": result}

    def _count_inline_comments(self, assignment, ctx):
        """Count inline review comments on the PR (not the top-level review body)."""
        pr_number = assignment.get("stage4_pr_number")
        if not pr_number:
            return 0
        result = run_gh_command([
            "api",
            f"repos/{ctx['my_user']}/{ctx['repo']}/pulls/{pr_number}/comments",
            "--jq", "length",
        ])
        if result["success"]:
            try:
                return int(result["output"].strip())
            except (ValueError, TypeError):
                pass
        return 0

    def _get_sa_findings(self, assignment, ctx):
        """Return SA findings string (truncated to 5000 chars) or empty string."""
        if not assignment.get("stage4_sa_run_id"):
            return ""
        sa_dispatcher = self.dispatchers.get("static_analysis")
        if not sa_dispatcher:
            return ""
        sa_results = sa_dispatcher.collect_results(None, ctx)
        if not sa_results.get("success"):
            return ""
        findings = sa_results["outputs"].get("findings", "")
        if len(findings) > 5000:
            findings = findings[:5000] + "\n... (truncated)"
        return findings

    def _build_remediation_context(self, assignment, ctx):
        """Build remediation prompt from review comments + SA findings.

        Delegates to pipeline_context_builders.build_remediation_context.
        """
        return _build_remediation_context_fn(assignment, ctx, self._get_sa_findings)

    # ---- Stage 4.5: Retrospective ----

    def _log_retrospective(self, assignment, ctx):
        """Stage 4.5: Log structured retrospective and finalize pipeline."""
        retro = self._collect_retrospective(assignment, ctx)

        if self.svc:
            self.svc.append_retrospective_log(retro)

        updates = {"stage4_status": "retrospective_complete"}
        self._update_assignment(assignment, updates)
        return {"success": True, "status": "retrospective_complete",
                "advanced": True, "retrospective": retro}

    def _collect_retrospective(self, assignment, ctx):
        """Gather structured metrics for the pipeline run.

        Delegates to pipeline_retrospective.collect_retrospective, passing
        self._fetch_workflow_analysis so patch.object on the class still works.
        """
        return _collect_retrospective_fn(
            assignment,
            ctx,
            self.dispatchers,
            self._count_inline_comments,
            fetch_workflow_analysis_fn=self._fetch_workflow_analysis,
        )

    # ---- Copilot session analysis ----

    def _fetch_workflow_analysis(self, my_user, repo, pr_number):
        """Fetch Copilot agent workflow analysis for a PR.

        Delegates to pipeline_session_analysis.fetch_workflow_analysis.
        Kept as a class method so tests can patch it via patch.object.
        """
        return _fetch_workflow_analysis_fn(my_user, repo, pr_number)

    def _fetch_session_log(self, my_user, repo, pr_number):
        """Fetch full Copilot session thinking log via copilot-sessions.py summary.

        Delegates to pipeline_session_analysis.fetch_session_log.
        """
        return _fetch_session_log_fn(my_user, repo, pr_number)

    def _fetch_fork_diff(self, my_user, repo, pr_number):
        """Fetch the full diff of the fork PR via gh pr diff.

        Delegates to pipeline_session_analysis.fetch_fork_diff.
        """
        return _fetch_fork_diff_fn(my_user, repo, pr_number)

    # ---- Context builders ----

    def _build_review_context(self, assignment, ctx):
        """Build review context from dossier + static analysis findings.

        Delegates to pipeline_context_builders.build_review_context.
        """
        return _build_review_context_fn(assignment, ctx, self.svc, self._get_sa_findings)

    def _update_assignment(self, assignment, updates):
        """Persist state changes to the assignment record."""
        if self.svc:
            self.svc.update_assignment(
                assignment["repo"],
                assignment["fork_issue_number"],
                updates,
            )
        # Also update the in-memory dict so subsequent calls see the change
        assignment.update(updates)
