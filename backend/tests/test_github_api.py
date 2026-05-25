"""Tests for github_api helper functions — REST command shape and output parsing."""

import json
from unittest.mock import patch, call

import pytest

from services.github_api import (
    get_repo_issues,
    get_repo_prs,
    get_authenticated_user,
    invalidate_authenticated_user_cache,
)


class TestGetRepoIssues:
    """Tests for get_repo_issues — REST replacement for gh issue list --json."""

    @patch("services.github_api.run_gh_command")
    def test_calls_rest_api_not_graphql(self, mock_gh):
        """Must use gh api (REST), not gh issue list (GraphQL)."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        assert args[0] == "api"
        assert "issue" not in args
        assert "list" not in args

    @patch("services.github_api.run_gh_command")
    def test_url_includes_owner_repo_and_params(self, mock_gh):
        """URL must target repos/{owner}/{repo}/issues with open + per_page params."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("vercel", "next.js")

        args = mock_gh.call_args[0][0]
        url = args[1]
        assert "repos/vercel/next.js/issues" in url
        assert "state=open" in url
        assert "per_page=100" in url

    @patch("services.github_api.run_gh_command")
    def test_label_filter_appended_to_url(self, mock_gh):
        """When labels is provided it must be appended as a query param."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api", labels="vibeCheck")

        args = mock_gh.call_args[0][0]
        url = args[1]
        assert "labels=vibeCheck" in url

    @patch("services.github_api.run_gh_command")
    def test_no_label_param_when_not_provided(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        url = args[1]
        assert "labels=" not in url

    @patch("services.github_api.run_gh_command")
    def test_jq_excludes_pull_requests(self, mock_gh):
        """jq expression must contain pull_request null check to filter PRs."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "pull_request" in jq_expr

    @patch("services.github_api.run_gh_command")
    def test_returns_parsed_list_on_success(self, mock_gh):
        issues = [
            {"number": 1, "title": "Fix bug", "labels": [], "state": "open",
             "createdAt": "2026-01-01T00:00:00Z", "assignees": [], "url": "https://github.com/a/b/issues/1"},
        ]
        mock_gh.return_value = {"success": True, "output": json.dumps(issues)}
        result = get_repo_issues("acme-corp", "widget-api")
        assert result == issues

    @patch("services.github_api.run_gh_command")
    def test_returns_empty_list_on_api_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "rate limited"}
        result = get_repo_issues("acme-corp", "widget-api")
        assert result == []

    @patch("services.github_api.run_gh_command")
    def test_returns_empty_list_on_invalid_json(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "not-json"}
        result = get_repo_issues("acme-corp", "widget-api")
        assert result == []

    @patch("services.github_api.run_gh_command")
    def test_output_fields_include_created_at_camel(self, mock_gh):
        """jq must remap created_at → createdAt for API consumers."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "createdAt" in jq_expr
        assert "created_at" in jq_expr  # source field

    @patch("services.github_api.run_gh_command")
    def test_output_fields_include_html_url(self, mock_gh):
        """jq must map .html_url → url (not .url which is the API url)."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_issues("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "html_url" in jq_expr


class TestGetRepoPRs:
    """Tests for get_repo_prs — REST replacement for gh pr list --json."""

    @patch("services.github_api.run_gh_command")
    def test_calls_rest_api_not_graphql(self, mock_gh):
        """Must use gh api (REST), not gh pr list (GraphQL)."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_prs("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        assert args[0] == "api"
        assert "pr" not in args
        assert "list" not in args

    @patch("services.github_api.run_gh_command")
    def test_url_includes_owner_repo_and_params(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_prs("vercel", "next.js")

        args = mock_gh.call_args[0][0]
        url = args[1]
        assert "repos/vercel/next.js/pulls" in url
        assert "state=open" in url
        assert "per_page=100" in url

    @patch("services.github_api.run_gh_command")
    def test_returns_parsed_list_on_success(self, mock_gh):
        prs = [
            {"number": 5, "title": "Add feature", "state": "open",
             "createdAt": "2026-01-01T00:00:00Z", "author": {"login": "bob"},
             "url": "https://github.com/a/b/pull/5", "headRefName": "feat/x",
             "isDraft": False, "reviewDecision": None, "labels": []},
        ]
        mock_gh.return_value = {"success": True, "output": json.dumps(prs)}
        result = get_repo_prs("acme-corp", "widget-api")
        assert result == prs

    @patch("services.github_api.run_gh_command")
    def test_returns_empty_list_on_api_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "not found"}
        assert get_repo_prs("acme-corp", "widget-api") == []

    @patch("services.github_api.run_gh_command")
    def test_returns_empty_list_on_invalid_json(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "bad-json{{"}
        assert get_repo_prs("acme-corp", "widget-api") == []

    @patch("services.github_api.run_gh_command")
    def test_jq_remaps_author_from_user_login(self, mock_gh):
        """jq must reshape .user.login → author.login to match GraphQL shape."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_prs("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "user.login" in jq_expr
        assert "author" in jq_expr

    @patch("services.github_api.run_gh_command")
    def test_jq_remaps_head_ref(self, mock_gh):
        """jq must map .head.ref → headRefName."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_prs("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "head.ref" in jq_expr
        assert "headRefName" in jq_expr

    @patch("services.github_api.run_gh_command")
    def test_review_decision_is_null(self, mock_gh):
        """reviewDecision must be null (not available from REST list endpoint)."""
        mock_gh.return_value = {"success": True, "output": "[]"}
        get_repo_prs("acme-corp", "widget-api")

        args = mock_gh.call_args[0][0]
        jq_expr = " ".join(args)
        assert "reviewDecision: null" in jq_expr


class TestGetAuthenticatedUserCache:
    """Tests for get_authenticated_user — caches login to avoid re-shelling
    out on every route call. The 2026-05-24 incident showed prod's gh CLI
    can hang 30s on the auth probe; route handlers shouldn't re-pay that
    cost when the username is stable for the life of the token."""

    def setup_method(self):
        invalidate_authenticated_user_cache()

    @patch("services.github_api.run_gh_command")
    def test_caches_successful_lookup(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "alice\n"}

        assert get_authenticated_user() == "alice"
        assert get_authenticated_user() == "alice"
        assert get_authenticated_user() == "alice"

        # Single shell-out across three calls.
        assert mock_gh.call_count == 1

    @patch("services.github_api.run_gh_command")
    def test_caches_failure_briefly_to_avoid_hammering_broken_path(self, mock_gh):
        """When gh times out, return 'unknown' but cache it for the failure
        TTL so a downstream burst of route hits doesn't re-trigger 30s
        hangs in a tight loop."""
        mock_gh.return_value = {"success": False, "error": "Command timed out after 30s"}

        assert get_authenticated_user() == "unknown"
        assert get_authenticated_user() == "unknown"
        assert mock_gh.call_count == 1

    @patch("services.github_api.run_gh_command")
    def test_invalidate_forces_reprobe(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "alice\n"}
        assert get_authenticated_user() == "alice"
        invalidate_authenticated_user_cache()
        assert get_authenticated_user() == "alice"
        assert mock_gh.call_count == 2

    @patch("services.github_api.time")
    @patch("services.github_api.run_gh_command")
    def test_success_ttl_expires_after_one_hour(self, mock_gh, mock_time):
        mock_gh.return_value = {"success": True, "output": "alice\n"}
        mock_time.monotonic.return_value = 0.0
        assert get_authenticated_user() == "alice"

        # 59 minutes later — still cached
        mock_time.monotonic.return_value = 59 * 60.0
        assert get_authenticated_user() == "alice"
        assert mock_gh.call_count == 1

        # 61 minutes later — re-probes
        mock_time.monotonic.return_value = 61 * 60.0
        assert get_authenticated_user() == "alice"
        assert mock_gh.call_count == 2

    @patch("services.github_api.time")
    @patch("services.github_api.run_gh_command")
    def test_failure_ttl_expires_after_one_minute(self, mock_gh, mock_time):
        mock_gh.return_value = {"success": False, "error": "timeout"}
        mock_time.monotonic.return_value = 0.0
        assert get_authenticated_user() == "unknown"

        # 30s later — still cached
        mock_time.monotonic.return_value = 30.0
        assert get_authenticated_user() == "unknown"
        assert mock_gh.call_count == 1

        # 70s later — re-probes
        mock_time.monotonic.return_value = 70.0
        assert get_authenticated_user() == "unknown"
        assert mock_gh.call_count == 2

    @patch("services.github_api.run_gh_command")
    def test_failure_then_success_swaps_in_real_user(self, mock_gh):
        """Real recovery path: prod hangs briefly, then re-auths cleanly.
        After failure cache expires, the cached 'unknown' must give way
        to the actual login on the next successful probe."""
        invalidate_authenticated_user_cache()
        mock_gh.return_value = {"success": False, "error": "timeout"}
        assert get_authenticated_user() == "unknown"

        invalidate_authenticated_user_cache()
        mock_gh.return_value = {"success": True, "output": "alice\n"}
        assert get_authenticated_user() == "alice"
