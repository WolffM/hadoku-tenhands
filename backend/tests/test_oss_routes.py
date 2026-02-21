"""Tests for OSS routes — all stages and polling endpoints."""

import json
from unittest.mock import patch, MagicMock

import pytest

from app import app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    """Disable caching for all route tests."""
    monkeypatch.setenv("CACHE_DISABLED", "1")


PREFIX = "/dispatch"


# ============ Stage 1: Target Repos ============


class TestAddTarget:
    """Tests for POST /api/oss/add-target."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_add_invalid_slug_no_slash(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "owner/repo" in data["error"]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_add_invalid_slug_empty_parts(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "/"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.run_gh_command")
    def test_add_nonexistent_repo(self, mock_gh, mock_user, client):
        mock_gh.return_value = {"success": False, "error": "Not found"}

        resp = client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "nonexistent/repo"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "not found" in data["error"].lower()

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_add_parses_owner_repo_correctly(self, mock_gh, mock_svc_cls, mock_user, mock_cache, client):
        """Verifies the slug.split('/') parsing passes correct args to service."""
        mock_gh.return_value = {"success": True, "output": "fastify/fastify"}
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.add_to_local_watchlist.assert_called_once_with("fastify", "fastify")

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_add_invalidates_both_caches(self, mock_gh, mock_svc_cls, mock_user, mock_cache, client):
        mock_gh.return_value = {"success": True, "output": "fastify/fastify"}

        client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        mock_cache.assert_any_call("oss-stage1-targets")
        mock_cache.assert_any_call("oss-stage2-issues")


class TestRemoveTarget:
    """Tests for POST /api/oss/remove-target."""

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_remove_with_slash_splits_correctly(self, mock_svc_cls, mock_user, mock_cache, client):
        """Tests the '/' in slug branch — parses owner/repo from slash format."""
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/remove-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.remove_from_local_watchlist.assert_called_once_with("fastify", "fastify")

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_remove_hyphenated_slug_looks_up_watchlist(self, mock_svc_cls, mock_user, mock_cache, client):
        """Tests the else branch — iterates watchlist to find matching slug."""
        svc = mock_svc_cls.return_value
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify"}
        ]

        client.post(
            f"{PREFIX}/api/oss/remove-target",
            json={"slug": "fastify-fastify"},
            content_type="application/json",
        )

        svc.remove_from_local_watchlist.assert_called_once_with("fastify", "fastify")

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_remove_hyphenated_slug_not_found_errors(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_local_watchlist.return_value = []

        resp = client.post(
            f"{PREFIX}/api/oss/remove-target",
            json={"slug": "nonexistent-repo"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "not found" in data["error"].lower()


class TestRefreshTarget:
    """Tests for POST /api/oss/refresh-target."""

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_refresh_converts_slash_to_hyphen(self, mock_svc_cls, mock_user, mock_cache, client):
        """Tests the slug.replace('/', '-') conversion logic."""
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.trigger_refresh.assert_called_once_with("fastify-fastify")


# ============ Stage 1: Enrichment ============


class TestStage1Enrichment:
    """Tests for the _enrich_target_via_gh logic in GET /api/oss/stage1-targets."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_local_watchlist_enriches_via_gh_json_parsing(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests that _enrich_target_via_gh actually parses JSON and builds the target dict."""
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify", "added_at": "2026-02-18T00:00:00Z"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({"stars": 1000, "language": "JavaScript", "license": "MIT", "openIssueCount": 42, "hasContributing": False})
        }

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["targets"]) == 1
        assert data["targets"][0]["slug"] == "fastify-fastify"
        assert data["targets"][0]["meta"]["stars"] == 1000
        assert data["targets"][0]["meta"]["language"] == "JavaScript"

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_local_watchlist_gh_failure_returns_target_without_meta(self, mock_gh, mock_svc_cls, mock_user, client):
        """When gh CLI fails, target should still appear but without meta field."""
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify", "added_at": "2026-02-18T00:00:00Z"}
        ]

        mock_gh.return_value = {"success": False, "error": "Network error"}

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["targets"]) == 1
        assert data["targets"][0]["slug"] == "fastify-fastify"
        assert "meta" not in data["targets"][0]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_local_watchlist_malformed_json_returns_target_without_meta(self, mock_gh, mock_svc_cls, mock_user, client):
        """When gh CLI returns invalid JSON, target appears without meta."""
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo", "added_at": "2026-02-18T00:00:00Z"}
        ]

        mock_gh.return_value = {"success": True, "output": "not valid json{{{"}

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["targets"]) == 1
        assert "meta" not in data["targets"][0]


# ============ Stage 2: Scored Issues ============


class TestStage2Issues:
    """Tests for GET /api/oss/stage2-issues — fallback scoring logic."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_scores_and_structures_issues(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the _fetch_repo_issues_fallback pipeline: JSON parse → score → build response dict."""
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([
                {
                    "number": 1,
                    "title": "Fix docs typo",
                    "url": "https://github.com/fastify/fastify/issues/1",
                    "labels": [{"name": "good first issue", "color": "7057ff"}],
                    "createdAt": "2026-02-18T00:00:00Z",
                    "updatedAt": "2026-02-18T00:00:00Z",
                    "comments": 2,
                    "assignees": [],
                }
            ])
        }

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["issues"]) == 1
        issue = data["issues"][0]
        assert issue["repo"] == "fastify/fastify"
        assert issue["number"] == 1
        assert issue["cvs"] == 70  # 50 base + 20 gfi
        assert issue["cvsTier"] == "likely"
        assert issue["dataCompleteness"] == "partial"
        assert issue["id"] == "github-fastify-fastify-1"

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_filters_out_assigned_issues(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([
                {
                    "number": 1,
                    "title": "Assigned issue",
                    "url": "https://github.com/fastify/fastify/issues/1",
                    "labels": [{"name": "good first issue"}],
                    "createdAt": "2026-02-18T00:00:00Z",
                    "updatedAt": "2026-02-18T00:00:00Z",
                    "comments": 0,
                    "assignees": [{"login": "someone"}],
                }
            ])
        }

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["issues"]) == 0

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_normalizes_dict_labels_to_strings(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([
                {
                    "number": 5,
                    "title": "Test issue",
                    "url": "https://github.com/org/repo/issues/5",
                    "labels": [{"name": "bug", "color": "d73a4a"}, {"name": "good first issue", "color": "7057ff"}],
                    "createdAt": "2026-02-18T00:00:00Z",
                    "updatedAt": "2026-02-18T00:00:00Z",
                    "comments": 1,
                    "assignees": [],
                }
            ])
        }

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["issues"][0]["labels"] == ["bug", "good first issue"]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_sorts_by_cvs_descending(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([
                {
                    "number": 1, "title": "No label issue",
                    "url": "https://github.com/org/repo/issues/1",
                    "labels": [],
                    "createdAt": "2026-02-18T00:00:00Z", "updatedAt": "2026-02-18T00:00:00Z",
                    "comments": 1, "assignees": [],
                },
                {
                    "number": 2, "title": "GFI issue",
                    "url": "https://github.com/org/repo/issues/2",
                    "labels": [{"name": "good first issue"}],
                    "createdAt": "2026-02-18T00:00:00Z", "updatedAt": "2026-02-18T00:00:00Z",
                    "comments": 1, "assignees": [],
                },
            ])
        }

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert len(data["issues"]) == 2
        assert data["issues"][0]["cvs"] >= data["issues"][1]["cvs"]
        assert data["issues"][0]["number"] == 2  # GFI issue (70) first

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_handles_malformed_json_gracefully(self, mock_gh, mock_svc_cls, mock_user, client):
        """When gh returns invalid JSON, the route should return empty issues (not crash)."""
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo"}
        ]

        mock_gh.return_value = {"success": True, "output": "not valid json"}

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert data["issues"] == []


# ============ GO-tier Notification ============


class TestGoTierNotification:
    """Tests for GO-tier notification firing in _fetch_repo_issues_fallback."""

    @patch("routes.oss_routes.notify_go_tier_issue")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.score_issue_fallback")
    def test_notification_fires_when_cvs_reaches_85(self, mock_score, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        """Bypass the real scorer and inject CVS >= 85 to test the notification trigger."""
        from routes.oss_routes import _notified_go_issues
        _notified_go_issues.clear()

        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 99,
                "title": "Critical fix",
                "url": "https://github.com/org/repo/issues/99",
                "labels": [{"name": "good first issue"}],
                "createdAt": "2026-02-18T00:00:00Z",
                "updatedAt": "2026-02-18T00:00:00Z",
                "comments": 0,
                "assignees": [],
            }])
        }

        # Force scorer to return GO-tier score
        mock_score.return_value = {"cvs": 92, "cvsTier": "go", "dataCompleteness": "partial"}

        client.get(f"{PREFIX}/api/oss/stage2-issues")

        mock_notify.assert_called_once_with("org/repo", 99, "Critical fix", 92)

    @patch("routes.oss_routes.notify_go_tier_issue")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.score_issue_fallback")
    def test_notification_deduplicates_by_issue_id(self, mock_score, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        """Same issue polled twice should only fire notification once."""
        from routes.oss_routes import _notified_go_issues
        _notified_go_issues.clear()

        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "org", "repo": "repo", "slug": "org-repo"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 99,
                "title": "Critical fix",
                "url": "https://github.com/org/repo/issues/99",
                "labels": [{"name": "good first issue"}],
                "createdAt": "2026-02-18T00:00:00Z",
                "updatedAt": "2026-02-18T00:00:00Z",
                "comments": 0,
                "assignees": [],
            }])
        }

        mock_score.return_value = {"cvs": 92, "cvsTier": "go", "dataCompleteness": "partial"}

        client.get(f"{PREFIX}/api/oss/stage2-issues")
        client.get(f"{PREFIX}/api/oss/stage2-issues")

        assert mock_notify.call_count == 1


# ============ Poll Submitted PRs ============


class TestPollSubmittedPRs:
    """Tests for POST /api/oss/poll-submitted-prs — state detection and notifications."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_detects_state_transition_to_merged(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "fastify/fastify",
            "pr_url": "https://github.com/fastify/fastify/pull/100",
            "pr_number": 100,
            "title": "Fix bug",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "MERGED",
                "reviewDecision": "APPROVED",
                "mergedAt": "2026-02-19T12:00:00Z",
                "closedAt": None,
            })
        }

        resp = client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                          json={}, content_type="application/json")
        data = resp.get_json()

        assert data["success"] is True
        assert data["submitted"][0]["state"] == "merged"
        assert data["submitted"][0]["review_decision"] == "APPROVED"
        assert data["submitted"][0]["merged_at"] == "2026-02-19T12:00:00Z"
        assert data["submitted"][0]["last_polled_at"] is not None
        svc.update_submitted_prs.assert_called_once()

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_skips_polling_for_already_terminal_prs(self, mock_svc_cls, mock_user, client):
        """PRs in merged/closed state should not trigger gh CLI calls."""
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "fastify/fastify",
            "pr_url": "https://github.com/fastify/fastify/pull/50",
            "pr_number": 50,
            "title": "Old fix",
            "state": "merged",
            "review_decision": "APPROVED",
            "merged_at": "2026-02-10T00:00:00Z",
            "closed_at": None,
            "last_polled_at": "2026-02-15T00:00:00Z",
            "submitted_at": "2026-02-08T00:00:00Z",
        }]

        resp = client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                          json={}, content_type="application/json")
        data = resp.get_json()

        assert data["submitted"][0]["state"] == "merged"

    @patch("routes.oss_routes.notify_upstream_merged")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fires_merge_notification_on_state_change(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "MERGED",
                "reviewDecision": "APPROVED",
                "mergedAt": "2026-02-19T12:00:00Z",
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_called_once_with(
            "vercel/next.js",
            "https://github.com/vercel/next.js/pull/200",
            "Fix routing",
        )

    @patch("routes.oss_routes.notify_upstream_feedback")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fires_feedback_notification_on_review_change(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "OPEN",
                "reviewDecision": "CHANGES_REQUESTED",
                "mergedAt": None,
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_called_once_with(
            "vercel/next.js",
            "https://github.com/vercel/next.js/pull/200",
            "CHANGES_REQUESTED",
        )

    @patch("routes.oss_routes.notify_upstream_feedback")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_no_notification_when_review_unchanged(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        """If review_decision hasn't changed, no notification should fire."""
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": "APPROVED",  # Already approved
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "OPEN",
                "reviewDecision": "APPROVED",  # Same — no change
                "mergedAt": None,
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_not_called()


# ============ Stage 3: Fork & Assign ============


class TestSelectIssue:
    """Tests for POST /api/oss/select-issue."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_select_issue_already_selected_returns_flag(self, mock_svc_cls, mock_user, client):
        """Tests the dedup branch — different response shape when already selected."""
        svc = mock_svc_cls.return_value
        svc.find_selected_issue.return_value = {"origin_slug": "fastify/fastify", "issue_number": 42}

        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_selected"] is True
        svc.select_issue.assert_not_called()

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_select_issue_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={"origin_owner": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()


class TestForkAndAssign:
    """Tests for POST /api/oss/fork-and-assign."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_dedup_returns_existing_assignment(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/fastify/issues/1"
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_assigned"] is True
        assert data["fork_issue_url"] == "https://github.com/testuser/fastify/issues/1"

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={"origin_owner": "fastify", "repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_fork_creation_failure(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = False
        svc.fork_repo.return_value = {"success": False, "error": "Rate limited"}
        svc.get_dossier.return_value = None

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "fork" in data["error"].lower()

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_fork_timeout(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = False
        svc.get_dossier.return_value = None

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "timed out" in data["error"].lower()

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_auto_fetches_dossier_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = {
            "slug": "fastify-fastify",
            "sections": {"contributionRules": "Follow the style guide"},
        }
        svc.build_agent_context.return_value = "## Context"

        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/testuser/fastify/issues/1\n",
        }

        client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )

        svc.get_dossier.assert_called_once_with("fastify-fastify")
        call_args = svc.build_agent_context.call_args
        assert call_args[0][5] == {"contributionRules": "Follow the style guide"}


# ============ Stage 4: Review on Fork ============


class TestStage4ForkPRs:
    """Tests for GET /api/oss/stage4-fork-prs."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_injects_repo_and_origin_slug_into_prs(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests that _get_fork_prs adds repo/originSlug fields to each PR dict."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 1, "title": "Fix docs",
                "url": "https://github.com/testuser/fastify/pull/1",
                "headRefName": "fix-docs", "additions": 10, "deletions": 2,
                "changedFiles": 1, "reviewDecision": None, "isDraft": False,
                "createdAt": "2026-02-19T00:00:00Z",
            }]),
        }

        resp = client.get(f"{PREFIX}/api/oss/stage4-fork-prs")
        data = resp.get_json()

        assert len(data["prs"]) == 1
        assert data["prs"][0]["repo"] == "fastify"
        assert data["prs"][0]["originSlug"] == "fastify/fastify"

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_deduplicates_forked_repos_via_set(self, mock_gh, mock_svc_cls, mock_user, client):
        """Two assignments for same repo should only fetch PRs once."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
        ]

        mock_gh.return_value = {"success": True, "output": json.dumps([])}

        client.get(f"{PREFIX}/api/oss/stage4-fork-prs")

        assert mock_gh.call_count == 1


class TestForkPRDetails:
    """Tests for POST /api/oss/fork-pr-details."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.run_gh_command")
    def test_merges_diff_into_pr_data(self, mock_gh, mock_user, client):
        """Tests that the route makes 2 gh calls and injects diff into pr_data."""
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"number": 1, "title": "Fix docs", "state": "OPEN"})},
            {"success": True, "output": "diff --git a/README.md b/README.md\n+fixed"},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/fork-pr-details",
            json={"repo": "fastify", "pr_number": 1},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["pr"]["title"] == "Fix docs"
        assert "diff" in data["pr"]
        assert "+fixed" in data["pr"]["diff"]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/fork-pr-details",
            json={"repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()


class TestApproveForkPR:
    """Tests for POST /api/oss/approve-fork-pr."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/approve-fork-pr",
            json={"repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False


class TestMergeForkPR:
    """Tests for POST /api/oss/merge-fork-pr."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_merge_extracts_branch_info_and_saves_to_stage5(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the multi-step merge flow: view → draft check → merge → save_ready_to_submit."""
        svc = mock_svc_cls.return_value

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"headRefName": "fix-docs", "title": "Fix docs", "baseRefName": "main"})},
            {"success": True, "output": json.dumps({"isDraft": False})},
            {"success": True, "output": "Merged"},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1, "origin_slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        svc.save_ready_to_submit.assert_called_once_with(
            origin_slug="fastify/fastify",
            repo="fastify",
            branch="fix-docs",
            title="Fix docs",
            base_branch="main",
        )

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_merge_marks_draft_as_ready_before_merge(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the isDraft branch — should call 'pr ready' before 'pr merge'."""
        svc = mock_svc_cls.return_value

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"headRefName": "fix", "title": "Fix", "baseRefName": "main"})},
            {"success": True, "output": json.dumps({"isDraft": True})},
            {"success": True, "output": ""},  # pr ready
            {"success": True, "output": "Merged"},  # pr merge
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1, "origin_slug": "fastify/fastify"},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is True
        assert mock_gh.call_count == 4  # view + draft check + ready + merge

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is False


# ============ Stage 5: Submit Upstream ============


class TestSubmitToOrigin:
    """Tests for POST /api/oss/submit-to-origin."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_submit_saves_and_removes_ready_item(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/fastify/fastify/pull/123\n",
        }

        resp = client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "fastify/fastify",
                "repo": "fastify",
                "branch": "fix-docs",
                "title": "Fix docs",
                "body": "## Summary\nFixes docs",
                "base_branch": "main",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["pr_url"] == "https://github.com/fastify/fastify/pull/123"
        svc.save_submitted_pr.assert_called_once_with(
            "fastify/fastify", "https://github.com/fastify/fastify/pull/123", "Fix docs"
        )
        svc.remove_ready_to_submit.assert_called_once_with("fastify/fastify", "fix-docs")

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_submit_generates_default_body_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the 'if not body' branch — route should call format_upstream_pr_body."""
        svc = mock_svc_cls.return_value
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/fastify/fastify/pull/123\n",
        }

        client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "fastify/fastify",
                "repo": "fastify",
                "branch": "fix-docs",
                "title": "Fix docs",
            },
            content_type="application/json",
        )

        call_args = mock_gh.call_args[0][0]
        body_idx = call_args.index("--body") + 1
        assert len(call_args[body_idx]) > 0
        assert "fastify/fastify" in call_args[body_idx]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={"origin_slug": "fastify/fastify"},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is False
