"""
Discord notification helpers for key OSS pipeline events.

Best-effort — all functions silently no-op when DISCORD_WEBHOOK_URL is unset
or when the request fails.
"""

import os
import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Colors for Discord embeds
COLOR_SUCCESS = 0x2ECC71  # Green
COLOR_INFO = 0x3498DB     # Blue
COLOR_WARNING = 0xF39C12  # Orange
COLOR_DANGER = 0xE74C3C   # Red


def send_discord_notification(title, description, color=None, fields=None):
    """Send a Discord webhook notification with an embed.

    Args:
        title: Embed title
        description: Embed description text
        color: Embed color (hex int), defaults to COLOR_INFO
        fields: Optional list of {name, value, inline} dicts
    """
    if not DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title": title,
        "description": description,
        "color": color or COLOR_INFO,
    }
    if fields:
        embed["fields"] = fields

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=5,
        )
    except Exception:
        pass  # Best-effort — never fail the caller


def notify_go_tier_issue(repo, issue_number, title, cvs):
    """Notify when a GO-tier issue (CVS >= 85) is discovered."""
    send_discord_notification(
        title="GO-tier Issue Found",
        description=f"**{repo}#{issue_number}**: {title}",
        color=COLOR_SUCCESS,
        fields=[
            {"name": "CVS Score", "value": str(cvs), "inline": True},
            {"name": "Repository", "value": repo, "inline": True},
        ],
    )


def notify_pr_ready_for_review(repo, pr_number, title):
    """Notify when an agent completes a PR on a fork (ready for review)."""
    send_discord_notification(
        title="Agent PR Ready for Review",
        description=f"**{repo}#{pr_number}**: {title}",
        color=COLOR_INFO,
        fields=[
            {"name": "Fork Repo", "value": repo, "inline": True},
            {"name": "PR", "value": f"#{pr_number}", "inline": True},
        ],
    )


def notify_upstream_merged(origin_slug, pr_url, title):
    """Notify when a submitted PR is merged upstream."""
    send_discord_notification(
        title="Upstream PR Merged!",
        description=f"**{origin_slug}**: {title}",
        color=COLOR_SUCCESS,
        fields=[
            {"name": "PR", "value": pr_url, "inline": False},
        ],
    )


def notify_upstream_feedback(origin_slug, pr_url, review_decision):
    """Notify when a submitted PR receives review feedback."""
    color = COLOR_WARNING if review_decision == "CHANGES_REQUESTED" else COLOR_INFO
    send_discord_notification(
        title="Upstream PR Feedback",
        description=f"**{origin_slug}**: Review decision: {review_decision}",
        color=color,
        fields=[
            {"name": "PR", "value": pr_url, "inline": False},
            {"name": "Decision", "value": review_decision or "pending", "inline": True},
        ],
    )
