"""
OSSForkMixin — fork management, CI/workflow setup, and PR review helpers.

Handles all GitHub operations on forked repos: creating forks, syncing,
configuring settings, pushing workflow files, detecting languages,
and interacting with PR checks and reviews.

Runner setup and firewall management are delegated to sub-mixins:
- OSSRunnerSetupMixin (oss_runner_setup.py)
- OSSFirewallMixin (oss_firewall.py)
"""

import logging
import os
import re
import json
import subprocess
import sys
import tempfile
import threading
import time
import base64

logger = logging.getLogger(__name__)

# Suppress console windows on Windows when spawning subprocesses
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    from ..config import COPILOT_REVIEWER, GITHUB_NOREPLY_EMAIL_TEMPLATE
except ImportError:
    from config import COPILOT_REVIEWER, GITHUB_NOREPLY_EMAIL_TEMPLATE
from .github_api import run_gh_command
from .oss_service import _parse_jsonl

try:
    from .oss_runner_setup import OSSRunnerSetupMixin
    from .oss_firewall import OSSFirewallMixin
except ImportError:
    from oss_runner_setup import OSSRunnerSetupMixin
    from oss_firewall import OSSFirewallMixin

# Per-repo locks: serialize concurrent dispatches for the same upstream repo.
# Prevents the race condition where two parallel dispatches for the same repo
# both call fork_repo() simultaneously, causing the second to fail with 422.
_FORK_LOCKS: dict = {}
_FORK_LOCKS_MUTEX = threading.Lock()


def get_fork_lock(origin_slug: str) -> threading.Lock:
    """Return (or create) the per-repo serialization lock for origin_slug.

    Keyed by 'owner/repo'. Lock must be held for the full fork/sync/configure
    sequence to prevent race conditions when two issues from the same repo are
    dispatched concurrently.
    """
    with _FORK_LOCKS_MUTEX:
        if origin_slug not in _FORK_LOCKS:
            _FORK_LOCKS[origin_slug] = threading.Lock()
        return _FORK_LOCKS[origin_slug]


class OSSForkMixin(OSSRunnerSetupMixin, OSSFirewallMixin):
    """Fork management and CI/workflow operations.

    Inherits runner registration from OSSRunnerSetupMixin and firewall
    management from OSSFirewallMixin.
    """

    # --- Fork lifecycle ---

    def fork_repo(self, origin_owner, repo):
        """Fork a repo. Returns the gh command result."""
        return run_gh_command([
            "repo", "fork", f"{origin_owner}/{repo}", "--clone=false"
        ])

    def sync_fork(self, my_user, repo):
        """Sync a fork with its upstream via REST merge-upstream API.

        Uses REST instead of 'gh repo sync' (which uses GraphQL internally)
        to avoid exhausting the GraphQL rate limit during batch dispatches.
        Falls back to gh repo sync if the REST call fails.
        """
        # Get the fork's default branch first
        branch_result = run_gh_command(["api", f"repos/{my_user}/{repo}", "--jq", ".default_branch"])
        if not branch_result["success"]:
            logger.error(
                "sync_fork: could not fetch default branch for %s/%s: %s",
                my_user, repo, branch_result.get("error", "unknown error")
            )
            return {"success": False, "error": f"Could not fetch default branch for {my_user}/{repo}"}
        branch = branch_result["output"].strip()

        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/merge-upstream",
            "-X", "POST", "-f", f"branch={branch}"
        ])
        if result["success"]:
            return result
        # Fallback to gh repo sync if REST fails (e.g. already up-to-date returns 409)
        if "409" in result.get("error", "") or "already" in result.get("error", "").lower():
            return {"success": True, "output": "already up-to-date"}
        return run_gh_command(["repo", "sync", f"{my_user}/{repo}"])

    def check_fork_exists(self, my_user, repo):
        """Check if a fork exists. Returns True/False. Uses REST to avoid GraphQL rate limits."""
        result = run_gh_command(["api", f"repos/{my_user}/{repo}", "--jq", ".name"])
        return result["success"]

    def wait_for_fork(self, my_user, repo, timeout=60, interval=3):
        """Poll until fork exists on GitHub. Returns True if ready, False on timeout."""
        for _ in range(timeout // interval):
            if self.check_fork_exists(my_user, repo):
                return True
            time.sleep(interval)
        return False

    def configure_fork_settings(self, my_user, repo, origin_owner=None):
        """Configure fork repository settings for the pipeline.

        Enables issues, configures Actions permissions, disables inherited
        upstream workflows (to prevent runaway CI costs), and sets any other
        repo-level settings needed for the Copilot coding agent.

        Args:
            origin_owner: Upstream repo owner. SAML-protected orgs force the
                Copilot firewall on, so self-hosted runner setup is skipped.
        """
        from .github_api import is_saml_org

        # 1. Enable issues (forks inherit has_issues=false)
        r = run_gh_command([
            "api", f"repos/{my_user}/{repo}",
            "-X", "PATCH", "-f", "has_issues=true"
        ])
        if not r["success"]:
            logger.warning("Failed to enable issues for %s/%s: %s", my_user, repo, r.get("error"))

        # 2. Enable Actions with "allow all" policy
        r = run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/permissions",
            "-X", "PUT",
            "-f", "enabled=true",
            "-f", "allowed_actions=all"
        ])
        if not r["success"]:
            logger.warning("Failed to enable Actions for %s/%s: %s", my_user, repo, r.get("error"))

        # 3. Disable ALL inherited upstream workflows to prevent cost explosions.
        #    Large repos (vscode, playwright) have expensive CI that runs on every
        #    push/PR. We only need our own workflows + copilot-setup-steps.
        self._disable_upstream_workflows(my_user, repo)

        # 4-5. Self-hosted runner setup — only for non-SAML orgs.
        # SAML-protected orgs (e.g. Microsoft) force COPILOT_AGENT_FIREWALL_ENABLED=true
        # on forks, which blocks self-hosted runners. Those forks use github-hosted.
        if is_saml_org(origin_owner):
            logger.info(
                "Skipping self-hosted runner + firewall toggle for %s/%s "
                "(SAML org %s forces firewall — using github-hosted runners)",
                my_user, repo, origin_owner
            )
        else:
            self._ensure_self_hosted_runner(my_user, repo)
            self._disable_copilot_firewall(my_user, repo)

    def _disable_upstream_workflows(self, my_user, repo):
        """Disable all inherited workflows except our own and Copilot's.

        Upstream repos like playwright/vscode have CI that costs $10-70+ per
        run. Forks inherit all these workflows. We disable them to prevent
        runaway Actions billing when we push workflow files or the agent
        creates PRs.
        """
        # Workflows we want to keep enabled
        keep_patterns = {
            "ci.yml",                    # our CI
            "static-analysis.yml",       # our Stage 4b
            "copilot-setup-steps.yml",   # Copilot agent environment setup
        }

        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/actions/workflows",
            "--jq", ".workflows[] | [.id, .path, .state] | @tsv",
            "--paginate"
        ])
        if not result["success"]:
            return

        disabled_count = 0
        for line in result["output"].strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            wf_id, wf_path, wf_state = parts[0], parts[1], parts[2]

            # Keep our workflows and Copilot's setup steps
            filename = wf_path.split("/")[-1] if "/" in wf_path else wf_path
            if filename in keep_patterns:
                continue
            # Keep dynamic workflows (Copilot agent, Copilot code review)
            if wf_path.startswith("dynamic/"):
                continue

            if wf_state == "active":
                disable_result = run_gh_command([
                    "api", f"repos/{my_user}/{repo}/actions/workflows/{wf_id}/disable",
                    "-X", "PUT"
                ])
                if disable_result["success"]:
                    disabled_count += 1

        if disabled_count:
            logger.info("Disabled %d upstream workflows on %s/%s", disabled_count, my_user, repo)

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

        logger.error(
            "get_default_branch: all sources failed for %s/%s — gh api returned: %s",
            owner, repo, result.get("error", "unknown error")
        )
        return None

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
        logger.error("get_user_identity failed: %s", result.get("error", "unknown error"))
        return None

    # Files pushed by ensure_pipeline_files() that must NEVER appear in upstream PRs.
    PIPELINE_FILES = frozenset({
        ".github/copilot-instructions.md",
        ".github/workflows/ci.yml",
        ".github/workflows/static-analysis.yml",
        ".github/workflows/copilot-setup-steps.yml",
    })

    def _strip_pipeline_files(self, my_user, repo, tree_sha, origin_slug, base_branch):
        """Create a new tree with pipeline-owned files restored to their upstream state.

        For each file in PIPELINE_FILES:
        - If the file exists upstream: restore the upstream blob SHA
        - If the file does NOT exist upstream: delete it from the tree

        Returns (new_tree_sha, files_stripped) or (original_tree_sha, []) on failure.
        """
        if not origin_slug or not base_branch:
            return tree_sha, []

        # Get the upstream base branch tree
        upstream_result = run_gh_command([
            "api", f"repos/{origin_slug}/git/trees/{base_branch}",
            "-q", ".sha",
        ])
        if not upstream_result["success"]:
            logger.warning("Could not fetch upstream tree for %s:%s", origin_slug, base_branch)
            return tree_sha, []

        upstream_tree_sha = upstream_result["output"].strip()

        # Fetch upstream entries for pipeline file paths
        upstream_entries = {}
        for fpath in self.PIPELINE_FILES:
            entry_result = run_gh_command([
                "api", f"repos/{origin_slug}/git/trees/{upstream_tree_sha}:{'/'.join(fpath.split('/')[:-1])}",
                "--jq", f'.tree[] | select(.path == "{fpath.split("/")[-1]}")'
            ])
            if entry_result["success"] and entry_result["output"].strip():
                try:
                    entry = json.loads(entry_result["output"])
                    upstream_entries[fpath] = entry
                except (json.JSONDecodeError, ValueError):
                    pass

        # Build tree modification entries
        tree_mods = []
        files_stripped = []
        for fpath in self.PIPELINE_FILES:
            if fpath in upstream_entries:
                # Restore to upstream version
                entry = upstream_entries[fpath]
                tree_mods.append({
                    "path": fpath,
                    "mode": entry.get("mode", "100644"),
                    "type": "blob",
                    "sha": entry["sha"],
                })
                files_stripped.append(f"{fpath} (restored to upstream)")
            else:
                # File doesn't exist upstream — delete it
                tree_mods.append({
                    "path": fpath,
                    "mode": "100644",
                    "type": "blob",
                    "sha": None,
                })
                files_stripped.append(f"{fpath} (removed)")

        if not tree_mods:
            return tree_sha, []

        # Create new tree with modifications applied on top of the squash tree
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"base_tree": tree_sha, "tree": tree_mods}, f)
            payload_path = f.name

        try:
            new_tree_result = run_gh_command([
                "api", f"repos/{my_user}/{repo}/git/trees",
                "-X", "POST",
                "--input", payload_path,
                "--jq", ".sha",
            ])
        finally:
            os.unlink(payload_path)

        if new_tree_result["success"] and new_tree_result["output"].strip():
            new_tree_sha = new_tree_result["output"].strip()
            logger.info("Stripped %d pipeline file(s) from tree: %s", len(files_stripped), files_stripped)
            return new_tree_sha, files_stripped

        logger.warning("Failed to create filtered tree, using original: %s", new_tree_result.get("error"))
        return tree_sha, []

    def create_clean_branch(self, my_user, repo, squash_sha, branch_name, commit_message,
                            origin_slug=None, base_branch=None):
        """Create a re-authored branch from a squash commit using the Git Data API.

        Takes the squash commit (authored by Copilot), creates a new commit with
        the same tree but the authenticated user's identity, then creates a branch.

        Pipeline-owned files (.github/copilot-instructions.md, workflow files) are
        stripped or restored to their upstream state so they never leak to upstream PRs.

        Returns {"success": True, "sha": new_commit_sha, "files_stripped": [...]}
        or {"success": False, "error": ...}.
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

        # 2. Strip pipeline-owned files from the tree
        tree_sha, files_stripped = self._strip_pipeline_files(
            my_user, repo, tree_sha, origin_slug, base_branch or "main"
        )

        # 3. Get user identity for authoring
        identity = self.get_user_identity()
        if not identity:
            return {"success": False, "error": "Failed to get user identity"}

        # 4. Create a new commit with the user's identity and filtered tree
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

        # 5. Create the clean branch pointing at the new commit
        ref_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/refs",
            "-X", "POST",
            "-f", f"ref=refs/heads/{branch_name}",
            "-f", f"sha={new_sha}",
        ])
        if not ref_result["success"]:
            return {"success": False, "error": f"Failed to create branch: {ref_result.get('error', '')}"}

        return {"success": True, "sha": new_sha, "files_stripped": files_stripped}

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

    def _push_files_as_single_commit(self, my_user, repo, files, commit_message):
        """Push multiple files in a single commit via the Git Data API.

        This avoids creating N separate commits (and triggering N CI runs)
        when pushing N workflow files. Uses the low-level tree/commit API:
        1. Get current HEAD commit and its tree
        2. Create blobs for each file
        3. Create a new tree with the blobs
        4. Create a commit pointing to the new tree
        5. Update the branch ref

        Args:
            files: list of (path, content) tuples
        """
        # Get default branch and its HEAD
        branch_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}", "--jq", ".default_branch"
        ])
        if not branch_result["success"]:
            logger.warning("Failed to get default branch for %s/%s", my_user, repo)
            return {"success": False, "error": "could not get default branch"}

        branch = branch_result["output"].strip()
        ref_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/ref/heads/{branch}",
            "--jq", ".object.sha"
        ])
        if not ref_result["success"]:
            logger.warning("Failed to get HEAD ref for %s/%s:%s", my_user, repo, branch)
            return {"success": False, "error": "could not get HEAD ref"}

        head_sha = ref_result["output"].strip()

        # Get the current tree
        commit_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/commits/{head_sha}",
            "--jq", ".tree.sha"
        ])
        if not commit_result["success"]:
            return {"success": False, "error": "could not get HEAD tree"}

        base_tree = commit_result["output"].strip()

        # Check which files actually need updating
        files_to_push = []
        for path, content in files:
            check = run_gh_command([
                "api", f"repos/{my_user}/{repo}/contents/{path}",
                "--jq", ".content"
            ])
            if check["success"] and check["output"].strip():
                try:
                    existing = base64.b64decode(
                        check["output"].strip().replace("\n", "")
                    ).decode("utf-8")
                    if existing == content:
                        logger.debug("Skip %s (unchanged)", path)
                        continue
                except UnicodeDecodeError:
                    pass  # Binary file — can't compare content as text, push it
                except Exception as e:
                    logger.warning("Unexpected error comparing %s content: %s", path, e)
            files_to_push.append((path, content))

        if not files_to_push:
            logger.debug("All files unchanged on %s/%s, skipping commit", my_user, repo)
            return {"success": True, "output": "all unchanged", "skipped": True}

        # Create blobs and tree entries
        tree_entries = []
        for path, content in files_to_push:
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
            blob_result = run_gh_command([
                "api", f"repos/{my_user}/{repo}/git/blobs",
                "-X", "POST",
                "-f", f"content={encoded}",
                "-f", "encoding=base64",
            ])
            if not blob_result["success"]:
                logger.error("Failed to create blob for %s: %s", path, blob_result.get("error", "unknown error"))
                continue
            blob_sha = json.loads(blob_result["output"]).get("sha")
            if not blob_sha:
                logger.error("Blob API returned no sha for %s — response: %r", path, blob_result["output"][:200])
                continue
            tree_entries.append({
                "path": path, "mode": "100644", "type": "blob", "sha": blob_sha
            })

        if not tree_entries:
            return {"success": False, "error": "no blobs created"}

        # Create new tree — uses subprocess directly because gh api --input
        # doesn't handle nested JSON tree entries correctly via -f flags
        _flags = _SUBPROCESS_FLAGS
        tree_body = json.dumps({"base_tree": base_tree, "tree": tree_entries})
        try:
            proc = subprocess.run(
                ["gh", "api", f"repos/{my_user}/{repo}/git/trees",
                 "-X", "POST", "--input", "-"],
                input=tree_body, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=_flags, timeout=30
            )
            if proc.returncode != 0:
                logger.warning("Failed to create tree: %s", proc.stderr[:200])
                return {"success": False, "error": "tree creation failed"}
            new_tree_sha = json.loads(proc.stdout).get("sha")
        except Exception as e:
            logger.warning("Tree creation error: %s", e)
            return {"success": False, "error": str(e)}

        # Create commit
        commit_body = json.dumps({
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [head_sha],
        })
        try:
            proc = subprocess.run(
                ["gh", "api", f"repos/{my_user}/{repo}/git/commits",
                 "-X", "POST", "--input", "-"],
                input=commit_body, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=_flags, timeout=30
            )
            if proc.returncode != 0:
                logger.warning("Failed to create commit: %s", proc.stderr[:200])
                return {"success": False, "error": "commit creation failed"}
            new_commit_sha = json.loads(proc.stdout).get("sha")
        except Exception as e:
            logger.error("Commit creation failed for %s/%s: %s", my_user, repo, e)
            return {"success": False, "error": str(e)}

        # Update branch ref
        update_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/refs/heads/{branch}",
            "-X", "PATCH",
            "-f", f"sha={new_commit_sha}",
        ])
        if not update_result["success"]:
            return {"success": False, "error": "ref update failed"}

        pushed = [p for p, _ in files_to_push]
        logger.info("Pushed %d files in 1 commit to %s/%s: %s",
                      len(pushed), my_user, repo, pushed)
        return {"success": True, "output": new_commit_sha, "files": pushed}

    def ensure_pipeline_files(self, my_user, repo, language=None, toolchain_profile=None,
                              origin_owner=None):
        """Push all pipeline files (copilot instructions + workflows) in a single commit.

        This replaces the separate ensure_copilot_instructions, ensure_ci_workflow,
        and ensure_static_analysis_workflow calls. A single commit means a single
        push event, which means upstream CI only triggers once (and we disable it
        anyway via _disable_upstream_workflows).

        Args:
            origin_owner: Upstream repo owner. Used to detect SAML-protected orgs
                that force Copilot firewall on (requiring github-hosted runners).
        """
        from .workflow_templates import build_jobs_from_toolchain, render_static_analysis_workflow
        from .github_api import is_saml_org

        copilot_instructions = (
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

        ci_yaml = self._build_ci_workflow(language)

        jobs = build_jobs_from_toolchain(toolchain_profile, language)
        sa_yaml = render_static_analysis_workflow(jobs)

        # SAML-protected orgs force Copilot firewall ON for forks — self-hosted
        # runners fail at the firewall validation step. Use github-hosted instead.
        use_self_hosted = not is_saml_org(origin_owner)
        setup_steps_yaml = self._build_copilot_setup_steps(language, use_self_hosted=use_self_hosted)

        return self._push_files_as_single_commit(my_user, repo, [
            (".github/copilot-instructions.md", copilot_instructions),
            (".github/workflows/ci.yml", ci_yaml),
            (".github/workflows/static-analysis.yml", sa_yaml),
            (".github/workflows/copilot-setup-steps.yml", setup_steps_yaml),
        ], "Configure pipeline: copilot instructions, CI, and static analysis")

    @staticmethod
    def _build_ci_workflow(language):
        """Build a CI workflow YAML appropriate for the detected language."""
        lang = (language or "").lower()

        if lang == "go":
            return (
                "name: CI\n"
                "on: [push]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: self-hosted\n"
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
                "on: [push]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: self-hosted\n"
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
                "on: [push]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: self-hosted\n"
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
                "on: [push]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: self-hosted\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - run: echo 'No language-specific CI configured'\n"
            )

    @staticmethod
    def _build_copilot_setup_steps(language, use_self_hosted=True):
        """Build copilot-setup-steps.yml for the Copilot coding agent.

        This workflow defines the environment the agent runs in.

        Args:
            language: Primary repo language (for setup steps).
            use_self_hosted: If True, use self-hosted runner (requires firewall
                disabled). If False, use ubuntu-latest (GitHub-hosted). Forks of
                SAML-protected orgs (e.g. Microsoft) force firewall ON, so they
                must use GitHub-hosted runners.
        """
        lang = (language or "").lower()
        runner = "self-hosted" if use_self_hosted else "ubuntu-latest"

        header = (
            "name: \"Copilot Setup Steps\"\n"
            "\n"
            "on:\n"
            "  workflow_dispatch:\n"
            "  push:\n"
            "    paths:\n"
            "      - .github/workflows/copilot-setup-steps.yml\n"
            "\n"
            "jobs:\n"
            "  copilot-setup-steps:\n"
            f"    runs-on: {runner}\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
        )

        if lang == "go":
            return header + (
                "      - uses: actions/setup-go@v5\n"
                "        with:\n"
                "          go-version: 'stable'\n"
                "      - run: go mod download 2>/dev/null || true\n"
            )
        elif lang == "python":
            return header + (
                "      - uses: actions/setup-python@v5\n"
                "        with:\n"
                "          python-version: '3.x'\n"
                "      - run: pip install -r requirements.txt 2>/dev/null || true\n"
            )
        elif lang in ("javascript", "typescript"):
            return header + (
                "      - uses: actions/setup-node@v4\n"
                "        with:\n"
                "          node-version: '20'\n"
                "      - run: npm ci 2>/dev/null || true\n"
            )
        else:
            return header

