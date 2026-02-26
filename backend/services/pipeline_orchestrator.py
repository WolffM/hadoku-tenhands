"""
Pipeline Orchestrator — sequences Stage 4 sub-stages (4a → 4b → 4c).

The orchestrator is a state machine that advances assignments through
the pipeline one step at a time. It delegates actual work to dispatchers
(pluggable backends) and tracks state in assignment records.

State transitions:
    swe_agent_working → swe_agent_done
    swe_agent_done → static_analysis_running
    static_analysis_running → static_analysis_done
    static_analysis_done → review_in_progress
    review_in_progress → review_complete
"""

from .dispatchers import create_default_registry
from .oss_service import _sanitize_upstream_refs


# Valid pipeline states in order
PIPELINE_STATES = [
    "swe_agent_working",
    "swe_agent_done",
    "static_analysis_running",
    "static_analysis_done",
    "review_in_progress",
    "review_complete",
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
            return {"success": True, "status": "review_complete",
                    "advanced": False, "message": "Pipeline complete"}

        return {"success": False, "status": status,
                "error": f"Unknown pipeline state: {status}"}

    def _check_swe_completion(self, assignment, ctx):
        """Check if the SWE agent (4a) has finished."""
        dispatcher = self.dispatchers["swe"]
        job_id = str(assignment.get("fork_issue_number", ""))
        result = dispatcher.check_status(job_id, ctx)

        if result.get("done"):
            updates = {
                "stage4_status": "swe_agent_done",
                "stage4_pr_number": result.get("pr_number"),
                "stage4_pr_branch": result.get("pr_branch"),
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
            updates = {
                "stage4_status": "static_analysis_done",
                "stage4_sa_run_id": result.get("run_id"),
                "stage4_sa_conclusion": result.get("conclusion"),
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
            updates = {"stage4_status": "review_complete"}
            self._update_assignment(assignment, updates)
            return {"success": True, "status": "review_complete",
                    "advanced": True, "details": result}

        return {"success": True, "status": "review_in_progress",
                "advanced": False, "details": result}

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
