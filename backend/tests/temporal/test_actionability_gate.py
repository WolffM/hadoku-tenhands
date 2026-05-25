"""Tests for temporal.gates.actionability — Phase 3 advisory.

Covers:
  - Advisory mode (default) ALWAYS returns Pass regardless of rubric
  - Enforce mode maps rubric verdict → Pass / Defer / Fail per thresholds
  - Soft-fail on missing brief / fetch errors / judge unreachable
  - Computed flags match the cross-repo contract (epic_shape,
    active_linked_pr, team_reassignment_recent, maintainer_debate,
    stale_discussion, title_changed_recent)
  - Payload includes the brief + comments + signal summary
  - Pagination walks until short response
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from temporal.evidence.store import EvidenceStore
from temporal.gates import IssueRef
from temporal.gates.actionability import (
    actionability,
    _compute_flags,
    _build_payload,
    _fetch_issue_signals,
    _gh_paginated,
)


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/somerepo",
        upstream_slug="owner/somerepo",
        upstream_number=42,
    )


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _seed_brief(ev, **issue_overrides):
    """Minimal eligibility brief — what the actionability gate reads."""
    brief = {
        "issue": {
            "title": "Some bug title",
            "body": "Issue body here.",
            "labels": ["bug"],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "commentCount": 0,
            **issue_overrides,
        },
    }
    ev.write_json("01-eligible/issue_brief.json", brief)


class _FakeJudgeResult:
    def __init__(self, verdict="pass", score=0.9, reasoning="ok", evidence=None):
        self.verdict = verdict
        self.score = score
        self.reasoning = reasoning
        self.raw = {"verdict": verdict, "score": score, "reasoning": reasoning,
                    "evidence": evidence or []}


def _stub_run_gh_returning_empty(args, stdin_data=None):
    """Return success but empty arrays/payloads — minimal viable response."""
    if not isinstance(args, list) or len(args) < 2:
        return {"success": False, "error": "bad args"}
    return {"success": True, "output": "[]"}


# ── advisory-mode behavior ──────────────────────────────────────────────


def test_advisory_mode_always_passes_even_when_rubric_says_fail(issue, ev):
    _seed_brief(ev)
    judge_fn = lambda r, p: _FakeJudgeResult(verdict="fail", score=0.10, reasoning="epic")

    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=judge_fn,
        load_rubric=lambda: "fake rubric",
    )

    assert result.verdict == "pass"
    assert result.evidence_data["rubric_verdict"] == "fail"
    assert result.evidence_data["rubric_score"] == 0.10
    assert result.evidence_data["mode"] == "advisory"


def test_advisory_mode_soft_fails_on_missing_brief(issue, ev):
    # No brief written
    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=lambda r, p: _FakeJudgeResult(),
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "pass"
    assert result.evidence_data["error"] == "actionability:no_brief"


def test_advisory_mode_soft_fails_on_judge_unreachable(issue, ev):
    _seed_brief(ev)
    from temporal.judge import JudgeUnreachable

    def judge_boom(r, p):
        raise JudgeUnreachable("canary timed out")

    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=judge_boom,
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "pass"
    assert result.evidence_data["error"] == "actionability:judge_error"
    assert "JudgeUnreachable" in result.evidence_data["message"]


# ── enforce mode behavior ───────────────────────────────────────────────


def test_enforce_mode_maps_rubric_pass(issue, ev, monkeypatch):
    monkeypatch.setenv("CRIMSON_ACTIONABILITY_MODE", "enforce")
    _seed_brief(ev)
    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=lambda r, p: _FakeJudgeResult(verdict="pass", score=0.85),
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "pass"
    assert result.score == 0.85


def test_enforce_mode_maps_rubric_fail(issue, ev, monkeypatch):
    monkeypatch.setenv("CRIMSON_ACTIONABILITY_MODE", "enforce")
    _seed_brief(ev)
    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=lambda r, p: _FakeJudgeResult(verdict="fail", score=0.10),
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "fail"
    assert "actionability rubric failed" in result.reason


def test_enforce_mode_maps_rubric_defer_band(issue, ev, monkeypatch):
    monkeypatch.setenv("CRIMSON_ACTIONABILITY_MODE", "enforce")
    _seed_brief(ev)
    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=lambda r, p: _FakeJudgeResult(verdict="defer", score=0.55),
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "defer"
    assert "borderline" in result.reason


def test_enforce_mode_soft_fails_to_defer_on_missing_brief(issue, ev, monkeypatch):
    """In enforce mode, soft-fails route through Defer (operator inbox)
    instead of advisory's silent Pass — we still don't want telemetry
    breakage to block, but we surface to a human."""
    monkeypatch.setenv("CRIMSON_ACTIONABILITY_MODE", "enforce")
    result = actionability(
        issue, ev,
        run_gh=_stub_run_gh_returning_empty,
        is_bot=lambda l: False,
        judge_score=lambda r, p: _FakeJudgeResult(),
        load_rubric=lambda: "fake",
    )
    assert result.verdict == "defer"
    assert "actionability:no_brief" in result.reason


# ── flag computation ────────────────────────────────────────────────────


def test_compute_flags_epic_shape_from_sub_issue_count():
    data = {"sub_issues": {"count": 7}, "linked_pr_urls": [], "recent_timeline_events": [],
            "commenter_mix": {"maintainers": 1}, "comments": []}
    flags = _compute_flags(data, {"labels": []})
    assert "epic_shape" in flags


def test_compute_flags_epic_shape_from_labels_alone():
    """Older repos may not adopt the GitHub sub-issues feature; the
    cross-repo contract says labels {epic, tracking, umbrella} also fire
    epic_shape."""
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [], "recent_timeline_events": [],
            "commenter_mix": {"maintainers": 0}, "comments": []}
    flags = _compute_flags(data, {"labels": ["bug", "tracking"]})
    assert "epic_shape" in flags


def test_compute_flags_active_linked_pr():
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": ["https://x/pull/1"],
            "recent_timeline_events": [], "commenter_mix": {"maintainers": 0}, "comments": []}
    flags = _compute_flags(data, {"labels": []})
    assert "active_linked_pr" in flags


def test_compute_flags_team_reassignment_recent():
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [],
            "recent_timeline_events": [{"event": "assigned", "at": recent}],
            "commenter_mix": {"maintainers": 0}, "comments": []}
    flags = _compute_flags(data, {"labels": []})
    assert "team_reassignment_recent" in flags


def test_compute_flags_title_changed_recent():
    recent = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [],
            "recent_timeline_events": [{"event": "renamed", "at": recent}],
            "commenter_mix": {"maintainers": 0}, "comments": []}
    flags = _compute_flags(data, {"labels": []})
    assert "title_changed_recent" in flags


def test_compute_flags_maintainer_debate():
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [], "recent_timeline_events": [],
            "commenter_mix": {"maintainers": 3, "distinct": 5, "count": 8}, "comments": []}
    flags = _compute_flags(data, {"labels": []})
    assert "maintainer_debate" in flags


def test_compute_flags_stale_discussion():
    long_ago = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [], "recent_timeline_events": [],
            "commenter_mix": {"maintainers": 1}, "comments": [{"author": "x"}]}
    flags = _compute_flags(data, {"labels": [], "updatedAt": long_ago, "commentCount": 1})
    assert "stale_discussion" in flags


def test_compute_flags_no_false_fires_on_clean_issue():
    """An issue with no penalty signals should fire zero flags."""
    data = {"sub_issues": {"count": 0}, "linked_pr_urls": [], "recent_timeline_events": [],
            "commenter_mix": {"maintainers": 1}, "comments": []}
    flags = _compute_flags(data, {"labels": ["bug"], "updatedAt": datetime.now(timezone.utc).isoformat(), "commentCount": 0})
    assert flags == []


# ── pagination ──────────────────────────────────────────────────────────


def test_gh_paginated_walks_until_short_response():
    """Pagination must NOT silently truncate. facebook/react#17355 had
    131 comments; a single per_page=100 fetch missed 31 and flipped the
    rubric verdict pass → fail."""
    pages = [
        # Page 1: 100 entries (full page → more expected)
        {"success": True, "output": json.dumps([{"i": i} for i in range(100)])},
        # Page 2: 31 entries (short → stop)
        {"success": True, "output": json.dumps([{"i": i} for i in range(100, 131)])},
    ]
    calls = []

    def fake_gh(args, stdin_data=None):
        calls.append(args)
        return pages.pop(0)

    out = _gh_paginated(fake_gh, "repos/x/y/issues/1/comments")
    assert len(out) == 131
    # Verified page=1 then page=2 fetched
    assert "page=1" in calls[0][1]
    assert "page=2" in calls[1][1]


def test_gh_paginated_stops_on_failure():
    """If a page errors, bail with what we have so far — don't return None."""
    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "network"}
    out = _gh_paginated(fake_gh, "repos/x/y/issues/1/comments")
    assert out == []


# ── payload composition ────────────────────────────────────────────────


def test_build_payload_includes_brief_comments_and_signals():
    brief_issue = {
        "title": "the bug",
        "body": "what went wrong",
        "labels": ["bug", "good first issue"],
        "updatedAt": "2026-05-01T00:00:00Z",
    }
    data = {
        "comments": [
            {"author": "alice", "association": "MEMBER", "is_maintainer": True, "is_bot": False,
             "at": "2026-05-02T00:00:00Z", "body": "PR welcome"},
            {"author": "bot[bot]", "association": "NONE", "is_maintainer": False, "is_bot": True,
             "at": "2026-05-03T00:00:00Z", "body": "noise"},
        ],
        "sub_issues": {"count": 0, "open": 0, "closed": 0},
        "recent_timeline_events": [],
        "commenter_mix": {"count": 1, "distinct": 1, "maintainers": 1},
        "linked_pr_urls": [],
    }
    payload = _build_payload(brief_issue, data, [])

    assert "the bug" in payload
    assert "what went wrong" in payload
    assert "PR welcome" in payload
    assert "[MAINTAINER]" in payload
    assert "[BOT]" in payload  # bots are labeled but not stripped from payload
    assert "good first issue" in payload
    # Signal summary as JSON block
    assert '"subIssues"' in payload
    assert '"commenterMix"' in payload


def test_build_payload_handles_no_comments():
    payload = _build_payload({"title": "x", "body": "y", "labels": []},
                             {"comments": [], "sub_issues": {"count": 0, "open": 0, "closed": 0},
                              "recent_timeline_events": [], "commenter_mix": {"count": 0, "distinct": 0, "maintainers": 0},
                              "linked_pr_urls": []}, [])
    assert "_(no comments)_" in payload
