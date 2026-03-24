"""Bot filter — exclude bot comments from human comment threads.

Raw comment data is always saved unfiltered at pipeline time.
Filtering happens at render time so adding new bots doesn't require re-fetching.
"""

BOT_LOGINS: set = {
    "copilot-swe-agent",
    "app/copilot-swe-agent",
    "github-actions[bot]",
    "dependabot[bot]",
    "coderabbitai[bot]",
    "renovate[bot]",
    "codecov[bot]",
    "snyk-bot",
    "vercel[bot]",
    "netlify[bot]",
    "sonarqubebot",
    "deepsource-autofix[bot]",
    "stale[bot]",
    "allcontributors[bot]",
    "imgbot[bot]",
    "whitesource-bolt-for-github[bot]",
}


def is_bot(login: str) -> bool:
    """Return True if the login belongs to a known bot."""
    if not login:
        return False
    lower = login.lower()
    return lower in BOT_LOGINS or lower.endswith("[bot]")


def filter_human_comments(comments: list) -> list:
    """Return only comments whose author is not a bot."""
    return [c for c in comments if not is_bot(c.get("author", ""))]
