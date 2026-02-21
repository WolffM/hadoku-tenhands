"""
OSS helpers — scoring fallback and PR template formatting.
"""

from datetime import datetime, timezone


def score_issue_fallback(issue):
    """Heuristic scoring when aggregator is unavailable.

    Args:
        issue: dict from gh issue list --json with keys:
            number, title, labels, createdAt, updatedAt, comments, assignees

    Returns:
        dict with cvs (int), cvsTier (str), dataCompleteness (str)
    """
    # Skip assigned issues entirely
    assignees = issue.get("assignees", [])
    if isinstance(assignees, list) and len(assignees) > 0:
        return {"cvs": 0, "cvsTier": "skip", "dataCompleteness": "partial"}

    score = 50  # Base score
    now = datetime.now(timezone.utc)

    # Parse updatedAt
    updated_at_str = issue.get("updatedAt") or issue.get("createdAt", "")
    try:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        days_since_update = (now - updated_at).days
    except (ValueError, AttributeError):
        days_since_update = 0

    # Parse createdAt
    created_at_str = issue.get("createdAt", "")
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        days_since_creation = (now - created_at).days
    except (ValueError, AttributeError):
        days_since_creation = 0

    # Penalize stale issues (updated > 90 days ago)
    if days_since_update > 90:
        score -= 30

    # Penalize zero-comment issues older than 14 days (no maintainer triage)
    comments = issue.get("comments", 0)
    if isinstance(comments, list):
        comments = len(comments)
    if comments == 0 and days_since_creation > 14:
        score -= 10

    # Boost "good first issue" label
    # gh CLI returns [{name: "...", color: "..."}], aggregator returns string[]
    labels = issue.get("labels", [])
    label_names = []
    for label in labels:
        if isinstance(label, dict):
            label_names.append(label.get("name", "").lower())
        elif isinstance(label, str):
            label_names.append(label.lower())

    if "good first issue" in label_names:
        score += 20

    # Clamp to 0-100
    score = max(0, min(100, score))

    # Map score to tier
    if score >= 80:
        tier = "go"
    elif score >= 60:
        tier = "likely"
    elif score >= 40:
        tier = "maybe"
    elif score >= 20:
        tier = "risky"
    else:
        tier = "skip"

    return {"cvs": score, "cvsTier": tier, "dataCompleteness": "partial"}


def format_upstream_pr_body(origin_slug, issue_number, issue_title, branch):
    """Format the PR body for submitting to an upstream repo."""
    return f"""## Summary

Fixes {origin_slug}#{issue_number}: {issue_title}

## Changes

This PR addresses the issue described above. Changes were developed on the `{branch}` branch.

## Related Issue

- Closes #{issue_number}
"""
