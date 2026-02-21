"""Tests for Discord notification helpers."""

from unittest.mock import patch, MagicMock

import pytest

from helpers.notifications import (
    send_discord_notification,
    notify_go_tier_issue,
    notify_pr_ready_for_review,
    notify_upstream_merged,
    notify_upstream_feedback,
    COLOR_SUCCESS,
    COLOR_INFO,
    COLOR_WARNING,
    COLOR_DANGER,
)


class TestSendDiscordNotification:
    """Tests for the core send_discord_notification function."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "")
    @patch("helpers.notifications.requests.post")
    def test_skips_when_webhook_url_empty(self, mock_post):
        send_discord_notification("Test Title", "Test Description")
        mock_post.assert_not_called()

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_correct_embed_format(self, mock_post):
        send_discord_notification(
            "Test Title",
            "Test Description",
            color=COLOR_SUCCESS,
            fields=[{"name": "Field1", "value": "Value1", "inline": True}],
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")

        assert len(payload["embeds"]) == 1
        embed = payload["embeds"][0]
        assert embed["title"] == "Test Title"
        assert embed["description"] == "Test Description"
        assert embed["color"] == COLOR_SUCCESS
        assert len(embed["fields"]) == 1
        assert embed["fields"][0]["name"] == "Field1"

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_uses_default_color_when_none_provided(self, mock_post):
        send_discord_notification("Title", "Desc")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]
        assert embed["color"] == COLOR_INFO

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_omits_fields_when_none(self, mock_post):
        send_discord_notification("Title", "Desc")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]
        assert "fields" not in embed

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post", side_effect=Exception("Connection error"))
    def test_exception_does_not_raise(self, mock_post):
        # Should silently handle the exception
        send_discord_notification("Title", "Desc")
        mock_post.assert_called_once()

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_to_correct_url_with_timeout(self, mock_post):
        send_discord_notification("Title", "Desc")

        call_args = mock_post.call_args
        assert call_args[0][0] == "https://discord.com/api/webhooks/test"
        assert call_args.kwargs.get("timeout") or call_args[1].get("timeout") == 5


class TestNotifyGoTierIssue:
    """Tests for notify_go_tier_issue."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_go_tier_notification(self, mock_post):
        notify_go_tier_issue("fastify/fastify", 42, "Fix memory leak", 92)

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert "GO-tier" in embed["title"]
        assert "fastify/fastify#42" in embed["description"]
        assert embed["color"] == COLOR_SUCCESS
        assert any(f["value"] == "92" for f in embed["fields"])


class TestNotifyPRReadyForReview:
    """Tests for notify_pr_ready_for_review."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_pr_ready_notification(self, mock_post):
        notify_pr_ready_for_review("my-user/fastify", 7, "Fix memory leak")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert "Ready for Review" in embed["title"]
        assert "my-user/fastify#7" in embed["description"]
        assert embed["color"] == COLOR_INFO


class TestNotifyUpstreamMerged:
    """Tests for notify_upstream_merged."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_merged_notification(self, mock_post):
        notify_upstream_merged(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "Fix memory leak",
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert "Merged" in embed["title"]
        assert "fastify/fastify" in embed["description"]
        assert embed["color"] == COLOR_SUCCESS


class TestNotifyUpstreamFeedback:
    """Tests for notify_upstream_feedback."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_changes_requested_uses_warning_color(self, mock_post):
        notify_upstream_feedback(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "CHANGES_REQUESTED",
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert embed["color"] == COLOR_WARNING
        assert "CHANGES_REQUESTED" in embed["description"]

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_approved_uses_info_color(self, mock_post):
        notify_upstream_feedback(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "APPROVED",
        )

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        embed = payload["embeds"][0]

        assert embed["color"] == COLOR_INFO
