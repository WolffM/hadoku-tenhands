"""Tests for pipeline orchestrator — Stage 4b static analysis dispatch/completion."""

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator
from tests.conftest import make_assignment, MockDispatcher


class TestOrchestratorStaticAnalysis:
    """Tests for static analysis (4b) dispatch and completion."""

    def test_advance_dispatches_static_analysis(self):
        sa = MockDispatcher(
            dispatch_result={"success": True, "job_id": "sa-1"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(), "static_analysis": sa,
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="swe_agent_done",
            stage4_pr_branch="copilot/fix-bug",
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "static_analysis_running"
        assert result["advanced"] is True

    def test_advance_detects_static_analysis_completion(self):
        sa = MockDispatcher(
            status_result={"done": True, "conclusion": "success", "run_id": 123},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(), "static_analysis": sa,
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(stage4_status="static_analysis_running")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "static_analysis_done"
        assert result["advanced"] is True
        assert assignment["stage4_sa_run_id"] == 123

    def test_static_analysis_dispatch_failure(self):
        sa = MockDispatcher(
            dispatch_result={"success": False, "error": "workflow not found"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(), "static_analysis": sa,
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(stage4_status="swe_agent_done")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is False
        assert "error" in result
