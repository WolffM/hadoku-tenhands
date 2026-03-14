"""Tests for Stage 4 dispatchers — pluggable agent backends."""

import json
from unittest.mock import patch, MagicMock

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
            "commits": [{"sha": "a"}],
        }
        copilot_pr_b = {
            "number": 14, "title": "Fix B",
            "headRefName": "copilot/fix-b",
            "author": {"login": "app/copilot-swe-agent"},
            "commits": [{"sha": "b"}, {"sha": "c"}],
        }
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs
            {"success": True, "output": json.dumps([copilot_pr_a, copilot_pr_b])},
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
            # pr list — single Copilot PR with 2 commits
            {"success": True, "output": json.dumps([{
                "number": 12, "title": "Fix tests",
                "headRefName": "copilot/fix-tests",
                "author": {"login": "app/copilot-swe-agent"},
                "commits": [{"sha": "plan"}, {"sha": "impl"}],
            }])},
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
            {"success": True, "output": json.dumps([{
                "number": 12, "title": "Fix tests",
                "headRefName": "copilot/fix-tests",
                "author": {"login": "app/copilot-swe-agent"},
                "commits": [{"sha": "plan"}],
            }])},
            {"success": True, "output": "abc123\n"},
            {"success": True, "output": "\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("11", {"my_user": "me", "repo": "r"})
        assert result["done"] is False
        assert result["commit_count"] == 1

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_fallback_when_ambiguous(self, mock_gh):
        """With multiple Copilot PRs and failed timeline, falls back to most commits."""
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs
            {"success": True, "output": json.dumps([
                {"number": 12, "headRefName": "copilot/fix-a",
                 "author": {"login": "app/copilot-swe-agent"},
                 "commits": [{"sha": "plan"}]},
                {"number": 14, "headRefName": "copilot/fix-b",
                 "author": {"login": "app/copilot-swe-agent"},
                 "commits": [{"sha": "plan"}, {"sha": "impl"}]},
            ])},
            # timeline — fails
            {"success": False, "error": "timeout"},
            # pr view headRefOid (for PR #14 via fallback)
            {"success": True, "output": "abc123\n"},
            # check-runs — empty
            {"success": True, "output": "\n"},
        ]
        d = CopilotSWEDispatcher()
        result = d.check_status("13", {
            "my_user": "me", "repo": "r", "fork_issue_number": 13,
        })
        # PR#14 has 2 commits → done via commit count fallback
        assert result["done"] is True
        assert result["pr_number"] == 14

    @patch("services.dispatchers.run_gh_command")
    def test_check_status_excludes_claimed_prs(self, mock_gh):
        """PRs already claimed by other assignments are excluded."""
        mock_gh.side_effect = [
            # pr list — 2 Copilot PRs
            {"success": True, "output": json.dumps([
                {"number": 12, "headRefName": "copilot/fix-a",
                 "author": {"login": "app/copilot-swe-agent"},
                 "commits": [{"sha": "plan"}, {"sha": "impl"}]},
                {"number": 14, "headRefName": "copilot/fix-b",
                 "author": {"login": "app/copilot-swe-agent"},
                 "commits": [{"sha": "plan"}]},
            ])},
            # timeline — no cross-refs for this issue
            {"success": True, "output": "[]\n"},
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
        import time
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
