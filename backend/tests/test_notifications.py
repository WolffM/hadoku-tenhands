"""Tests for Discord notification helpers."""

from unittest.mock import patch

from helpers.notifications import (
    send_discord_notification,
    notify_copilot_pr_ready,
    notify_fork_merged,
    notify_upstream_submitted,
    notify_upstream_merged,
    notify_upstream_feedback,
    notify_upstream_closed,
    notify_inbox_queue,
    notify_human_comment,
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
            "acme-corp/widget-api",
            "https://github.com/acme-corp/widget-api/pull/100",
            "Fix memory leak",
        )

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Merged" in embed["title"]
        assert "acme-corp/widget-api" in embed["description"]
        assert embed["color"] == COLOR_SUCCESS


class TestNotifyUpstreamFeedback:

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_changes_requested_uses_warning_color(self, mock_post):
        notify_upstream_feedback(
            "acme-corp/widget-api",
            "https://github.com/acme-corp/widget-api/pull/100",
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


class TestNotifyInboxQueue:
    """Phase 5 — operator inbox notifications must distinguish judge defers
    from operator_signoff entries so the operator can triage from Discord."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_operator_signoff_uses_signoff_title(self, mock_post):
        notify_inbox_queue(
            "[crimson-kitty] inbox: strapi/strapi#26009 deferred at "
            "awaiting_signoff/operator_signoff — preview PR ready on fork"
        )
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Awaiting Signoff" in embed["title"]
        assert embed["color"] == COLOR_INFO
        assert "strapi/strapi#26009" in embed["description"]

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_submission_judge_defer_uses_judge_title_and_warning_color(self, mock_post):
        notify_inbox_queue(
            "[crimson-kitty] inbox: prisma/prisma#29399 deferred at "
            "submittable/submission_judge — borderline 0.62"
        )
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Judge Defer" in embed["title"]
        assert embed["color"] == COLOR_WARNING

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_relevance_defer_uses_judge_title(self, mock_post):
        notify_inbox_queue(
            "[crimson-kitty] inbox: ollama/ollama#15669 deferred at "
            "fixed/relevance — borderline 0.66"
        )
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Judge Defer" in embed["title"]

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "")
    @patch("helpers.notifications.requests.post")
    def test_skips_when_webhook_url_empty(self, mock_post):
        notify_inbox_queue("[crimson-kitty] inbox: x/y#1 deferred at z/operator_signoff — ok")
        mock_post.assert_not_called()


class TestNotifyHumanComment:
    """Phase 5.1 — upstream human comments + blocking reviews route here.
    Blocking reviews need visual urgency."""

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_blocking_review_uses_warning_color(self, mock_post):
        notify_human_comment(
            "[crimson-kitty] BLOCKING review on prisma/prisma#28901 from "
            "alice: please fix the schema migration"
        )
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "Blocking Review" in embed["title"]
        assert embed["color"] == COLOR_WARNING

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/test")
    @patch("helpers.notifications.requests.post")
    def test_regular_comment_uses_info_color(self, mock_post):
        notify_human_comment(
            "[crimson-kitty] new comment on prisma/prisma#28901 from "
            "alice: thanks for the patch"
        )
        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        embed = payload["embeds"][0]
        assert "New Comment" in embed["title"]
        assert embed["color"] == COLOR_INFO

    @patch("helpers.notifications.DISCORD_WEBHOOK_URL", "")
    @patch("helpers.notifications.requests.post")
    def test_skips_when_webhook_url_empty(self, mock_post):
        notify_human_comment("[crimson-kitty] BLOCKING review on x/y#1 from a: hi")
        mock_post.assert_not_called()
