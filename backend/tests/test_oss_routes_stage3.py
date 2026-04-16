"""Tests for OSS routes — Stage 3: Fork & Assign."""

import json
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


def _fork_assign_gh_mock(
    issue_output='{"html_url": "https://github.com/testuser/widget-api/issues/1", "number": 1}\n',
):
    """Build a run_gh_command side_effect for fork-and-assign tests.

    Returns proper numeric responses for the preflight checks (size, rate limit),
    "false" for the Copilot firewall variable (so the check passes immediately),
    and the given issue_output for all other calls.
    """
    def side_effect(cmd, **kw):
        jq = next((cmd[i + 1] for i, c in enumerate(cmd) if c == "--jq"), None)
        if jq == ".size":
            return {"success": True, "output": "1000\n"}  # 1MB — under limit
        if jq == ".resources.core.remaining":
            return {"success": True, "output": "5000\n"}  # plenty of calls
        if jq == ".value" and any("COPILOT_AGENT_FIREWALL_ENABLED" in str(c) for c in cmd):
            return {"success": True, "output": "false\n"}  # firewall disabled
        return {"success": True, "output": issue_output}
    return side_effect


PREFIX = "/dispatch"


# ============ Stage 3: Fork & Assign ============


class TestSelectIssue:
    """Tests for POST /api/oss/select-issue."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_select_issue_already_selected_returns_flag(self, mock_svc_cls, mock_user, client):
        """Tests the dedup branch — different response shape when already selected."""
        svc = mock_svc_cls.return_value
        svc.find_selected_issue.return_value = {"origin_slug": "acme-corp/widget-api", "issue_number": 42}

        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_selected"] is True
        svc.select_issue.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    def test_select_issue_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={"origin_owner": "acme-corp"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()


class TestForkAndAssign:
    """Tests for POST /api/oss/fork-and-assign."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_dedup_returns_existing_assignment(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/widget-api/issues/1"
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_assigned"] is True
        assert data["fork_issue_url"] == "https://github.com/testuser/widget-api/issues/1"

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={"origin_owner": "acme-corp", "repo": "widget-api"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_fork_creation_failure(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = False
        svc.fork_repo.return_value = {"success": False, "error": "Rate limited"}
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "rate limit" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_fork_timeout(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = False
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "timed out" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_auto_fetches_dossier_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (
            {"slug": "acme-corp-widget-api", "sections": {"contributionRules": "Follow the style guide"}},
            {"scraped_at": "2026-02-24T00:00:00Z"},
        )
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.side_effect = _fork_assign_gh_mock()

        client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )

        svc.get_dossier.assert_called_once_with("acme-corp-widget-api", include_meta=True)
        call_args = svc.build_agent_context.call_args
        assert call_args[0][5] == {"contributionRules": "Follow the style guide"}

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_self_owned_skips_fork_and_sync(self, mock_gh, mock_svc_cls, mock_user, client):
        """When origin_owner == my_user, fork/sync steps are skipped."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.side_effect = _fork_assign_gh_mock(
            '{"html_url": "https://github.com/testuser/myrepo/issues/1", "number": 1}\n'
        )

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "testuser",
                "repo": "myrepo",
                "issue_number": 42,
                "issue_title": "Fix bug",
                "issue_url": "https://github.com/testuser/myrepo/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["is_self_owned"] is True
        # Fork/sync methods should NOT have been called
        svc.check_fork_exists.assert_not_called()
        svc.fork_repo.assert_not_called()
        svc.wait_for_fork.assert_not_called()
        svc.sync_fork.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_third_party_uses_fork_flow(self, mock_gh, mock_svc_cls, mock_user, client):
        """When origin_owner != my_user, the full fork flow runs."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.side_effect = _fork_assign_gh_mock()

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["is_self_owned"] is False
        svc.check_fork_exists.assert_called_once()
        svc.wait_for_fork.assert_called_once()
        svc.sync_fork.assert_called_once()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_response_includes_context_sources(self, mock_gh, mock_svc_cls, mock_user, client):
        """Response should include context_sources from metadata."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = (
            "## Context",
            {"sources": ["gh-issue-view", "gh-contributing-md"]},
        )

        mock_gh.side_effect = _fork_assign_gh_mock()

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "context_sources" in data
        assert "gh-issue-view" in data["context_sources"]
        assert "gh-contributing-md" in data["context_sources"]

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_tracks_dispatched_repo_on_success(self, mock_gh, mock_svc_cls, mock_user, client):
        """Successful dispatch must call track_dispatched_repo with origin_slug."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": []})

        mock_gh.side_effect = _fork_assign_gh_mock()

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )

        assert resp.get_json()["success"] is True
        svc.track_dispatched_repo.assert_called_once_with("acme-corp/widget-api")

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_does_not_track_dispatched_repo_on_dedup(self, mock_svc_cls, mock_user, client):
        """Dedup early-return must NOT call track_dispatched_repo."""
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/widget-api/issues/1"
        }

        client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "acme-corp",
                "repo": "widget-api",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/acme-corp/widget-api/issues/42",
            },
            content_type="application/json",
        )

        svc.track_dispatched_repo.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_dedup_response_includes_is_self_owned(self, mock_svc_cls, mock_user, client):
        """Dedup (already_assigned) response should include is_self_owned."""
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/myrepo/issues/1"
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "testuser",
                "repo": "myrepo",
                "issue_number": 42,
                "issue_title": "Fix bug",
                "issue_url": "https://github.com/testuser/myrepo/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_assigned"] is True
        assert data["is_self_owned"] is True
        assert data["context_sources"] == []


# ============ Rate Limiting ============


class TestRateLimiting:
    """Verify rate limiting works when enabled."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_fork_and_assign_rate_limit(self, mock_gh, mock_svc_cls, mock_user):
        """Hitting fork-and-assign more than 5x/min should return 429."""
        limiter.enabled = True
        try:
            with app.test_client() as client:
                svc = mock_svc_cls.return_value
                svc.find_assignment.return_value = {"fork_issue_url": "https://github.com/testuser/r/issues/1"}
                svc.get_dossier.return_value = (None, None)
                svc.get_issue_brief.return_value = (None, None)

                statuses = []
                for i in range(6):
                    resp = client.post(
                        f"{PREFIX}/api/oss/fork-and-assign",
                        json={
                            "origin_owner": "acme-corp",
                            "repo": "widget-api",
                            "issue_number": i + 1,
                            "issue_title": "Fix",
                            "issue_url": f"https://github.com/acme-corp/widget-api/issues/{i + 1}",
                        },
                        content_type="application/json",
                    )
                    statuses.append(resp.status_code)

                # First 5 should succeed, 6th should be rate-limited
                assert statuses[:5] == [200] * 5
                assert statuses[5] == 429
        finally:
            limiter.enabled = False
