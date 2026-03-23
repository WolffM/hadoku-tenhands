"""Tests for pipeline orchestrator — Stage 4a SWE agent dispatch/completion."""

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator
from tests.conftest import make_assignment, MockDispatcher


class TestOrchestratorSWECompletion:
    """Tests for SWE agent (4a) completion detection."""

    def test_advance_detects_swe_completion(self):
        swe = MockDispatcher(
            status_result={"done": True, "pr_number": 2, "pr_branch": "fix/bug"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "swe_agent_done"
        assert result["advanced"] is True
        assert assignment["stage4_status"] == "swe_agent_done"
        assert assignment["stage4_pr_number"] == 2

    def test_advance_returns_not_advanced_when_still_working(self):
        swe = MockDispatcher(
            status_result={"done": False, "status": "working", "pr_number": 2},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "swe_agent_working"
        assert result["advanced"] is False
