"""the human-review inbox activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

def test_notify_human_comments_filters_bots_and_dedupes(ev):
    from temporal.activities.watchers import notify_human_comments_for_issue

    notifications: list[str] = []

    def fake_gh(args, stdin_data=None):
        return {
            "success": True,
            "output": json.dumps([
                {"id": 1, "user": "alice", "body": "looks good", "created_at": "2026-04-14T00:00Z"},
                {"id": 2, "user": "copilot[bot]", "body": "auto", "created_at": "2026-04-14T00:01Z"},
                {"id": 3, "user": "bob", "body": "fix this", "created_at": "2026-04-14T00:02Z"},
            ]),
        }

    def fake_notify(message: str) -> None:
        notifications.append(message)

    def fake_is_bot(login: str) -> bool:
        return "[bot]" in login.lower()

    result = notify_human_comments_for_issue(
        "microsoft/markitdown", 9, set(), ev,
        run_gh=fake_gh, notify=fake_notify, is_bot=fake_is_bot,
    )
    assert result["new_count"] == 2  # alice + bob, copilot filtered
    assert len(notifications) == 2

    # Second call with same seen_ids → no new
    result2 = notify_human_comments_for_issue(
        "microsoft/markitdown", 9, set(result["seen_ids"]), ev,
        run_gh=fake_gh, notify=fake_notify, is_bot=fake_is_bot,
    )
    assert result2["new_count"] == 0


def test_enqueue_for_human_review_writes_entry_and_notifies(ev):
    from temporal.activities.inbox import enqueue_for_human_review

    notifications = []

    enqueue_for_human_review(
        state="fixed",
        gate_name="relevance",
        reason="borderline score 0.55",
        score=0.55,
        upstream_slug="microsoft/markitdown",
        issue_number=183,
        evidence=ev,
        notify=lambda m, **kw: notifications.append((m, kw)),
    )

    entry = ev.read_json("awaiting/inbox_entry.json")
    assert entry["state"] == "fixed"
    assert entry["gate"] == "relevance"
    assert entry["score"] == 0.55
    assert ev.exists("awaiting/queued_at")
    assert len(notifications) == 1
    msg, kw = notifications[0]
    assert "183" in msg
    # Deep-link URL is computed from evidence.root; the test fixture's
    # evidence path encodes batch+issue ids that should appear in the URL.
    assert "view=temporal" in kw["url"]


def test_enqueue_for_human_review_swallows_notify_errors(ev):
    from temporal.activities.inbox import enqueue_for_human_review

    def boom(message: str, **kw):
        raise RuntimeError("discord down")

    # Should not raise — notification failure is best-effort
    result = enqueue_for_human_review(
        "fixed", "relevance", "x", 0.5, "x/y", 1, ev, notify=boom,
    )
    assert result["ok"] is True
    assert ev.exists("awaiting/inbox_entry.json")
