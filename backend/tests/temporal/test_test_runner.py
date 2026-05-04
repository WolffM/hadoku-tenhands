"""Tests for the test-runner activity (Phase 5.6).

Covers the read-command → dispatch → persist-output pipeline. Uses a
stub `dispatch` callable to avoid needing a real cktest runner up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from temporal.evidence.store import EvidenceStore


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _stub_dispatch(captured: list[dict], **canned_response: Any):
    """Build a dispatch stub that captures inputs and returns canned bytes."""
    response = canned_response if canned_response else {
        "stdout": "PASS\nok 0.04s",
        "stderr": "",
        "exit_code": 0,
        "duration_ms": 1234,
    }

    def _dispatch(runner_url, fork_slug, branch, command, timeout_s):
        captured.append({
            "runner_url": runner_url,
            "fork_slug": fork_slug,
            "branch": branch,
            "command": command,
            "timeout_s": timeout_s,
        })
        return response

    return _dispatch


def test_run_test_command_happy_path(ev):
    """test_command.txt exists → dispatch called with correct args →
    stdout written to 06-verified/test_output.txt."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "go test ./middleware/logger/... -v\n")

    captured: list[dict] = []
    result = run_test_command(
        ev,
        fork_slug="WolffM/gofiber-fiber",
        branch_name="crimson-kitty-4226",
        runner_url="http://test:5500",
        dispatch=_stub_dispatch(captured),
    )

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["bytes"] > 0
    assert result["duration_ms"] == 1234
    # Output persisted at the canonical path
    assert ev.exists("06-verified/test_output.txt")
    assert "PASS" in ev.read_text("06-verified/test_output.txt")
    # Dispatch received the right command + slug
    assert len(captured) == 1
    call = captured[0]
    assert call["runner_url"] == "http://test:5500"
    assert call["fork_slug"] == "WolffM/gofiber-fiber"
    assert call["branch"] == "crimson-kitty-4226"
    assert call["command"] == "go test ./middleware/logger/... -v"


def test_run_test_command_returns_failure_when_no_command_file(ev):
    """Workflow shouldn't crash if Copilot didn't write the command.
    Activity returns ok=False; downstream falls back to text-only verify."""
    from temporal.activities.test_runner import run_test_command

    captured: list[dict] = []
    result = run_test_command(
        ev,
        fork_slug="WolffM/x",
        branch_name="crimson-kitty-1",
        dispatch=_stub_dispatch(captured),
    )

    assert result["ok"] is False
    assert "no test_command" in result["reason"]
    assert len(captured) == 0  # dispatch never called
    assert not ev.exists("06-verified/test_output.txt")


def test_run_test_command_returns_failure_when_command_empty(ev):
    """Whitespace-only command file is a no-op same as missing."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "   \n  \t\n")

    captured: list[dict] = []
    result = run_test_command(
        ev,
        fork_slug="WolffM/x",
        branch_name="crimson-kitty-1",
        dispatch=_stub_dispatch(captured),
    )

    assert result["ok"] is False
    assert "empty" in result["reason"]
    assert len(captured) == 0


def test_run_test_command_takes_first_nonempty_line_only(ev):
    """If Copilot accidentally committed multi-line prose, we only run
    the first executable-looking line — defense against agent variance."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text(
        "05-fixed/test_command.txt",
        "pytest tests/test_x.py -v\n"
        "Run this to verify the fix.\n"
        "It tests the corrected behavior.\n",
    )

    captured: list[dict] = []
    run_test_command(
        ev, fork_slug="WolffM/x", branch_name="b", dispatch=_stub_dispatch(captured),
    )

    assert captured[0]["command"] == "pytest tests/test_x.py -v"


def test_run_test_command_handles_dispatch_exception(ev):
    """Network/HTTP failure → ok=False with the underlying error.
    Workflow proceeds without crashing; runner outage is non-fatal."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "pytest")

    def boom(runner_url, fork_slug, branch, command, timeout_s):
        raise ConnectionRefusedError("runner not up")

    result = run_test_command(
        ev, fork_slug="WolffM/x", branch_name="b", dispatch=boom,
    )

    assert result["ok"] is False
    assert "runner unreachable" in result["reason"]
    assert "ConnectionRefusedError" in result["reason"]
    assert not ev.exists("06-verified/test_output.txt")


def test_run_test_command_treats_runner_internal_error_as_failure(ev):
    """Runner returns 200 but with `error` field → activity surfaces it
    as a failure rather than persisting an empty/garbage output."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "pytest")

    captured: list[dict] = []
    result = run_test_command(
        ev,
        fork_slug="WolffM/x", branch_name="b",
        dispatch=_stub_dispatch(captured, error="failed to install dependencies"),
    )

    assert result["ok"] is False
    assert "failed to install dependencies" in result["reason"]
    assert not ev.exists("06-verified/test_output.txt")


def test_run_test_command_merges_stderr_when_distinct_from_stdout(ev):
    """Most test runners write to both streams. If the runner returns
    distinct stdout + stderr, we merge them with a clear separator so
    the screenshot has both."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "pytest")

    captured: list[dict] = []
    run_test_command(
        ev, fork_slug="WolffM/x", branch_name="b",
        dispatch=_stub_dispatch(
            captured,
            stdout="PASS: 5 tests passed",
            stderr="warning: deprecated API",
            exit_code=0,
        ),
    )

    output = ev.read_text("06-verified/test_output.txt")
    assert "PASS: 5 tests passed" in output
    assert "warning: deprecated API" in output
    assert "--- stderr ---" in output


def test_run_test_command_uses_stderr_only_when_stdout_empty(ev):
    """Some test runners (e.g., go test in some configs) write everything
    to stderr. If stdout is empty, just use stderr — no separator
    confusion."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "go test ./...")

    captured: list[dict] = []
    run_test_command(
        ev, fork_slug="WolffM/x", branch_name="b",
        dispatch=_stub_dispatch(
            captured, stdout="", stderr="ok ./pkg 0.034s", exit_code=0,
        ),
    )

    output = ev.read_text("06-verified/test_output.txt")
    assert output == "ok ./pkg 0.034s"
    assert "--- stderr ---" not in output


def test_run_test_command_writes_empty_output_for_silent_pass(ev):
    """Some test runners can be silent on success (`--quiet`). The
    activity still writes the (empty) file so downstream knows the
    test ran — just that the screenshot stage will produce nothing
    interesting."""
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "pytest --quiet")

    captured: list[dict] = []
    result = run_test_command(
        ev, fork_slug="WolffM/x", branch_name="b",
        dispatch=_stub_dispatch(captured, stdout="", stderr="", exit_code=0),
    )

    assert result["ok"] is True
    assert ev.exists("06-verified/test_output.txt")


def test_run_test_command_uses_default_runner_url_when_unspecified(ev):
    """When called without an explicit runner_url, picks up the env-var
    default — which the worker wrapper sets to the cktest service URL."""
    import temporal.activities.test_runner as mod
    from temporal.activities.test_runner import run_test_command

    ev.write_text("05-fixed/test_command.txt", "pytest")

    captured: list[dict] = []
    original = mod._DEFAULT_RUNNER_URL
    mod._DEFAULT_RUNNER_URL = "http://cktest:5500"
    try:
        run_test_command(
            ev, fork_slug="WolffM/x", branch_name="b",
            dispatch=_stub_dispatch(captured),
        )
    finally:
        mod._DEFAULT_RUNNER_URL = original

    assert captured[0]["runner_url"] == "http://cktest:5500"
