"""
Integration tests — verify the full route → notification → webhook flow.

Unlike unit tests that mock notification functions at the route level,
these tests let the real notification code run and instead mock at the
HTTP boundary (requests.post) to verify Discord webhook payloads.
"""

import json
from unittest.mock import patch

import pytest

from app import app
from extensions import limiter


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c
    limiter.enabled = True


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    """Disable caching for all integration tests."""
    monkeypatch.setenv("CACHE_DISABLED", "1")




PREFIX = "/tenhands"


class TestPollSubmittedPRsIntegration:
    """
    Integration: hit poll-submitted-prs endpoint, let the full notification
    chain run (route handler → notify_*() → send_discord_notification() →
    requests.post()), and verify the Discord webhook payload.
    """

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_poll_detects_merge_and_sends_discord_notification(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "acme-corp/widget-api",
            "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
            "pr_number": 100,
            "title": "Fix memory leak",
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

        resp = client.post(
            f"{PREFIX}/api/oss/poll-submitted-prs",
            json={}, content_type="application/json"
        )
        data = resp.get_json()

        # Route response is correct
        assert data["success"] is True
        assert data["submitted"][0]["state"] == "merged"

        # Only merge notification fires (APPROVED does not trigger feedback)
        mock_discord_post.assert_called_once()
        payload = mock_discord_post.call_args.kwargs.get("json") or mock_discord_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Merged" in embed["title"]
        assert "acme-corp/widget-api" in embed["description"]
        assert embed["color"] == 0x2ECC71  # COLOR_SUCCESS

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_poll_detects_review_feedback_and_sends_notification(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
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

        client.post(
            f"{PREFIX}/api/oss/poll-submitted-prs",
            json={}, content_type="application/json"
        )

        mock_discord_post.assert_called_once()
        call_kwargs = mock_discord_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert "Changes Requested" in embed["title"]
        assert embed["color"] == 0xF39C12  # COLOR_WARNING

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_no_notification_when_state_unchanged(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "acme-corp/widget-api",
            "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
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
                "state": "OPEN",
                "reviewDecision": None,
                "mergedAt": None,
                "closedAt": None,
            })
        }

        client.post(
            f"{PREFIX}/api/oss/poll-submitted-prs",
            json={}, content_type="application/json"
        )

        mock_discord_post.assert_not_called()

    @patch("helpers.notifications.requests.post")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_no_notification_when_webhook_url_empty(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        with patch("helpers.notifications.DISCORD_WEBHOOK_URL", ""):
            svc = mock_svc_cls.return_value
            svc.get_submitted_prs.return_value = [{
                "origin_slug": "acme-corp/widget-api",
                "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
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

            client.post(
                f"{PREFIX}/api/oss/poll-submitted-prs",
                json={}, content_type="application/json"
            )

            mock_discord_post.assert_not_called()

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_multiple_prs_produce_separate_notifications(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [
            {
                "origin_slug": "acme-corp/widget-api",
                "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
                "pr_number": 100,
                "title": "Fix memory leak",
                "state": "open",
                "review_decision": None,
                "merged_at": None,
                "closed_at": None,
                "last_polled_at": None,
                "submitted_at": "2026-02-18T00:00:00Z",
            },
            {
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
            },
        ]

        mock_gh.side_effect = [
            {
                "success": True,
                "output": json.dumps({
                    "state": "MERGED",
                    "reviewDecision": "APPROVED",
                    "mergedAt": "2026-02-19T12:00:00Z",
                    "closedAt": None,
                })
            },
            {
                "success": True,
                "output": json.dumps({
                    "state": "OPEN",
                    "reviewDecision": "APPROVED",
                    "mergedAt": None,
                    "closedAt": None,
                })
            },
        ]

        client.post(
            f"{PREFIX}/api/oss/poll-submitted-prs",
            json={}, content_type="application/json"
        )

        # PR1 (merged) fires merge notification only. PR2 (APPROVED) fires nothing.
        mock_discord_post.assert_called_once()
        payload = mock_discord_post.call_args.kwargs.get("json") or mock_discord_post.call_args[1].get("json")
        assert "Merged" in payload["embeds"][0]["title"]

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes_stage5.run_gh_command")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_poll_detects_close_and_sends_notification(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "acme-corp/widget-api",
            "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
            "pr_number": 100,
            "title": "Fix memory leak",
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
                "state": "CLOSED",
                "reviewDecision": None,
                "mergedAt": None,
                "closedAt": "2026-02-19T12:00:00Z",
            })
        }

        client.post(
            f"{PREFIX}/api/oss/poll-submitted-prs",
            json={}, content_type="application/json"
        )

        mock_discord_post.assert_called_once()
        payload = mock_discord_post.call_args.kwargs.get("json") or mock_discord_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Closed" in embed["title"]
        assert embed["color"] == 0xE74C3C  # COLOR_ERROR


