"""Tests for OSS routes — Stage 1 and Stage 2 endpoints."""

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


class TestStage1Targets:
    """Tests for GET /api/oss/stage1-targets."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_returns_empty_when_no_watchlist(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = []
        svc.get_local_watchlist.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        assert data["targets"] == []
        assert data["owner"] == "testuser"

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_local_watchlist_fallback_enriches_via_gh(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = []  # No aggregator
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
    @patch("routes.oss_routes._call_aggregator")
    def test_aggregator_path_returns_health(self, mock_agg, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_watchlist.return_value = ["fastify-fastify"]  # Aggregator available

        mock_agg.return_value = {
            "maintainerHealthScore": 80,
            "mergeAccessibilityScore": 75,
            "availabilityScore": 90,
            "overallViability": 82,
        }

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["targets"]) == 1
        assert data["targets"][0]["health"]["overallViability"] == 82


class TestAddTarget:
    """Tests for POST /api/oss/add-target."""

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_add_valid_repo(self, mock_gh, mock_svc_cls, mock_user, mock_cache, client):
        mock_gh.return_value = {"success": True, "output": "fastify/fastify"}
        svc = mock_svc_cls.return_value

        resp = client.post(
            f"{PREFIX}/api/oss/add-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        svc.add_to_local_watchlist.assert_called_once_with("fastify", "fastify")

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
    def test_add_invalidates_cache(self, mock_gh, mock_svc_cls, mock_user, mock_cache, client):
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
    def test_remove_with_slash_format(self, mock_svc_cls, mock_user, mock_cache, client):
        svc = mock_svc_cls.return_value

        resp = client.post(
            f"{PREFIX}/api/oss/remove-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        svc.remove_from_local_watchlist.assert_called_once_with("fastify", "fastify")

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_remove_with_hyphenated_slug_found(self, mock_svc_cls, mock_user, mock_cache, client):
        svc = mock_svc_cls.return_value
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify"}
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/remove-target",
            json={"slug": "fastify-fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        svc.remove_from_local_watchlist.assert_called_once_with("fastify", "fastify")

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_remove_with_hyphenated_slug_not_found(self, mock_svc_cls, mock_user, client):
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
    def test_refresh_returns_success(self, mock_svc_cls, mock_user, mock_cache, client):
        resp = client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "message" in data

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_refresh_invalidates_cache(self, mock_svc_cls, mock_user, mock_cache, client):
        client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        mock_cache.assert_any_call("oss-stage1-targets")
        mock_cache.assert_any_call("oss-stage2-issues")

    @patch("routes.oss_routes.clear_cache")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_refresh_converts_slash_to_hyphen(self, mock_svc_cls, mock_user, mock_cache, client):
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.trigger_refresh.assert_called_once_with("fastify-fastify")


# ============ Stage 2: Scored Issues ============


class TestStage2Issues:
    """Tests for GET /api/oss/stage2-issues."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_returns_empty_when_no_watchlist(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert data["issues"] == []

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_fetches_and_scores_issues(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []  # No aggregator
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

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_skips_assigned_issues(self, mock_gh, mock_svc_cls, mock_user, client):
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
        assert len(data["issues"]) == 0  # Assigned = skip, filtered out

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_normalizes_labels_to_strings(self, mock_gh, mock_svc_cls, mock_user, client):
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

        issue = data["issues"][0]
        assert issue["labels"] == ["bug", "good first issue"]

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.run_gh_command")
    def test_fallback_sorts_by_cvs_desc(self, mock_gh, mock_svc_cls, mock_user, client):
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
    def test_aggregator_path_returns_directly(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [
            {"id": "agg-1", "cvs": 85, "cvsTier": "go", "repo": "org/repo"}
        ]

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["issues"]) == 1
        assert data["issues"][0]["id"] == "agg-1"


# ============ Dossier ============


class TestDossier:
    """Tests for GET /api/oss/dossier/<slug>."""

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_dossier_returns_null_when_no_aggregator(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = None

        resp = client.get(f"{PREFIX}/api/oss/dossier/fastify-fastify")
        data = resp.get_json()

        assert data["success"] is True
        assert data["dossier"] is None

    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes.OSSService")
    def test_dossier_returns_data_from_aggregator(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = {
            "slug": "fastify-fastify",
            "sections": {"overview": "A fast framework"},
        }

        resp = client.get(f"{PREFIX}/api/oss/dossier/fastify-fastify")
        data = resp.get_json()

        assert data["success"] is True
        assert data["dossier"]["slug"] == "fastify-fastify"
        assert data["dossier"]["sections"]["overview"] == "A fast framework"
