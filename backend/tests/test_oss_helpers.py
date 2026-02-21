"""Tests for oss_helpers — heuristic scoring fallback."""

import pytest
from helpers.oss_helpers import score_issue_fallback


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

    def test_score_clamped_at_100(self):
        """Score should never exceed 100."""
        # Even with all boosts, max is 50 + 20 = 70 currently
        # But verify the clamp logic works
        result = score_issue_fallback({
            "assignees": [],
            "labels": ["good first issue"],
            "createdAt": "2026-02-18T00:00:00Z",
            "updatedAt": "2026-02-18T00:00:00Z",
            "comments": 10,
        })
        assert result["cvs"] <= 100

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
