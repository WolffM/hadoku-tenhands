"""Tests for pipeline orchestrator — Stage 4.5 retrospective logging."""

from unittest.mock import MagicMock, patch

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator
from tests.conftest import make_assignment, MockDispatcher


class TestOrchestratorRetrospective:
    """Tests for retrospective logging (4.5)."""

    @patch.object(PipelineOrchestrator, "_fetch_workflow_analysis", return_value={
        "reproduced": True, "verified": True, "tool_installed": False,
        "code_review": True, "codeql": False, "self_corrected": False,
        "tools_used": ["ruff"], "step_count": 25,
    })
    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_logs_retrospective_and_finalizes(self, mock_gh, _mock_wf):
        """Retrospective collects metrics and advances to complete."""
        mock_gh.return_value = {"success": True, "output": "2\n"}

        mock_svc = MagicMock()
        swe = MockDispatcher(
            results_result={"success": True, "outputs": {
                "pr_number": 14, "additions": 20, "deletions": 5,
                "commit_count": 3,
            }},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe,
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
            oss_service=mock_svc,
        )
        assignment = make_assignment(
            stage4_status="remediation_done",
            stage4_pr_number=14,
            stage4_pr_branch="copilot/fix-bug",
            stage4_sa_run_id=99,
            stage4_sa_conclusion="failure",
            stage4d_skipped=False,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "retrospective_complete"
        assert result["advanced"] is True
        assert "retrospective" in result

        mock_svc.append_retrospective_log.assert_called_once()
        retro = mock_svc.append_retrospective_log.call_args[0][0]
        assert retro["swe"]["pr_number"] == 14
        assert retro["review"]["actionable"] is True
        assert retro["remediation"]["skipped"] is False
        assert retro["workflow"]["reproduced"] is True
        assert retro["workflow"]["code_review"] is True
        assert retro["workflow"]["step_count"] == 25
        assert "data_quality" in retro
        assert "context_tier" in retro["data_quality"]
        assert "context_sources" in retro["data_quality"]

    @patch.object(PipelineOrchestrator, "_fetch_workflow_analysis", return_value={})
    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_retrospective_without_service(self, mock_gh, _mock_wf):
        """Retrospective works without oss_service (no persistence)."""
        mock_gh.return_value = {"success": True, "output": "0\n"}
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="remediation_done",
            stage4_pr_number=14,
            stage4d_skipped=True,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "retrospective_complete"
        retro = result["retrospective"]
        assert retro["remediation"]["skipped"] is True
        assert retro["workflow"] == {}

    @patch.object(PipelineOrchestrator, "_fetch_workflow_analysis", return_value={})
    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_retrospective_includes_data_quality(self, mock_gh, _mock_wf):
        """Retrospective data_quality section reflects assignment metadata."""
        mock_gh.return_value = {"success": True, "output": "0\n"}
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="remediation_done",
            stage4_pr_number=14,
            stage4d_skipped=True,
            context_tier=2,
            context_sources=["aggregator-dossier", "gh-issue-view"],
            dossier_completeness={"score": 5, "total": 6},
            aggregator_meta={"dossier": {"scraped_at": "2026-02-24T00:00:00Z"}},
        )
        result = orch.advance(assignment, {"my_user": "me"})
        retro = result["retrospective"]
        dq = retro["data_quality"]
        assert dq["context_tier"] == 2
        assert "aggregator-dossier" in dq["context_sources"]
        assert dq["dossier_completeness"]["score"] == 5
        assert dq["aggregator_meta"]["dossier"]["scraped_at"] == "2026-02-24T00:00:00Z"
