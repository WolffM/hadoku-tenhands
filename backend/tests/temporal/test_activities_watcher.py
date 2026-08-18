"""the upstream-PR watcher activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

def test_watch_upstream_pr_state_open_no_changes(ev):
    """Healthy poll on an open PR with no new reviews: ok=True, no
    terminal flags, all_seen_review_ids unchanged."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh,
        is_bot=lambda l: False,
        notify=lambda m: None,
    )
    assert result["ok"] is True
    assert result["state"] == "open"
    assert result["merged"] is False
    assert result["closed_unmerged"] is False
    assert result["new_blocking_review"] is False
    assert result["all_seen_review_ids"] == []


def test_watch_upstream_pr_state_detects_merged(ev):
    """A merged PR returns merged=True with merge_sha + writes 11-merged/."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "closed", "merged": True,
                    "merged_at": "2026-04-26T12:00:00Z",
                    "merge_commit_sha": "abc1234deadbeef",
                    "closed_at": None,
                    "merged_by": "maintainer",
                    "closed_by_login": "operator",
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["merged"] is True
    assert result["merge_sha"] == "abc1234deadbeef"
    assert result["closed_unmerged"] is False
    # Terminal evidence written
    assert ev.exists("11-merged/merge_info.json")
    assert ev.read_text("11-merged/merge_sha") == "abc1234deadbeef"
    info = ev.read_json("11-merged/merge_info.json")
    assert info["merge_sha"] == "abc1234deadbeef"
    assert info["pr_number"] == 9


def test_watch_upstream_pr_state_detects_closed_unmerged(ev):
    """A closed-without-merge PR returns closed_unmerged=True + writes
    11-closed_by_upstream/."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "closed", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": "2026-04-26T13:00:00Z",
                    "merged_by": None,
                    "closed_by_login": "grumpy-maintainer",
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["closed_unmerged"] is True
    assert result["merged"] is False
    assert ev.exists("11-closed_by_upstream/close_info.json")
    info = ev.read_json("11-closed_by_upstream/close_info.json")
    assert info["closed_at"] == "2026-04-26T13:00:00Z"


def test_watch_upstream_pr_state_flags_new_blocking_review(ev):
    """A new CHANGES_REQUESTED review from a non-bot user → new_blocking_review=True."""
    from temporal.activities.watchers import watch_upstream_pr_state

    notifications: list[str] = []

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {
                "success": True,
                "output": json.dumps([
                    {"id": 100, "user": "bot[bot]", "state": "CHANGES_REQUESTED",
                     "body": "auto-flagged", "submitted_at": "2026-04-26T10:00Z"},
                    {"id": 200, "user": "alice", "state": "COMMENTED",
                     "body": "looks good", "submitted_at": "2026-04-26T10:30Z"},
                    {"id": 300, "user": "bob", "state": "CHANGES_REQUESTED",
                     "body": "needs work on src/x.py", "submitted_at": "2026-04-26T11:00Z"},
                ]),
            }
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh,
        is_bot=lambda l: "[bot]" in l.lower(),
        notify=lambda m: notifications.append(m),
    )
    # Bob's CHANGES_REQUESTED is the blocking one (bot's filtered out, alice is COMMENTED)
    assert result["new_blocking_review"] is True
    assert result["new_blocking_review_id"] == 300
    assert result["new_blocking_review_user"] == "bob"
    # all_seen_review_ids includes both new ids (bot, alice, bob)
    assert set(result["all_seen_review_ids"]) == {100, 200, 300}
    # Discord notification fired with blocking-review marker
    assert len(notifications) == 1
    assert "BLOCKING" in notifications[0]


def test_watch_upstream_pr_state_dedupes_seen_reviews(ev):
    """Reviews already in seen_review_ids don't re-fire."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {
                "success": True,
                "output": json.dumps([
                    {"id": 300, "user": "bob", "state": "CHANGES_REQUESTED",
                     "body": "needs work", "submitted_at": "2026-04-26T11:00Z"},
                ]),
            }
        raise AssertionError(f"unexpected gh call: {args}")

    # 300 was already seen — shouldn't re-fire
    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [300], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["new_blocking_review"] is False
    assert result["all_seen_review_ids"] == [300]


def test_watch_upstream_pr_state_returns_ok_false_on_pr_fetch_failure(ev):
    """Transient gh failure → ok=False, error populated, no terminal flags."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "503 service unavailable"}

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["ok"] is False
    assert "503" in (result["error"] or "")
    assert result["merged"] is False
    assert result["closed_unmerged"] is False
    assert result["new_blocking_review"] is False
