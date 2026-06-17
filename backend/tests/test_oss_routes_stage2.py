"""Tests for OSS routes — Stage 2: Scored Issues."""

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


PREFIX = "/tenhands"


# ============ Stage 2: Scored Issues ============


class TestStage2Issues:
    """Tests for GET /api/oss/stage2-issues."""

    @patch("routes.oss_routes_stage2.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage2.OSSService")
    def test_returns_empty_when_aggregator_unavailable(self, mock_svc_cls, mock_user, client):
        """When aggregator returns no issues, route returns empty list."""
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = ([], None)

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert data["issues"] == []
