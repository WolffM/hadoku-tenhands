"""
OSS helpers — scoring fallback and PR template formatting.
"""


def score_issue_fallback(issue):
    """Basic heuristic scoring when aggregator is unavailable.

    Stub returning 50 (neutral). M2 implements full heuristic scoring
    based on labels, age, comment count, and assignee status.
    """
    return 50


def format_upstream_pr_body(origin_slug, issue_number, issue_title, branch):
    """Format the PR body for submitting to an upstream repo."""
    return f"""## Summary

Fixes {origin_slug}#{issue_number}: {issue_title}

## Changes

This PR addresses the issue described above. Changes were developed on the `{branch}` branch.

## Related Issue

- Closes #{issue_number}
"""
