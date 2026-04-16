"""Tests for centralized validation helpers."""

import pytest

from helpers.validation import (
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


class TestValidateSlug:
    """Tests for validate_slug()."""

    def test_valid_slugs(self):
        assert validate_slug("acme-corp/widget-api") is None
        assert validate_slug("vercel/next.js") is None
        assert validate_slug("WolffM/hadoku-watchparty") is None
        assert validate_slug("a/b") is None
        assert validate_slug("user_name/repo-name") is None
        assert validate_slug("Org.Name/repo.name") is None

    def test_empty_slug(self):
        assert validate_slug("") is not None
        assert validate_slug(None) is not None

    def test_no_slash(self):
        assert validate_slug("acme-corp") is not None

    def test_path_traversal(self):
        assert validate_slug("../../../etc/passwd") is not None
        assert validate_slug("owner/../secret") is not None

    def test_shell_injection(self):
        assert validate_slug("owner/repo;rm -rf /") is not None
        assert validate_slug("owner/repo$(whoami)") is not None
        assert validate_slug("owner/repo`id`") is not None

    def test_just_slash(self):
        assert validate_slug("/") is not None

    def test_empty_parts(self):
        assert validate_slug("/repo") is not None
        assert validate_slug("owner/") is not None

    def test_too_long(self):
        assert validate_slug("a" * 101 + "/" + "b" * 101) is not None

    def test_starts_with_special(self):
        assert validate_slug("-owner/repo") is not None
        assert validate_slug("owner/-repo") is not None
        assert validate_slug(".owner/repo") is not None


class TestValidateOwner:
    """Tests for validate_owner()."""

    def test_valid_owners(self):
        assert validate_owner("acme-corp") is None
        assert validate_owner("WolffM") is None
        assert validate_owner("user-name") is None
        assert validate_owner("user_name") is None
        assert validate_owner("Org.Name") is None

    def test_empty(self):
        assert validate_owner("") is not None
        assert validate_owner(None) is not None

    def test_invalid_chars(self):
        assert validate_owner("owner/repo") is not None
        assert validate_owner("owner;cmd") is not None
        assert validate_owner("owner$(x)") is not None

    def test_starts_with_special(self):
        assert validate_owner("-owner") is not None
        assert validate_owner(".owner") is not None


class TestValidateRepoName:
    """Tests for validate_repo_name()."""

    def test_valid_repos(self):
        assert validate_repo_name("acme-corp") is None
        assert validate_repo_name("next.js") is None
        assert validate_repo_name("hadoku-watchparty") is None
        assert validate_repo_name("my_repo") is None

    def test_empty(self):
        assert validate_repo_name("") is not None
        assert validate_repo_name(None) is not None

    def test_invalid(self):
        assert validate_repo_name("repo;cmd") is not None
        assert validate_repo_name("a/b") is not None

    def test_starts_with_special(self):
        assert validate_repo_name("-repo") is not None


class TestValidateIssueNumber:
    """Tests for validate_issue_number()."""

    def test_valid_numbers(self):
        assert validate_issue_number(1) is None
        assert validate_issue_number(12345) is None
        assert validate_issue_number("42") is None

    def test_invalid(self):
        assert validate_issue_number(0) is not None
        assert validate_issue_number(-1) is not None
        assert validate_issue_number(None) is not None
        assert validate_issue_number("abc") is not None
        assert validate_issue_number("") is not None


class TestValidateGithubUrl:
    """Tests for validate_github_url()."""

    def test_valid_urls(self):
        assert validate_github_url("https://github.com/acme-corp/widget-api/issues/1234") is None
        assert validate_github_url("https://github.com/vercel/next.js/issues/1") is None

    def test_invalid_urls(self):
        assert validate_github_url("") is not None
        assert validate_github_url(None) is not None
        assert validate_github_url("http://example.com") is not None
        assert validate_github_url("https://github.com/owner/repo/pull/1") is not None  # PRs not valid
        assert validate_github_url("https://github.com/owner/repo") is not None
        assert validate_github_url("javascript:alert(1)") is not None


class TestValidateAggregatorUrl:
    """Tests for validate_aggregator_url()."""

    def test_valid_urls(self):
        assert validate_aggregator_url("https://aggregator.example.com/api") is None
        assert validate_aggregator_url("http://localhost:8787/oss/api") is None
        assert validate_aggregator_url("") is None  # empty is fine — offline mode

    def test_invalid_urls(self):
        assert validate_aggregator_url("ftp://bad.com") is not None
        assert validate_aggregator_url("not-a-url") is not None


class TestNormalizeRepoName:
    """Tests for normalize_repo_name()."""

    def test_extracts_repo(self):
        assert normalize_repo_name("owner/repo") == "repo"
        assert normalize_repo_name("acme-corp/widget-api") == "widget-api"

    def test_plain_name(self):
        assert normalize_repo_name("repo") == "repo"

    def test_non_string(self):
        assert normalize_repo_name(123) == "123"


class TestToAggregatorSlug:
    """Tests for to_aggregator_slug()."""

    def test_converts(self):
        assert to_aggregator_slug("acme-corp/widget-api") == "acme-corp-widget-api"
        assert to_aggregator_slug("vercel/next.js") == "vercel-next.js"

    def test_already_hyphenated(self):
        assert to_aggregator_slug("acme-corp-widget-api") == "acme-corp-widget-api"



class TestSafeErrorMessage:
    """Tests for safe_error_message()."""

    def test_known_patterns(self):
        assert safe_error_message("repo not found") == "Resource not found"
        assert safe_error_message("permission denied for resource") == "Permission denied"
        assert safe_error_message("API rate limit exceeded") == "Rate limit exceeded — try again later"
        assert safe_error_message("request timed out") == "Request timed out"
        assert safe_error_message("connection refused") == "Network error"

    def test_unknown_error_returns_default(self):
        assert safe_error_message("some internal stacktrace") == "Operation failed"
        assert safe_error_message("some error", "Custom default") == "Custom default"

    def test_empty_returns_default(self):
        assert safe_error_message("") == "Operation failed"
        assert safe_error_message(None) == "Operation failed"

    def test_case_insensitive(self):
        assert safe_error_message("NOT FOUND") == "Resource not found"
        assert safe_error_message("Permission Denied") == "Permission denied"


class TestValidateRequiredFields:
    """Tests for validate_required_fields()."""

    def test_all_present(self):
        data = {"owner": "acme-corp", "repo": "acme-corp", "issue_number": 42}
        assert validate_required_fields(data, ["owner", "repo", "issue_number"]) is None

    def test_missing_one(self):
        data = {"owner": "acme-corp", "repo": ""}
        err = validate_required_fields(data, ["owner", "repo"])
        assert "repo" in err

    def test_missing_key(self):
        data = {"owner": "acme-corp"}
        err = validate_required_fields(data, ["owner", "repo"])
        assert "repo" in err

    def test_none_data(self):
        err = validate_required_fields(None, ["owner"])
        assert "owner" in err

    def test_not_dict(self):
        err = validate_required_fields("string", ["owner"])
        assert "owner" in err

    def test_empty_dict(self):
        err = validate_required_fields({}, ["owner", "repo"])
        assert "owner" in err
        assert "repo" in err

    def test_falsy_values(self):
        data = {"owner": 0, "repo": None, "title": False}
        err = validate_required_fields(data, ["owner", "repo", "title"])
        assert "owner" in err
        assert "repo" in err
        assert "title" in err
