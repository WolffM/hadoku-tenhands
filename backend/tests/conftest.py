"""Pytest configuration — add backend/ to sys.path so tests can import modules."""

import sys
import os

import pytest

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import helpers.notifications as _notifications  # noqa: E402


@pytest.fixture(autouse=True)
def suppress_discord(monkeypatch):
    """Suppress Discord notifications during test runs.

    Forcibly clears DISCORD_WEBHOOK_URL so no test fires a real webhook,
    regardless of what's set in the environment. Tests that need to
    verify webhook payloads explicitly `@patch("helpers.notifications.
    DISCORD_WEBHOOK_URL", ...)` + `@patch("helpers.notifications.
    requests.post")` — their decorators run after this fixture and
    override it.
    """
    monkeypatch.setattr(_notifications, "DISCORD_WEBHOOK_URL", "")


@pytest.fixture(autouse=True)
def clean_data_dir(tmp_path, monkeypatch):
    """Point OSS_DATA_DIR to a temp directory for each test."""
    monkeypatch.setattr("services.oss_service.OSS_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def admit_authed_by_default(monkeypatch):
    """Neutralize the global tier gate (``app._enforce_tier``) for the route
    suite.

    The gate treats keyless requests as ``public`` → 401/403. The
    route-behavior tests predate it and send no ``X-User-Key``, so patch the
    resolver to admit by default here. ``test_auth_gate.py`` overrides this
    fixture with a no-op to exercise the real gate.
    """
    import app as _app

    monkeypatch.setattr(_app, "resolve_tier_from_key", lambda _key: "admin")


@pytest.fixture(autouse=True)
def no_real_judge_title(monkeypatch):
    """Force `generate_title` to the JudgeUnreachable fallback in every test.

    `submission.render_pr_body` calls the haiku judge's `generate_title`,
    which spawns a real `claude` CLI subprocess whenever
    CLAUDE_CODE_OAUTH_TOKEN is present (e.g. when the suite is run through the
    dev-vault wrapper). That makes the unit/e2e suite slow and
    non-deterministic — the generated title text varies per call. The suite
    already mocks the gate judges at their import sites; this does the same
    for `generate_title`, so results don't depend on whether a token is in
    the environment. Real `generate_title` / `score` coverage lives in
    tests/temporal/test_judge.py, which calls them directly and is unaffected
    by this stub (it patches the source module's name; the integration test
    invokes `score`).
    """
    import temporal.judge as judge

    def _unreachable(*args, **kwargs):
        raise judge.JudgeUnreachable("generate_title stubbed in unit tests")

    monkeypatch.setattr(judge, "generate_title", _unreachable)


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
