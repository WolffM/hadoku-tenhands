"""Pytest configuration — add backend/ to sys.path so tests can import modules."""

import sys
import os

import pytest

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def clean_data_dir(tmp_path, monkeypatch):
    """Point OSS_DATA_DIR to a temp directory for each test."""
    monkeypatch.setattr("services.oss_service.OSS_DATA_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# Shared helpers for pipeline orchestrator tests
# ---------------------------------------------------------------------------

from services.dispatchers import StageDispatcher  # noqa: E402


def make_assignment(**overrides):
    """Create a test assignment dict with sensible defaults."""
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
