"""
OSS Service — core business logic for the OSS contribution pipeline.

Handles fork management, local JSON tracking, agent context building,
and aggregator API communication.
"""

import os
import re
import json
import time
import base64
import requests

from .cache import CACHE_DIR
from .github_api import run_gh_command, get_authenticated_user

# ============ Constants ============

OSS_DATA_DIR = os.path.join(CACHE_DIR, "oss")
AGGREGATOR_API_URL = os.environ.get("AGGREGATOR_API_URL", "")


# ============ Private Helpers ============

def _load_json(filename):
    """Load a JSON file from the OSS data directory. Returns [] if missing."""
    path = os.path.join(OSS_DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_json(filename, data):
    """Save data as JSON to the OSS data directory."""
    os.makedirs(OSS_DATA_DIR, exist_ok=True)
    path = os.path.join(OSS_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _call_aggregator(endpoint, method="GET", data=None, timeout=10):
    """Call aggregator API with graceful failure. Returns None on any error."""
    if not AGGREGATOR_API_URL:
        return None
    try:
        url = f"{AGGREGATOR_API_URL}{endpoint}"
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)
        if resp.ok:
            return resp.json()
        return None
    except Exception:
        return None


def _detect_tool_from_issue(issue_body):
    """Extract the detection tool name from a vibecheck issue body.

    vibecheck issues use a markdown table with a row like:
        | Tool | `ruff` |

    Returns the tool name (str) or None if not detected.
    """
    if not issue_body:
        return None
    # Match vibecheck table format: | Tool | `toolname` |
    match = re.search(r'\|\s*Tool\s*\|\s*`(\w[\w-]*)`', issue_body)
    if match:
        return match.group(1).lower()
    return None


# ============ OSSService ============

class OSSService:
    """Service layer for the OSS contribution pipeline."""

    def __init__(self):
        self.data_dir = OSS_DATA_DIR

    # --- Local watchlist ---

    def get_local_watchlist(self):
        """Get the local watchlist. Returns list of {owner, repo, slug, added_at}."""
        return _load_json("watchlist.json")

    def add_to_local_watchlist(self, owner, repo):
        """Add a repo to the local watchlist. Dedup by owner+repo.

        Stores owner and repo as separate fields to avoid slug ambiguity
        (e.g., vercel-next-js could be vercel/next-js or vercel/next.js).
        The slug field is the hyphenated form for aggregator compatibility.
        """
        items = self.get_local_watchlist()
        for item in items:
            if item["owner"] == owner and item["repo"] == repo:
                return  # Already exists
        items.append({
            "owner": owner,
            "repo": repo,
            "slug": f"{owner}-{repo}",
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("watchlist.json", items)

    def remove_from_local_watchlist(self, owner, repo):
        """Remove a repo from the local watchlist."""
        items = self.get_local_watchlist()
        items = [i for i in items if not (i["owner"] == owner and i["repo"] == repo)]
        _save_json("watchlist.json", items)

    # --- Aggregator API (proxied when available, returns empty/None otherwise) ---

    def get_watchlist(self):
        """Get the watchlist from the aggregator.

        Aggregator returns: { success: true, data: { slugs: [...] } }
        """
        result = _call_aggregator("/recon/watchlist")
        if not result or not isinstance(result, dict):
            return []
        # Unwrap: { success, data: { slugs: [...] } }
        data = result.get("data") or result
        if isinstance(data, dict) and "slugs" in data:
            return data["slugs"]
        if "slugs" in result:
            return result["slugs"]
        return []

    def add_to_watchlist(self, slug):
        """Add a repo to the aggregator watchlist. Stub — returns False."""
        result = _call_aggregator("/recon/watchlist/add", method="POST", data={"slug": slug})
        return result is not None

    def remove_from_watchlist(self, slug):
        """Remove a repo from the aggregator watchlist. Stub — returns False."""
        result = _call_aggregator("/recon/watchlist/remove", method="POST", data={"slug": slug})
        return result is not None

    def get_scored_issues(self, slug=None):
        """Get scored issues from the aggregator.

        Aggregator returns: { success: true, data: { issues: [...] } }
        When pre-computed data is missing: { success: true, data: { status: "pending" } }

        Returns list of issues, or [] if unavailable/pending.
        """
        if slug:
            result = _call_aggregator(f"/recon/{slug}/scored-issues")
        else:
            result = _call_aggregator("/recon/all-scored-issues")
        if not result:
            return []
        # Unwrap aggregator response: { success, data: { issues: [...] } }
        if isinstance(result, dict):
            data = result.get("data") or result
            # Check for pending status (pre-computed data not yet available)
            if isinstance(data, dict) and data.get("status") == "pending":
                return []
            issues = data.get("issues") if isinstance(data, dict) else None
            if isinstance(issues, list):
                return issues
        if isinstance(result, list):
            return result
        return []

    def get_dossier(self, slug):
        """Get a repo dossier from the aggregator.

        Aggregator returns: { success: true, data: { slug, sections: {...} } }
        When pre-computed data is missing: { success: true, data: { status: "pending" } }
        Callers expect: { slug, sections: {...} } (the inner data object), or None.
        """
        result = _call_aggregator(f"/recon/{slug}/dossier")
        if not result or not isinstance(result, dict):
            return None
        # Unwrap: { success, data: { ... } }
        if "data" in result and isinstance(result["data"], dict):
            data = result["data"]
            # Check for pending status
            if data.get("status") == "pending":
                return None
            return data
        return result

    def get_issue_brief(self, slug, issue_id):
        """Get a pre-built issue brief from the aggregator.

        Args:
            slug: Hyphenated repo slug (e.g., "fastify-fastify")
            issue_id: Issue identifier (e.g., "github-fastify-fastify-1234")

        Returns:
            dict with {issue, repoHealth, brief} or None if unavailable/pending.
        """
        result = _call_aggregator(f"/recon/{slug}/issue-brief/{issue_id}")
        if result and result.get("success") and result.get("data"):
            data = result["data"]
            # Check for pending status
            if isinstance(data, dict) and data.get("status") == "pending":
                return None
            return data
        return None

    def trigger_compute(self, slug):
        """Trigger pre-computation of scored issues, dossier, and briefs for a repo.

        The aggregator requires POST /:slug/compute to run before scored-issues,
        dossier, and issue-brief endpoints return data.
        """
        result = _call_aggregator(f"/recon/{slug}/compute", method="POST", timeout=30)
        return result is not None

    def trigger_refresh(self, slug):
        """Trigger a re-scrape for a repo."""
        result = _call_aggregator(f"/recon/{slug}/refresh", method="POST")
        return result is not None

    # --- Local JSON tracking ---

    def get_selected_issues(self):
        """Get issues the user has selected for work."""
        return _load_json("selected-issues.json")

    def select_issue(self, origin_slug, issue_number, issue_title, issue_url):
        """Mark an issue as selected for work. Dedup by origin_slug + issue_number."""
        existing = self.find_selected_issue(origin_slug, issue_number)
        if existing:
            return
        items = self.get_selected_issues()
        items.append({
            "origin_slug": origin_slug,
            "issue_number": issue_number,
            "issue_title": issue_title,
            "issue_url": issue_url,
            "selected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("selected-issues.json", items)

    def get_assigned_issues(self):
        """Get fork issues that have been created and assigned to an agent."""
        return _load_json("assignments.json")

    def save_assignment(self, origin_owner, repo, issue_number, fork_issue_number, fork_issue_url,
                         is_self_owned=False, default_branch="main"):
        """Record a fork-and-assign action."""
        items = self.get_assigned_issues()
        items.append({
            "origin_slug": f"{origin_owner}/{repo}",
            "repo": repo,
            "issue_number": issue_number,
            "fork_issue_number": int(fork_issue_number),
            "fork_issue_url": fork_issue_url,
            "is_self_owned": is_self_owned,
            "default_branch": default_branch,
            "assigned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("assignments.json", items)

    def get_ready_to_submit(self):
        """Get items ready to submit upstream (merged fork PRs)."""
        return _load_json("ready-to-submit.json")

    def save_ready_to_submit(self, origin_slug, repo, branch, title, base_branch,
                              issue_number=0):
        """Record a merged fork PR that's ready for upstream submission."""
        items = self.get_ready_to_submit()
        items.append({
            "origin_slug": origin_slug,
            "repo": repo,
            "branch": branch,
            "title": title,
            "base_branch": base_branch,
            "issue_number": issue_number,
            "merged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("ready-to-submit.json", items)

    def remove_ready_to_submit(self, origin_slug, branch):
        """Remove an item from ready-to-submit after successful upstream submission."""
        items = self.get_ready_to_submit()
        items = [i for i in items if not (i["origin_slug"] == origin_slug and i["branch"] == branch)]
        _save_json("ready-to-submit.json", items)

    def get_submitted_prs(self):
        """Get PRs that have been submitted to upstream repos."""
        return _load_json("submitted-prs.json")

    def save_submitted_pr(self, origin_slug, pr_url, title):
        """Record a PR submission to an upstream repo."""
        # Parse PR number from URL (https://github.com/owner/repo/pull/123)
        pr_number = None
        try:
            pr_number = int(pr_url.rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            pass

        items = self.get_submitted_prs()
        items.append({
            "origin_slug": origin_slug,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "title": title,
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("submitted-prs.json", items)

    def update_submitted_prs(self, items):
        """Write the full updated submitted PRs list (used by polling endpoint)."""
        _save_json("submitted-prs.json", items)

    # --- Fork management (gh CLI) ---

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

    def enable_fork_issues(self, my_user, repo):
        """Enable issues on a forked repo (forks inherit has_issues=false)."""
        return run_gh_command([
            "api", f"repos/{my_user}/{repo}",
            "-X", "PATCH", "-f", "has_issues=true"
        ])

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
            email = f"{uid}+{login}@users.noreply.github.com"
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

    # --- Agent context ---

    def build_agent_context(self, origin_owner, repo, issue_number, issue_title, issue_url,
                             dossier=None, issue_brief=None, return_metadata=False,
                             is_self_owned=False):
        """Build the markdown context body for a fork issue assigned to an agent.

        Three-tier context strategy:
        1. issue_brief.brief available: Brief-first layout — aggregator's pre-built brief
           (rules, env setup, issue details, contribution rules) at top, our TDD workflow appended.
        2. dossier available (no brief): Our own rules + dossier sections.
        3. Neither available: Our own rules + CONTRIBUTING.md via gh CLI.

        Args:
            return_metadata: If True, return (body, metadata) tuple instead of just body.
            is_self_owned: If True, the repo is owned by the contributor (not a fork).
        """
        metadata = {
            "issue_body_fetched": False,
            "contributing_fetched": False,
            "dossier_used": False,
            "issue_brief_used": False,
            "sources": [],
        }

        # --- Tier 1: Brief-first layout ---
        # The aggregator brief is a complete context document (CRITICAL RULES, Environment Setup,
        # Issue Details, Contribution Rules, PR patterns, Quirks). Use it as the primary body
        # and only append our TDD workflow + failure instructions.
        if issue_brief and issue_brief.get("brief"):
            # Detect tool from the brief's issue body for TDD step customization
            brief_issue_body = ""
            if issue_brief.get("issue"):
                brief_issue_body = issue_brief["issue"].get("body") or ""
            detected_tool = _detect_tool_from_issue(brief_issue_body)

            reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

            if is_self_owned:
                pr_target = f"Your changes will be reviewed as a PR on `{origin_owner}/{repo}`."
            else:
                pr_target = f"Your changes will be submitted as a PR to `{origin_owner}/{repo}`."

            body = issue_brief["brief"]
            body += f"\n\n---\n## Instructions\n\n{pr_target}\n"
            body += f"\n### Workflow: Test-Driven Fix\n\n{reproduce_step}\n\n"
            body += "2. **Implement the fix:** Make the minimal change needed to resolve the issue.\n"
            body += "   Follow the upstream repo's coding style and conventions. Write clear commit messages.\n\n"
            body += f"{verify_step}\n"
            body += "\n### If You Cannot Complete This Task\n"
            body += "If you are unable to reproduce the finding or implement a fix:\n"
            body += "- **Add a comment on this issue** explaining what you tried and why it failed.\n"
            body += "- Include the relevant tool output or error messages in the comment.\n"
            body += "- Do **NOT** create a PR with no meaningful changes or with suppressed warnings.\n"

            metadata["issue_brief_used"] = True
            metadata["issue_body_fetched"] = True
            metadata["sources"].append("aggregator-issue-brief")

            if return_metadata:
                return body, metadata
            return body

        # --- Tiers 2 & 3: Our own body with rules ---
        # When no brief is available, build the full context ourselves.

        # Get original issue body via gh CLI
        issue_body = ""
        original = run_gh_command([
            "issue", "view", str(issue_number),
            "-R", f"{origin_owner}/{repo}",
            "--json", "body,labels"
        ])
        original_data = {}
        if original["success"]:
            try:
                original_data = json.loads(original["output"])
                metadata["issue_body_fetched"] = True
                metadata["sources"].append("gh-issue-view")
            except (json.JSONDecodeError, KeyError):
                pass
        issue_body = original_data.get('body', '')

        # Detect tool from vibecheck issue body for tool-specific instructions
        detected_tool = _detect_tool_from_issue(issue_body)
        reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

        if is_self_owned:
            pr_target = f"Your changes will be reviewed as a PR on `{origin_owner}/{repo}`."
        else:
            pr_target = f"Your changes will be submitted as a PR to `{origin_owner}/{repo}`."

        body = f"""## Issue Context
**Title:** {issue_title}

### Description
{issue_body or '*No description provided.*'}

---
## Instructions

{pr_target}

### Workflow: Test-Driven Fix

{reproduce_step}

2. **Implement the fix:** Make the minimal change needed to resolve the issue.
   Follow the upstream repo's coding style and conventions. Write clear commit messages.

{verify_step}

### Rules
- **DO NOT** reference, close, or link any external issues in your PR or commits. No "Closes", "Fixes", or "Resolves" directives.
- **DO NOT** use GitHub MCP tools to look up issues on other repositories.
- **DO NOT** modify or weaken a test to make it pass. The test must accurately verify the fix.
- **DO NOT** disable linter rules or add suppression comments to "fix" the issue.
- **DO NOT** commit `__pycache__/` directories. Add to `.gitignore` if missing.
- Keep changes minimal and focused — do not refactor unrelated code.
- If the repo has a test suite, your PR **must** include a test that covers the fix.

### If You Cannot Complete This Task
If you are unable to reproduce the finding or implement a fix:
- **Add a comment on this issue** explaining what you tried and why it failed.
- Include the relevant tool output or error messages in the comment.
- Do **NOT** create a PR with no meaningful changes or with suppressed warnings.
"""

        # Tier 2: Use dossier sections if available
        if dossier and (dossier.get("contributionRules") or dossier.get("detectedQuirks")):
            if dossier.get("contributionRules"):
                body += f"\n---\n## Contribution Rules\n{dossier['contributionRules']}\n"
            metadata["dossier_used"] = True
            metadata["sources"].append("aggregator-dossier")

            if dossier.get("successPatterns"):
                body += f"\n---\n## What Successful PRs Look Like\n{dossier['successPatterns']}\n"

            # Add quirk warnings when available
            if dossier.get("detectedQuirks"):
                quirks = dossier["detectedQuirks"]
                body += "\n---\n## Important Quirks & Warnings\n"
                for quirk in quirks:
                    impact = quirk.get("impact", "minor")
                    icon = "BLOCKER" if impact == "blocker" else "WARNING" if impact == "important" else "NOTE"
                    body += f"**[{icon}]** {quirk.get('type', 'unknown')}: {quirk.get('description', '')}\n"
                    if quirk.get("evidence"):
                        body += f"  Evidence: {quirk['evidence']}\n"
                body += "\n"
        # Tier 3: Fetch CONTRIBUTING.md via gh CLI
        else:
            contrib = run_gh_command([
                "api", f"/repos/{origin_owner}/{repo}/contents/CONTRIBUTING.md",
                "--jq", ".content"
            ])
            if contrib["success"] and contrib["output"].strip():
                try:
                    contrib_text = base64.b64decode(contrib["output"].strip()).decode("utf-8")
                    body += f"\n---\n## CONTRIBUTING.md\n<details><summary>Expand</summary>\n\n{contrib_text[:3000]}\n\n</details>\n"
                    metadata["contributing_fetched"] = True
                    metadata["sources"].append("gh-contributing-md")
                except Exception:
                    pass

        if return_metadata:
            return body, metadata
        return body

    @staticmethod
    def _build_tdd_steps(detected_tool):
        """Build TDD reproduce/verify steps based on detected tool.

        Returns (reproduce_step, verify_step) strings.
        """
        if detected_tool:
            reproduce_step = (
                f"1. **Reproduce the finding:** Run `{detected_tool}` on the affected file(s) "
                f"to confirm the issue exists.\n"
                f"   If `{detected_tool}` is not already installed, install it first. "
                f"Capture the output showing the finding."
            )
            verify_step = (
                f"3. **Verify the fix:** Re-run `{detected_tool}` on the affected file(s) "
                f"and confirm the finding is resolved.\n"
                f"   The tool should no longer report this specific issue. "
                f"No new issues should be introduced."
            )
        else:
            reproduce_step = (
                "1. **Reproduce the issue:** Write a failing test or run the relevant "
                "linting/analysis tool to confirm the problem.\n"
                "   If the repo has a test suite, add a test case that fails due to this issue."
            )
            verify_step = (
                "3. **Verify the fix:** Re-run the test or tool and confirm the issue is resolved.\n"
                "   All existing tests must still pass. No new issues should be introduced."
            )
        return reproduce_step, verify_step

    # --- Claim management ---

    def report_claim(self, origin_slug, issue_id, claimed_by, fork_issue_url):
        """Report a claim to the aggregator. Best-effort — doesn't fail if aggregator is down.

        NOTE: origin_slug is stored in slash format (owner/repo) for gh CLI compatibility.
        The aggregator API uses hyphenated format (owner-repo) for KV key compatibility.
        The conversion happens here — do not "fix" this by changing the stored format.
        """
        slug = origin_slug.replace("/", "-")
        _call_aggregator(f"/recon/{slug}/claim", method="POST", data={
            "issueId": issue_id,
            "claimedBy": claimed_by,
            "forkIssueUrl": fork_issue_url,
        })

    def report_unclaim(self, origin_slug, issue_id):
        """Report an unclaim to the aggregator. Best-effort.

        NOTE: See report_claim() for slug format convention.
        """
        slug = origin_slug.replace("/", "-")
        _call_aggregator(f"/recon/{slug}/unclaim", method="POST", data={
            "issueId": issue_id,
        })

    # --- Dedup ---

    def find_assignment(self, origin_slug, issue_number):
        """Check if an assignment already exists for this issue. Returns it or None."""
        for a in self.get_assigned_issues():
            if a["origin_slug"] == origin_slug and a["issue_number"] == issue_number:
                return a
        return None

    def find_selected_issue(self, origin_slug, issue_number):
        """Check if an issue is already selected. Returns it or None."""
        for item in self.get_selected_issues():
            if item["origin_slug"] == origin_slug and item["issue_number"] == issue_number:
                return item
        return None
