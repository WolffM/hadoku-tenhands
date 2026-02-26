"""
Stage 4 Dispatchers — pluggable backends for pipeline sub-stages.

Each dispatcher handles a specific type of work (SWE, static analysis, review)
via a common interface. The pipeline orchestrator delegates to dispatchers
without knowing which tool or system is doing the work.

To add a new agent backend (e.g., Devin, Cursor), implement StageDispatcher
and register it in the dispatcher registry.
"""

import json

from .github_api import run_gh_command


class StageDispatcher:
    """Abstract interface for dispatching Stage 4 jobs.

    All dispatchers must implement three methods:
    - dispatch: start the job
    - check_status: poll for completion
    - collect_results: extract outputs from a completed job
    """

    def dispatch(self, job_spec, context):
        """Start a job.

        Args:
            job_spec: Dict describing the work to do.
            context: Dict with assignment metadata (repo, user, etc.)
        Returns:
            Dict with at least {success: bool}. May include job_id, metadata.
        """
        raise NotImplementedError

    def check_status(self, job_id, context):
        """Check if a dispatched job is complete.

        Args:
            job_id: Identifier returned by dispatch().
            context: Dict with assignment metadata.
        Returns:
            Dict with {done: bool, status: str, ...details}.
        """
        raise NotImplementedError

    def collect_results(self, job_id, context):
        """Extract outputs from a completed job.

        Args:
            job_id: Identifier returned by dispatch().
            context: Dict with assignment metadata.
        Returns:
            Dict with {success: bool, outputs: dict}.
        """
        raise NotImplementedError


# ============ Copilot SWE Agent Dispatcher ============


class CopilotSWEDispatcher(StageDispatcher):
    """Dispatches work to GitHub Copilot coding agent via fork issue assignment.

    This is the Stage 4a dispatcher. It:
    - Creates a context issue on the fork (done during Stage 3)
    - Assigns @Copilot to the issue
    - Detects completion via the Copilot check-run status
    - Collects results: PR number, branch, commit count
    """

    def dispatch(self, job_spec, context):
        """Stage 4a dispatch is handled during Stage 3 (fork-and-assign).

        By the time the orchestrator runs, the SWE agent is already working.
        This method is a no-op — it returns the existing assignment info.
        """
        return {
            "success": True,
            "job_id": str(context.get("fork_issue_number", "")),
            "message": "SWE agent already dispatched during Stage 3",
        }

    def check_status(self, job_id, context):
        """Check if the Copilot SWE agent has finished.

        Detection: look for a Copilot-authored PR and check if
        the 'Running Copilot coding agent' check-run has completed.
        """
        my_user = context["my_user"]
        repo = context["repo"]

        # Find Copilot-authored PRs
        result = run_gh_command([
            "pr", "list", "-R", f"{my_user}/{repo}",
            "--json", "number,title,headRefName,author,commits",
            "--state", "open",
        ])
        if not result["success"]:
            return {"done": False, "status": "error",
                    "error": result.get("error", "")}

        prs = json.loads(result["output"])

        # Find the agent's PR
        agent_pr = None
        for pr in prs:
            author = pr.get("author", {})
            login = author.get("login", "") if isinstance(author, dict) else ""
            if "copilot" in login.lower():
                agent_pr = pr
                break

        if not agent_pr:
            return {"done": False, "status": "waiting_for_pr", "pr_number": None}

        pr_number = agent_pr["number"]
        pr_branch = agent_pr["headRefName"]

        # Check the Copilot coding agent check-run
        head_result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json", "headRefOid", "--jq", ".headRefOid",
        ])
        if head_result["success"]:
            head_sha = head_result["output"].strip()
            checks_result = run_gh_command([
                "api",
                f"repos/{my_user}/{repo}/commits/{head_sha}/check-runs",
                "--jq",
                '.check_runs[] | select(.name=="Running Copilot coding agent") | .status',
            ])
            if checks_result["success"]:
                status = checks_result["output"].strip()
                if status == "completed":
                    return {
                        "done": True,
                        "status": "completed",
                        "pr_number": pr_number,
                        "pr_branch": pr_branch,
                    }

        commits = agent_pr.get("commits", [])
        commit_count = len(commits) if isinstance(commits, list) else 0
        return {
            "done": False,
            "status": "working",
            "pr_number": pr_number,
            "pr_branch": pr_branch,
            "commit_count": commit_count,
        }

    def collect_results(self, job_id, context):
        """Collect the SWE agent's output: PR details."""
        my_user = context["my_user"]
        repo = context["repo"]
        pr_number = context.get("stage4_pr_number")

        if not pr_number:
            return {"success": False, "error": "No PR number available"}

        result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json",
            "number,title,headRefName,additions,deletions,changedFiles,commits",
        ])
        if not result["success"]:
            return {"success": False, "error": result.get("error", "")}

        pr_data = json.loads(result["output"])
        return {
            "success": True,
            "outputs": {
                "pr_number": pr_data["number"],
                "pr_branch": pr_data["headRefName"],
                "title": pr_data["title"],
                "additions": pr_data.get("additions", 0),
                "deletions": pr_data.get("deletions", 0),
                "changed_files": pr_data.get("changedFiles", 0),
                "commit_count": len(pr_data.get("commits", [])),
            },
        }


# ============ GitHub Actions Dispatcher ============


class GitHubActionsDispatcher(StageDispatcher):
    """Dispatches work via GitHub Actions workflow_dispatch.

    This is the Stage 4b dispatcher. It:
    - Ensures the static-analysis workflow exists on the fork
    - Triggers it via workflow_dispatch with the PR branch as input
    - Polls the workflow run for completion
    - Collects logs and annotations as results
    """

    def __init__(self, workflow_name="static-analysis.yml"):
        self.workflow_name = workflow_name

    def dispatch(self, job_spec, context):
        """Trigger the static analysis workflow against a branch."""
        my_user = context["my_user"]
        repo = context["repo"]
        branch = job_spec.get("branch", "main")

        result = run_gh_command([
            "workflow", "run", self.workflow_name,
            "-R", f"{my_user}/{repo}",
            "-f", f"ref={branch}",
        ])
        if not result["success"]:
            return {"success": False, "error": result.get("error", "")}

        return {
            "success": True,
            "job_id": f"{my_user}/{repo}:{self.workflow_name}",
            "branch": branch,
        }

    def check_status(self, job_id, context):
        """Check if the latest static analysis workflow run is complete."""
        my_user = context["my_user"]
        repo = context["repo"]

        result = run_gh_command([
            "run", "list", "-R", f"{my_user}/{repo}",
            "-w", self.workflow_name,
            "--json", "databaseId,status,conclusion,createdAt",
            "--limit", "1",
        ])
        if not result["success"]:
            return {"done": False, "status": "error",
                    "error": result.get("error", "")}

        runs = json.loads(result["output"])
        if not runs:
            return {"done": False, "status": "not_found"}

        run = runs[0]
        if run["status"] == "completed":
            return {
                "done": True,
                "status": "completed",
                "conclusion": run.get("conclusion", "unknown"),
                "run_id": run["databaseId"],
            }
        return {
            "done": False,
            "status": run["status"],
            "run_id": run["databaseId"],
        }

    def collect_results(self, job_id, context):
        """Extract logs from the completed workflow run."""
        my_user = context["my_user"]
        repo = context["repo"]
        run_id = context.get("stage4_sa_run_id")

        if not run_id:
            return {"success": False, "error": "No run ID available"}

        # Get the workflow run log
        log_result = run_gh_command([
            "run", "view", str(run_id), "-R", f"{my_user}/{repo}",
            "--log",
        ], timeout=60)

        findings = log_result.get("output", "") if log_result["success"] else ""

        # Truncate to avoid massive payloads
        if len(findings) > 20000:
            findings = findings[:20000] + "\n\n... (log truncated)"

        return {
            "success": True,
            "outputs": {
                "run_id": run_id,
                "findings": findings,
            },
        }


# ============ Copilot Review Dispatcher ============


class CopilotReviewDispatcher(StageDispatcher):
    """Dispatches review via Copilot pull-request-reviewer.

    This is the Stage 4c dispatcher. It:
    - Posts review context as a PR comment (patterns, anti-patterns, findings)
    - Requests Copilot pull-request-reviewer as a reviewer
    - Polls for the review to be posted
    - Collects the review state and body
    """

    def _fetch_copilot_review(self, my_user, repo, pr_number):
        """Fetch the Copilot review from a PR's reviews list.

        Returns the review dict {user, state, body} or None if not found.
        """
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/pulls/{pr_number}/reviews",
            "--jq", ".[] | {user: .user.login, state: .state, body: .body}",
        ])
        if not result["success"]:
            return None

        for line in result["output"].strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                review = json.loads(line)
                if "copilot" in (review.get("user") or "").lower():
                    return review
            except json.JSONDecodeError:
                continue
        return None

    def dispatch(self, job_spec, context):
        """Post review context and request Copilot review."""
        my_user = context["my_user"]
        repo = context["repo"]
        pr_number = job_spec.get("pr_number")
        review_context = job_spec.get("review_context", "")

        if not pr_number:
            return {"success": False, "error": "No PR number"}

        # Post review context as a PR comment
        if review_context:
            run_gh_command([
                "pr", "comment", str(pr_number),
                "-R", f"{my_user}/{repo}",
                "--body", review_context,
            ])

        # Request Copilot review
        review_result = run_gh_command([
            "api", "-X", "POST",
            f"repos/{my_user}/{repo}/pulls/{pr_number}/requested_reviewers",
            "-f", "reviewers[]=copilot-pull-request-reviewer[bot]",
        ])

        return {
            "success": review_result.get("success", False),
            "job_id": f"{my_user}/{repo}#{pr_number}",
            "pr_number": pr_number,
        }

    def check_status(self, job_id, context):
        """Check if the Copilot review has been posted."""
        pr_number = context.get("stage4_pr_number")
        if not pr_number:
            return {"done": False, "status": "error", "error": "No PR number"}

        review = self._fetch_copilot_review(
            context["my_user"], context["repo"], pr_number)
        if review:
            return {
                "done": True,
                "status": "review_posted",
                "review_state": review.get("state"),
                "review_body": review.get("body", ""),
            }
        return {"done": False, "status": "waiting_for_review"}

    def collect_results(self, job_id, context):
        """Collect the Copilot review details."""
        pr_number = context.get("stage4_pr_number")
        if not pr_number:
            return {"success": False, "error": "No PR number"}

        review = self._fetch_copilot_review(
            context["my_user"], context["repo"], pr_number)
        if review:
            return {
                "success": True,
                "outputs": {
                    "review_state": review.get("state"),
                    "review_body": review.get("body", ""),
                    "reviewer": review.get("user", ""),
                },
            }
        return {"success": False, "error": "No Copilot review found"}


# ============ Dispatcher Registry ============


def create_default_registry():
    """Create the default dispatcher registry with Copilot + GitHub Actions.

    To swap dispatchers, replace entries in this registry.
    """
    return {
        "swe": CopilotSWEDispatcher(),
        "static_analysis": GitHubActionsDispatcher(),
        "review": CopilotReviewDispatcher(),
    }
