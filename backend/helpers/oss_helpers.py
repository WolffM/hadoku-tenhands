"""
OSS helpers — scoring fallback and PR template formatting.
"""

import re
from datetime import datetime, timezone


# ============ Reaction scoring (Tier 1) ============

_REACTION_WEIGHTS = {
    "THUMBS_UP": 2,
    "HEART": 1,
    "ROCKET": 1,
    "HOORAY": 1,
    "LAUGH": 0,
    "EYES": 0,
    "THUMBS_DOWN": -2,
    "CONFUSED": -1,
}

_REACTION_SCORE_CAP = 15


def _score_reactions(reaction_groups):
    """Score an issue based on its GitHub reaction groups.

    Args:
        reaction_groups: list of dicts from gh CLI reactionGroups field.
            Each dict has: {"content": "THUMBS_UP", "users": {"totalCount": N}}

    Returns:
        tuple: (score clamped to ±15, detail dict with per-type breakdown)
    """
    if not reaction_groups or not isinstance(reaction_groups, list):
        return (0, {})

    raw_score = 0
    detail = {}
    for group in reaction_groups:
        content = group.get("content", "")
        users = group.get("users") or {}
        count = users.get("totalCount", 0) if isinstance(users, dict) else 0
        weight = _REACTION_WEIGHTS.get(content, 0)
        contribution = count * weight
        if count > 0 or weight != 0:
            detail[content] = {"count": count, "weight": weight, "contribution": contribution}
        raw_score += contribution

    clamped = max(-_REACTION_SCORE_CAP, min(_REACTION_SCORE_CAP, raw_score))
    return (clamped, detail)


# ============ Comment sentiment scoring (Tier 2) ============

_POSITIVE_PATTERNS = [
    r"^\+1$",
    r"^\+1\b",
    r"\bme too\b",
    r"\bsame here\b",
    r"\bsame issue\b",
    r"\bbump\b",
    r"\bseconded\b",
    r"\bagreed\b",
    r"\bi also need this\b",
    r"\bi['\u2019]?d like this too\b",
    r"\bneed this\b",
    r"\bwould love this\b",
    r"\bplease add\b",
    r"\bplease fix\b",
    r"\byes please\b",
]

_NEGATIVE_PATTERNS = [
    r"^-1$",
    r"^-1\b",
    r"\bduplicate of\b",
    r"\bwon['\u2019]?t fix\b",
    r"\bwontfix\b",
    r"\bstale\b",
    r"\bas designed\b",
    r"\bnot a bug\b",
    r"\bclosing\b",
    r"\bwill not implement\b",
]

_COMPILED_POSITIVE = [re.compile(p, re.IGNORECASE) for p in _POSITIVE_PATTERNS]
_COMPILED_NEGATIVE = [re.compile(p, re.IGNORECASE) for p in _NEGATIVE_PATTERNS]

_POSITIVE_COMMENT_SCORE = 3
_NEGATIVE_COMMENT_SCORE = -3
_COMMENT_SENTIMENT_CAP = 10


def _score_comment_sentiment(comments):
    """Score comment sentiment using lightweight text pattern matching.

    Args:
        comments: list of comment dicts with "body" key, or an int (count).

    Returns:
        tuple: (score clamped to ±10, detail dict with counts)
    """
    if not isinstance(comments, list):
        return (0, {"analyzed_count": 0})

    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = (comment.get("body") or "").strip()
        if not body:
            continue

        matched = False
        for pattern in _COMPILED_POSITIVE:
            if pattern.search(body):
                positive_count += 1
                matched = True
                break
        if not matched:
            for pattern in _COMPILED_NEGATIVE:
                if pattern.search(body):
                    negative_count += 1
                    matched = True
                    break
        if not matched:
            neutral_count += 1

    analyzed = positive_count + negative_count + neutral_count
    raw_score = (positive_count * _POSITIVE_COMMENT_SCORE) + (negative_count * _NEGATIVE_COMMENT_SCORE)
    clamped = max(-_COMMENT_SENTIMENT_CAP, min(_COMMENT_SENTIMENT_CAP, raw_score))

    detail = {
        "analyzed_count": analyzed,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
    }
    return (clamped, detail)


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
        "reaction_score": 0,
        "comment_sentiment_score": 0,
        "assigned_skip": False,
        "days_since_update": 0,
        "days_since_creation": 0,
        "final_score": 0,
        "reaction_detail": {},
        "comment_sentiment_detail": {},
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

    # Reaction-based scoring (Tier 1 — available when reactionGroups fetched)
    reaction_groups = issue.get("reactionGroups")
    if reaction_groups is not None:
        reaction_score, reaction_detail = _score_reactions(reaction_groups)
        score += reaction_score
        breakdown["reaction_score"] = reaction_score
        breakdown["reaction_detail"] = reaction_detail

    # Comment sentiment scoring (Tier 2 — only when comment bodies available)
    raw_comments = issue.get("comments", 0)
    if isinstance(raw_comments, list) and len(raw_comments) > 0:
        if isinstance(raw_comments[0], dict) and "body" in raw_comments[0]:
            sentiment_score, sentiment_detail = _score_comment_sentiment(raw_comments)
            score += sentiment_score
            breakdown["comment_sentiment_score"] = sentiment_score
            breakdown["comment_sentiment_detail"] = sentiment_detail

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

Fixes {origin_slug}#{issue_number}: {issue_title}

## Changes

This PR addresses the issue described above. Changes were developed on the `{branch}` branch.

## Related Issue

- Closes #{issue_number}
"""
