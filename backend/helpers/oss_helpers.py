"""
OSS helpers — scoring fallback, PR template formatting, and markdown utilities.
"""

import re
from datetime import datetime, timezone


def strip_leading_header(text):
    """Strip a leading markdown header if the text starts with one.

    Dossier sections often begin with their own '## Section Name' header.
    When we wrap them in our own '## Header', the result is a double header.
    """
    return re.sub(r'^#{1,4}\s+[^\n]+\n+', '', text.lstrip(), count=1)


def _map_tier(score):
    """Map a CVS score to a tier string."""
    if score >= 80:
        return "go"
    elif score >= 60:
        return "likely"
    elif score >= 40:
        return "maybe"
    elif score >= 20:
        return "risky"
    else:
        return "skip"


def score_issue_with_breakdown(issue):
    """Score an issue and return the full breakdown of scoring factors.

    Args:
        issue: dict from gh issue list --json with keys:
            number, title, labels, createdAt, updatedAt, comments, assignees

    Returns:
        dict with cvs, cvsTier, dataCompleteness, and breakdown dict.
    """
    breakdown = {
        "base_score": 50,
        "good_first_issue_bonus": 0,
        "stale_penalty": 0,
        "no_triage_penalty": 0,
        "assigned_skip": False,
        "days_since_update": 0,
        "days_since_creation": 0,
        "final_score": 0,
    }

    # Skip assigned issues entirely
    assignees = issue.get("assignees", [])
    if isinstance(assignees, list) and len(assignees) > 0:
        breakdown["assigned_skip"] = True
        breakdown["final_score"] = 0
        return {
            "cvs": 0, "cvsTier": "skip", "dataCompleteness": "partial",
            "breakdown": breakdown,
        }

    score = 50  # Base score
    now = datetime.now(timezone.utc)

    # Parse updatedAt
    updated_at_str = issue.get("updatedAt") or issue.get("createdAt", "")
    try:
        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        days_since_update = (now - updated_at).days
    except (ValueError, AttributeError):
        days_since_update = 0
    breakdown["days_since_update"] = days_since_update

    # Parse createdAt
    created_at_str = issue.get("createdAt", "")
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        days_since_creation = (now - created_at).days
    except (ValueError, AttributeError):
        days_since_creation = 0
    breakdown["days_since_creation"] = days_since_creation

    # Penalize stale issues (updated > 90 days ago)
    if days_since_update > 90:
        score -= 30
        breakdown["stale_penalty"] = -30

    # Penalize zero-comment issues older than 14 days (no maintainer triage)
    comments = issue.get("comments", 0)
    if isinstance(comments, list):
        comments = len(comments)
    if comments == 0 and days_since_creation > 14:
        score -= 10
        breakdown["no_triage_penalty"] = -10

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
        breakdown["good_first_issue_bonus"] = 20

    # Clamp to 0-100
    score = max(0, min(100, score))
    breakdown["final_score"] = score

    return {
        "cvs": score,
        "cvsTier": _map_tier(score),
        "dataCompleteness": "partial",
        "breakdown": breakdown,
    }


def score_issue_fallback(issue):
    """Heuristic scoring when aggregator is unavailable.

    Args:
        issue: dict from gh issue list --json with keys:
            number, title, labels, createdAt, updatedAt, comments, assignees

    Returns:
        dict with cvs (int), cvsTier (str), dataCompleteness (str)
    """
    result = score_issue_with_breakdown(issue)
    return {"cvs": result["cvs"], "cvsTier": result["cvsTier"], "dataCompleteness": result["dataCompleteness"]}


def format_upstream_pr_body(origin_slug, issue_number, issue_title, branch):
    """Format the PR body for submitting to an upstream repo."""
    return f"""## Summary

{issue_title}

Closes #{issue_number}
"""
