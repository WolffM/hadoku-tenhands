"""Tests for pipeline orchestrator — shared structure, state machine, edge cases."""

from unittest.mock import MagicMock, patch

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator, PIPELINE_STATES
from tests.conftest import make_assignment, MockDispatcher


class TestPipelineStates:
    """Test that pipeline states are defined correctly."""

    def test_states_in_order(self):
        assert PIPELINE_STATES[0] == "swe_agent_working"
        assert PIPELINE_STATES[-1] == "retrospective_complete"
        assert len(PIPELINE_STATES) == 9


class TestOrchestratorEdgeCases:
    """Tests for edge cases and idempotency."""

    def test_advance_on_completed_is_noop(self):
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(stage4_status="retrospective_complete")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["advanced"] is False
        assert result["status"] == "retrospective_complete"

    def test_unknown_status_returns_error(self):
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(stage4_status="bogus_state")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is False
        assert "Unknown" in result.get("error", "")

    def test_state_persists_via_oss_service(self):
        """Verify the orchestrator calls update_assignment on the service."""
        mock_svc = MagicMock()
        swe = MockDispatcher(
            status_result={"done": True, "pr_number": 2, "pr_branch": "fix/x"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": MockDispatcher(),
                         "review": MockDispatcher(),
                         "remediation": MockDispatcher()},
            oss_service=mock_svc,
        )
        assignment = make_assignment()
        orch.advance(assignment, {"my_user": "me"})

        mock_svc.update_assignment.assert_called_once()
        call_args = mock_svc.update_assignment.call_args
        assert call_args[0][0] == "repo"
        assert call_args[0][1] == 1
        updates = call_args[0][2]
        assert updates["stage4_status"] == "swe_agent_done"
        assert updates["stage4_pr_number"] == 2
        assert updates["stage4_pr_branch"] == "fix/x"

    @patch.object(PipelineOrchestrator, "_fetch_workflow_analysis", return_value={})
    @patch("services.pipeline_orchestrator.run_gh_command")
    def test_full_pipeline_walk_with_skip(self, mock_gh, _mock_wf):
        """Walk through pipeline with 4d skipped (no inline comments)."""
        mock_gh.return_value = {"success": True, "output": "0\n"}

        swe = MockDispatcher(
            status_result={"done": True, "pr_number": 2, "pr_branch": "fix/x"},
        )
        sa = MockDispatcher(
            dispatch_result={"success": True, "job_id": "sa"},
            status_result={"done": True, "conclusion": "success", "run_id": 99},
        )
        review = MockDispatcher(
            dispatch_result={"success": True, "job_id": "rev"},
            status_result={"done": True, "review_state": "APPROVED"},
        )
        remediation = MockDispatcher()
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": sa,
                         "review": review, "remediation": remediation},
        )
        assignment = make_assignment()
        ctx = {"my_user": "me"}

        r1 = orch.advance(assignment, ctx)
        assert r1["status"] == "swe_agent_done"

        r2 = orch.advance(assignment, ctx)
        assert r2["status"] == "static_analysis_running"

        r3 = orch.advance(assignment, ctx)
        assert r3["status"] == "static_analysis_done"

        r4 = orch.advance(assignment, ctx)
        assert r4["status"] == "review_in_progress"

        r5 = orch.advance(assignment, ctx)
        assert r5["status"] == "review_complete"

        r6 = orch.advance(assignment, ctx)
        assert r6["status"] == "remediation_done"
        assert r6["skipped"] is True

        r7 = orch.advance(assignment, ctx)
        assert r7["status"] == "retrospective_complete"

        r8 = orch.advance(assignment, ctx)
        assert r8["advanced"] is False


class TestDispatcherSwappability:
    """Tests verifying dispatchers can be swapped without changing orchestrator."""

    def test_custom_dispatcher_works(self):
        """A completely custom dispatcher should work with the orchestrator."""
        from services.dispatchers import StageDispatcher

        class MyCustomSWE(StageDispatcher):
            def dispatch(self, job_spec, context):
                return {"success": True, "job_id": "custom-1"}

            def check_status(self, job_id, context):
                return {"done": True, "pr_number": 10, "pr_branch": "custom/branch"}

            def collect_results(self, job_id, context):
                return {"success": True, "outputs": {"custom": True}}

        orch = PipelineOrchestrator(
            dispatchers={
                "swe": MyCustomSWE(),
                "static_analysis": MockDispatcher(
                    dispatch_result={"success": True, "job_id": "sa"},
                ),
                "review": MockDispatcher(),
                "remediation": MockDispatcher(),
            },
        )
        assignment = make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["status"] == "swe_agent_done"
        assert assignment["stage4_pr_number"] == 10
        assert assignment["stage4_pr_branch"] == "custom/branch"
