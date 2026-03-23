"""Tests for pipeline orchestrator — Stage 4c review dispatch/completion."""

import time as _time

import pytest

from services.pipeline_orchestrator import PipelineOrchestrator
from tests.conftest import make_assignment, MockDispatcher


class TestOrchestratorReview:
    """Tests for review agent (4c) dispatch and completion."""

    def test_advance_dispatches_review(self):
        review = MockDispatcher(
            dispatch_result={"success": True, "job_id": "rev-1"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review,
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
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
                         "review": review,
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="review_in_progress",
            stage4_pr_number=5,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "review_complete"
        assert result["advanced"] is True

    def test_review_dispatch_saves_timestamp(self):
        review = MockDispatcher(
            dispatch_result={"success": True, "job_id": "rev-1"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review,
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="static_analysis_done",
            stage4_pr_number=5,
        )
        orch.advance(assignment, {"my_user": "me"})
        assert "stage4_review_dispatched_at" in assignment

    def test_review_timeout_after_10_minutes(self):
        """Review times out after 10 minutes with no Copilot review."""
        review = MockDispatcher(
            status_result={"done": False, "status": "waiting_for_review"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review,
                         "remediation": MockDispatcher()},
        )
        assignment = make_assignment(
            stage4_status="review_in_progress",
            stage4_pr_number=5,
            stage4_review_dispatched_at="2020-01-01T00:00:00Z",
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "review_complete"
        assert result["advanced"] is True
        assert assignment.get("stage4_review_timed_out") is True

    def test_review_no_timeout_when_recent(self):
        """Review does not timeout when dispatched recently."""
        review = MockDispatcher(
            status_result={"done": False, "status": "waiting_for_review"},
        )
        orch = PipelineOrchestrator(
            dispatchers={"swe": MockDispatcher(),
                         "static_analysis": MockDispatcher(),
                         "review": review,
                         "remediation": MockDispatcher()},
        )
        now_iso = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        assignment = make_assignment(
            stage4_status="review_in_progress",
            stage4_pr_number=5,
            stage4_review_dispatched_at=now_iso,
        )
        result = orch.advance(assignment, {"my_user": "me"})

        assert result["success"] is True
        assert result["status"] == "review_in_progress"
        assert result["advanced"] is False
