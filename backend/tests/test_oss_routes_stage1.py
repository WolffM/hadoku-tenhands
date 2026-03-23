"""Tests for OSS routes — Stage 1: Target Repos."""

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


PREFIX = "/dispatch"


# ============ Stage 1: Target Repos ============


class TestDispatchedReposEndpoint:
    """Tests for GET /api/oss/dispatched-repos."""

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_returns_dispatched_list(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dispatched_repos.return_value = [
            {"origin_slug": "fastify/fastify", "aggregator_slug": "fastify-fastify",
             "dispatch_count": 2},
        ]

        resp = client.get(f"{PREFIX}/api/oss/dispatched-repos")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["dispatched_repos"]) == 1
        assert data["dispatched_repos"][0]["origin_slug"] == "fastify/fastify"
        assert data["owner"] == "testuser"

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_returns_empty_list_when_none_dispatched(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dispatched_repos.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/dispatched-repos")
        data = resp.get_json()

        assert data["success"] is True
        assert data["dispatched_repos"] == []


class TestStage1AlreadyDispatched:
    """Tests for already_dispatched flag in stage1 targets."""

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_true_for_matching_slug(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "fastify-fastify"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = [
            {"aggregator_slug": "fastify-fastify"},
        ]

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        target = next(t for t in data["targets"] if t["slug"] == "fastify-fastify")
        assert target["already_dispatched"] is True

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_false_for_unmatched_slug(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "vercel-next.js"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = [
            {"aggregator_slug": "fastify-fastify"},
        ]

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        target = next(t for t in data["targets"] if t["slug"] == "vercel-next.js")
        assert target["already_dispatched"] is False

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_false_when_no_dispatches(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "fastify-fastify"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        target = data["targets"][0]
        assert target["already_dispatched"] is False


class TestRefreshTarget:
    """Tests for POST /api/oss/refresh-target."""

    @patch("routes.oss_routes_stage1.clear_cache")
    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_refresh_converts_slash_to_hyphen(self, mock_svc_cls, mock_user, mock_cache, client):
        """Tests the slug.replace('/', '-') conversion logic."""
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.trigger_refresh.assert_called_once_with("fastify-fastify")
