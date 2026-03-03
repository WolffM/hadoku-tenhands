"""Tests for OSS debug routes — 14 diagnostic endpoints."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from app import app
from extensions import limiter


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as client:
        yield client
    limiter.enabled = True


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    """Disable caching for all route tests."""
    monkeypatch.setenv("CACHE_DISABLED", "1")


PREFIX = "/dispatch"


# ============ Admin Key Gating ============


class TestAdminKeyGating:
    """Tests for require_admin_key decorator on debug endpoints."""

    def test_no_gating_when_admin_key_unset(self, client, monkeypatch):
        """When ADMIN_KEY is not set, debug endpoints are accessible without auth."""
        monkeypatch.delenv("ADMIN_KEY", raising=False)
        with patch("routes.oss_debug_routes.run_gh_command") as mock_gh, \
             patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser"):
            mock_gh.return_value = {"success": True, "output": "testuser"}
            resp = client.get(f"{PREFIX}/api/oss/debug/gh-health")
            assert resp.status_code == 200

    def test_401_when_admin_key_set_but_not_provided(self, client, monkeypatch):
        """When ADMIN_KEY is set, requests without the key get 401."""
        monkeypatch.setenv("ADMIN_KEY", "secret123")
        resp = client.get(f"{PREFIX}/api/oss/debug/gh-health")
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False
        assert data["error"] == "Unauthorized"

    def test_401_when_admin_key_wrong(self, client, monkeypatch):
        """When ADMIN_KEY is set, wrong key gets 401."""
        monkeypatch.setenv("ADMIN_KEY", "secret123")
        resp = client.get(
            f"{PREFIX}/api/oss/debug/gh-health",
            headers={"X-Admin-Key": "wrong"}
        )
        assert resp.status_code == 401

    def test_success_with_correct_header(self, client, monkeypatch):
        """When correct X-Admin-Key header is provided, request succeeds."""
        monkeypatch.setenv("ADMIN_KEY", "secret123")
        with patch("routes.oss_debug_routes.run_gh_command") as mock_gh, \
             patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser"):
            mock_gh.return_value = {"success": True, "output": "testuser"}
            resp = client.get(
                f"{PREFIX}/api/oss/debug/gh-health",
                headers={"X-Admin-Key": "secret123"}
            )
            assert resp.status_code == 200

    def test_success_with_query_param(self, client, monkeypatch):
        """admin_key query param also works."""
        monkeypatch.setenv("ADMIN_KEY", "secret123")
        with patch("routes.oss_debug_routes.run_gh_command") as mock_gh, \
             patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser"):
            mock_gh.return_value = {"success": True, "output": "testuser"}
            resp = client.get(f"{PREFIX}/api/oss/debug/gh-health?admin_key=secret123")
            assert resp.status_code == 200


# ============ Group A: Health Checks ============


class TestGhHealth:
    """Tests for GET /api/oss/debug/gh-health."""

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_healthy_gh(self, mock_user, mock_gh, client):
        mock_gh.side_effect = [
            {"success": True, "output": "Logged in"},  # auth status
            {"success": True, "output": "testuser"},     # api user
            {"success": True, "output": json.dumps({"remaining": 4999, "limit": 5000, "reset": 1700000000})},  # rate limit
        ]
        resp = client.get(f"{PREFIX}/api/oss/debug/gh-health")
        data = resp.get_json()
        assert data["success"] is True
        assert data["authenticated"] is True
        assert data["api_working"] is True
        assert data["rate_limit"]["remaining"] == 4999
        assert data["response_time_ms"] >= 0

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_gh_not_authenticated(self, mock_user, mock_gh, client):
        mock_gh.return_value = {"success": False, "error": "not logged in"}
        resp = client.get(f"{PREFIX}/api/oss/debug/gh-health")
        data = resp.get_json()
        assert data["authenticated"] is False
        assert data["api_working"] is False


class TestAggregatorHealth:
    """Tests for GET /api/oss/debug/aggregator-health."""

    @patch("routes.oss_debug_routes._call_aggregator")
    @patch("routes.oss_debug_routes.AGGREGATOR_API_URL", "https://test-aggregator.example.com/oss/api")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_aggregator_reachable(self, mock_user, mock_agg, client):
        mock_agg.return_value = {"slugs": ["fastify-fastify", "vercel-next.js"]}
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["success"] is True
        assert data["configured"] is True
        assert data["reachable"] is True
        assert data["watchlist_count"] == 2

    @patch("routes.oss_debug_routes._call_aggregator")
    @patch("routes.oss_debug_routes.AGGREGATOR_API_URL", "")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_aggregator_not_configured(self, mock_user, mock_agg, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["configured"] is False
        assert data["error"] == "AGGREGATOR_API_URL not configured"

    @patch("routes.oss_debug_routes._call_aggregator")
    @patch("routes.oss_debug_routes.AGGREGATOR_API_URL", "https://test-aggregator.example.com/oss/api")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_aggregator_unreachable(self, mock_user, mock_agg, client):
        mock_agg.return_value = None
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["reachable"] is False
        assert data["error"] is not None


class TestStateDump:
    """Tests for GET /api/oss/debug/state-dump."""

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_state_dump_returns_all_sections(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/state-dump")
        data = resp.get_json()
        assert data["success"] is True
        assert "state" in data
        assert "counts" in data
        assert "watchlist" in data["counts"]
        assert "assignments" in data["counts"]
        assert "submitted_prs" in data["counts"]


# ============ Group B: Fork & Assign Decomposition ============


class TestForkExists:
    """Tests for GET /api/oss/debug/fork-exists."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_fork_exists(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.check_fork_exists.return_value = True
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists?repo=fastify")
        data = resp.get_json()
        assert data["exists"] is True
        assert data["fork_url"] == "https://github.com/testuser/fastify"

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_fork_not_exists(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.check_fork_exists.return_value = False
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists?repo=fastify")
        data = resp.get_json()
        assert data["exists"] is False
        assert data["fork_url"] is None

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_missing_repo_param(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists")
        data = resp.get_json()
        assert data["success"] is False


class TestForkRepo:
    """Tests for POST /api/oss/debug/fork-repo."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_fork_succeeds(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.fork_repo.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/fork-repo",
            json={"origin_owner": "fastify", "repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["forked"] is True

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/debug/fork-repo",
            json={"origin_owner": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is False


class TestSyncFork:
    """Tests for POST /api/oss/debug/sync-fork."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_sync_succeeds(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.sync_fork.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/sync-fork",
            json={"repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["synced"] is True


class TestBuildContext:
    """Tests for POST /api/oss/debug/build-context."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_build_context_returns_markdown(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.get_dossier.return_value = None
        mock_svc.get_issue_brief.return_value = None
        mock_svc.build_agent_context.return_value = ("# Context", {"sources": ["gh-issue-view"]})
        resp = client.post(
            f"{PREFIX}/api/oss/debug/build-context",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 1234,
                "issue_title": "Fix memory leak",
                "issue_url": "https://github.com/fastify/fastify/issues/1234",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is True
        assert data["context_markdown"] == "# Context"

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/debug/build-context",
            json={"origin_owner": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is False


class TestCreateContextIssue:
    """Tests for POST /api/oss/debug/create-context-issue."""

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_create_issue_succeeds(self, mock_user, mock_gh, client):
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/testuser/fastify/issues/5",
        }
        resp = client.post(
            f"{PREFIX}/api/oss/debug/create-context-issue",
            json={"repo": "fastify", "title": "Fix #1234", "body": "Context body"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is True
        assert data["issue_number"] == 5


class TestAssignCopilot:
    """Tests for POST /api/oss/debug/assign-copilot."""

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_assign_succeeds(self, mock_user, mock_gh, client):
        mock_gh.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/assign-copilot",
            json={"repo": "fastify", "issue_number": 5},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["assigned"] is True


# ============ Group C: Scoring & Tracking ============


class TestScoreIssue:
    """Tests for GET /api/oss/debug/score-issue."""

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_score_issue_returns_breakdown(self, mock_user, mock_gh, client):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "number": 1234,
                "title": "Fix bug",
                "labels": [{"name": "good first issue"}],
                "createdAt": "2025-01-01T00:00:00Z",
                "updatedAt": "2025-01-01T00:00:00Z",
                "comments": [],
                "assignees": [],
                "url": "https://github.com/org/repo/issues/1234",
            }),
        }
        resp = client.get(f"{PREFIX}/api/oss/debug/score-issue?owner=org&repo=repo&issue_number=1234")
        data = resp.get_json()
        assert data["success"] is True
        assert "score" in data
        assert "breakdown" in data
        assert data["score"]["cvs"] > 0
        assert data["breakdown"]["good_first_issue_bonus"] == 20

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_missing_params(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/score-issue?owner=org")
        data = resp.get_json()
        assert data["success"] is False


class TestForkPRStatus:
    """Tests for GET /api/oss/debug/fork-pr-status."""

    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_pr_status_returns_data(self, mock_user, mock_gh, client):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "number": 1,
                "title": "Fix",
                "state": "OPEN",
                "reviewDecision": None,
                "additions": 10,
                "deletions": 5,
                "changedFiles": 2,
                "isDraft": False,
                "headRefName": "fix/bug",
                "baseRefName": "main",
                "createdAt": "2025-01-01T00:00:00Z",
                "url": "https://github.com/testuser/repo/pull/1",
            }),
        }
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-pr-status?repo=repo&pr_number=1")
        data = resp.get_json()
        assert data["success"] is True
        assert data["pr"]["number"] == 1


class TestPollSubmittedPR:
    """Tests for GET /api/oss/debug/poll-submitted-pr."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.run_gh_command")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_poll_returns_state(self, mock_user, mock_gh, mock_svc_class, client):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "OPEN",
                "reviewDecision": None,
                "mergedAt": None,
                "closedAt": None,
            }),
        }
        mock_svc = mock_svc_class.return_value
        mock_svc.get_submitted_prs.return_value = []
        resp = client.get(f"{PREFIX}/api/oss/debug/poll-submitted-pr?pr_url=https://github.com/org/repo/pull/123")
        data = resp.get_json()
        assert data["success"] is True
        assert data["current_state"] == "open"

    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_missing_pr_url(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/poll-submitted-pr")
        data = resp.get_json()
        assert data["success"] is False


class TestNotificationPreview:
    """Tests for GET /api/oss/debug/notification-preview."""

    @patch("routes.oss_debug_routes.OSSService")
    @patch("routes.oss_debug_routes.get_authenticated_user", return_value="testuser")
    def test_preview_returns_structure(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.get_submitted_prs.return_value = [
            {"pr_url": "https://github.com/org/repo/pull/1", "state": "open"},
        ]
        resp = client.get(f"{PREFIX}/api/oss/debug/notification-preview")
        data = resp.get_json()
        assert data["success"] is True
        assert "discord_webhook_configured" in data
        assert data["submitted_pr_count"] == 1
        assert len(data["pr_scenarios"]) == 1
