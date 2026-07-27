"""Tests for OSS debug routes — 14 diagnostic endpoints."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from app import app
from extensions import limiter
from middleware.whoami import clear_cache, resolve_tier_from_key as _real_resolve
import routes.debug._middleware as _gate

ADMIN_K, FRIEND_K, SERVICE_K = "admin-key", "friend-key", "service-key"


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as client:
        yield client
    limiter.enabled = True


@pytest.fixture(autouse=True)
def disable_cache_and_admit_admin(monkeypatch):
    """Disable caching, and admit the route tests past the debug gate.

    The gate resolves `X-User-Key` through whoami; these tests predate it and
    send no key, so stub the resolver rather than teach 200 tests to carry a
    header. `TestDebugGate` overrides this to exercise the real thing.
    """
    monkeypatch.setenv("CACHE_DISABLED", "1")
    monkeypatch.setattr(_gate, "resolve_tier_from_key", lambda _key: "admin")


PREFIX = "/tenhands"

# Module paths for patching (names live in their sub-module now)
_health = "routes.debug.health_routes"
_fork = "routes.debug.fork_routes"
_context = "routes.debug.context_routes"
_assignment = "routes.debug.assignment_routes"
_tracking = "routes.debug.tracking_routes"


# ============ Debug gate ============


class TestDebugGate:
    """Admin tier only, resolved through whoami, failing closed.

    **The regression this exists for:** the gate used to compare the request
    against an `ADMIN_KEY` env var *only when that var was set*, and admit
    everyone when it wasn't. TenHands is not permitted an admin credential, so
    the var was unset in production and the gate became a no-op — and the tests
    this class replaces asserted exactly that ("accessible without auth"), so
    the suite stayed green while the endpoints stood open.

    There is no stored secret now. The caller brings a key, whoami says what
    tier it is, and anything below admin is refused.
    """

    @pytest.fixture(autouse=True)
    def real_gate(self, monkeypatch):
        """Restore the real resolver, driven by overrides so no network runs."""
        monkeypatch.setattr(_gate, "resolve_tier_from_key", _real_resolve)
        monkeypatch.setenv("WHOAMI_TEST_OVERRIDES", json.dumps({
            ADMIN_K: "admin", FRIEND_K: "friend", SERVICE_K: "service"}))
        clear_cache()
        yield
        clear_cache()

    def _get(self, client, **headers):
        return client.get(f"{PREFIX}/api/oss/debug/gh-health", headers=headers)

    def test_no_key_is_401(self, client):
        resp = self._get(client)
        assert resp.status_code == 401
        assert resp.get_json()["success"] is False

    def test_admin_tier_gets_in(self, client):
        with patch(f"{_health}.run_gh_command") as mock_gh, \
             patch(f"{_health}.get_authenticated_user", return_value="testuser"):
            mock_gh.return_value = {"success": True, "output": "testuser"}
            assert self._get(client, **{"X-User-Key": ADMIN_K}).status_code == 200

    @pytest.mark.parametrize("key, tier", [
        (FRIEND_K, "friend"),
        (SERVICE_K, "service"),
        ("never-issued", "public"),
    ])
    def test_below_admin_is_403_and_says_why(self, client, key, tier):
        """A service key belongs to a machine with no business here, and an
        unrecognised key resolves to public — both refused, both told which."""
        resp = self._get(client, **{"X-User-Key": key})
        assert resp.status_code == 403
        assert resp.get_json()["tier"] == tier

    def test_fails_closed_when_whoami_cannot_answer(self, client, monkeypatch):
        """An outage resolves to public, which is refused.

        The gate this replaces failed *open* under exactly this condition —
        no answer meant no gating at all.
        """
        monkeypatch.delenv("WHOAMI_TEST_OVERRIDES", raising=False)
        monkeypatch.setattr("middleware.whoami._fetch_tier_from_whoami",
                            lambda _key: None)
        clear_cache()
        assert self._get(client, **{"X-User-Key": ADMIN_K}).status_code == 403

    def test_the_old_admin_key_channels_are_gone(self, client, monkeypatch):
        """`X-Admin-Key` and `?admin_key=` no longer authenticate anything.

        Setting the env var too, so this fails if the old branch is revived.
        """
        monkeypatch.setenv("ADMIN_KEY", "secret123")
        assert self._get(client, **{"X-Admin-Key": "secret123"}).status_code == 401
        assert client.get(
            f"{PREFIX}/api/oss/debug/gh-health?admin_key=secret123"
        ).status_code == 401


# ============ Group A: Health Checks ============


class TestGhHealth:
    """Tests for GET /api/oss/debug/gh-health."""

    @patch(f"{_health}.run_gh_command")
    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
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

    @patch(f"{_health}.run_gh_command")
    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
    def test_gh_not_authenticated(self, mock_user, mock_gh, client):
        mock_gh.return_value = {"success": False, "error": "not logged in"}
        resp = client.get(f"{PREFIX}/api/oss/debug/gh-health")
        data = resp.get_json()
        assert data["authenticated"] is False
        assert data["api_working"] is False


class TestAggregatorHealth:
    """Tests for GET /api/oss/debug/aggregator-health."""

    @patch(f"{_health}._call_aggregator")
    @patch(f"{_health}.AGGREGATOR_API_URL", "https://test-aggregator.example.com/oss/api")
    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
    def test_aggregator_reachable(self, mock_user, mock_agg, client):
        mock_agg.return_value = {"success": True, "data": {"issues": []}}
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["success"] is True
        assert data["configured"] is True
        assert data["reachable"] is True

    @patch(f"{_health}._call_aggregator")
    @patch(f"{_health}.AGGREGATOR_API_URL", "")
    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
    def test_aggregator_not_configured(self, mock_user, mock_agg, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["configured"] is False
        assert data["error"] == "AGGREGATOR_API_URL not configured"

    @patch(f"{_health}._call_aggregator")
    @patch(f"{_health}.AGGREGATOR_API_URL", "https://test-aggregator.example.com/oss/api")
    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
    def test_aggregator_unreachable(self, mock_user, mock_agg, client):
        mock_agg.return_value = None
        resp = client.get(f"{PREFIX}/api/oss/debug/aggregator-health")
        data = resp.get_json()
        assert data["reachable"] is False
        assert data["error"] is not None


class TestStateDump:
    """Tests for GET /api/oss/debug/state-dump."""

    @patch(f"{_health}.get_authenticated_user", return_value="testuser")
    def test_state_dump_returns_all_sections(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/state-dump")
        data = resp.get_json()
        assert data["success"] is True
        assert "state" in data
        assert "counts" in data
        assert "assignments" in data["counts"]
        assert "submitted_prs" in data["counts"]


# ============ Group B: Fork & Assign Decomposition ============


class TestForkExists:
    """Tests for GET /api/oss/debug/fork-exists."""

    @patch(f"{_fork}.OSSService")
    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_fork_exists(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.check_fork_exists.return_value = True
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists?repo=widget-api")
        data = resp.get_json()
        assert data["exists"] is True
        assert data["fork_url"] == "https://github.com/testuser/widget-api"

    @patch(f"{_fork}.OSSService")
    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_fork_not_exists(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.check_fork_exists.return_value = False
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists?repo=widget-api")
        data = resp.get_json()
        assert data["exists"] is False
        assert data["fork_url"] is None

    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_missing_repo_param(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/fork-exists")
        data = resp.get_json()
        assert data["success"] is False


class TestForkRepo:
    """Tests for POST /api/oss/debug/fork-repo."""

    @patch(f"{_fork}.OSSService")
    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_fork_succeeds(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.fork_repo.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/fork-repo",
            json={"origin_owner": "acme-corp", "repo": "widget-api"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["forked"] is True

    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/debug/fork-repo",
            json={"origin_owner": "acme-corp"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is False


class TestSyncFork:
    """Tests for POST /api/oss/debug/sync-fork."""

    @patch(f"{_fork}.OSSService")
    @patch(f"{_fork}.get_authenticated_user", return_value="testuser")
    def test_sync_succeeds(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.sync_fork.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/sync-fork",
            json={"repo": "widget-api"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["synced"] is True


class TestBuildContext:
    """Tests for POST /api/oss/debug/build-context."""

    @patch(f"{_context}.OSSService")
    @patch(f"{_context}.get_authenticated_user", return_value="testuser")
    def test_build_context_returns_markdown(self, mock_user, mock_svc_class, client):
        mock_svc = mock_svc_class.return_value
        mock_svc.get_dossier.return_value = None
        mock_svc.get_issue_brief.return_value = None
        mock_svc.build_agent_context.return_value = ("# Context", {"sources": ["gh-issue-view"]})
        resp = client.post(
            f"{PREFIX}/api/oss/debug/build-context",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 1234,
                "issue_title": "Fix memory leak",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/1234",
            },
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is True
        assert data["context_markdown"] == "# Context"

    @patch(f"{_context}.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/debug/build-context",
            json={"origin_owner": "acme-corp"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is False


class TestCreateContextIssue:
    """Tests for POST /api/oss/debug/create-context-issue."""

    @patch(f"{_context}.run_gh_command")
    @patch(f"{_context}.get_authenticated_user", return_value="testuser")
    def test_create_issue_succeeds(self, mock_user, mock_gh, client):
        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/widget-api/issues/5", "number": 5}',
        }
        resp = client.post(
            f"{PREFIX}/api/oss/debug/create-context-issue",
            json={"repo": "widget-api", "title": "Fix #1234", "body": "Context body"},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["success"] is True
        assert data["issue_number"] == 5


class TestAssignCopilot:
    """Tests for POST /api/oss/debug/assign-copilot."""

    @patch(f"{_assignment}.run_gh_command")
    @patch(f"{_assignment}.get_authenticated_user", return_value="testuser")
    def test_assign_succeeds(self, mock_user, mock_gh, client):
        mock_gh.return_value = {"success": True, "output": ""}
        resp = client.post(
            f"{PREFIX}/api/oss/debug/assign-copilot",
            json={"repo": "widget-api", "issue_number": 5},
            content_type="application/json",
        )
        data = resp.get_json()
        assert data["assigned"] is True


# ============ Group C: Scoring & Tracking ============


class TestScoreIssue:
    """Tests for GET /api/oss/debug/score-issue."""

    @patch(f"{_assignment}.run_gh_command")
    @patch(f"{_assignment}.get_authenticated_user", return_value="testuser")
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

    @patch(f"{_assignment}.get_authenticated_user", return_value="testuser")
    def test_missing_params(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/score-issue?owner=org")
        data = resp.get_json()
        assert data["success"] is False


class TestForkPRStatus:
    """Tests for GET /api/oss/debug/fork-pr-status."""

    @patch(f"{_tracking}.run_gh_command")
    @patch(f"{_tracking}.get_authenticated_user", return_value="testuser")
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

    @patch(f"{_tracking}.OSSService")
    @patch(f"{_tracking}.run_gh_command")
    @patch(f"{_tracking}.get_authenticated_user", return_value="testuser")
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

    @patch(f"{_tracking}.get_authenticated_user", return_value="testuser")
    def test_missing_pr_url(self, mock_user, client):
        resp = client.get(f"{PREFIX}/api/oss/debug/poll-submitted-pr")
        data = resp.get_json()
        assert data["success"] is False


class TestNotificationPreview:
    """Tests for GET /api/oss/debug/notification-preview."""

    @patch(f"{_tracking}.OSSService")
    @patch(f"{_tracking}.get_authenticated_user", return_value="testuser")
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
