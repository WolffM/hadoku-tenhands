"""Tests for the pipeline orchestrator — state machine for Stage 4."""

import json
from unittest.mock import patch, MagicMock, call

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator, PIPELINE_STATES
from services.dispatchers import (
    StageDispatcher,
    CopilotSWEDispatcher,
    GitHubActionsDispatcher,
    CopilotReviewDispatcher,
)


def _make_assignment(**overrides):
    """Helper to create a test assignment dict."""
    base = {
        "origin_slug": "org/repo",
        "repo": "repo",
        "issue_number": 42,
        "fork_issue_number": 1,
        "fork_issue_url": "https://github.com/me/repo/issues/1",
        "is_self_owned": False,
        "default_branch": "main",
        "assigned_at": "2026-02-26T00:00:00Z",
    }
    base.update(overrides)
    return base


class MockDispatcher(StageDispatcher):
    """A simple mock dispatcher for testing the orchestrator."""

    def __init__(self, dispatch_result=None, status_result=None, results_result=None):
        self._dispatch = dispatch_result or {"success": True, "job_id": "test"}
        self._status = status_result or {"done": False, "status": "working"}
        self._results = results_result or {"success": True, "outputs": {}}

    def dispatch(self, job_spec, context):
        return self._dispatch

    def check_status(self, job_id, context):
        return self._status

    def collect_results(self, job_id, context):
        return self._results


class TestPipelineStates:
    """Test that pipeline states are defined correctly."""

    def test_states_in_order(self):
        assert PIPELINE_STATES[0] == "swe_agent_working"
        assert PIPELINE_STATES[-1] == "review_complete"
        assert len(PIPELINE_STATES) == 6


class TestOrchestratorSWECompletion:
    """Tests for SWE agent (4a) completion detection."""

    def test_advance_detects_swe_completion(self):
        swe = MockDispatcher(
            status_result={"done": True, "pr_number": 2, "pr_branch": "fix/bug"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": MockDispatcher(),
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "swe_agent_done"
        assert result["advanced"] is True
        # In-memory assignment should be updated
        assert assignment["stage4_status"] == "swe_agent_done"
        assert assignment["stage4_pr_number"] == 2

    def test_advance_returns_not_advanced_when_still_working(self):
        swe = MockDispatcher(
            status_result={"done": False, "status": "working", "pr_number": 2},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": MockDispatcher(),
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "swe_agent_working"
        assert result["advanced"] is False


class TestOrchestratorStaticAnalysis:
    """Tests for static analysis (4b) dispatch and completion."""

    def test_advance_dispatches_static_analysis(self):
        sa = MockDispatcher(
            dispatch_result={"success": True, "job_id": "sa-1"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(), "static_analysis": sa,
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment(
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
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment(stage4_status="static_analysis_running")
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
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment(stage4_status="swe_agent_done")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is False
        assert "error" in result


class TestOrchestratorReview:
    """Tests for review agent (4c) dispatch and completion."""

    def test_advance_dispatches_review(self):
        review = MockDispatcher(
            dispatch_result={"success": True, "job_id": "rev-1"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review},
        )
        assignment = _make_assignment(
            stage4_status="static_analysis_done",
            stage4_pr_number=5,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "review_in_progress"
        assert result["advanced"] is True

    def test_advance_detects_review_completion(self):
        review = MockDispatcher(
            status_result={"done": True, "review_state": "APPROVED"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review},
        )
        assignment = _make_assignment(
            stage4_status="review_in_progress",
            stage4_pr_number=5,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "review_complete"
        assert result["advanced"] is True


class TestOrchestratorEdgeCases:
    """Tests for edge cases and idempotency."""

    def test_advance_on_completed_is_noop(self):
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment(stage4_status="review_complete")
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["advanced"] is False
        assert result["status"] == "review_complete"

    def test_unknown_status_returns_error(self):
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": MockDispatcher()},
        )
        assignment = _make_assignment(stage4_status="bogus_state")
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
                         "review": MockDispatcher()},
            oss_service=mock_svc,
        )
        assignment = _make_assignment()
        orch.advance(assignment, {"my_user": "me"})

        mock_svc.update_assignment.assert_called_once_with(
            "repo", 1,
            {"stage4_status": "swe_agent_done",
             "stage4_pr_number": 2,
             "stage4_pr_branch": "fix/x"},
        )

    def test_full_pipeline_walk(self):
        """Walk through the entire pipeline from start to finish."""
        # Each dispatcher returns "done" on check_status
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
        orch = PipelineOrchestrator(
            dispatchers={"swe": swe, "static_analysis": sa, "review": review},
        )
        assignment = _make_assignment()
        ctx = {"my_user": "me"}

        # Step 1: swe_agent_working → swe_agent_done
        r1 = orch.advance(assignment, ctx)
        assert r1["status"] == "swe_agent_done"

        # Step 2: swe_agent_done → static_analysis_running
        r2 = orch.advance(assignment, ctx)
        assert r2["status"] == "static_analysis_running"

        # Step 3: static_analysis_running → static_analysis_done
        r3 = orch.advance(assignment, ctx)
        assert r3["status"] == "static_analysis_done"

        # Step 4: static_analysis_done → review_in_progress
        r4 = orch.advance(assignment, ctx)
        assert r4["status"] == "review_in_progress"

        # Step 5: review_in_progress → review_complete
        r5 = orch.advance(assignment, ctx)
        assert r5["status"] == "review_complete"

        # Step 6: review_complete → no-op
        r6 = orch.advance(assignment, ctx)
        assert r6["advanced"] is False


class TestDispatcherSwappability:
    """Tests verifying dispatchers can be swapped without changing orchestrator."""

    def test_custom_dispatcher_works(self):
        """A completely custom dispatcher should work with the orchestrator."""

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
            },
        )
        assignment = _make_assignment()
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["status"] == "swe_agent_done"
        assert assignment["stage4_pr_number"] == 10
        assert assignment["stage4_pr_branch"] == "custom/branch"
