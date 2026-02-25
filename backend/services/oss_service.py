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

# Pattern: https://github.com/owner/repo/issues/123 or /pull/123
_GITHUB_ISSUE_URL_RE = re.compile(
    r'https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/\d+'
)
# Pattern: owner/repo#123  (but NOT standalone #123 which is fine on a fork)
_CROSS_REPO_REF_RE = re.compile(
    r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+'
)
# Pattern: Closes/Fixes/Resolves #123 (GitHub auto-close keywords)
_AUTOCLOSE_RE = re.compile(
    r'\b(Closes?|Fixes?|Resolves?)\s+#\d+', re.IGNORECASE
)


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


def _sanitize_upstream_refs(text):
    """Strip upstream GitHub references from text to prevent cross-linking.

    When we post issues on a fork, GitHub auto-creates cross-reference
    notifications on the upstream repo for any of these patterns:
    - Full URLs: https://github.com/owner/repo/issues/123
    - Cross-repo refs: owner/repo#123
    - Auto-close keywords: Closes #123, Fixes #123, Resolves #123

    This function neutralizes them so the fork work stays invisible to upstream.
    """
    if not text:
        return text
    # Replace full GitHub issue/PR URLs with plain text (no link)
    # e.g. https://github.com/reisepass/email-verifier/issues/4 → reisepass/email-verifier issue 4
    text = _GITHUB_ISSUE_URL_RE.sub(
        lambda m: m.group(0)
            .replace("https://github.com/", "")
            .replace("/issues/", " issue ")
            .replace("/pull/", " PR "),
        text
    )
    # Replace cross-repo refs: owner/repo#123 → owner/repo issue 123
    text = _CROSS_REPO_REF_RE.sub(
        lambda m: m.group(0).replace("#", " issue "),
        text
    )
    # Neutralize auto-close keywords: "Closes #4" → "Related to issue 4"
    text = _AUTOCLOSE_RE.sub(
        lambda m: "Related to issue " + m.group(0).split("#")[-1],
        text
    )
    return text


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

    def ensure_copilot_instructions(self, my_user, repo):
        """Write .github/copilot-instructions.md on the fork.

        This file is read by the Copilot coding agent BEFORE the issue body,
        so it's the best place for workflow enforcement. Always overwrites any
        existing file (including one inherited from upstream) to ensure our
        quality gates and cross-linking rules are applied consistently.
        Best-effort — failures are silently ignored.
        """
        # Check if file already exists (need sha for update)
        existing_sha = None
        check = run_gh_command([
            "api", f"repos/{my_user}/{repo}/contents/.github/copilot-instructions.md",
            "--jq", ".sha"
        ])
        if check["success"] and check["output"].strip():
            existing_sha = check["output"].strip()

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
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        cmd = [
            "api", f"repos/{my_user}/{repo}/contents/.github/copilot-instructions.md",
            "-X", "PUT",
            "-f", f"message=Add Copilot workflow instructions",
            "-f", f"content={encoded}",
        ]
        if existing_sha:
            cmd.extend(["-f", f"sha={existing_sha}"])
        run_gh_command(cmd)

    def ensure_ci_workflow(self, my_user, repo, language=None):
        """Push a CI workflow to the fork that runs on every push.

        Provides deterministic quality checks (tests + linting) instead of
        relying on the Copilot agent to voluntarily run them. The workflow
        triggers on push and pull_request events, so it runs automatically
        when the Copilot coding agent pushes commits.

        Language detection: checks for marker files (go.mod, package.json, etc.)
        first, then falls back to the GitHub API .language field.
        """
        if not language:
            language = self._detect_repo_language(my_user, repo)

        workflow_yaml = self._build_ci_workflow(language)

        # Check if workflow already exists (need sha for update)
        existing_sha = None
        check = run_gh_command([
            "api", f"repos/{my_user}/{repo}/contents/.github/workflows/ci.yml",
            "--jq", ".sha"
        ])
        if check["success"] and check["output"].strip():
            existing_sha = check["output"].strip()

        encoded = base64.b64encode(workflow_yaml.encode("utf-8")).decode("utf-8")
        cmd = [
            "api", f"repos/{my_user}/{repo}/contents/.github/workflows/ci.yml",
            "-X", "PUT",
            "-f", "message=Add CI workflow for automated testing",
            "-f", f"content={encoded}",
        ]
        if existing_sha:
            cmd.extend(["-f", f"sha={existing_sha}"])
        run_gh_command(cmd)

    def _detect_repo_language(self, my_user, repo):
        """Detect the primary language of a repo by checking for marker files.

        Checks for language-specific marker files (go.mod, package.json, etc.)
        before falling back to the GitHub API .language field, which is unreliable
        (it reports based on file count/size, not project intent — e.g. a Go repo
        with Python test scripts may be reported as Python).

        Returns a language string like 'Go', 'Python', 'JavaScript', or None.
        """
        # Marker files in priority order (most specific first)
        markers = [
            ("go.mod", "Go"),
            ("Cargo.toml", "Rust"),
            ("package.json", "JavaScript"),
            ("pyproject.toml", "Python"),
            ("setup.py", "Python"),
            ("requirements.txt", "Python"),
            ("Gemfile", "Ruby"),
            ("pom.xml", "Java"),
            ("build.gradle", "Java"),
        ]

        for filename, lang in markers:
            result = run_gh_command([
                "api", f"repos/{my_user}/{repo}/contents/{filename}",
                "--jq", ".name"
            ])
            if result["success"] and result["output"].strip():
                return lang

        # Fallback to GitHub API language field
        result = run_gh_command([
            "api", f"repos/{my_user}/{repo}",
            "--jq", ".language"
        ])
        if result["success"] and result["output"].strip():
            return result["output"].strip()

        return None

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

    def request_copilot_review(self, my_user, repo, pr_number):
        """Request Copilot code review on a PR.

        Uses the bot username 'copilot-pull-request-reviewer[bot]'.
        This triggers a separate Copilot review agent that analyzes the PR
        independently from the coding agent that created it.
        Best-effort — returns the gh command result.
        """
        return run_gh_command([
            "api", "-X", "POST",
            f"repos/{my_user}/{repo}/pulls/{pr_number}/requested_reviewers",
            "-f", "reviewers[]=copilot-pull-request-reviewer[bot]"
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

        # Parse JSONL output (one JSON object per line)
        checks = []
        for line in checks_result["output"].strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    checks.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return checks

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

        reviews = []
        for line in result["output"].strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    reviews.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return reviews

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

        # --- Build common elements used by all tiers ---
        if is_self_owned:
            pr_target = f"Your changes will be reviewed as a PR on `{origin_owner}/{repo}`."
        else:
            pr_target = f"Your changes will be submitted as a PR to `{origin_owner}/{repo}`."

        # --- Tier 1: Brief available ---
        if issue_brief and issue_brief.get("brief"):
            brief_issue_body = ""
            if issue_brief.get("issue"):
                brief_issue_body = issue_brief["issue"].get("body") or ""
            detected_tool = _detect_tool_from_issue(brief_issue_body)
            reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

            # TDD workflow FIRST — this is the most important section
            body = self._build_workflow_header(pr_target, reproduce_step, verify_step)
            # Then the brief content (issue details, env setup, contribution rules, etc.)
            body += "\n---\n"
            body += _sanitize_upstream_refs(issue_brief["brief"])

            metadata["issue_brief_used"] = True
            metadata["issue_body_fetched"] = True
            metadata["sources"].append("aggregator-issue-brief")

            if return_metadata:
                return body, metadata
            return body

        # --- Tiers 2 & 3: No brief — build context ourselves ---
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
        issue_body = _sanitize_upstream_refs(issue_body)

        detected_tool = _detect_tool_from_issue(issue_body)
        reproduce_step, verify_step = self._build_tdd_steps(detected_tool)

        # TDD workflow FIRST, then issue context
        body = self._build_workflow_header(pr_target, reproduce_step, verify_step)
        body += f"""
---
## Issue Context
**Title:** {issue_title}

### Description
{issue_body or '*No description provided.*'}
"""

        # Tier 2: Use dossier sections if available (sanitize to prevent cross-refs)
        if dossier and (dossier.get("contributionRules") or dossier.get("detectedQuirks")):
            if dossier.get("contributionRules"):
                body += f"\n---\n## Contribution Rules\n{_sanitize_upstream_refs(dossier['contributionRules'])}\n"
            metadata["dossier_used"] = True
            metadata["sources"].append("aggregator-dossier")

            if dossier.get("successPatterns"):
                body += f"\n---\n## What Successful PRs Look Like\n{_sanitize_upstream_refs(dossier['successPatterns'])}\n"

            # Add quirk warnings when available
            if dossier.get("detectedQuirks"):
                quirks = dossier["detectedQuirks"]
                body += "\n---\n## Important Quirks & Warnings\n"
                for quirk in quirks:
                    impact = quirk.get("impact", "minor")
                    icon = "BLOCKER" if impact == "blocker" else "WARNING" if impact == "important" else "NOTE"
                    body += f"**[{icon}]** {quirk.get('type', 'unknown')}: {_sanitize_upstream_refs(quirk.get('description', ''))}\n"
                    if quirk.get("evidence"):
                        body += f"  Evidence: {_sanitize_upstream_refs(quirk['evidence'])}\n"
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
                    contrib_text = _sanitize_upstream_refs(contrib_text[:3000])
                    body += f"\n---\n## CONTRIBUTING.md\n<details><summary>Expand</summary>\n\n{contrib_text}\n\n</details>\n"
                    metadata["contributing_fetched"] = True
                    metadata["sources"].append("gh-contributing-md")
                except Exception:
                    pass

        if return_metadata:
            return body, metadata
        return body

    @staticmethod
    def _build_workflow_header(pr_target, reproduce_step, verify_step):
        """Build the mandatory workflow section that goes at the TOP of every context issue.

        This must be the first thing the agent reads. Research shows that instructions
        at the top of issue bodies have the highest compliance rate, and explicit
        "Do NOT proceed until..." gates create the strongest behavioral boundaries.
        """
        return f"""## Mandatory Workflow (Read First — Do NOT Skip)

{pr_target}

You MUST follow these phases in order. Do NOT skip ahead.

### Phase 1: Reproduce (MUST complete before Phase 2)
{reproduce_step}
- **Do NOT proceed to Phase 2 until you have confirmed a failing test or reproduced the issue.**
- If you cannot reproduce it, document why in a comment on this issue and stop.

### Phase 2: Implement (MUST complete before Phase 3)
2. **Implement the fix:** Make the minimal code change needed to resolve the issue.
   Follow the upstream repo's coding style and conventions. Write clear commit messages.
- Do NOT refactor unrelated code. Do NOT add features beyond what the issue asks for.

### Phase 3: Verify (MUST complete before committing)
{verify_step}
- Re-run the specific failing test from Phase 1 to confirm it now passes.
- Run the full test suite to check for regressions.
- **Do NOT commit until all tests pass.**

### Rules
- **DO NOT** reference, close, or link any external issues in your PR or commits. No "Closes", "Fixes", or "Resolves" directives.
- **DO NOT** use GitHub MCP tools to look up issues on other repositories.
- **DO NOT** modify or weaken a test to make it pass. The test must accurately verify the fix.
- **DO NOT** disable linter rules or add suppression comments to "fix" the issue.
- **DO NOT** commit `__pycache__/` directories. Add to `.gitignore` if missing.
- Keep changes minimal and focused.
- If the repo has a test suite, your PR **must** include a test that covers the fix.

### If You Cannot Complete This Task
If you are unable to reproduce the finding or implement a fix:
- **Add a comment on this issue** explaining what you tried and why it failed.
- Include the relevant tool output or error messages in the comment.
- Do **NOT** create a PR with no meaningful changes or with suppressed warnings.
"""

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
