"""
OSSForkMixin — fork management, CI/workflow setup, and PR review helpers.

Handles all GitHub operations on forked repos: creating forks, syncing,
configuring settings, pushing workflow files, detecting languages,
and interacting with PR checks and reviews.
"""

import re
import json
import time
import base64

try:
    from ..config import COPILOT_REVIEWER, GITHUB_NOREPLY_EMAIL_TEMPLATE
except ImportError:
    from config import COPILOT_REVIEWER, GITHUB_NOREPLY_EMAIL_TEMPLATE
from .github_api import run_gh_command
from .oss_service import _parse_jsonl


class OSSForkMixin:
    """Fork management and CI/workflow operations."""

    # --- Fork lifecycle ---

    def fork_repo(self, origin_owner, repo):
        """Fork a repo. Returns the gh command result."""
        return run_gh_command([
            "repo", "fork", f"{origin_owner}/{repo}", "--clone=false"
        ])

    def sync_fork(self, my_user, repo):
        """Sync a fork with its upstream. Returns the gh command result."""
        return run_gh_command(["repo", "sync", f"{my_user}/{repo}"])

    def check_fork_exists(self, my_user, repo):
        """Check if a fork exists. Returns True/False."""
        result = run_gh_command(["repo", "view", f"{my_user}/{repo}", "--json", "name"])
        return result["success"]

    def wait_for_fork(self, my_user, repo, timeout=60, interval=3):
        """Poll until fork exists on GitHub. Returns True if ready, False on timeout."""
        for _ in range(timeout // interval):
            if self.check_fork_exists(my_user, repo):
                return True
            time.sleep(interval)
        return False

    def configure_fork_settings(self, my_user, repo):
        """Configure fork repository settings for the pipeline.

        Enables issues, configures Actions permissions, and sets
        any other repo-level settings needed for automated CI
        and Copilot agent work.
        """
        # 1. Enable issues (forks inherit has_issues=false)
        run_gh_command([
            "api", f"repos/{my_user}/{repo}",
            "-X", "PATCH", "-f", "has_issues=true"
        ])

        # 2. Enable Actions with "allow all" policy
        run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/permissions",
            "-X", "PUT",
            "-f", "enabled=true",
            "-f", "allowed_actions=all"
        ])

    def approve_pending_workflow_runs(self, my_user, repo):
        """Unblock any workflow runs waiting for approval on the fork.

        GitHub blocks first-time workflow runs on forked repos with
        'action_required' status. This finds them and tries two strategies:
        1. Approve via the fork-PR approval API
        2. Fall back to re-running the workflow (works for non-fork-PR runs)
        Returns the number of runs unblocked.
        """
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/runs",
            "--jq", '.workflow_runs[] | select(.conclusion=="action_required") | .id'
        ])
        if not result["success"]:
            return 0

        unblocked = 0
        for line in result["output"].strip().split("\n"):
            run_id = line.strip()
            if run_id:
                # Try approve first (works for fork-PR triggered runs)
                approve_result = run_gh_command([
                    "api", "-X", "POST",
                    f"repos/{my_user}/{repo}/actions/runs/{run_id}/approve"
                ])
                if approve_result["success"]:
                    unblocked += 1
                else:
                    # Fall back to rerun (works for push-triggered runs on forks)
                    rerun_result = run_gh_command([
                        "api", "-X", "POST",
                        f"repos/{my_user}/{repo}/actions/runs/{run_id}/rerun"
                    ])
                    if rerun_result["success"]:
                        unblocked += 1
        return unblocked

    # --- Branch and commit operations ---

    def get_default_branch(self, owner, repo, issue_brief=None, dossier_context=None):
        """Get the default branch of a repo.

        Fallback chain:
        1. issue_brief.repoHealth.defaultBranch (structured, from aggregator)
        2. Parse from dossier text ("Default branch: `master`")
        3. gh api /repos/{owner}/{repo} (last resort)
        4. "main" (final fallback)
        """
        # 1. From aggregator issue-brief (already fetched)
        if issue_brief:
            health = issue_brief.get("repoHealth") or {}
            db = health.get("defaultBranch")
            if db:
                return db

        # 2. Parse from dossier contributionRules text
        if dossier_context:
            rules = dossier_context if isinstance(dossier_context, str) else ""
            if isinstance(dossier_context, dict):
                rules = dossier_context.get("contributionRules", "")
            match = re.search(r"Default branch:\s*`([^`]+)`", rules)
            if match:
                return match.group(1)

        # 3. gh api as last resort
        result = run_gh_command([
            "api", f"/repos/{owner}/{repo}", "--jq", ".default_branch"
        ])
        if result["success"] and result["output"].strip():
            return result["output"].strip()

        return "main"

    def get_user_identity(self):
        """Get the authenticated user's name and noreply email for commit authoring."""
        result = run_gh_command(["api", "user", "--jq", "{login: .login, name: .name, id: .id}"])
        if result["success"]:
            data = json.loads(result["output"])
            login = data.get("login", "")
            name = data.get("name") or login
            uid = data.get("id", "")
            email = GITHUB_NOREPLY_EMAIL_TEMPLATE.format(uid=uid, login=login)
            return {"name": name, "email": email, "login": login}
        return None

    def create_clean_branch(self, my_user, repo, squash_sha, branch_name, commit_message):
        """Create a re-authored branch from a squash commit using the Git Data API.

        Takes the squash commit (authored by Copilot), creates a new commit with
        the same tree but the authenticated user's identity, then creates a branch.
        Returns {"success": True, "sha": new_commit_sha} or {"success": False, "error": ...}.
        """
        # 1. Get the squash commit's tree and parent
        commit_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/commits/{squash_sha}",
            "--jq", "{tree: .tree.sha, parents: [.parents[].sha]}"
        ])
        if not commit_result["success"]:
            return {"success": False, "error": f"Failed to read commit: {commit_result.get('error', '')}"}

        commit_data = json.loads(commit_result["output"])
        tree_sha = commit_data["tree"]
        parents = commit_data["parents"]

        # 2. Get user identity for authoring
        identity = self.get_user_identity()
        if not identity:
            return {"success": False, "error": "Failed to get user identity"}

        # 3. Create a new commit with the user's identity
        create_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/commits",
            "-X", "POST",
            "-f", f"message={commit_message}",
            "-f", f"tree={tree_sha}",
            "-f", f"parents[]={parents[0]}",
            "-f", f"author[name]={identity['name']}",
            "-f", f"author[email]={identity['email']}",
            "-f", f"committer[name]={identity['name']}",
            "-f", f"committer[email]={identity['email']}",
        ])
        if not create_result["success"]:
            return {"success": False, "error": f"Failed to create commit: {create_result.get('error', '')}"}

        new_sha = json.loads(create_result["output"]).get("sha")

        # 4. Create the clean branch pointing at the new commit
        ref_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/refs",
            "-X", "POST",
            "-f", f"ref=refs/heads/{branch_name}",
            "-f", f"sha={new_sha}",
        ])
        if not ref_result["success"]:
            return {"success": False, "error": f"Failed to create branch: {ref_result.get('error', '')}"}

        return {"success": True, "sha": new_sha}

    def delete_branch(self, my_user, repo, branch_name):
        """Delete a branch from a repo via the Git Data API."""
        # URL-encode slashes in branch name (e.g., copilot/fix-foo → copilot%2Ffix-foo)
        encoded = branch_name.replace("/", "%2F")
        return run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/refs/heads/{encoded}",
            "-X", "DELETE"
        ])

    def close_fork_issue(self, my_user, repo, issue_number):
        """Close a context issue on a fork to hide it from public view."""
        return run_gh_command([
            "issue", "close", str(issue_number),
            "-R", f"{my_user}/{repo}"
        ])

    # --- File push operations ---

    def _push_file_to_repo(self, my_user, repo, file_path, content, commit_message):
        """Push a file to a repo via the GitHub Contents API (create or update).

        Handles checking for an existing file (to get its sha for updates),
        base64-encoding the content, and executing the PUT.
        """
        existing_sha = None
        check = run_gh_command([
            "api", f"repos/{my_user}/{repo}/contents/{file_path}",
            "--jq", ".sha"
        ])
        if check["success"] and check["output"].strip():
            existing_sha = check["output"].strip()

        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        cmd = [
            "api", f"repos/{my_user}/{repo}/contents/{file_path}",
            "-X", "PUT",
            "-f", f"message={commit_message}",
            "-f", f"content={encoded}",
        ]
        if existing_sha:
            cmd.extend(["-f", f"sha={existing_sha}"])
        return run_gh_command(cmd)

    def ensure_copilot_instructions(self, my_user, repo):
        """Write .github/copilot-instructions.md on the fork.

        This file is read by the Copilot coding agent BEFORE the issue body,
        so it's the best place for workflow enforcement. Always overwrites any
        existing file (including one inherited from upstream) to ensure our
        quality gates and cross-linking rules are applied consistently.
        Best-effort — failures are silently ignored.
        """
        content = (
            "# Copilot Coding Agent Instructions\n\n"
            "## Mandatory Workflow (MUST follow in order)\n\n"
            "### Phase 1: Reproduce (MUST complete before Phase 2)\n"
            "- Read the issue description and understand the problem.\n"
            "- Write a failing test or run the existing test suite to confirm the bug.\n"
            "- **Do NOT proceed to Phase 2 until you have a confirmed failure.**\n\n"
            "### Phase 2: Implement (MUST complete before Phase 3)\n"
            "- Make the minimal code change to fix the bug.\n"
            "- Do NOT refactor unrelated code or add features.\n\n"
            "### Phase 3: Verify (MUST complete before committing)\n"
            "- Re-run the specific test from Phase 1 and confirm it passes.\n"
            "- Run the full test suite to check for regressions.\n"
            "- **Do NOT commit until all tests pass.**\n\n"
            "## Rules\n"
            "- DO NOT reference, close, or link any external issues. "
            "No Closes, Fixes, or Resolves directives.\n"
            "- DO NOT use GitHub MCP tools to look up issues on other repositories.\n"
            "- DO NOT modify or weaken a test to make it pass.\n"
            "- DO NOT commit __pycache__/ directories. Add to .gitignore if missing.\n"
            "- Keep changes minimal and focused.\n"
        )
        self._push_file_to_repo(
            my_user, repo,
            ".github/copilot-instructions.md",
            content,
            "Add Copilot workflow instructions",
        )

    def ensure_ci_workflow(self, my_user, repo, language=None):
        """Push a CI workflow to the fork that runs on every push."""
        workflow_yaml = self._build_ci_workflow(language)
        self._push_file_to_repo(
            my_user, repo,
            ".github/workflows/ci.yml",
            workflow_yaml,
            "Add CI workflow for automated testing",
        )

    def ensure_static_analysis_workflow(self, my_user, repo, toolchain_profile=None,
                                         language=None):
        """Push a static-analysis workflow to the fork for Stage 4b.

        Unlike ci.yml (which triggers on push), this workflow uses
        workflow_dispatch so vibedispatch controls when it runs —
        specifically after the SWE agent finishes.
        """
        from .workflow_templates import build_jobs_from_toolchain, render_static_analysis_workflow

        jobs = build_jobs_from_toolchain(toolchain_profile, language)
        workflow_yaml = render_static_analysis_workflow(jobs)
        self._push_file_to_repo(
            my_user, repo,
            ".github/workflows/static-analysis.yml",
            workflow_yaml,
            "Add static analysis workflow (Stage 4b)",
        )


    @staticmethod
    def _build_ci_workflow(language):
        """Build a CI workflow YAML appropriate for the detected language."""
        lang = (language or "").lower()

        if lang == "go":
            return (
                "name: CI\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-go@v5\n"
                "        with:\n"
                "          go-version: 'stable'\n"
                "      - run: go vet ./...\n"
                "      - run: go test ./...\n"
            )
        elif lang == "python":
            return (
                "name: CI\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-python@v5\n"
                "        with:\n"
                "          python-version: '3.x'\n"
                "      - run: pip install -r requirements.txt 2>/dev/null || true\n"
                "      - run: pip install pytest ruff 2>/dev/null || true\n"
                "      - run: python -m pytest || true\n"
                "      - run: ruff check . || true\n"
            )
        elif lang in ("javascript", "typescript"):
            return (
                "name: CI\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-node@v4\n"
                "        with:\n"
                "          node-version: '20'\n"
                "      - run: npm ci\n"
                "      - run: npm test || true\n"
                "      - run: npx eslint . || true\n"
            )
        else:
            # Generic fallback — just checkout and list files
            return (
                "name: CI\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - run: echo 'No language-specific CI configured'\n"
            )

    # --- PR review helpers ---

    def request_copilot_review(self, my_user, repo, pr_number):
        """Request Copilot code review on a PR."""
        return run_gh_command([
            "api", "-X", "POST",
            f"repos/{my_user}/{repo}/pulls/{pr_number}/requested_reviewers",
            "-f", f"reviewers[]={COPILOT_REVIEWER}"
        ])

    def get_pr_check_runs(self, my_user, repo, pr_number):
        """Get CI check run results for a PR.

        Returns list of {name, status, conclusion} or empty list on failure.
        """
        # Get the head SHA of the PR
        pr_result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
            "--json", "headRefOid", "--jq", ".headRefOid"
        ])
        if not pr_result["success"] or not pr_result["output"].strip():
            return []

        head_sha = pr_result["output"].strip()
        checks_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/commits/{head_sha}/check-runs",
            "--jq", ".check_runs[] | {name, status, conclusion}"
        ])
        if not checks_result["success"]:
            return []

        return _parse_jsonl(checks_result["output"])

    def get_pr_reviews(self, my_user, repo, pr_number):
        """Get reviews on a PR.

        Returns list of {user, state, body} or empty list on failure.
        """
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/pulls/{pr_number}/reviews",
            "--jq", ".[] | {user: .user.login, state: .state, body: .body}"
        ])
        if not result["success"]:
            return []

        return _parse_jsonl(result["output"])
