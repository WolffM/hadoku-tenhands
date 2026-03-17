"""
OSSStateMixin — local JSON state management for the OSS pipeline.

Handles reading/writing the local JSON files that track pipeline state:
selected issues, assignments, ready-to-submit, and submitted PRs.
"""

import time

from .oss_service import _load_json, _save_json


class OSSStateMixin:
    """Local JSON state management for the OSS pipeline."""

    # --- Selected issues ---

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

    # --- Assignments ---

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

    def find_assignment_by_fork_issue(self, repo, fork_issue_number):
        """Find an assignment by repo name and fork issue number."""
        items = self.get_assigned_issues()
        for item in items:
            if item["repo"] == repo and item["fork_issue_number"] == int(fork_issue_number):
                return item
        return None

    def update_assignment(self, repo, fork_issue_number, updates):
        """Update fields on an existing assignment record.

        Args:
            repo: Repository name (e.g., "email-verifier")
            fork_issue_number: The fork issue number to find
            updates: Dict of fields to merge into the assignment
        Returns:
            True if the assignment was found and updated, False otherwise.
        """
        items = self.get_assigned_issues()
        for item in items:
            if item["repo"] == repo and item["fork_issue_number"] == int(fork_issue_number):
                item.update(updates)
                _save_json("assignments.json", items)
                return True
        return False

    # --- Ready to submit ---

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

    # --- Submitted PRs ---

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

    # --- Retrospective logs ---

    def get_retrospective_logs(self):
        """Get all retrospective log entries."""
        return _load_json("retrospective-logs.json")

    def append_retrospective_log(self, entry):
        """Append a single retrospective entry to the log."""
        items = self.get_retrospective_logs()
        items.append(entry)
        _save_json("retrospective-logs.json", items)

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

    # --- Dispatched repos ---

    def get_dispatched_repos(self):
        """Get all repos that have had at least one successful dispatch."""
        return _load_json("dispatched-repos.json")

    def track_dispatched_repo(self, origin_slug):
        """Record a successful dispatch for origin_slug. Idempotent — deduped by slug.

        Stores both slash-format ('owner/repo') and aggregator-format ('owner-repo')
        so Stage 1 can filter by either format without conversion at read time.
        """
        items = self.get_dispatched_repos()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for item in items:
            if item["origin_slug"] == origin_slug:
                item["last_dispatched_at"] = now
                item["dispatch_count"] = item.get("dispatch_count", 1) + 1
                _save_json("dispatched-repos.json", items)
                return
        items.append({
            "origin_slug": origin_slug,
            "aggregator_slug": origin_slug.replace("/", "-", 1),
            "first_dispatched_at": now,
            "last_dispatched_at": now,
            "dispatch_count": 1,
        })
        _save_json("dispatched-repos.json", items)
