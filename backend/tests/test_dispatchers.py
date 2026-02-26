"""Tests for Stage 4 dispatchers — pluggable agent backends."""

import json
from unittest.mock import patch, MagicMock

import pytest

from services.dispatchers import (
    StageDispatcher,
    CopilotSWEDispatcher,
    GitHubActionsDispatcher,
    CopilotReviewDispatcher,
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
        assert isinstance(registry["swe"], CopilotSWEDispatcher)
        assert isinstance(registry["static_analysis"], GitHubActionsDispatcher)
        assert isinstance(registry["review"], CopilotReviewDispatcher)


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
            # pr list — Copilot PR found
            {"success": True, "output": json.dumps([{
                "number": 2,
                "title": "Fix bug",
                "headRefName": "copilot/fix-bug",
                "author": {"login": "app/copilot-swe-agent"},
                "commits": [{"sha": "a"}, {"sha": "b"}],
            }])},
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
            # pr list
            {"success": True, "output": json.dumps([{
                "number": 2,
                "title": "Fix bug",
                "headRefName": "copilot/fix-bug",
                "author": {"login": "app/copilot-swe-agent"},
                "commits": [{"sha": "a"}],
            }])},
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


class TestGitHubActionsDispatcher:
    """Tests for the GitHub Actions dispatcher (Stage 4b)."""

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_triggers_workflow(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": ""}
        d = GitHubActionsDispatcher()
        result = d.dispatch(
            {"branch": "copilot/fix-bug"},
            {"my_user": "me", "repo": "r"},
        )

        assert result["success"] is True
        cmd = mock_gh.call_args[0][0]
        assert "workflow" in cmd
        assert "run" in cmd
        assert "static-analysis.yml" in cmd
        assert "ref=copilot/fix-bug" in " ".join(cmd)

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "workflow not found"}
        d = GitHubActionsDispatcher()
        result = d.dispatch(
            {"branch": "main"},
            {"my_user": "me", "repo": "r"},
        )
        assert result["success"] is False

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_completed(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "databaseId": 12345,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-02-26T00:00:00Z",
            }]),
        }
        d = GitHubActionsDispatcher()
        result = d.check_status("id", {"my_user": "me", "repo": "r"})

        assert result["done"] is True
        assert result["conclusion"] == "success"
        assert result["run_id"] == 12345

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_in_progress(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "databaseId": 12345,
                "status": "in_progress",
                "conclusion": None,
                "createdAt": "2026-02-26T00:00:00Z",
            }]),
        }
        d = GitHubActionsDispatcher()
        result = d.check_status("id", {"my_user": "me", "repo": "r"})

        assert result["done"] is False
        assert result["status"] == "in_progress"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_no_runs(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "[]"}
        d = GitHubActionsDispatcher()
        result = d.check_status("id", {"my_user": "me", "repo": "r"})

        assert result["done"] is False
        assert result["status"] == "not_found"

    @patch("services.dispatchers.run_gh_command")
    def test_collect_results_returns_logs(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": "test output\nruff: 3 errors found\n",
        }
        d = GitHubActionsDispatcher()
        result = d.collect_results("id", {
            "my_user": "me", "repo": "r", "stage4_sa_run_id": 12345,
        })

        assert result["success"] is True
        assert "ruff" in result["outputs"]["findings"]

    def test_custom_workflow_name(self):
        d = GitHubActionsDispatcher(workflow_name="custom-ci.yml")
        assert d.workflow_name == "custom-ci.yml"


class TestCopilotReviewDispatcher:
    """Tests for the Copilot review dispatcher (Stage 4c)."""

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_posts_comment_and_requests_review(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        d = CopilotReviewDispatcher()
        result = d.dispatch(
            {"pr_number": 5, "review_context": "Check for style issues"},
            {"my_user": "me", "repo": "r"},
        )

        assert result["success"] is True
        # Should make 2 calls: PR comment + request review
        assert mock_gh.call_count == 2
        # First call: PR comment
        comment_cmd = " ".join(mock_gh.call_args_list[0][0][0])
        assert "pr" in comment_cmd
        assert "comment" in comment_cmd
        # Second call: request reviewer
        review_cmd = " ".join(mock_gh.call_args_list[1][0][0])
        assert "requested_reviewers" in review_cmd

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_without_context_skips_comment(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        d = CopilotReviewDispatcher()
        result = d.dispatch(
            {"pr_number": 5, "review_context": ""},
            {"my_user": "me", "repo": "r"},
        )

        assert result["success"] is True
        # Only 1 call: request review (no comment for empty context)
        assert mock_gh.call_count == 1

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_finds_copilot_review(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": '{"user":"copilot-pull-request-reviewer[bot]","state":"APPROVED","body":"LGTM"}\n',
        }
        d = CopilotReviewDispatcher()
        result = d.check_status("id", {
            "my_user": "me", "repo": "r", "stage4_pr_number": 5,
        })

        assert result["done"] is True
        assert result["review_state"] == "APPROVED"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_waiting_when_no_review(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "\n"}
        d = CopilotReviewDispatcher()
        result = d.check_status("id", {
            "my_user": "me", "repo": "r", "stage4_pr_number": 5,
        })

        assert result["done"] is False
        assert result["status"] == "waiting_for_review"

    @patch("services.dispatchers.run_gh_command")
    def test_collect_results_returns_review_details(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": '{"user":"copilot-pull-request-reviewer[bot]","state":"CHANGES_REQUESTED","body":"Please fix X"}\n',
        }
        d = CopilotReviewDispatcher()
        result = d.collect_results("id", {
            "my_user": "me", "repo": "r", "stage4_pr_number": 5,
        })

        assert result["success"] is True
        assert result["outputs"]["review_state"] == "CHANGES_REQUESTED"
        assert "fix X" in result["outputs"]["review_body"]
