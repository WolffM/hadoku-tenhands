"""Test-runner activity — Phase 5.6 (verify split).

Reads `05-fixed/test_command.txt` (committed by the agent's fix phase)
and dispatches it to a sandbox runner service. The runner clones the
fork's branch, installs deps, runs the command, returns stdout+stderr
+exit_code. We persist the output to `06-verified/test_output.txt`
which the screenshot stage downstream renders as a terminal PNG.

Why a separate activity (and a separate sandbox) rather than asking
Copilot to run + capture itself: Copilot is an LLM code-reasoning
agent; asking it to do shell ops as a sidecar to its coding work
caused 100% adoption failure in the v4 batch (every workflow
committed test source files but no test_output.txt). Splitting
"identify the test command" (Copilot's job) from "run the test in
a sandbox" (this activity's job) gives each component a single
crisp responsibility.

Sandbox: a dedicated `debian-cktest` WSL distro running a small
HTTP service. The worker reaches it via host-loopback. If the
runner is unavailable or the runner-side execution fails, this
activity returns `{ok: False, ...}` non-fatally — the workflow
proceeds with text-only verification (the synthesized
`verify_notes.md` + the existing `_extract_verification` fallback
path).

Configuration:
  TEST_RUNNER_URL  env var, default `http://localhost:5500`
                   (set in the prod wrapper from a vault key once
                    the cktest distro + service are deployed)
  TEST_RUNNER_TIMEOUT_S  HTTP timeout for the run-test call;
                         default 600 (10 min — covers most test
                         suites; longer-running tests hit a
                         workflow-level timeout instead)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


_DEFAULT_RUNNER_URL = os.environ.get("TEST_RUNNER_URL", "http://localhost:5500")
_DEFAULT_TIMEOUT_S = float(os.environ.get("TEST_RUNNER_TIMEOUT_S", "600"))


def _default_dispatch_test(
    runner_url: str,
    fork_slug: str,
    branch: str,
    command: str,
    timeout_s: float,
) -> dict:
    """POST to the cktest sandbox runner. Returns a dict shaped like
    `{stdout, stderr, exit_code, duration_ms, error?}`.

    Uses `requests` (already in requirements.txt). Failures (network,
    non-2xx, timeout) raise — caller catches and surfaces as
    activity-level failure.
    """
    import requests  # type: ignore

    r = requests.post(
        f"{runner_url}/run",
        json={
            "fork_slug": fork_slug,
            "branch": branch,
            "command": command,
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json()


def run_test_command(
    evidence,
    *,
    fork_slug: str,
    branch_name: str,
    runner_url: Optional[str] = None,
    timeout_s: Optional[float] = None,
    dispatch: Optional[Callable[..., dict]] = None,
) -> dict:
    """Read `05-fixed/test_command.txt`, dispatch to runner, persist output.

    Returns:
      `{ok: True, exit_code, bytes, duration_ms}` on success — the runner
        executed the command and we persisted stdout+stderr to
        06-verified/test_output.txt.
      `{ok: False, reason}` if no test_command.txt, the command is empty,
        the runner is unreachable, or the runner reported an internal
        failure. Non-fatal: workflow proceeds, screenshot stage no-ops,
        verification body falls back to text-only.

    Seam for tests: `dispatch(runner_url, fork_slug, branch, command,
    timeout_s) -> dict` is the actual HTTP call. Default uses requests;
    tests pass a stub that returns a canned response.
    """
    if not evidence.exists("05-fixed/test_command.txt"):
        return {"ok": False, "reason": "no test_command.txt"}

    command = evidence.read_text("05-fixed/test_command.txt").strip()
    if not command:
        return {"ok": False, "reason": "test_command empty"}
    # Single line only — agent might have committed extra prose by mistake.
    # Take the first non-empty line and treat the rest as accidental.
    first_line = next((line for line in command.splitlines() if line.strip()), "")
    if not first_line:
        return {"ok": False, "reason": "test_command had no executable line"}
    command = first_line.strip()

    if runner_url is None:
        runner_url = _DEFAULT_RUNNER_URL
    if timeout_s is None:
        timeout_s = _DEFAULT_TIMEOUT_S
    if dispatch is None:
        dispatch = _default_dispatch_test

    try:
        result = dispatch(runner_url, fork_slug, branch_name, command, timeout_s)
    except Exception as e:
        logger.warning(
            "test-runner dispatch failed for %s@%s: %s",
            fork_slug, branch_name, e, exc_info=True,
        )
        return {"ok": False, "reason": f"runner unreachable: {type(e).__name__}: {e}"}

    if not isinstance(result, dict):
        return {"ok": False, "reason": f"runner returned non-dict: {type(result).__name__}"}

    error = result.get("error")
    if error:
        return {"ok": False, "reason": f"runner internal error: {str(error)[:200]}"}

    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    # Combine stdout+stderr in chronological best-effort order — most
    # test runners interleave them; the runner service may merge them
    # at its end (preferable), but if not, we just concat with a
    # separator so the screenshot doesn't lose either stream.
    if stderr and stderr != stdout:
        if stdout:
            output = f"{stdout}\n--- stderr ---\n{stderr}"
        else:
            output = stderr
    else:
        output = stdout

    if not output.strip():
        # Empty output is suspicious but not strictly an error — the
        # test might genuinely have no output (e.g., silent pass with
        # `--quiet`). Fall through and write what we have so the
        # screenshot stage has something to render.
        logger.info(
            "test-runner returned empty output for %s@%s (cmd=%r); writing anyway",
            fork_slug, branch_name, command,
        )

    evidence.write_text("06-verified/test_output.txt", output)

    return {
        "ok": True,
        "exit_code": result.get("exit_code"),
        "bytes": len(output),
        "duration_ms": result.get("duration_ms"),
    }
