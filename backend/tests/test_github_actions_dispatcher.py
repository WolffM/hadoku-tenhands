"""Tests for GitHubActionsDispatcher (Stage 4b)."""

import json
from unittest.mock import patch

from services.dispatchers import GitHubActionsDispatcher


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
    def test_collect_results_returns_findings(self, mock_gh):
        mock_gh.side_effect = [
            # jobs API
            {"success": True, "output": json.dumps([
                {"name": "ruff", "conclusion": "failure", "id": 101},
            ])},
            # annotations API for job 101
            {"success": True, "output": json.dumps([
                {"path": "src/app.py", "start_line": 10,
                 "annotation_level": "error",
                 "message": "ruff: 3 errors found"},
            ])},
        ]
        d = GitHubActionsDispatcher()
        result = d.collect_results("id", {
            "my_user": "me", "repo": "r", "stage4_sa_run_id": 12345,
        })

        assert result["success"] is True
        assert "ruff" in result["outputs"]["findings"]

    def test_custom_workflow_name(self):
        d = GitHubActionsDispatcher(workflow_name="custom-ci.yml")
        assert d.workflow_name == "custom-ci.yml"
