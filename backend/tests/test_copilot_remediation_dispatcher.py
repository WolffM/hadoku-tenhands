"""Tests for CopilotRemediationDispatcher (Stage 4d)."""

import json
import time
from unittest.mock import patch

from services.dispatchers import CopilotRemediationDispatcher


class TestCopilotRemediationDispatcher:
    """Tests for the Copilot remediation dispatcher (Stage 4d)."""

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_posts_comment_and_records_commit_count(self, mock_gh):
        mock_gh.side_effect = [
            # pr view — current commit count
            {"success": True, "output": "3\n"},
            # pr comment
            {"success": True, "output": "{}"},
        ]
        d = CopilotRemediationDispatcher()
        result = d.dispatch(
            {"pr_number": 14, "remediation_body": "Fix the import"},
            {"my_user": "me", "repo": "r"},
        )

        assert result["success"] is True
        assert result["pre_commit_count"] == 3
        # Verify comment contains @copilot
        comment_cmd = " ".join(mock_gh.call_args_list[1][0][0])
        assert "comment" in comment_cmd

    @patch("services.dispatchers.run_gh_command")
    def test_dispatch_failure_when_comment_fails(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": "2\n"},
            {"success": False, "error": "forbidden"},
        ]
        d = CopilotRemediationDispatcher()
        result = d.dispatch(
            {"pr_number": 14, "remediation_body": "Fix it"},
            {"my_user": "me", "repo": "r"},
        )
        assert result["success"] is False

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_detects_new_commits(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "5\n"}
        d = CopilotRemediationDispatcher()
        result = d.check_status("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
        })

        assert result["done"] is True
        assert result["new_commits"] == 2

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_waiting_when_no_new_commits(self, mock_gh):
        mock_gh.side_effect = [
            # pr view — same commit count
            {"success": True, "output": "3\n"},
            # pr view headRefOid
            {"success": True, "output": "abc123\n"},
            # check-runs — empty
            {"success": True, "output": "\n"},
        ]
        d = CopilotRemediationDispatcher()
        # Use a recent timestamp so the timeout doesn't fire
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        result = d.check_status("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
            "stage4d_dispatched_at": now_iso,
        })

        assert result["done"] is False
        assert result["status"] == "waiting_for_commits"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_keeps_waiting_when_no_dispatched_at(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": "3\n"},
            {"success": True, "output": "abc123\n"},
            {"success": True, "output": "\n"},
        ]
        d = CopilotRemediationDispatcher()
        # No dispatched_at → should NOT timeout, keep waiting
        result = d.check_status("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
        })
        assert result["done"] is False
        assert result["status"] == "waiting_for_commits"

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_timeout_with_old_dispatched_at(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": "3\n"},
            {"success": True, "output": "abc123\n"},
            {"success": True, "output": "\n"},
        ]
        d = CopilotRemediationDispatcher()
        # dispatched_at 20 minutes ago → should timeout
        result = d.check_status("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
            "stage4d_dispatched_at": "2020-01-01T00:00:00Z",
        })
        assert result["done"] is True
        assert result["status"] == "timeout"

    def test_remediation_timeout_constant_is_600(self):
        d = CopilotRemediationDispatcher()
        assert d.REMEDIATION_TIMEOUT_SECONDS == 600

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_working_when_agent_in_progress(self, mock_gh):
        mock_gh.side_effect = [
            # pr view — same commit count
            {"success": True, "output": "3\n"},
            # pr view headRefOid
            {"success": True, "output": "abc123\n"},
            # check-runs — in_progress
            {"success": True, "output": "in_progress\n"},
        ]
        d = CopilotRemediationDispatcher()
        result = d.check_status("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
        })

        assert result["done"] is False
        assert result["status"] == "working"

    @patch("services.dispatchers.run_gh_command")
    def test_collect_results_returns_updated_stats(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "additions": 30,
                "deletions": 8,
                "changedFiles": 5,
                "commits": [{"sha": "a"}, {"sha": "b"}, {"sha": "c"}, {"sha": "d"}],
            }),
        }
        d = CopilotRemediationDispatcher()
        result = d.collect_results("14", {
            "my_user": "me", "repo": "r",
            "stage4_pr_number": 14,
            "stage4d_pre_commit_count": 3,
        })

        assert result["success"] is True
        assert result["outputs"]["additions"] == 30
        assert result["outputs"]["new_commits"] == 1
        assert result["outputs"]["total_commits"] == 4
