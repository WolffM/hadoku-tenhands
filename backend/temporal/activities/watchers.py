"""Watcher activities — Phase 1C.9.

Wraps the existing `helpers/notifications.py` Discord helpers as a
Temporal activity. The watcher polls the upstream PR for new human
comments (via `helpers/bot_filter.is_bot`) and emits a Discord alert
on each new one.

The watcher does NOT change workflow state — it's a side-effect
activity that runs concurrently with the `submitted` state and exits
when the workflow reaches a terminal state.
"""

from __future__ import annotations

from typing import Any


def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


def _default_notify(message: str) -> None:
    from helpers.notifications import notify_human_comment  # type: ignore
    notify_human_comment(message)


def _default_is_bot(login: str) -> bool:
    from helpers.bot_filter import is_bot  # type: ignore
    return is_bot(login)


def notify_human_comments_for_issue(
    upstream_slug: str,
    pr_number: int,
    seen_comment_ids: set[int],
    evidence,
    *,
    run_gh=None,
    notify=None,
    is_bot=None,
) -> dict:
    """Poll the upstream PR for new human comments since the last call.

    `seen_comment_ids` is the set of comment IDs already reported. The
    activity returns the updated set so the orchestrator can pass it
    back on the next invocation. Bot comments (Copilot, dependabot,
    GitHub-actions, etc.) are filtered out via the existing bot_filter.

    Each new human comment fires one Discord notification AND appends one
    record to `events.jsonl` for retro reporting.
    """
    if run_gh is None:
        run_gh = _default_run_gh
    if notify is None:
        notify = _default_notify
    if is_bot is None:
        is_bot = _default_is_bot

    fetch = run_gh([
        "api",
        f"repos/{upstream_slug}/issues/{pr_number}/comments?per_page=100",
        "--jq",
        '[.[] | {id: .id, user: .user.login, body: .body, created_at: .created_at}]',
    ])
    if not fetch.get("success"):
        return {"ok": False, "error": fetch.get("error", ""), "new_count": 0}

    import json
    try:
        comments = json.loads(fetch["output"])
    except (ValueError, TypeError):
        comments = []

    new_count = 0
    new_seen = set(seen_comment_ids)
    for c in comments:
        cid = c.get("id")
        if cid in new_seen:
            continue
        login = c.get("user", "") or ""
        if is_bot(login):
            continue
        new_seen.add(cid)
        new_count += 1

        notify(
            f"[crimson-kitty] new comment on {upstream_slug}#{pr_number} from "
            f"{login}: {(c.get('body') or '')[:160]}"
        )
        evidence.append_jsonl("events.jsonl", {
            "event": "human_comment",
            "upstream_slug": upstream_slug,
            "pr_number": pr_number,
            "comment_id": cid,
            "user": login,
            "created_at": c.get("created_at"),
            "body_excerpt": (c.get("body") or "")[:300],
        })

    return {"ok": True, "new_count": new_count, "seen_ids": list(new_seen)}
