"""Pytest configuration — add backend/ to sys.path so tests can import modules."""

import os
import socket
import subprocess
import sys

import pytest

# Add the backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# `import app` starts the background pipeline loop, whose first tick (10s in)
# calls the real `gh api user` and then advances whatever assignments it finds
# — from a daemon thread, inside whichever test happens to be running then.
# Set before any test module imports `app`.
os.environ["PIPELINE_LOOP_ENABLED"] = "false"

import helpers.notifications as _notifications  # noqa: E402


@pytest.fixture(autouse=True)
def suppress_outbound_notifications(monkeypatch):
    """Stop any test reaching a real notification sink.

    Forcibly clears both destinations, regardless of what is set in the
    environment. Tests that need to verify payloads explicitly `@patch` the
    module constant back — their decorators run after this fixture and
    override it.

    **Two sinks, not one.** `DISCORD_WEBHOOK_URL` was the original, and for a
    while it was the only one. `send_discord_notification` later grew a mirror
    into monitoring-api's event ledger, gated on `HADOKU_SERVICE_KEY` and
    deliberately independent of the Discord webhook — so clearing the webhook
    alone stopped covering it, silently.

    That gap was real, not theoretical. Run the suite with the vault
    credentials loaded (`dev-vault.mjs -- pytest`, which is the only way to run
    it with zero skips) and three notifications escaped to the live telemetry
    endpoint: two "Upstream PR Submitted" and one "Upstream PR Merged!", none
    of which happened. Fake alerts in the sitrep are worse than no alerts,
    because they are indistinguishable from real ones at the point somebody is
    trusting the dashboard.

    It also made ten tests fail whenever a service key was present, since the
    mirror and the webhook post through the *same* `requests.post` the tests
    mock, so `assert_not_called` saw the mirror's call. A test that passes only
    when a credential is absent is not testing what it claims to.

    Any future sink needs a line here too.
    """
    monkeypatch.setattr(_notifications, "DISCORD_WEBHOOK_URL", "")
    monkeypatch.setattr(_notifications, "HADOKU_SERVICE_KEY", "")


# Executables that talk to GitHub or Anthropic. The two scripts are listed
# because they shell out to `gh` themselves, in a child process this guard
# cannot see into.
_EGRESS_EXECUTABLES = {"gh", "claude"}
_EGRESS_SCRIPTS = {"copilot-sessions.py", "disable-copilot-firewall.py"}
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_egress: the test deliberately reaches GitHub/Claude/the network "
        "and is exempt from the no_real_egress guard",
    )


def _egress_target(argv):
    """The part of a subprocess argv that makes it egress, or None."""
    if isinstance(argv, (str, bytes, os.PathLike)):
        argv = [argv]
    argv = [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in argv]
    if not argv:
        return None
    if os.path.basename(argv[0]) in _EGRESS_EXECUTABLES:
        return " ".join(argv[:4])
    for arg in argv[1:3]:
        if os.path.basename(arg) in _EGRESS_SCRIPTS:
            return " ".join(argv[:3])
    return None


@pytest.fixture(autouse=True)
def no_real_egress(request, monkeypatch):
    """Fail any test that reaches `gh`, `claude` or a non-loopback socket.

    Unit tests that shell out to the real `gh` pass or fail with the state of
    the fleet's *shared* GitHub quota, not the code under test (#110:
    `TestForkAndAssign` read `gh api rate_limit`, got 0, and the required
    `backend pytest` check went red twice). Most such leaks don't fail loudly
    — `run_gh_command` turns a dead `gh` into `success: False`, which several
    code paths tolerate — so a leak sits unnoticed until the quota runs out.

    The attempt is refused *and* recorded, and the test fails at teardown even
    if the code under test swallowed the refusal. Stub `run_gh_command` (or
    whatever the call site is) instead. The one test that is meant to reach
    the real Claude CLI carries `@pytest.mark.real_egress`.
    """
    if request.node.get_closest_marker("real_egress"):
        yield
        return

    attempts = []

    def refuse(what):
        attempts.append(what)
        raise PermissionError(f"test reached real egress without a stub: {what}")

    real_popen_init = subprocess.Popen.__init__

    def guarded_popen_init(self, args, *a, **kw):
        target = _egress_target(args)
        if target:
            refuse(f"subprocess `{target}`")
        real_popen_init(self, args, *a, **kw)

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def check_addr(sock, addr):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and addr[0] not in _LOOPBACK:
            refuse(f"socket connect to {addr[0]}:{addr[1]}")

    def guarded_connect(self, addr):
        check_addr(self, addr)
        return real_connect(self, addr)

    def guarded_connect_ex(self, addr):
        check_addr(self, addr)
        return real_connect_ex(self, addr)

    monkeypatch.setattr(subprocess.Popen, "__init__", guarded_popen_init)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
    if attempts:
        pytest.fail("test reached real egress without a stub:\n  " + "\n  ".join(attempts),
                    pytrace=False)


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

    monkeypatch.setattr(_app, "resolve_caller", lambda _key: ("admin", True))


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


_GH_OFFLINE = {"success": False, "output": "", "error": "stubbed: no GitHub in unit tests"}


@pytest.fixture
def offline_orchestrator(monkeypatch):
    """Keep the orchestrator's side calls to GitHub inside the test.

    `MockDispatcher` replaces the stage dispatchers, but `advance()` still
    makes calls of its own around them — closing stale Copilot PRs, counting
    inline comments, building the remediation context, and the retrospective's
    job/annotation, comment, session-log and diff fetches — each through its
    own module's `run_gh_command` binding (or a `copilot-sessions.py`
    subprocess). Unstubbed, those ran against the real `me/repo`, whose 404
    the code tolerates, so they passed while spending shared quota.

    This gives each the answer that 404 used to: a failed gh call, an empty
    log, an empty diff. Tests that need real-looking responses still
    `@patch` the seam themselves; their decorators apply after this fixture.
    Opt in per module with ``pytestmark = pytest.mark.usefixtures("offline_orchestrator")``.
    """
    for module in ("services.pipeline_orchestrator",
                   "services.pipeline_retrospective",
                   "services.pipeline_context_builders"):
        monkeypatch.setattr(f"{module}.run_gh_command", lambda *a, **kw: dict(_GH_OFFLINE))
    monkeypatch.setattr("services.pipeline_retrospective.fetch_session_log", lambda *a, **kw: "")
    monkeypatch.setattr("services.pipeline_retrospective.fetch_fork_diff", lambda *a, **kw: "")


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
