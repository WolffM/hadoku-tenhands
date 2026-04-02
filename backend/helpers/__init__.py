"""
Helpers package - shared utility functions for route handlers.
"""

from .stage_helpers import is_demo_pr, get_severity_score, check_copilot_completed
from .oss_helpers import score_issue_fallback, format_upstream_pr_body, strip_leading_header
from .bot_filter import BOT_LOGINS, is_bot, filter_human_comments
from .validation import (
    validate_slug,
    validate_owner,
    validate_repo_name,
    validate_issue_number,
    validate_github_url,
    validate_aggregator_url,
    validate_required_fields,
    normalize_repo_name,
    to_aggregator_slug,
    safe_error_message,
)

__all__ = [
    'is_demo_pr',
    'get_severity_score',
    'check_copilot_completed',
    'score_issue_fallback',
    'format_upstream_pr_body',
    'strip_leading_header',
    'validate_slug',
    'validate_owner',
    'validate_repo_name',
    'validate_issue_number',
    'validate_github_url',
    'validate_aggregator_url',
    'validate_required_fields',
    'normalize_repo_name',
    'to_aggregator_slug',
    'safe_error_message',
    'BOT_LOGINS',
    'is_bot',
    'filter_human_comments',
]
