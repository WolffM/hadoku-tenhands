"""Watcher activities — Phase 1C.9 + Phase 5.1.

Two activities live here:

1. `notify_human_comments_for_issue` — polls the upstream PR's *issue*
   comment timeline, filters bots, fires Discord on each new human
   comment and appends to events.jsonl. Side-effect only; does NOT
   change workflow state.

2. `watch_upstream_pr_state` — Phase 5.1. Polls upstream PR state +
   reviews. Drives the post-submission state machine: merged,
   closed_by_upstream, or remediating_upstream when a maintainer
   leaves a CHANGES_REQUESTED (blocking) review. Writes terminal
   evidence (`11-merged/` or `11-closed_by_upstream/`) when the
   upstream PR reaches a final state.

Both are designed to be called on a poll cadence from
IssueWorkflow.run after the workflow reaches `submitted`.
"""

from __future__ import annotations

import json as _json
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


# ── Phase 5.1: post-submission lifecycle watcher ──────────────────────────


def _default_heartbeat(detail: str) -> None:
    """Best-effort heartbeat — quietly no-op outside an activity context."""
    try:
        from temporalio import activity  # type: ignore
        activity.heartbeat(detail)
    except Exception:
        pass


def watch_upstream_pr_state(
    upstream_slug: str,
    pr_number: int,
    seen_review_ids: list[int] | set[int],
    evidence,
    *,
    run_gh=None,
    is_bot=None,
    notify=None,
    heartbeat=None,
) -> dict:
    """One poll cycle against the upstream PR.

    Returns a dict with all the fields the workflow's poll loop needs to
    drive the post-submission state machine:

    ```
    {
        "ok": bool,                    # poll succeeded; transient gh failures → ok=False
        "state": "open" | "closed",
        "merged": bool,
        "merged_at": str | None,
        "merge_sha": str | None,
        "closed_at": str | None,
        "closer": str | None,
        "closed_unmerged": bool,       # closed but NOT merged → terminal failure
        "new_blocking_review": bool,
        "new_blocking_review_id": int | None,
        "new_blocking_review_user": str | None,
        "new_blocking_review_body": str | None,
        "all_seen_review_ids": list[int],
        "error": str | None,           # populated when ok=False
    }
    ```

    "Blocking" = a `CHANGES_REQUESTED` review from a non-bot user that we
    haven't seen before. `COMMENTED` and `APPROVED` reviews are tracked
    in `all_seen_review_ids` so future polls don't re-flag them, but they
    do not trigger the remediation branch. (Plain inline review comments
    that arrive without a top-level review are picked up by
    `notify_human_comments_for_issue` and surface to the operator via
    Discord.)

    On terminal states (merged or closed_unmerged), this activity writes
    `11-merged/` or `11-closed_by_upstream/` evidence files so the retro
    tool can pick up the outcome without re-querying GitHub.

    Transient failures (network blip, gh 5xx, rate limit) return
    `ok=False` with an error string. The workflow's poll loop treats
    that as "no new info, sleep and retry next cycle" — it does NOT
    abort the workflow.
    """
    if run_gh is None:
        run_gh = _default_run_gh
    if is_bot is None:
        is_bot = _default_is_bot
    if notify is None:
        notify = _default_notify
    if heartbeat is None:
        heartbeat = _default_heartbeat

    heartbeat(f"watch {upstream_slug}#{pr_number}")

    seen = {int(x) for x in (seen_review_ids or [])}
    base: dict[str, Any] = {
        "ok": False,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "merge_sha": None,
        "closed_at": None,
        "closer": None,
        "closed_unmerged": False,
        "new_blocking_review": False,
        "new_blocking_review_id": None,
        "new_blocking_review_user": None,
        "new_blocking_review_body": None,
        "all_seen_review_ids": sorted(seen),
        "error": None,
    }

    # ── PR detail ────────────────────────────────────────────────────────
    pr_fetch = run_gh([
        "api",
        f"repos/{upstream_slug}/pulls/{pr_number}",
        "--jq",
        '{state: .state, merged: .merged, merged_at: .merged_at, '
        'merge_commit_sha: .merge_commit_sha, closed_at: .closed_at, '
        'merged_by: (.merged_by.login // null), '
        'closed_by_login: (.user.login // null)}',
    ])
    if not pr_fetch.get("success"):
        base["error"] = f"pr fetch: {pr_fetch.get('error', '')}"
        return base
    try:
        pr_data = _json.loads(pr_fetch.get("output", "") or "{}")
    except (ValueError, TypeError):
        base["error"] = "pr fetch: invalid JSON"
        return base

    state = (pr_data.get("state") or "open").lower()
    merged = bool(pr_data.get("merged"))
    merged_at = pr_data.get("merged_at")
    merge_sha = pr_data.get("merge_commit_sha")
    closed_at = pr_data.get("closed_at")

    base["state"] = state
    base["merged"] = merged
    base["merged_at"] = merged_at
    base["merge_sha"] = merge_sha
    base["closed_at"] = closed_at

    # ── Reviews ─────────────────────────────────────────────────────────
    reviews_fetch = run_gh([
        "api",
        f"repos/{upstream_slug}/pulls/{pr_number}/reviews?per_page=100",
        "--jq",
        '[.[] | {id: .id, user: (.user.login // ""), state: .state, '
        'body: .body, submitted_at: .submitted_at}]',
    ])
    if not reviews_fetch.get("success"):
        # PR fetch worked, reviews didn't — treat as transient. Don't
        # short-circuit the merged/closed handling, but flag the error.
        base["error"] = f"reviews fetch: {reviews_fetch.get('error', '')}"
        # fall through with no review changes
        reviews: list[dict] = []
    else:
        try:
            reviews = _json.loads(reviews_fetch.get("output", "") or "[]") or []
        except (ValueError, TypeError):
            reviews = []

    new_blocking: dict | None = None
    for rv in reviews:
        rid = rv.get("id")
        if rid is None:
            continue
        rid = int(rid)
        if rid in seen:
            continue
        seen.add(rid)
        rstate = (rv.get("state") or "").upper()
        login = rv.get("user") or ""
        if rstate == "CHANGES_REQUESTED" and not is_bot(login):
            if new_blocking is None:
                new_blocking = {
                    "id": rid,
                    "user": login,
                    "body": rv.get("body") or "",
                    "submitted_at": rv.get("submitted_at"),
                }
            evidence.append_jsonl("events.jsonl", {
                "event": "blocking_review",
                "upstream_slug": upstream_slug,
                "pr_number": pr_number,
                "review_id": rid,
                "user": login,
                "submitted_at": rv.get("submitted_at"),
                "body_excerpt": (rv.get("body") or "")[:300],
            })

    base["all_seen_review_ids"] = sorted(seen)

    if new_blocking is not None:
        base["new_blocking_review"] = True
        base["new_blocking_review_id"] = new_blocking["id"]
        base["new_blocking_review_user"] = new_blocking["user"]
        base["new_blocking_review_body"] = new_blocking["body"]
        # Discord: only blocking severity (Phase 5.1 open-question call —
        # see docs). Plain comments still notify via the sibling activity.
        try:
            notify(
                f"[crimson-kitty] BLOCKING review on {upstream_slug}#{pr_number} "
                f"from {new_blocking['user']}: "
                f"{(new_blocking['body'] or '')[:160]}"
            )
        except Exception:
            pass

    # ── Terminal evidence ───────────────────────────────────────────────
    if merged:
        evidence.write_json("11-merged/merge_info.json", {
            "merge_sha": merge_sha or "",
            "merged_at": merged_at or "",
            "merged_by": pr_data.get("merged_by") or "",
            "upstream_slug": upstream_slug,
            "pr_number": pr_number,
        })
        if merge_sha:
            evidence.write_text("11-merged/merge_sha", str(merge_sha))
        if merged_at:
            evidence.write_text("11-merged/merged_at", str(merged_at))
        evidence.append_jsonl("events.jsonl", {
            "event": "upstream_merged",
            "upstream_slug": upstream_slug,
            "pr_number": pr_number,
            "merge_sha": merge_sha,
            "merged_at": merged_at,
        })
    elif state == "closed" and not merged:
        base["closed_unmerged"] = True
        base["closer"] = pr_data.get("closed_by_login")  # best-effort
        evidence.write_json("11-closed_by_upstream/close_info.json", {
            "closed_at": closed_at or "",
            "closer": base["closer"] or "",
            "upstream_slug": upstream_slug,
            "pr_number": pr_number,
        })
        if closed_at:
            evidence.write_text("11-closed_by_upstream/closed_at", str(closed_at))
        evidence.append_jsonl("events.jsonl", {
            "event": "upstream_closed_unmerged",
            "upstream_slug": upstream_slug,
            "pr_number": pr_number,
            "closed_at": closed_at,
        })

    base["ok"] = True
    return base
