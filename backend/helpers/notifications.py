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
DISCORD_TEST_WEBHOOK_URL = os.environ.get("DISCORD_TEST_WEBHOOK_URL", "")

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


def notify_upstream_comment(origin_slug, pr_url, author, comment_body):
    """Notify when a human comments on a submitted upstream PR."""
    snippet = comment_body[:1000] + ("…" if len(comment_body) > 1000 else "")
    send_discord_notification(
        title="Upstream PR: New Comment",
        description=f"**@{author}** on [{origin_slug}]({pr_url})\n\n{snippet}",
        color=COLOR_INFO,
    )


def notify_upstream_feedback(origin_slug, pr_url, review_decision):
    """Notify when a submitted PR receives a formal review decision (changes requested)."""
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


# --- Phase 5: Inbox + watcher notifications ---

def notify_inbox_queue(message):
    """Notify when a workflow enqueues an entry to the operator inbox.

    Fires for both judge defers (relevance, submission_judge) and for
    operator_signoff entries (pipeline ready to ship upstream PR).
    Distinguishes the two visually so the operator can triage from the
    Discord channel — operator_signoff = "all gates passed, your call",
    judge defer = "judge wasn't sure, please decide".

    Caller passes a pre-formatted string from
    `temporal/activities/inbox.py:enqueue_for_human_review`.
    """
    if "operator_signoff" in message:
        title = "Inbox: Awaiting Signoff"
        color = COLOR_INFO
    elif "submission_judge" in message or "relevance" in message:
        title = "Inbox: Judge Defer"
        color = COLOR_WARNING
    else:
        title = "Inbox"
        color = COLOR_INFO
    send_discord_notification(
        title=title,
        description=message,
        color=color,
    )


def notify_human_comment(message):
    """Notify when a human comment or blocking review lands on an upstream PR.

    Phase 5.1: called as a side effect of `notify_human_comments_for_issue`
    (regular comments) and `watch_upstream_pr_state` (blocking reviews).
    Caller pre-formats the message; this routes to Discord.

    Distinguishes blocking reviews from comments — blocking reviews
    require operator action (route to remediation), comments are FYI.
    """
    if "BLOCKING" in message:
        title = "Upstream: Blocking Review"
        color = COLOR_WARNING
    else:
        title = "Upstream: New Comment"
        color = COLOR_INFO
    send_discord_notification(
        title=title,
        description=message,
        color=color,
    )
