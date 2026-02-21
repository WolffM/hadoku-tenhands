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


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    """Disable caching for all integration tests."""
    monkeypatch.setenv("CACHE_DISABLED", "1")


@pytest.fixture(autouse=True)
def reset_dedup_sets():
    """Clear module-level dedup sets between tests."""
    from routes.oss_routes import _notified_go_issues
    _notified_go_issues.clear()
    yield
    _notified_go_issues.clear()


PREFIX = "/dispatch"


class TestPollSubmittedPRsIntegration:
    """
    Integration: hit poll-submitted-prs endpoint, let the full notification
    chain run (route handler → notify_*() → send_discord_notification() →
    requests.post()), and verify the Discord webhook payload.
    """

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_poll_detects_merge_and_sends_discord_notification(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "fastify/fastify",
            "pr_url": "https://github.com/fastify/fastify/pull/100",
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

        # Discord webhook was called (merged + feedback for APPROVED review)
        assert mock_discord_post.call_count >= 1

        # Find the merge notification among all calls
        merge_embeds = []
        for c in mock_discord_post.call_args_list:
            webhook_url = c[0][0]
            assert webhook_url == "https://discord.com/api/webhooks/test"
            payload = c.kwargs.get("json") or c[1].get("json")
            embed = payload["embeds"][0]
            if "Merged" in embed["title"]:
                merge_embeds.append(embed)

        assert len(merge_embeds) == 1
        embed = merge_embeds[0]
        assert "fastify/fastify" in embed["description"]
        assert embed["color"] == 0x2ECC71  # COLOR_SUCCESS

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
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

        assert "Feedback" in embed["title"]
        assert "CHANGES_REQUESTED" in embed["description"]
        assert embed["color"] == 0xF39C12  # COLOR_WARNING

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_no_notification_when_state_unchanged(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
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
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_no_notification_when_webhook_url_empty(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        with patch("helpers.notifications.DISCORD_WEBHOOK_URL", ""):
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

            client.post(
                f"{PREFIX}/api/oss/poll-submitted-prs",
                json={}, content_type="application/json"
            )

            mock_discord_post.assert_not_called()

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_multiple_prs_produce_separate_notifications(
        self, _mock_user, mock_svc_cls, mock_gh, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [
            {
                "origin_slug": "fastify/fastify",
                "pr_url": "https://github.com/fastify/fastify/pull/100",
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

        # PR1 (merged+APPROVED) fires merge + feedback, PR2 (APPROVED) fires feedback
        assert mock_discord_post.call_count >= 2

        titles = []
        for c in mock_discord_post.call_args_list:
            payload = c.kwargs.get("json") or c[1].get("json")
            titles.append(payload["embeds"][0]["title"])

        assert any("Merged" in t for t in titles)
        assert any("Feedback" in t for t in titles)


class TestGoTierNotificationIntegration:
    """
    Integration: hit stage2-issues endpoint, let scorer + notification chain
    run, verify Discord webhook payload for GO-tier issues.
    """

    @patch("helpers.notifications.requests.post")
    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("routes.oss_routes.score_issue_fallback")
    @patch("routes.oss_routes.run_gh_command")
    @patch("routes.oss_routes.OSSService")
    @patch("routes.oss_routes.get_authenticated_user", return_value="testuser")
    def test_go_tier_issue_sends_discord_notification(
        self, _mock_user, mock_svc_cls, mock_gh, mock_score, mock_discord_post, client
    ):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = []
        svc.get_local_watchlist.return_value = [
            {"owner": "fastify", "repo": "fastify", "slug": "fastify-fastify"}
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 42,
                "title": "Fix critical bug",
                "url": "https://github.com/fastify/fastify/issues/42",
                "labels": [{"name": "good first issue"}],
                "createdAt": "2026-02-18T00:00:00Z",
                "updatedAt": "2026-02-18T00:00:00Z",
                "comments": 0,
                "assignees": [],
            }])
        }

        mock_score.return_value = {"cvs": 92, "cvsTier": "go", "dataCompleteness": "partial"}

        client.get(f"{PREFIX}/api/oss/stage2-issues")

        mock_discord_post.assert_called_once()
        call_kwargs = mock_discord_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert "GO-tier" in embed["title"]
        assert "fastify/fastify#42" in embed["description"]
        assert embed["color"] == 0x2ECC71
        assert any(f["value"] == "92" for f in embed["fields"])
