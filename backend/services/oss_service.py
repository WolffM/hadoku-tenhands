"""
OSS Service — core business logic for the OSS contribution pipeline.

Handles fork management, local JSON tracking, agent context building,
and aggregator API communication.
"""

import os
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


# ============ OSSService ============

class OSSService:
    """Service layer for the OSS contribution pipeline."""

    def __init__(self):
        self.data_dir = OSS_DATA_DIR

    # --- Aggregator API stubs (M2 implementation) ---

    def get_watchlist(self):
        """Get the watchlist from the aggregator. Stub — returns []."""
        result = _call_aggregator("/recon/watchlist")
        if result and "slugs" in result:
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
        """Get scored issues from the aggregator. Stub — returns []."""
        if slug:
            result = _call_aggregator(f"/recon/{slug}/scored-issues")
        else:
            result = _call_aggregator("/recon/all-scored-issues")
        if result and isinstance(result, list):
            return result
        return []

    def get_dossier(self, slug):
        """Get a repo dossier from the aggregator. Stub — returns None."""
        return _call_aggregator(f"/recon/{slug}/dossier")

    def trigger_refresh(self, slug):
        """Trigger a re-scrape for a repo. Stub — returns False."""
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

    def save_assignment(self, origin_owner, repo, issue_number, fork_issue_number, fork_issue_url):
        """Record a fork-and-assign action."""
        items = self.get_assigned_issues()
        items.append({
            "origin_slug": f"{origin_owner}/{repo}",
            "repo": repo,
            "issue_number": issue_number,
            "fork_issue_number": int(fork_issue_number),
            "fork_issue_url": fork_issue_url,
            "assigned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        _save_json("assignments.json", items)

    def get_ready_to_submit(self):
        """Get items ready to submit upstream (merged fork PRs)."""
        return _load_json("ready-to-submit.json")

    def save_ready_to_submit(self, origin_slug, repo, branch, title, base_branch):
        """Record a merged fork PR that's ready for upstream submission."""
        items = self.get_ready_to_submit()
        items.append({
            "origin_slug": origin_slug,
            "repo": repo,
            "branch": branch,
            "title": title,
            "base_branch": base_branch,
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
        items = self.get_submitted_prs()
        items.append({
            "origin_slug": origin_slug,
            "pr_url": pr_url,
            "title": title,
            "state": "open",
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
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

    # --- Agent context ---

    def build_agent_context(self, origin_owner, repo, issue_number, issue_title, issue_url, dossier=None):
        """Build the markdown context body for a fork issue assigned to an agent."""
        # Fetch original issue body
        original = run_gh_command([
            "issue", "view", str(issue_number),
            "-R", f"{origin_owner}/{repo}",
            "--json", "body,labels"
        ])
        original_data = {}
        if original["success"]:
            try:
                original_data = json.loads(original["output"])
            except (json.JSONDecodeError, KeyError):
                pass

        # Fetch CONTRIBUTING.md (fallback if no dossier)
        contrib_text = ""
        if not dossier:
            contrib = run_gh_command([
                "api", f"/repos/{origin_owner}/{repo}/contents/CONTRIBUTING.md",
                "--jq", ".content"
            ])
            if contrib["success"] and contrib["output"].strip():
                try:
                    contrib_text = base64.b64decode(contrib["output"].strip()).decode("utf-8")
                except Exception:
                    pass

        body = f"""## Upstream Issue
**Repository:** [{origin_owner}/{repo}](https://github.com/{origin_owner}/{repo})
**Issue:** [#{issue_number}: {issue_title}]({issue_url})

### Original Issue Description
{original_data.get('body', '*No description provided.*')}

---
## Instructions
Fix the issue described above. Your changes will be submitted as a PR to `{origin_owner}/{repo}`.

**Important:**
- Follow the upstream repo's coding style and conventions
- Keep changes minimal and focused
- Write clear commit messages
- Add tests if the repo has a test suite
"""

        if dossier and dossier.get("contributionRules"):
            body += f"\n---\n## Contribution Rules\n{dossier['contributionRules']}\n"
        elif contrib_text:
            body += f"\n---\n## CONTRIBUTING.md\n<details><summary>Expand</summary>\n\n{contrib_text[:3000]}\n\n</details>\n"

        if dossier and dossier.get("successPatterns"):
            body += f"\n---\n## What Successful PRs Look Like\n{dossier['successPatterns']}\n"

        return body

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
