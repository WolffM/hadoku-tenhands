"""Unit tests for outcome_snapshot activity — Phase 0 / M0.1.

Covers:
  - terminal evidence (11-merged, 11-closed_by_upstream) wins, no GH calls
  - never-submitted classifies as not_submitted
  - operator-aborted classifies as aborted_by_operator (reads transitions.jsonl)
  - open PR triggers live poll + maintainer-engagement scan
  - bot activity does NOT reset the staleness clock
  - merged-since-last-snapshot (state changes between polls)
  - closed-since-last-snapshot
  - 30d/90d checkpoints flip based on last engagement
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from temporal.activities.outcome_snapshot import (
    classify_outcome,
    snapshot_outcome,
)
from temporal.evidence.store import EvidenceStore


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _fake_is_bot(login: str) -> bool:
    """Minimal bot filter for tests — anything with [bot] or 'copilot' counts."""
    lower = (login or "").lower()
    return "[bot]" in lower or "copilot" in lower


NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_merged_terminal_evidence_wins_no_gh_call(ev):
    """If `11-merged/` exists, classification skips GH entirely."""
    ev.write_json("11-merged/merge_info.json", {
        "merge_sha": "abc1234",
        "merged_at": "2026-04-10T10:00:00Z",
        "merged_by": "alice",
        "upstream_slug": "owner/repo",
        "pr_number": 99,
    })

    def gh_fail(args, stdin_data=None):
        pytest.fail("GH should not be called when terminal evidence is on disk")

    snap = classify_outcome(ev, run_gh=gh_fail, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "merged"
    assert snap["merge_sha"] == "abc1234"
    assert snap["merged_at"] == "2026-04-10T10:00:00Z"
    assert snap["merged_by"] == "alice"
    assert snap["upstream_pr_url"] == "https://github.com/owner/repo/pull/99"
    assert snap["snapshot_source"] == "evidence"


def test_closed_unmerged_terminal_evidence_wins_no_gh_call(ev):
    ev.write_json("11-closed_by_upstream/close_info.json", {
        "closed_at": "2026-03-15T08:00:00Z",
        "closer": "maintainer-bot",  # bot closer is still recorded as-is
        "upstream_slug": "owner/repo",
        "pr_number": 42,
    })

    def gh_fail(args, stdin_data=None):
        pytest.fail("GH should not be called when terminal evidence is on disk")

    snap = classify_outcome(ev, run_gh=gh_fail, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "closed_unmerged"
    assert snap["closed_at"] == "2026-03-15T08:00:00Z"
    assert snap["upstream_pr_number"] == 42
    assert snap["snapshot_source"] == "evidence"


def test_never_submitted_classifies_as_not_submitted(ev):
    """No 10-submitted/, no transitions → not_submitted."""
    def gh_fail(args, stdin_data=None):
        pytest.fail("GH should not be called when never submitted")

    snap = classify_outcome(ev, run_gh=gh_fail, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "not_submitted"
    assert snap["upstream_pr_url"] is None
    assert snap["snapshot_source"] == "evidence"


def test_operator_aborted_classifies_specifically(ev):
    """If the final transitions.jsonl entry is operator-aborted, surface that
    distinctly from `not_submitted` so the calibration corpus can tell
    'we walked away' apart from 'never got there'."""
    ev.append_jsonl("transitions.jsonl", {
        "from": "submittable",
        "to": "awaiting_signoff",
        "at": "2026-04-01T12:00:00Z",
    })
    ev.append_jsonl("transitions.jsonl", {
        "from": "awaiting_signoff",
        "to": "aborted",
        "reason": "operator aborted: not the right fix after review",
        "at": "2026-04-02T08:00:00Z",
    })

    def gh_fail(args, stdin_data=None):
        pytest.fail("GH should not be called on operator abort")

    snap = classify_outcome(ev, run_gh=gh_fail, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "aborted_by_operator"


def test_open_pr_triggers_live_poll_and_engagement_scan(ev):
    """No terminal evidence + 10-submitted/upstream_pr_url present → live poll."""
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/owner/repo/pull/55")
    ev.write_text("10-submitted/upstream_pr_number", "55")

    # PR is open, created 10 days ago, last human comment 5 days ago,
    # an APPROVED review from a real maintainer 2 days ago.
    pr_created = (NOW - timedelta(days=10)).isoformat()
    comment_at = (NOW - timedelta(days=5)).isoformat()
    review_at = (NOW - timedelta(days=2)).isoformat()

    calls = []
    def fake_gh(args, stdin_data=None):
        calls.append(args)
        if args[1] == "repos/owner/repo/pulls/55":
            return {"success": True, "output": json.dumps({
                "state": "open",
                "merged": False,
                "merged_at": None,
                "merge_commit_sha": None,
                "closed_at": None,
                "created_at": pr_created,
                "updated_at": (NOW - timedelta(days=1)).isoformat(),
                "merged_by": None,
                "closer": "someone",
            })}
        if "/issues/55/comments" in args[1]:
            return {"success": True, "output": json.dumps([
                {"user": "github-actions[bot]", "at": (NOW - timedelta(days=1)).isoformat()},
                {"user": "alice", "at": comment_at},
            ])}
        if "/pulls/55/reviews" in args[1]:
            return {"success": True, "output": json.dumps([
                {"user": "maintainer-bob", "at": review_at},
            ])}
        pytest.fail(f"unexpected gh call: {args}")

    snap = classify_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "open"
    assert snap["snapshot_source"] == "live_poll"
    assert snap["upstream_slug"] == "owner/repo"
    assert snap["upstream_pr_number"] == 55
    assert snap["days_since_submission"] == 10
    # Latest non-bot is the review at 2 days ago (more recent than comment)
    assert snap["days_since_last_engagement"] == 2
    assert snap["stale_30d_at_snapshot"] is False
    assert snap["stale_90d_at_snapshot"] is False


def test_bot_activity_does_not_reset_staleness_clock(ev):
    """A PR whose only recent activity is bot pushes / Copilot comments
    must read as stale based on the last HUMAN engagement, not the bot
    timestamps. This is the load-bearing reason we filter."""
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/owner/repo/pull/77")
    ev.write_text("10-submitted/upstream_pr_number", "77")

    pr_created = (NOW - timedelta(days=100)).isoformat()
    human_comment_at = (NOW - timedelta(days=95)).isoformat()  # >90d → stale_90d
    bot_comment_at = (NOW - timedelta(days=3)).isoformat()      # would falsely reset clock

    def fake_gh(args, stdin_data=None):
        if args[1] == "repos/owner/repo/pulls/77":
            return {"success": True, "output": json.dumps({
                "state": "open", "merged": False,
                "merged_at": None, "merge_commit_sha": None, "closed_at": None,
                "created_at": pr_created,
                "updated_at": bot_comment_at,  # bot reset updated_at
                "merged_by": None, "closer": None,
            })}
        if "/issues/77/comments" in args[1]:
            return {"success": True, "output": json.dumps([
                {"user": "copilot-swe-agent[bot]", "at": bot_comment_at},
                {"user": "github-actions[bot]", "at": (NOW - timedelta(days=2)).isoformat()},
                {"user": "real-human", "at": human_comment_at},
            ])}
        if "/pulls/77/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        pytest.fail(f"unexpected gh call: {args}")

    snap = classify_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "open"
    assert snap["days_since_last_engagement"] == 95
    assert snap["stale_30d_at_snapshot"] is True
    assert snap["stale_90d_at_snapshot"] is True


def test_live_poll_detects_merged_since_last_snapshot(ev):
    """If the upstream PR was merged between snapshots, the poll picks it
    up and classifies as merged (terminal-state-via-poll, not via disk)."""
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/owner/repo/pull/88")
    ev.write_text("10-submitted/upstream_pr_number", "88")

    def fake_gh(args, stdin_data=None):
        if args[1] == "repos/owner/repo/pulls/88":
            return {"success": True, "output": json.dumps({
                "state": "closed",
                "merged": True,
                "merged_at": "2026-05-20T10:00:00Z",
                "merge_commit_sha": "deadbeef",
                "closed_at": "2026-05-20T10:00:00Z",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-20T10:00:00Z",
                "merged_by": "maintainer-x",
                "closer": "maintainer-x",
            })}
        pytest.fail(f"unexpected gh call after merged: {args}")

    snap = classify_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "merged"
    assert snap["merge_sha"] == "deadbeef"
    assert snap["merged_by"] == "maintainer-x"


def test_live_poll_handles_pr_fetch_failure(ev):
    """Transient GH errors must yield state='unknown' with the error
    captured, not blow up the caller. Caller can retry next cron tick."""
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/owner/repo/pull/9")
    ev.write_text("10-submitted/upstream_pr_number", "9")

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "GH 5xx blip"}

    snap = classify_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)

    assert snap["state"] == "unknown"
    assert any("pr fetch" in e for e in snap["errors"])


def test_snapshot_outcome_persists_to_outcomes_dir(ev):
    """Integration: snapshot_outcome writes outcomes/upstream_state.json."""
    ev.write_json("11-merged/merge_info.json", {
        "merge_sha": "abc1234",
        "merged_at": "2026-04-10T10:00:00Z",
        "merged_by": "alice",
        "upstream_slug": "owner/repo",
        "pr_number": 99,
    })

    def gh_fail(args, stdin_data=None):
        pytest.fail("no GH expected for terminal evidence")

    snap = snapshot_outcome(ev, run_gh=gh_fail, is_bot=_fake_is_bot, now=NOW)

    assert ev.exists("outcomes/upstream_state.json")
    persisted = ev.read_json("outcomes/upstream_state.json")
    assert persisted == snap
    assert persisted["state"] == "merged"


def test_snapshot_overwrites_prior_snapshot_idempotently(ev):
    """Re-running the snapshot updates in place — important for cron re-runs."""
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/owner/repo/pull/42")
    ev.write_text("10-submitted/upstream_pr_number", "42")

    state_seq = ["open", "merged"]
    def fake_gh(args, stdin_data=None):
        s = state_seq.pop(0) if state_seq else "merged"
        if "/issues/42/comments" in args[1] or "/pulls/42/reviews" in args[1]:
            return {"success": True, "output": "[]"}
        return {"success": True, "output": json.dumps({
            "state": "closed" if s == "merged" else "open",
            "merged": s == "merged",
            "merged_at": "2026-05-20T10:00:00Z" if s == "merged" else None,
            "merge_commit_sha": "deadbeef" if s == "merged" else None,
            "closed_at": "2026-05-20T10:00:00Z" if s == "merged" else None,
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-20T10:00:00Z",
            "merged_by": "alice" if s == "merged" else None,
            "closer": None,
        })}

    first = snapshot_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)
    assert first["state"] == "open"

    second = snapshot_outcome(ev, run_gh=fake_gh, is_bot=_fake_is_bot, now=NOW)
    assert second["state"] == "merged"
    # Disk reflects the LATEST snapshot
    persisted = ev.read_json("outcomes/upstream_state.json")
    assert persisted["state"] == "merged"
