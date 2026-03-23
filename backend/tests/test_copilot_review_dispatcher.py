"""Tests for CopilotReviewDispatcher (Stage 4c)."""

from unittest.mock import patch

from services.dispatchers import CopilotReviewDispatcher


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
