"""Tests for oss_helpers — heuristic scoring fallback and PR template formatting."""

import pytest
from helpers.oss_helpers import (
    score_issue_fallback, score_issue_with_breakdown, format_upstream_pr_body,
    _score_reactions, _score_comment_sentiment,
)


class TestScoreIssueFallback:
    """Tests for the heuristic issue scorer."""

    def test_assigned_issue_is_skipped(self):
        """Issues with assignees should get cvs=0, tier=skip."""
        result = score_issue_fallback({
            "assignees": [{"login": "someone"}],
            "labels": [{"name": "good first issue"}],
            "createdAt": "2026-02-01T00:00:00Z",
            "updatedAt": "2026-02-01T00:00:00Z",
            "comments": 5,
        })
        assert result["cvs"] == 0
        assert result["cvsTier"] == "skip"
        assert result["dataCompleteness"] == "partial"

    def test_assigned_issue_string_format(self):
        """Assignees as plain strings should also trigger skip."""
        result = score_issue_fallback({
            "assignees": ["someone"],
            "labels": [],
            "createdAt": "2026-02-01T00:00:00Z",
            "updatedAt": "2026-02-01T00:00:00Z",
            "comments": 0,
        })
        assert result["cvs"] == 0
        assert result["cvsTier"] == "skip"

    def test_empty_assignees_not_skipped(self):
        """Empty assignee list should not trigger skip."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        })
        assert result["cvs"] > 0
        assert result["cvsTier"] != "skip"

    def test_base_score_is_50(self):
        """A fresh issue with no labels, some comments → base 50 → tier maybe."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        })
        assert result["cvs"] == 50
        assert result["cvsTier"] == "maybe"

    def test_good_first_issue_label_boost_dict_format(self):
        """'good first issue' label (dict format from gh CLI) should add +20."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [{"name": "good first issue", "color": "7057ff"}],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        })
        assert result["cvs"] == 70
        assert result["cvsTier"] == "likely"

    def test_good_first_issue_label_boost_string_format(self):
        """'good first issue' label (string format from aggregator) should add +20."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": ["good first issue", "bug"],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        })
        assert result["cvs"] == 70
        assert result["cvsTier"] == "likely"

    def test_good_first_issue_case_insensitive(self):
        """Label matching should be case-insensitive."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [{"name": "Good First Issue"}],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        })
        assert result["cvs"] == 70

    def test_stale_issue_penalty(self):
        """Issues updated > 90 days ago should get -30 penalty."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "comments": 1,
        })
        # 50 - 30 (stale) = 20
        assert result["cvs"] == 20
        assert result["cvsTier"] == "risky"

    def test_no_comments_old_issue_penalty(self):
        """Issues with 0 comments older than 14 days should get -10."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 0,
        })
        # 50 - 10 (no comments, > 14 days old) = 40
        assert result["cvs"] == 40
        assert result["cvsTier"] == "maybe"

    def test_stale_and_no_comments_combined(self):
        """Both penalties should stack."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2025-01-01T00:00:00Z",
            "updatedAt": "2025-01-01T00:00:00Z",
            "comments": 0,
        })
        # 50 - 30 (stale) - 10 (no comments) = 10
        assert result["cvs"] == 10
        assert result["cvsTier"] == "skip"

    def test_comments_as_list_normalized(self):
        """gh issue view returns comments as list of objects; scorer handles both."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": [{"body": "hello"}, {"body": "world"}],
        })
        # comments=2 (from list length), so no zero-comment penalty
        assert result["cvs"] == 50

    def test_score_clamped_at_zero(self):
        """Score should never go below 0."""
        result = score_issue_fallback({
            "assignees": [],
            "labels": [],
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2020-01-01T00:00:00Z",
            "comments": 0,
        })
        assert result["cvs"] >= 0

    def test_tier_boundaries(self):
        """Verify tier boundaries: go >= 80, likely >= 60, maybe >= 40, risky >= 20, skip < 20."""
        # go tier: not achievable with current max (70) — that's fine
        # likely: 70 (base + gfi)
        likely = score_issue_fallback({
            "assignees": [], "labels": ["good first issue"],
            "createdAt": "2026-02-18T00:00:00Z", "updatedAt": "2026-02-18T00:00:00Z", "comments": 1,
        })
        assert likely["cvsTier"] == "likely"

        # maybe: 50 (base only)
        maybe = score_issue_fallback({
            "assignees": [], "labels": [],
            "createdAt": "2026-02-18T00:00:00Z", "updatedAt": "2026-02-18T00:00:00Z", "comments": 1,
        })
        assert maybe["cvsTier"] == "maybe"

        # risky: 20 (base - stale)
        risky = score_issue_fallback({
            "assignees": [], "labels": [],
            "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-01-01T00:00:00Z", "comments": 1,
        })
        assert risky["cvsTier"] == "risky"

        # skip: 10 (base - stale - no comments)
        skip = score_issue_fallback({
            "assignees": [], "labels": [],
            "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-01-01T00:00:00Z", "comments": 0,
        })
        assert skip["cvsTier"] == "skip"

    def test_missing_fields_dont_crash(self):
        """Scorer should handle missing fields gracefully."""
        result = score_issue_fallback({})
        assert "cvs" in result
        assert "cvsTier" in result
        assert "dataCompleteness" in result

    def test_all_results_have_partial_completeness(self):
        """Fallback scorer always returns dataCompleteness=partial."""
        result = score_issue_fallback({
            "assignees": [], "labels": ["good first issue"],
            "createdAt": "2026-02-18T00:00:00Z", "updatedAt": "2026-02-18T00:00:00Z", "comments": 5,
        })
        assert result["dataCompleteness"] == "partial"


def _make_reactions(**kwargs):
    """Helper: build reactionGroups list from keyword args like THUMBS_UP=5."""
    groups = []
    for content, count in kwargs.items():
        groups.append({"content": content, "users": {"totalCount": count}})
    return groups


class TestScoreReactions:
    """Tests for _score_reactions helper."""

    def test_thumbs_up_positive_score(self):
        groups = _make_reactions(THUMBS_UP=5)
        score, detail = _score_reactions(groups)
        assert score == 10  # 5 * 2

    def test_thumbs_down_negative_score(self):
        groups = _make_reactions(THUMBS_DOWN=3)
        score, detail = _score_reactions(groups)
        assert score == -6  # 3 * -2

    def test_mixed_reactions_capped(self):
        groups = _make_reactions(THUMBS_UP=10, CONFUSED=3)
        score, detail = _score_reactions(groups)
        # raw = 10*2 + 3*(-1) = 17, capped to 15
        assert score == 15

    def test_cap_at_positive_15(self):
        groups = _make_reactions(THUMBS_UP=100)
        score, _ = _score_reactions(groups)
        assert score == 15

    def test_cap_at_negative_15(self):
        groups = _make_reactions(THUMBS_DOWN=100)
        score, _ = _score_reactions(groups)
        assert score == -15

    def test_empty_reaction_groups(self):
        score, detail = _score_reactions([])
        assert score == 0
        assert detail == {}

    def test_none_reaction_groups(self):
        score, detail = _score_reactions(None)
        assert score == 0
        assert detail == {}

    def test_missing_users_key(self):
        """Reaction group without users key should not crash."""
        groups = [{"content": "THUMBS_UP"}]
        score, detail = _score_reactions(groups)
        assert score == 0

    def test_unknown_reaction_type(self):
        groups = [{"content": "ALIEN", "users": {"totalCount": 5}}]
        score, _ = _score_reactions(groups)
        assert score == 0  # weight 0 for unknown

    def test_laugh_and_eyes_are_neutral(self):
        groups = _make_reactions(LAUGH=10, EYES=10)
        score, _ = _score_reactions(groups)
        assert score == 0

    def test_detail_has_per_type_breakdown(self):
        groups = _make_reactions(THUMBS_UP=3, HEART=2)
        score, detail = _score_reactions(groups)
        assert detail["THUMBS_UP"]["count"] == 3
        assert detail["THUMBS_UP"]["weight"] == 2
        assert detail["THUMBS_UP"]["contribution"] == 6
        assert detail["HEART"]["count"] == 2
        assert detail["HEART"]["contribution"] == 2
        assert score == 8


class TestScoreCommentSentiment:
    """Tests for _score_comment_sentiment helper."""

    def test_plus_one_positive(self):
        score, detail = _score_comment_sentiment([{"body": "+1"}])
        assert score == 3
        assert detail["positive_count"] == 1

    def test_minus_one_negative(self):
        score, detail = _score_comment_sentiment([{"body": "-1"}])
        assert score == -3
        assert detail["negative_count"] == 1

    def test_me_too_positive(self):
        score, _ = _score_comment_sentiment([{"body": "me too, I need this feature"}])
        assert score == 3

    def test_duplicate_of_negative(self):
        score, _ = _score_comment_sentiment([{"body": "duplicate of #123"}])
        assert score == -3

    def test_neutral_comment_no_score(self):
        score, detail = _score_comment_sentiment([{"body": "I tried the workaround and it seems fine."}])
        assert score == 0
        assert detail["neutral_count"] == 1

    def test_mixed_comments(self):
        comments = [
            {"body": "+1"},
            {"body": "+1"},
            {"body": "duplicate of #5"},
        ]
        score, detail = _score_comment_sentiment(comments)
        # 2*3 + 1*(-3) = 3
        assert score == 3
        assert detail["positive_count"] == 2
        assert detail["negative_count"] == 1

    def test_cap_at_positive_10(self):
        comments = [{"body": "+1"} for _ in range(10)]
        score, _ = _score_comment_sentiment(comments)
        # 10 * 3 = 30, capped to 10
        assert score == 10

    def test_cap_at_negative_10(self):
        comments = [{"body": "-1"} for _ in range(10)]
        score, _ = _score_comment_sentiment(comments)
        assert score == -10

    def test_comments_as_int_returns_zero(self):
        score, detail = _score_comment_sentiment(5)
        assert score == 0
        assert detail["analyzed_count"] == 0

    def test_empty_list_returns_zero(self):
        score, detail = _score_comment_sentiment([])
        assert score == 0
        assert detail["analyzed_count"] == 0

    def test_comment_without_body_key_skipped(self):
        score, detail = _score_comment_sentiment([{"author": "someone"}])
        assert score == 0
        assert detail["analyzed_count"] == 0

    def test_case_insensitive(self):
        score, _ = _score_comment_sentiment([{"body": "ME TOO"}])
        assert score == 3

    def test_bump_positive(self):
        score, _ = _score_comment_sentiment([{"body": "bump"}])
        assert score == 3

    def test_wont_fix_negative(self):
        score, _ = _score_comment_sentiment([{"body": "won't fix"}])
        assert score == -3

    def test_stale_negative(self):
        score, _ = _score_comment_sentiment([{"body": "This issue is stale"}])
        assert score == -3

    def test_please_fix_positive(self):
        score, _ = _score_comment_sentiment([{"body": "please fix this"}])
        assert score == 3

    def test_detail_has_correct_counts(self):
        comments = [
            {"body": "+1"},
            {"body": "interesting approach"},
            {"body": "duplicate of #10"},
        ]
        score, detail = _score_comment_sentiment(comments)
        assert detail["analyzed_count"] == 3
        assert detail["positive_count"] == 1
        assert detail["negative_count"] == 1
        assert detail["neutral_count"] == 1


class TestScoringWithSentiment:
    """Integration tests: reaction + comment sentiment in score_issue_with_breakdown."""

    def _fresh_issue(self, **overrides):
        """Build a fresh issue dict (no staleness, no penalties)."""
        base = {
            "assignees": [],
            "labels": [],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 1,
        }
        base.update(overrides)
        return base

    def test_reactions_add_to_base_score(self):
        issue = self._fresh_issue(reactionGroups=_make_reactions(THUMBS_UP=5))
        result = score_issue_with_breakdown(issue)
        # 50 + 10 (5 thumbs_up * 2) = 60
        assert result["cvs"] == 60
        assert result["breakdown"]["reaction_score"] == 10

    def test_reactions_and_gfi_combine(self):
        issue = self._fresh_issue(
            labels=["good first issue"],
            reactionGroups=_make_reactions(THUMBS_UP=5),
        )
        result = score_issue_with_breakdown(issue)
        # 50 + 20 (gfi) + 10 (reactions) = 80 -> go tier!
        assert result["cvs"] == 80
        assert result["cvsTier"] == "go"

    def test_negative_reactions_reduce_score(self):
        issue = self._fresh_issue(reactionGroups=_make_reactions(THUMBS_DOWN=3))
        result = score_issue_with_breakdown(issue)
        # 50 + (-6) = 44
        assert result["cvs"] == 44

    def test_comment_sentiment_adds_when_bodies_available(self):
        issue = self._fresh_issue(
            comments=[{"body": "+1"}, {"body": "+1"}],
        )
        result = score_issue_with_breakdown(issue)
        # 50 + 6 (2 * +3) = 56
        assert result["cvs"] == 56
        assert result["breakdown"]["comment_sentiment_score"] == 6

    def test_full_enrichment_all_signals(self):
        issue = self._fresh_issue(
            labels=["good first issue"],
            reactionGroups=_make_reactions(THUMBS_UP=5, HEART=3),
            comments=[{"body": "+1"}, {"body": "me too"}],
        )
        result = score_issue_with_breakdown(issue)
        # 50 + 20 (gfi) + 13 (10+3 reactions) + 6 (2 positive) = 89
        assert result["cvs"] == 89
        assert result["cvsTier"] == "go"

    def test_score_still_clamped_at_100(self):
        issue = self._fresh_issue(
            labels=["good first issue"],
            reactionGroups=_make_reactions(THUMBS_UP=100),
            comments=[{"body": "+1"} for _ in range(20)],
        )
        result = score_issue_with_breakdown(issue)
        # 50 + 20 + 15 (cap) + 10 (cap) = 95, within 100
        assert result["cvs"] == 95
        assert result["cvs"] <= 100

    def test_backward_compatible_no_reaction_data(self):
        """Issues without reactionGroups score identically to before."""
        issue = self._fresh_issue()
        result = score_issue_with_breakdown(issue)
        assert result["cvs"] == 50
        assert result["breakdown"]["reaction_score"] == 0

    def test_backward_compatible_comments_as_int(self):
        """Comments as integer (batch mode) — no sentiment scoring."""
        issue = self._fresh_issue(comments=5)
        result = score_issue_with_breakdown(issue)
        assert result["cvs"] == 50
        assert result["breakdown"]["comment_sentiment_score"] == 0

    def test_breakdown_includes_new_keys(self):
        issue = self._fresh_issue()
        result = score_issue_with_breakdown(issue)
        bd = result["breakdown"]
        assert "reaction_score" in bd
        assert "comment_sentiment_score" in bd
        assert "reaction_detail" in bd
        assert "comment_sentiment_detail" in bd

    def test_go_tier_now_achievable(self):
        """With reactions, the go tier (>=80) is now reachable."""
        issue = self._fresh_issue(
            labels=["good first issue"],
            reactionGroups=_make_reactions(THUMBS_UP=8),
        )
        result = score_issue_with_breakdown(issue)
        # 50 + 20 + 15 (capped from 16) = 85
        assert result["cvs"] == 85
        assert result["cvsTier"] == "go"


class TestFormatUpstreamPrBody:
    """Tests for format_upstream_pr_body — PR template for upstream submissions."""

    def test_contains_issue_reference(self):
        body = format_upstream_pr_body("fastify/fastify", 42, "Fix memory leak", "fix-memleak")
        assert "fastify/fastify#42" in body
        assert "Fix memory leak" in body

    def test_contains_closes_directive(self):
        """PR body should include 'Closes #N' for GitHub auto-close."""
        body = format_upstream_pr_body("vercel/next.js", 100, "Fix routing", "fix-routing")
        assert "Closes #100" in body

    def test_contains_branch_name(self):
        body = format_upstream_pr_body("org/repo", 1, "Title", "my-feature-branch")
        assert "`my-feature-branch`" in body

    def test_special_characters_in_title(self):
        """Titles with special chars should be included as-is (no escaping needed for markdown)."""
        body = format_upstream_pr_body("org/repo", 1, "Fix `foo` & <bar>", "fix-foo")
        assert "Fix `foo` & <bar>" in body
