"""Tests for pipeline orchestrator — Stage 4d remediation dispatch/skip logic."""

from unittest.mock import patch

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator
from tests.conftest import make_assignment, MockDispatcher


class TestOrchestratorRemediation:
    """Tests for remediation (4d) dispatch and skip logic."""

    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_skips_remediation_when_no_inline_comments(self, mock_gh):
        """When review has 0 inline comments, skip 4d."""
        mock_gh.return_value = {"success": True, "output": "0\n"}
        remediation = MockDispatcher()
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": remediation},
        )
        assignment = make_assignment(
            stage4_status="review_complete", stage4_pr_number=12,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "remediation_done"
        assert result["skipped"] is True
        assert assignment["stage4d_skipped"] is True

    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_dispatches_remediation_when_inline_comments_exist(self, mock_gh):
        """When review has inline comments, dispatch 4d."""
        mock_gh.side_effect = [
            {"success": True, "output": "3\n"},
            {"success": True, "output": "- `file.py:10`: Fix import\n"},
        ]
        remediation = MockDispatcher(
            dispatch_result={"success": True, "job_id": "14",
                             "pre_commit_count": 2},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": remediation},
        )
        assignment = make_assignment(
            stage4_status="review_complete", stage4_pr_number=14,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "remediation_running"
        assert assignment["stage4d_skipped"] is False

    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_check_remediation_completion(self, mock_gh):
        """Remediation done when dispatcher says done."""
        remediation = MockDispatcher(
            status_result={"done": True, "new_commits": 1},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": remediation},
        )
        assignment = make_assignment(
            stage4_status="remediation_running",
            stage4_pr_number=14,
            stage4d_pre_commit_count=3,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "remediation_done"
        assert result["advanced"] is True

    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_check_remediation_still_working(self, mock_gh):
        """Remediation not done yet."""
        remediation = MockDispatcher(
            status_result={"done": False, "status": "waiting_for_commits"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": remediation},
        )
        assignment = make_assignment(
            stage4_status="remediation_running",
            stage4_pr_number=14,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "remediation_running"
        assert result["advanced"] is False
