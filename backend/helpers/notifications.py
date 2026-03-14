"""
Discord notification helpers for key OSS pipeline events.

Best-effort — all functions silently no-op when DISCORD_WEBHOOK_URL is unset
or when the request fails.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# Colors for Discord embeds
COLOR_SUCCESS = 0x2ECC71  # Green
COLOR_INFO = 0x3498DB     # Blue
COLOR_WARNING = 0xF39C12  # Orange
COLOR_ERROR = 0xE74C3C    # Red


def _issue_url(origin_slug, issue_number):
    """Build a GitHub issue URL, or None if data is missing/invalid."""
    if not origin_slug or not issue_number:
        return None
    return f"https://github.com/{origin_slug}/issues/{issue_number}"


def _field(name, value, inline=False):
    """Build a Discord embed field, skipping empty/None values."""
    if not value:
        return None
    return {"name": name, "value": str(value), "inline": inline}


def send_discord_notification(title, description, color=None, fields=None):
    """Send a Discord webhook notification with an embed."""
    if not DISCORD_WEBHOOK_URL:
        return

    embed = {
        "title": title,
        "description": description,
        "color": color or COLOR_INFO,
    }
    if fields:
        # Filter out None entries from _field() calls
        embed["fields"] = [f for f in fields if f]

    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=5,
        )
    except Exception as e:
        logger.debug("Discord notification failed: %s", e)


# --- Stage 3: Dispatched ---

def notify_dispatched(origin_slug, issue_number, issue_title, fork_issue_url, context_tier):
    """Notify when an issue is dispatched (forked + Copilot assigned)."""
    issue_link = _issue_url(origin_slug, issue_number)
    send_discord_notification(
        title="Dispatched",
        description=f"[{origin_slug}#{issue_number}]({issue_link}): {issue_title}" if issue_link
                    else f"{origin_slug} #{issue_number}: {issue_title}",
        color=COLOR_INFO,
        fields=[
            _field("Fork Issue", fork_issue_url),
            _field("Context Tier", context_tier, inline=True),
        ],
    )


# --- Stage 4: Copilot PR ready ---

def notify_copilot_pr_ready(origin_slug, issue_number, fork_pr_url, pr_title):
    """Notify when Copilot has created a PR on the fork."""
    issue_link = _issue_url(origin_slug, issue_number)
    send_discord_notification(
        title="Copilot PR Ready",
        description=f"[{origin_slug}#{issue_number}]({issue_link})" if issue_link
                    else f"{origin_slug} #{issue_number}",
        color=COLOR_INFO,
        fields=[
            _field("Fork PR", fork_pr_url),
        ],
    )


# --- Stage 4.5: Merged & sanitized on fork ---

def notify_fork_merged(origin_slug, issue_number, pr_title, clean_branch):
    """Notify when a fork PR is merged and sanitized."""
    issue_link = _issue_url(origin_slug, issue_number)
    send_discord_notification(
        title="Fork PR Merged",
        description=f"[{origin_slug}#{issue_number}]({issue_link}): {pr_title}" if issue_link
                    else f"{origin_slug}: {pr_title}",
        color=COLOR_SUCCESS,
        fields=[
            _field("Clean Branch", f"`{clean_branch}`", inline=True),
        ],
    )


# --- Stage 5: Submitted upstream ---

def notify_upstream_submitted(origin_slug, issue_number, pr_url, pr_title):
    """Notify when a PR is submitted to the upstream repo."""
    issue_link = _issue_url(origin_slug, issue_number)
    send_discord_notification(
        title="Upstream PR Submitted",
        description=f"[{origin_slug}#{issue_number}]({issue_link}): {pr_title}" if issue_link
                    else f"{origin_slug}: {pr_title}",
        color=COLOR_INFO,
        fields=[
            _field("PR", pr_url),
        ],
    )


def notify_upstream_merged(origin_slug, pr_url, title):
    """Notify when a submitted PR is merged upstream."""
    send_discord_notification(
        title="Upstream PR Merged!",
        description=f"**{origin_slug}**: {title}",
        color=COLOR_SUCCESS,
        fields=[
            _field("PR", pr_url),
        ],
    )


def notify_upstream_feedback(origin_slug, pr_url, review_decision):
    """Notify when a submitted PR receives actionable review feedback."""
    send_discord_notification(
        title="Upstream PR: Changes Requested",
        description=f"**{origin_slug}**",
        color=COLOR_WARNING,
        fields=[
            _field("PR", pr_url),
        ],
    )


def notify_upstream_closed(origin_slug, pr_url, title):
    """Notify when a submitted PR is closed (not merged)."""
    send_discord_notification(
        title="Upstream PR Closed",
        description=f"**{origin_slug}**: {title}",
        color=COLOR_ERROR,
        fields=[
            _field("PR", pr_url),
        ],
    )
