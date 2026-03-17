"""
Stage 4 Dispatchers — pluggable backends for pipeline sub-stages.

Each dispatcher handles a specific type of work (SWE, static analysis, review)
via a common interface. The pipeline orchestrator delegates to dispatchers
without knowing which tool or system is doing the work.

To add a new agent backend (e.g., Devin, Cursor), implement StageDispatcher
and register it in the dispatcher registry.
"""

import json
import logging

try:
    from ..config import COPILOT_REVIEWER, COPILOT_MENTION, COPILOT_CHECK_RUN_NAME
except ImportError:
    from config import COPILOT_REVIEWER, COPILOT_MENTION, COPILOT_CHECK_RUN_NAME
from .github_api import run_gh_command

logger = logging.getLogger(__name__)


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
            job_id: Correlation key identifying the specific job to check.
                    Dispatchers MUST use this to distinguish between
                    concurrent jobs of the same type.
            context: Dict with ambient metadata (my_user, repo, etc.)
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

    def _find_pr_for_issue(self, my_user, repo, fork_issue_number, copilot_prs):
        """Correlate a fork issue to its Copilot PR by matching the fork issue
        title against the <issue_title> tag we inject into every Copilot context.

        This is reliable because we control the PR body content — we inject
        <issue_title>{title}</issue_title> into the context we give Copilot,
        and Copilot includes it verbatim in the PR description.

        Falls back to cross-reference timeline if the title match fails.

        Args:
            copilot_prs: List of open Copilot-authored PR dicts (must include .body).
        Returns the matched PR dict from copilot_prs, or None.
        """
        # Fetch the fork issue title — this is what we injected into Copilot's context.
        issue_result = run_gh_command([
            "api",
            f"repos/{my_user}/{repo}/issues/{fork_issue_number}",
            "--jq", ".title",
        ])
        if issue_result["success"]:
            fork_issue_title = issue_result["output"].strip().strip('"')
            if fork_issue_title:
                matched = [
                    p for p in copilot_prs
                    if f"<issue_title>{fork_issue_title}</issue_title>" in (p.get("body") or "")
                ]
                if matched:
                    return max(matched, key=lambda p: len(p.get("commits", [])))

        # Fallback: cross-reference timeline (works when repo has a PR template
        # that Copilot fills with "Fixes owner/repo#N").
        result = run_gh_command([
            "api",
            f"repos/{my_user}/{repo}/issues/{fork_issue_number}/timeline",
            "--jq",
            '[.[] | select(.event=="cross-referenced") | .source.issue.number]',
        ])
        if not result["success"]:
            return None
        try:
            linked_numbers = json.loads(result["output"].strip())
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
        if not linked_numbers:
            return None

        pr_by_number = {p["number"]: p for p in copilot_prs}
        matched = [pr_by_number[n] for n in linked_numbers if n in pr_by_number]
        if not matched:
            return None
        return max(matched, key=lambda p: len(p.get("commits", [])))

    def check_status(self, job_id, context):
        """Check if the Copilot SWE agent has finished.

        Detection: correlate the fork issue (job_id) to its Copilot PR
        via the issue timeline, then check the check-run status.
        """
        my_user = context["my_user"]
        repo = context["repo"]
        fork_issue_number = context.get("fork_issue_number")

        # Fetch all open PRs via REST to avoid GraphQL rate limits
        result = run_gh_command([
            "api",
            f"repos/{my_user}/{repo}/pulls?state=open&per_page=100",
            "--jq",
            '[.[] | {number: .number, title: .title, body: .body, '
            'headRefName: .head.ref, author: {login: .user.login}}]',
        ])
        if not result["success"]:
            return {"done": False, "status": "error",
                    "error": result.get("error", "")}

        prs = json.loads(result["output"])

        # Filter to Copilot-authored PRs
        copilot_prs = []
        for pr in prs:
            author = pr.get("author", {})
            login = author.get("login", "") if isinstance(author, dict) else ""
            if "copilot" in login.lower():
                copilot_prs.append(pr)

        if not copilot_prs:
            return {"done": False, "status": "waiting_for_pr", "pr_number": None}

        # Fetch commits for each Copilot PR — needed for correlation and commit_count.
        # REST PR list doesn't include commits inline; fetch separately per PR.
        for pr in copilot_prs:
            commits_result = run_gh_command([
                "api",
                f"repos/{my_user}/{repo}/pulls/{pr['number']}/commits?per_page=100",
                "--jq", "[.[].sha]",
            ])
            if commits_result["success"]:
                try:
                    shas = json.loads(commits_result["output"])
                    pr["commits"] = [{"sha": s} for s in shas]
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        "Failed to parse commits for PR #%s in %s/%s: %s — raw: %r",
                        pr["number"], my_user, repo, e, commits_result["output"][:200]
                    )
                    pr["commits"] = []
            else:
                logger.warning(
                    "Failed to fetch commits for PR #%s in %s/%s: %s",
                    pr["number"], my_user, repo, commits_result.get("error", "unknown error")
                )
                pr["commits"] = []

        # Exclude PRs already claimed by other assignments in this repo.
        # This prevents the "most commits" fallback from stealing another
        # issue's PR when timeline correlation returns nothing.
        claimed_prs = set(context.get("_claimed_pr_numbers", []))
        available_prs = [p for p in copilot_prs if p["number"] not in claimed_prs]

        # Correlate: find the PR for this specific fork issue
        agent_pr = None
        if fork_issue_number and len(available_prs) > 1:
            agent_pr = self._find_pr_for_issue(
                my_user, repo, int(fork_issue_number), available_prs)

        # Single available PR — use it directly
        if not agent_pr and len(available_prs) == 1:
            agent_pr = available_prs[0]

        # If correlation failed with multiple PRs, don't guess — wait for Copilot
        # to update the PR body with the issue title (usually happens quickly).

        if not agent_pr:
            return {"done": False, "status": "waiting_for_pr", "pr_number": None}

        pr_number = agent_pr["number"]
        pr_branch = agent_pr["headRefName"]

        commits = agent_pr.get("commits", [])
        commit_count = len(commits) if isinstance(commits, list) else 0

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
                f'.check_runs[] | select(.name=="{COPILOT_CHECK_RUN_NAME}") | .status',
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
                if status and status != "completed":
                    return {
                        "done": False,
                        "status": "working",
                        "pr_number": pr_number,
                        "pr_branch": pr_branch,
                        "commit_count": commit_count,
                    }

        # Fallback: check-run absent or API failed. Copilot always creates
        # an "Initial plan" commit first, then implementation commits.
        # 2+ commits means implementation work exists — treat as done.
        if commit_count >= 2:
            return {
                "done": True,
                "status": "completed",
                "pr_number": pr_number,
                "pr_branch": pr_branch,
            }

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
        """Extract annotations from the completed workflow run.

        Uses the check-runs annotations API instead of raw logs to get
        structured findings without runner setup noise.
        """
        my_user = context["my_user"]
        repo = context["repo"]
        run_id = context.get("stage4_sa_run_id")

        if not run_id:
            return {"success": False, "error": "No run ID available"}

        # Get jobs for this workflow run
        jobs_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/runs/{run_id}/jobs",
            "--jq", ".jobs",
        ])
        if not jobs_result["success"]:
            return {"success": False, "error": "Failed to fetch jobs"}

        try:
            jobs_data = json.loads(jobs_result["output"])
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"success": False, "error": "Failed to parse jobs response"}

        findings_lines = []
        job_conclusions = []

        for job in jobs_data:
            job_name = job.get("name", "unknown")
            conclusion = job.get("conclusion", "unknown")
            job_id_val = job.get("id")
            job_conclusions.append(f"{job_name}: {conclusion}")

            if not job_id_val:
                continue

            ann_result = run_gh_command([
                "api",
                f"repos/{my_user}/{repo}/check-runs/{job_id_val}/annotations",
            ])
            if not ann_result["success"]:
                continue

            try:
                annotations = json.loads(ann_result["output"])
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

            for a in annotations:
                path = a.get("path", "")
                if path.startswith(".github"):
                    continue
                level = a.get("annotation_level", "notice")
                line = a.get("start_line", 0)
                message = a.get("message", "")
                findings_lines.append(f"- {level}: {path}:{line} — {message}")

        conclusions_text = "Job conclusions: " + ", ".join(job_conclusions)
        if findings_lines:
            findings = conclusions_text + "\n\n" + "\n".join(findings_lines)
        else:
            findings = conclusions_text + "\n\nNo findings."

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
            "-f", f"reviewers[]={COPILOT_REVIEWER}",
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


# ============ Copilot Remediation Dispatcher ============


class CopilotRemediationDispatcher(StageDispatcher):
    """Dispatches remediation to Copilot via PR comment on existing PR.

    This is the Stage 4d dispatcher. It:
    - Posts a PR comment tagging @copilot with review feedback + SA findings
    - Monitors for new commits on the PR branch (Copilot responds by pushing)
    - Collects updated PR stats after remediation
    """

    def dispatch(self, job_spec, context):
        """Post a remediation comment on the PR to trigger Copilot."""
        my_user = context["my_user"]
        repo = context["repo"]
        pr_number = job_spec.get("pr_number")
        remediation_body = job_spec.get("remediation_body", "")

        if not pr_number:
            return {"success": False, "error": "No PR number"}

        # Record current commit count for change detection
        pr_result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json", "commits", "--jq", ".commits | length",
        ])
        pre_commit_count = 0
        if pr_result["success"]:
            try:
                pre_commit_count = int(pr_result["output"].strip())
            except (ValueError, TypeError):
                pass

        # Post remediation comment tagging @copilot
        comment_body = f"{COPILOT_MENTION} Please address the following feedback:\n\n{remediation_body}"
        comment_result = run_gh_command([
            "pr", "comment", str(pr_number),
            "-R", f"{my_user}/{repo}",
            "--body", comment_body,
        ])

        if not comment_result.get("success", False):
            return {"success": False, "error": comment_result.get("error", "Comment failed")}

        return {
            "success": True,
            "job_id": str(pr_number),
            "pr_number": pr_number,
            "pre_commit_count": pre_commit_count,
        }

    # Copilot coding agent responds to issue assignments, not PR comments.
    # If no new commits or check-runs appear within this timeout after the
    # remediation comment was posted, treat remediation as done (no response).
    REMEDIATION_TIMEOUT_SECONDS = 600  # 10 minutes

    def check_status(self, job_id, context):
        """Check if Copilot has pushed new commits after the remediation comment."""
        import time as _time

        my_user = context["my_user"]
        repo = context["repo"]
        pr_number = context.get("stage4_pr_number")
        pre_commit_count = context.get("stage4d_pre_commit_count", 0)

        if not pr_number:
            return {"done": False, "status": "error", "error": "No PR number"}

        # Fetch current commit count
        pr_result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json", "commits", "--jq", ".commits | length",
        ])
        if not pr_result["success"]:
            return {"done": False, "status": "error",
                    "error": pr_result.get("error", "")}

        try:
            current_count = int(pr_result["output"].strip())
        except (ValueError, TypeError):
            return {"done": False, "status": "error",
                    "error": "Could not parse commit count"}

        new_commits = current_count - pre_commit_count
        if new_commits > 0:
            return {
                "done": True,
                "status": "completed",
                "new_commits": new_commits,
                "total_commits": current_count,
            }

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
                f'.check_runs[] | select(.name=="{COPILOT_CHECK_RUN_NAME}") | .status',
            ])
            if checks_result["success"]:
                status = checks_result["output"].strip()
                if status and status != "completed":
                    return {"done": False, "status": "working",
                            "new_commits": 0}

        # No new commits and no active check-run. Check if we've waited
        # long enough — Copilot may not respond to PR comments at all.
        dispatched_at = context.get("stage4d_dispatched_at")
        if dispatched_at:
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(dispatched_at.replace("Z", "+00:00"))
                elapsed = (_time.time() - dt.timestamp())
            except (ValueError, TypeError):
                elapsed = 0
        else:
            # No timestamp recorded — don't timeout, keep waiting
            return {"done": False, "status": "waiting_for_commits",
                    "new_commits": 0}

        if elapsed > self.REMEDIATION_TIMEOUT_SECONDS:
            return {
                "done": True,
                "status": "timeout",
                "new_commits": 0,
                "total_commits": current_count,
                "message": "No agent response after timeout — treating as done",
            }

        return {"done": False, "status": "waiting_for_commits",
                "new_commits": 0}

    def collect_results(self, job_id, context):
        """Collect updated PR stats after remediation."""
        my_user = context["my_user"]
        repo = context["repo"]
        pr_number = context.get("stage4_pr_number")

        if not pr_number:
            return {"success": False, "error": "No PR number"}

        result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json", "additions,deletions,changedFiles,commits",
        ])
        if not result["success"]:
            return {"success": False, "error": result.get("error", "")}

        pr_data = json.loads(result["output"])
        pre_count = context.get("stage4d_pre_commit_count", 0)
        total_commits = len(pr_data.get("commits", []))

        return {
            "success": True,
            "outputs": {
                "additions": pr_data.get("additions", 0),
                "deletions": pr_data.get("deletions", 0),
                "changed_files": pr_data.get("changedFiles", 0),
                "new_commits": total_commits - pre_count,
                "total_commits": total_commits,
            },
        }


# ============ Dispatcher Registry ============


def create_default_registry():
    """Create the default dispatcher registry with Copilot + GitHub Actions.

    To swap dispatchers, replace entries in this registry.
    """
    return {
        "swe": CopilotSWEDispatcher(),
        "static_analysis": GitHubActionsDispatcher(),
        "review": CopilotReviewDispatcher(),
        "remediation": CopilotRemediationDispatcher(),
    }
