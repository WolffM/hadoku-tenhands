"""Tests for Discord notification helpers."""

from unittest.mock import patch

from helpers.notifications import (
    send_discord_notification,
    notify_dispatched,
    notify_copilot_pr_ready,
    notify_fork_merged,
    notify_upstream_submitted,
    notify_upstream_merged,
    notify_upstream_feedback,
    notify_upstream_closed,
    COLOR_SUCCESS,
    COLOR_INFO,
    COLOR_WARNING,
    COLOR_ERROR,
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
    @patch("helpers.notifications.requests.post")
    def test_filters_none_fields(self, mock_post):
        """Fields with None values from _field() should be filtered out."""
        send_discord_notification(
            "Title", "Desc",
            fields=[
                {"name": "Real", "value": "val", "inline": False},
                None,
                {"name": "Also Real", "value": "val2", "inline": False},
            ],
        )

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert len(embed["fields"]) == 2

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post", side_effect=Exception("Connection error"))
    def test_exception_does_not_raise(self, mock_post):
        send_discord_notification("Title", "Desc")
        mock_post.assert_called_once()


class TestNotifyDispatched:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_includes_issue_link_in_description(self, mock_post):
        notify_dispatched("microsoft/terminal", 5301, "Fix tab close", "https://github.com/WolffM/terminal/issues/1", 1)

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "microsoft/terminal#5301" in embed["description"]
        assert "github.com/microsoft/terminal/issues/5301" in embed["description"]
        assert embed["color"] == COLOR_INFO

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_omits_context_tier_when_none(self, mock_post):
        notify_dispatched("org/repo", 1, "Fix", "https://fork/1", None)

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        # Context Tier field should be filtered out (None value)
        tier_fields = [f for f in embed.get("fields", []) if f["name"] == "Context Tier"]
        assert len(tier_fields) == 0


class TestNotifyCopilotPrReady:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_includes_fork_pr_link(self, mock_post):
        notify_copilot_pr_ready("microsoft/terminal", 5301, "https://github.com/WolffM/terminal/pull/2", "Fix tab close")

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Copilot PR Ready" in embed["title"]
        fork_pr_field = next(f for f in embed["fields"] if f["name"] == "Fork PR")
        assert "WolffM/terminal/pull/2" in fork_pr_field["value"]


class TestNotifyUpstreamMerged:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_sends_merged_notification(self, mock_post):
        notify_upstream_merged(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "Fix memory leak",
        )

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Merged" in embed["title"]
        assert "fastify/fastify" in embed["description"]
        assert embed["color"] == COLOR_SUCCESS


class TestNotifyUpstreamFeedback:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_changes_requested_uses_warning_color(self, mock_post):
        notify_upstream_feedback(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "CHANGES_REQUESTED",
        )

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert embed["color"] == COLOR_WARNING
        assert "Changes Requested" in embed["title"]


class TestNotifyUpstreamClosed:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_closed_uses_error_color(self, mock_post):
        notify_upstream_closed(
            "microsoft/pyright",
            "https://github.com/microsoft/pyright/pull/11331",
            "Add debounce setting",
        )

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert embed["color"] == COLOR_ERROR
        assert "Closed" in embed["title"]
        assert "microsoft/pyright" in embed["description"]
