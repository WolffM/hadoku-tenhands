"""Tests for StageDispatcher interface and CopilotSWEDispatcher (Stage 4a)."""

import json
from unittest.mock import patch

import pytest

from services.dispatchers import (
    StageDispatcher,
    CopilotSWEDispatcher,
    GitHubActionsDispatcher,
    CopilotReviewDispatcher,
    CopilotRemediationDispatcher,
    create_default_registry,
)


class TestStageDispatcherInterface:
    """Tests for the abstract dispatcher interface."""

    def test_abstract_dispatch_raises(self):
        d = StageDispatcher()
        with pytest.raises(NotImplementedError):
            d.dispatch({}, {})

    def test_abstract_check_status_raises(self):
        d = StageDispatcher()
        with pytest.raises(NotImplementedError):
            d.check_status("id", {})

    def test_abstract_collect_results_raises(self):
        d = StageDispatcher()
        with pytest.raises(NotImplementedError):
            d.collect_results("id", {})

    def test_default_registry_has_all_keys(self):
        registry = create_default_registry()
        assert "swe" in registry
        assert "static_analysis" in registry
        assert "review" in registry
        assert "remediation" in registry
        assert isinstance(registry["swe"], CopilotSWEDispatcher)
        assert isinstance(registry["static_analysis"], GitHubActionsDispatcher)
        assert isinstance(registry["review"], CopilotReviewDispatcher)
        assert isinstance(registry["remediation"], CopilotRemediationDispatcher)


class TestCopilotSWEDispatcher:
    """Tests for the Copilot SWE agent dispatcher (Stage 4a)."""

    def test_dispatch_returns_existing_assignment(self):
        d = CopilotSWEDispatcher()
        result = d.dispatch({}, {"fork_issue_number": 7})
        assert result["success"] is True
        assert result["job_id"] == "7"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_detects_completed_agent(self, mock_gh):
        mock_gh.side_effect = [
            # pr list — Copilot PR found (no commits inline)
            {"success": True, "output": json.dumps([{
                "number": 2,
                "title": "Fix bug",
                "headRefName": "copilot/fix-bug",
                "author": {"login": "app/copilot-swe-agent"},
            }])},
            # commits fetch for PR#2
            {"success": True, "output": '["a","b"]'},
            # pr view headRefOid
            {"success": True, "output": "abc123\n"},
            # check-runs — completed
            {"success": True, "output": "completed\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("1", {"my_user": "me", "repo": "r"})

        assert result["done"] is True
        assert result["pr_number"] == 2
        assert result["pr_branch"] == "copilot/fix-bug"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_returns_waiting_when_no_pr(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "[]"}
        d = CopilotSWEDispatcher()
        result = d.check_status("1", {"my_user": "me", "repo": "r"})

        assert result["done"] is False
        assert result["status"] == "waiting_for_pr"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_returns_working_when_in_progress(self, mock_gh):
        mock_gh.side_effect = [
            # pr list (no commits inline)
            {"success": True, "output": json.dumps([{
                "number": 2,
                "title": "Fix bug",
                "headRefName": "copilot/fix-bug",
                "author": {"login": "app/copilot-swe-agent"},
            }])},
            # commits fetch for PR#2
            {"success": True, "output": '["a"]'},
            # pr view headRefOid
            {"success": True, "output": "abc123\n"},
            # check-runs — in_progress
            {"success": True, "output": "in_progress\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("1", {"my_user": "me", "repo": "r"})

        assert result["done"] is False
        assert result["status"] == "working"
        assert result["pr_number"] == 2

    @patch("services.dispatchers.run_gh_command")
    def test_collect_results_returns_pr_details(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "number": 2,
                "title": "Fix bug",
                "headRefName": "copilot/fix-bug",
                "additions": 50,
                "deletions": 10,
                "changedFiles": 3,
                "commits": [{"sha": "a"}, {"sha": "b"}],
            }),
        }
        d = CopilotSWEDispatcher()
        result = d.collect_results("1", {
            "my_user": "me", "repo": "r", "stage4_pr_number": 2,
        })

        assert result["success"] is True
        assert result["outputs"]["pr_number"] == 2
        assert result["outputs"]["additions"] == 50
        assert result["outputs"]["commit_count"] == 2

    @patch("services.dispatchers.run_gh_command")
    def test_find_pr_for_issue_success(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "[14]\n"}
        d = CopilotSWEDispatcher()
        prs = [
            {"number": 12, "headRefName": "copilot/fix-a", "commits": [{"sha": "a"}]},
            {"number": 14, "headRefName": "copilot/fix-b", "commits": [{"sha": "b"}, {"sha": "c"}]},
        ]
        result = d._find_pr_for_issue("me", "r", 13, prs)
        assert result is not None
        assert result["number"] == 14

    @patch("services.dispatchers.run_gh_command")
    def test_find_pr_for_issue_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "not found"}
        d = CopilotSWEDispatcher()
        prs = [{"number": 12}, {"number": 14}]
        result = d._find_pr_for_issue("me", "r", 13, prs)
        assert result is None

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_correlates_via_timeline(self, mock_gh):
        """With multiple Copilot PRs, timeline selects the correct one."""
        copilot_pr_a = {
            "number": 12, "title": "Fix A",
            "headRefName": "copilot/fix-a",
            "author": {"login": "app/copilot-swe-agent"},
        }
        copilot_pr_b = {
            "number": 14, "title": "Fix B",
            "headRefName": "copilot/fix-b",
            "author": {"login": "app/copilot-swe-agent"},
        }
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs (no commits inline)
            {"success": True, "output": json.dumps([copilot_pr_a, copilot_pr_b])},
            # commits fetch for PR#12
            {"success": True, "output": '["a"]'},
            # commits fetch for PR#14
            {"success": True, "output": '["b","c"]'},
            # issue title fetch (no body on PRs → title-tag match fails → fall through)
            {"success": True, "output": '"Some issue title"\n'},
            # timeline — issue #13 links to PR #14
            {"success": True, "output": "[14]\n"},
            # pr view headRefOid
            {"success": True, "output": "def456\n"},
            # check-runs — completed
            {"success": True, "output": "completed\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("13", {
            "my_user": "me", "repo": "r", "fork_issue_number": 13,
        })
        assert result["done"] is True
        assert result["pr_number"] == 14
        assert result["pr_branch"] == "copilot/fix-b"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_done_via_commit_count_fallback(self, mock_gh):
        """When check-run is absent but PR has 2+ commits, treat as done."""
        mock_gh.side_effect = [
            # pr list — single Copilot PR (no commits inline)
            {"success": True, "output": json.dumps([{
                "number": 12, "title": "Fix tests",
                "headRefName": "copilot/fix-tests",
                "author": {"login": "app/copilot-swe-agent"},
            }])},
            # commits fetch for PR#12
            {"success": True, "output": '["plan","impl"]'},
            # pr view headRefOid
            {"success": True, "output": "abc123\n"},
            # check-runs — empty (no Copilot check-run found)
            {"success": True, "output": "\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("11", {"my_user": "me", "repo": "r"})
        assert result["done"] is True
        assert result["pr_number"] == 12

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_working_single_commit_no_checkrun(self, mock_gh):
        """When check-run is absent and only 1 commit, still working."""
        mock_gh.side_effect = [
            # pr list (no commits inline)
            {"success": True, "output": json.dumps([{
                "number": 12, "title": "Fix tests",
                "headRefName": "copilot/fix-tests",
                "author": {"login": "app/copilot-swe-agent"},
            }])},
            # commits fetch for PR#12
            {"success": True, "output": '["plan"]'},
            {"success": True, "output": "abc123\n"},
            {"success": True, "output": "\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("11", {"my_user": "me", "repo": "r"})
        assert result["done"] is False
        assert result["commit_count"] == 1

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_no_fallback_when_ambiguous(self, mock_gh):
        """With multiple Copilot PRs and failed correlation, we don't guess — wait."""
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs (no commits inline)
            {"success": True, "output": json.dumps([
                {"number": 12, "headRefName": "copilot/fix-a",
                 "author": {"login": "app/copilot-swe-agent"}},
                {"number": 14, "headRefName": "copilot/fix-b",
                 "author": {"login": "app/copilot-swe-agent"}},
            ])},
            # commits fetch for PR#12
            {"success": True, "output": '["plan"]'},
            # commits fetch for PR#14
            {"success": True, "output": '["plan","impl"]'},
            # issue title fetch (no body on PRs → title-tag match fails)
            {"success": True, "output": '"Some title"\n'},
            # timeline — fails
            {"success": False, "error": "timeout"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("13", {
            "my_user": "me", "repo": "r", "fork_issue_number": 13,
        })
        # Both correlation methods failed — do not guess, wait for PR body to be updated
        assert result["done"] is False
        assert result["status"] == "waiting_for_pr"
        assert result["pr_number"] is None

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_excludes_claimed_prs(self, mock_gh):
        """PRs already claimed by other assignments are excluded."""
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs (no commits inline)
            {"success": True, "output": json.dumps([
                {"number": 12, "headRefName": "copilot/fix-a",
                 "author": {"login": "app/copilot-swe-agent"}},
                {"number": 14, "headRefName": "copilot/fix-b",
                 "author": {"login": "app/copilot-swe-agent"}},
            ])},
            # commits fetch for PR#12
            {"success": True, "output": '["plan","impl"]'},
            # commits fetch for PR#14
            {"success": True, "output": '["plan"]'},
            # pr view headRefOid (for PR #14 — the only available one)
            {"success": True, "output": "abc123\n"},
            # check-runs — empty
            {"success": True, "output": "\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("13", {
            "my_user": "me", "repo": "r", "fork_issue_number": 13,
            "_claimed_pr_numbers": [12],  # PR#12 belongs to another issue
        })
        # PR#12 excluded, only PR#14 available (1 commit = working)
        assert result["done"] is False
        assert result["pr_number"] == 14
