"""
Stage helpers - shared logic for pipeline stage routes.
"""

import json

try:
    from ..services import run_gh_command
except ImportError:
    from services import run_gh_command


def is_demo_pr(pr):
    """Check if a PR has the 'demo' label (case-insensitive)."""
    pr_labels = [label.get("name", "").lower() for label in pr.get("labels", [])]
    return "demo" in pr_labels


def get_severity_score(issue):
    """Score an issue by severity label for sorting. Lower = more severe."""
    labels = [label.get("name", "").lower() for label in issue.get("labels", [])]
    if any("severity:critical" in label for label in labels):
        return 0
    if any("severity:high" in label for label in labels):
        return 1
    if any("severity:medium" in label for label in labels):
        return 2
    return 3


def check_copilot_completed(owner, repo_name, pr_number, pr_title):
    """Check if Copilot has completed work on a PR.

    Returns True if:
    - Title no longer starts with [WIP]
    - OR a comment contains 'completed task' or 'completed work'
    """
    if not pr_title.startswith("[WIP]"):
        return True

    result = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{owner}/{repo_name}",
        "--json", "comments"
    ])
    if result["success"]:
        try:
            data = json.loads(result["output"])
            comments = data.get("comments", [])
            for comment in comments:
                body = (comment.get("body") or "").lower()
                if "completed task" in body or "completed work" in body:
                    return True
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            pass
    return False
