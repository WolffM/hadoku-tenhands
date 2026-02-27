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
import os
import subprocess
import time

from .dispatchers import create_default_registry
from .github_api import run_gh_command
from .oss_service import _sanitize_upstream_refs

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
            return {"success": True, "status": "swe_agent_done",
                    "advanced": True, "details": result}

        return {"success": True, "status": "swe_agent_working",
                "advanced": False, "details": result}

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
            updates = {
                "stage4_status": "review_in_progress",
                "stage4_review_requested": True,
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
            updates = {
                "stage4_status": "remediation_running",
                "stage4d_pre_commit_count": result.get("pre_commit_count"),
                "stage4d_skipped": False,
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

    def _build_remediation_context(self, assignment, ctx):
        """Build remediation prompt from review comments + SA findings."""
        parts = ["## Remediation Required\n"]

        pr_number = assignment.get("stage4_pr_number")
        my_user = ctx["my_user"]
        repo = ctx["repo"]

        # Gather inline review comments
        if pr_number:
            result = run_gh_command([
                "api",
                f"repos/{my_user}/{repo}/pulls/{pr_number}/comments",
                "--jq",
                '.[] | "- `\\(.path):\\(.line // .original_line // \"?\")`: \\(.body)"',
            ])
            if result["success"] and result["output"].strip():
                parts.append(
                    "### Review Comments\n"
                    f"{result['output'].strip()}\n"
                )

        # Gather SA findings that survived auto-fix
        sa_run_id = assignment.get("stage4_sa_run_id")
        if sa_run_id:
            sa_dispatcher = self.dispatchers.get("static_analysis")
            if sa_dispatcher:
                sa_results = sa_dispatcher.collect_results(None, ctx)
                if sa_results.get("success"):
                    findings = sa_results["outputs"].get("findings", "")
                    if findings:
                        if len(findings) > 5000:
                            findings = findings[:5000] + "\n... (truncated)"
                        parts.append(
                            "### Static Analysis Findings (post auto-fix)\n"
                            f"```\n{findings}\n```\n"
                        )

        parts.append(
            "### Instructions\n"
            "1. Address each review comment above.\n"
            "2. Fix any remaining static analysis findings.\n"
            "3. Do not introduce new issues.\n"
        )

        context = "\n".join(parts)
        context = _sanitize_upstream_refs(context)
        return context

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
        """Gather structured metrics for the pipeline run."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        repo = assignment.get("repo", "")
        fork_issue = assignment.get("fork_issue_number", 0)
        pr_number = assignment.get("stage4_pr_number")

        retro = {
            "id": f"{repo}/{fork_issue}/{now}",
            "created_at": now,
            "origin_slug": assignment.get("origin_slug", ""),
            "repo": repo,
            "issue_number": assignment.get("issue_number"),
            "fork_issue_number": fork_issue,
        }

        # Pipeline configuration — what model/dispatcher/tools ran each stage
        retro["pipeline"] = {
            "swe_agent": type(self.dispatchers.get("swe", None)).__name__,
            "static_analysis": type(
                self.dispatchers.get("static_analysis", None)).__name__,
            "review_agent": type(self.dispatchers.get("review", None)).__name__,
            "remediation_agent": type(
                self.dispatchers.get("remediation", None)).__name__,
            "language": assignment.get("language"),
            "toolchain_profile": assignment.get("toolchain_profile"),
        }

        # SWE metrics
        swe_data = {"pr_number": pr_number,
                     "pr_branch": assignment.get("stage4_pr_branch")}
        if pr_number and self.dispatchers.get("swe"):
            swe_results = self.dispatchers["swe"].collect_results(
                str(fork_issue), ctx)
            if swe_results.get("success"):
                swe_data.update(swe_results["outputs"])
        retro["swe"] = swe_data

        # SA metrics
        retro["static_analysis"] = {
            "run_id": assignment.get("stage4_sa_run_id"),
            "conclusion": assignment.get("stage4_sa_conclusion"),
        }

        # Review metrics
        inline_count = self._count_inline_comments(assignment, ctx)
        retro["review"] = {
            "inline_comment_count": inline_count,
            "actionable": inline_count > 0,
        }

        # Remediation metrics
        skipped = assignment.get("stage4d_skipped", True)
        retro["remediation"] = {"skipped": skipped}
        if not skipped and self.dispatchers.get("remediation"):
            remed_results = self.dispatchers["remediation"].collect_results(
                str(pr_number), ctx)
            if remed_results.get("success"):
                retro["remediation"].update(remed_results["outputs"])

        # Data quality — how complete was the aggregator data for this run?
        retro["data_quality"] = {
            "context_tier": assignment.get("context_tier"),
            "context_sources": assignment.get("context_sources", []),
            "dossier_completeness": assignment.get("dossier_completeness"),
            "aggregator_meta": assignment.get("aggregator_meta"),
        }

        # Copilot session workflow analysis
        retro["workflow"] = self._fetch_workflow_analysis(
            ctx.get("my_user", ""), repo, pr_number)

        # Timing — per-stage timestamps from assignment record
        retro["timing"] = {
            "assigned_at": assignment.get("assigned_at"),
            "swe_done_at": assignment.get("stage4_swe_done_at"),
            "sa_done_at": assignment.get("stage4_sa_done_at"),
            "review_done_at": assignment.get("stage4_review_done_at"),
            "remediation_done_at": assignment.get("stage4d_done_at"),
            "completed_at": now,
        }

        return retro

    # ---- Copilot session analysis ----

    def _fetch_workflow_analysis(self, my_user, repo, pr_number):
        """Fetch Copilot agent workflow analysis for a PR.

        Calls scripts/copilot-sessions.py compare --json to get
        reproduced/verified/tools/step_count data. Returns a dict
        with workflow metrics, or an empty dict on failure.
        """
        if not pr_number or not my_user or not repo:
            return {}

        script = os.path.join(
            os.path.dirname(__file__), "..", "..", "scripts", "copilot-sessions.py"
        )
        script = os.path.normpath(script)

        if not os.path.exists(script):
            logger.warning("copilot-sessions.py not found at %s", script)
            return {}

        try:
            result = subprocess.run(
                ["python", script, "compare",
                 "-R", f"{my_user}/{repo}",
                 "--prs", str(pr_number),
                 "--json"],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("Workflow analysis failed for PR #%s: %s", pr_number, exc)
            return {}

        # The JSON block is printed after the table — find the top-level array
        # Use "\n[" to avoid matching "[" inside JSON values (e.g. empty arrays)
        output = result.stdout
        json_start = output.rfind("\n[")
        if json_start == -1:
            return {}
        json_start += 1  # skip the newline itself

        try:
            entries = json.loads(output[json_start:])
        except (json.JSONDecodeError, ValueError):
            return {}

        if not entries or "error" in entries[0]:
            return {}

        analysis = entries[0]
        return {
            "reproduced": analysis.get("reproduced", False),
            "verified": analysis.get("verified", False),
            "tool_installed": analysis.get("tool_installed", False),
            "code_review": analysis.get("code_review", False),
            "codeql": analysis.get("codeql", False),
            "self_corrected": analysis.get("self_corrected", False),
            "tools_used": analysis.get("tools_used", []),
            "step_count": analysis.get("step_count", 0),
        }

    # ---- Context builders ----

    def _build_review_context(self, assignment, ctx):
        """Build review context from dossier + static analysis findings.

        This assembles the information the review agent needs to do a
        repo-specific review. All content is sanitized to prevent
        upstream cross-linking.
        """
        if not self.svc:
            return ""

        parts = ["## Review Context\n"]

        # Get dossier for contribution rules and patterns
        origin_slug = assignment.get("origin_slug", "")
        if origin_slug:
            hyphenated = origin_slug.replace("/", "-")
            dossier_data = self.svc.get_dossier(hyphenated)
            if dossier_data and dossier_data.get("sections"):
                sections = dossier_data["sections"]
                if sections.get("contributionRules"):
                    parts.append(
                        "### Contribution Rules\n"
                        f"{sections['contributionRules']}\n"
                    )
                if sections.get("successPatterns"):
                    parts.append(
                        "### What Successful PRs Look Like\n"
                        f"{sections['successPatterns']}\n"
                    )
                if sections.get("antiPatterns"):
                    parts.append(
                        "### Common Rejection Reasons\n"
                        f"{sections['antiPatterns']}\n"
                    )

        # Get static analysis findings
        sa_run_id = assignment.get("stage4_sa_run_id")
        if sa_run_id:
            sa_dispatcher = self.dispatchers.get("static_analysis")
            if sa_dispatcher:
                sa_results = sa_dispatcher.collect_results(None, ctx)
                if sa_results.get("success"):
                    findings = sa_results["outputs"].get("findings", "")
                    if findings:
                        # Truncate for review context
                        if len(findings) > 5000:
                            findings = findings[:5000] + "\n... (truncated)"
                        parts.append(
                            "### Static Analysis Findings\n"
                            f"```\n{findings}\n```\n"
                        )

        parts.append(
            "### Review Instructions\n"
            "1. Check that the code change fixes the problem.\n"
            "2. Check for issues flagged by static analysis above.\n"
            "3. Verify the change follows contribution rules and patterns.\n"
            "4. Check for anti-patterns that would cause upstream rejection.\n"
            "5. Leave specific, actionable review comments.\n"
        )

        context = "\n".join(parts)

        # Sanitize to prevent upstream cross-linking
        context = _sanitize_upstream_refs(context)
        return context

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
