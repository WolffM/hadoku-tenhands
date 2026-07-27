"""
Centralized validation, slug conversion, and parsing helpers.

All user input validation for route handlers lives here.
"""

import re
from urllib.parse import urlparse

# Matches valid GitHub owner/repo slugs: owner/repo
# Each segment: starts with alphanumeric, then alphanumeric/dot/hyphen/underscore
SLUG_PATTERN = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$'
)

# Matches a single owner or repo name segment
_NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')

# Matches a valid GitHub issue/PR URL
_GITHUB_URL_PATTERN = re.compile(
    r'^https://github\.com/[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*/issues/\d+$'
)


def validate_slug(slug):
    """Validate an owner/repo slug. Returns error message or None."""
    if not slug or not isinstance(slug, str):
        return "Slug is required"
    slug = slug.strip()
    if not SLUG_PATTERN.match(slug):
        return "Invalid slug format — must be owner/repo"
    if len(slug) > 200:
        return "Slug too long"
    return None


def validate_owner(owner):
    """Validate a GitHub owner name. Returns error message or None."""
    if not owner or not isinstance(owner, str):
        return "Owner is required"
    owner = owner.strip()
    if not _NAME_PATTERN.match(owner):
        return "Invalid owner format"
    if len(owner) > 100:
        return "Owner name too long"
    return None


def validate_repo_name(name):
    """Validate a GitHub repo name. Returns error message or None."""
    if not name or not isinstance(name, str):
        return "Repo name is required"
    name = name.strip()
    if not _NAME_PATTERN.match(name):
        return "Invalid repo name format"
    if len(name) > 100:
        return "Repo name too long"
    return None


def validate_issue_number(n):
    """Validate an issue number. Returns error message or None."""
    if n is None:
        return "Issue number is required"
    try:
        num = int(n)
        if num <= 0:
            return "Issue number must be positive"
    except (TypeError, ValueError):
        return "Issue number must be a positive integer"
    return None


def validate_github_url(url):
    """Validate a GitHub issue URL. Returns error message or None."""
    if not url or not isinstance(url, str):
        return "URL is required"
    url = url.strip()
    if not _GITHUB_URL_PATTERN.match(url):
        return "Invalid GitHub issue URL format"
    return None


def validate_aggregator_url(url):
    """Validate an aggregator API URL at startup. Returns error message or None."""
    if not url:
        return None  # Empty is fine — means offline/fallback mode
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"AGGREGATOR_API_URL has invalid scheme: {parsed.scheme}"
        if not parsed.hostname:
            return "AGGREGATOR_API_URL has no hostname"
    except ValueError:
        return "AGGREGATOR_API_URL is not a valid URL"
    return None


def normalize_repo_name(repo):
    """Extract repo name from a full slug (owner/repo -> repo)."""
    repo = str(repo)
    return repo.split("/")[-1] if "/" in repo else repo


def to_aggregator_slug(slug):
    """Convert owner/repo slug to aggregator format (owner-repo)."""
    return slug.replace("/", "-")



# Known gh CLI error patterns → safe user-facing messages
_ERROR_PATTERNS = [
    ("not found", "Resource not found"),
    ("could not resolve", "Resource not found"),
    ("permission", "Permission denied"),
    ("forbidden", "Permission denied"),
    ("rate limit", "Rate limit exceeded — try again later"),
    ("timed out", "Request timed out"),
    ("timeout", "Request timed out"),
    ("network", "Network error"),
    ("connection", "Network error"),
]


def validate_request_or_error(data, required_fields, extra_validators=()):
    """Validate request fields; return jsonify'd error Response or None.

    Args:
        data: Request JSON dict.
        required_fields: List of field names that must be present and truthy.
        extra_validators: Iterable of (value, validator_fn) pairs evaluated
            after the required-field check. validator_fn(value) returns an
            error string or None.

    Returns:
        A Flask jsonify Response with success=False on first error, or None
        if all checks pass.
    """
    from flask import jsonify
    err = validate_required_fields(data, required_fields)
    if err:
        return jsonify({"success": False, "error": err})
    for value, validator_fn in extra_validators:
        err = validator_fn(value)
        if err:
            return jsonify({"success": False, "error": err})
    return None


def validate_required_fields(data, fields):
    """Check that all required fields are present and truthy in a dict.

    Returns:
        Error message string if any field is missing/falsy, or None if all present.
    """
    if not data or not isinstance(data, dict):
        return f"Missing required fields: {', '.join(fields)}"
    missing = [f for f in fields if not data.get(f)]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None



def safe_error_message(raw_error, default="Operation failed"):
    """Map raw gh CLI error messages to safe, non-leaking user-facing messages.

    Prevents internal paths, tokens, and implementation details from leaking
    to the client in error responses.
    """
    if not raw_error:
        return default
    lower = str(raw_error).lower()
    for pattern, safe_msg in _ERROR_PATTERNS:
        if pattern in lower:
            return safe_msg
    return default


def error_response(raw_error, default, owner=None):
    """Return a Flask JSON error response with a safe error message.

    Convenience wrapper combining safe_error_message + jsonify so route
    handlers don't repeat the same three-key dict pattern.

    Args:
        raw_error: Raw error from a gh command result (may contain internal details).
        default:   User-facing fallback message if raw_error doesn't match any pattern.
        owner:     Authenticated user to include in the response (optional).

    Returns:
        Flask Response with {"success": False, "error": ..., "owner": ...}
    """
    from flask import jsonify
    payload = {"success": False, "error": safe_error_message(raw_error, default)}
    if owner is not None:
        payload["owner"] = owner
    return jsonify(payload)
