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

Sandbox: a systemd-managed Flask service on `claw-3` (claw fleet,
Debian Trixie), reachable from the Windows worker host over
Tailscale at `http://claw-3:5500`. If the runner is unavailable or
the runner-side execution fails, this activity returns
`{ok: False, ...}` non-fatally — the workflow proceeds with
text-only verification (the synthesized `verify_notes.md` + the
existing `_extract_verification` fallback path).

Auth: `Authorization: Bearer <CKTEST_RUNNER_BEARER>` on every call.
Worker reads the secret from env (populated by the wrapper's vault
fetch); claw-3 reads the same secret from /run/cktest-runner/env
(populated by `fetch-bearer.sh`). Mismatch → 401 → `ok=False`.

Concurrency: the runner gates concurrent jobs with a semaphore (1 by
default) and returns 503 with a `Retry-After: 60` hint when busy. We
retry 503 with exponential backoff (1 → 2 → 4 → 8s) before falling
back to text-only verify. Other errors (timeouts, connection refused,
401) bail immediately — retrying won't help.

Configuration:
  TEST_RUNNER_URL  env var, default `http://localhost:5500` (overridden
                   in the prod wrapper to `http://claw-3:5500` once the
                   claw-3 service is up)
  CKTEST_RUNNER_BEARER  env var, the shared bearer secret. Empty in
                        local/test environments — the worker still
                        sends `Authorization: Bearer ` (empty) and the
                        runner rejects with 401, which the activity
                        surfaces as `ok=False` non-fatally.
  TEST_RUNNER_TIMEOUT_S  HTTP timeout for the run-test call; default
                         600 (10 min — covers most test suites;
                         longer-running tests hit a workflow-level
                         timeout instead)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


_DEFAULT_RUNNER_URL = os.environ.get("TEST_RUNNER_URL", "http://localhost:5500")
_DEFAULT_TIMEOUT_S = float(os.environ.get("TEST_RUNNER_TIMEOUT_S", "600"))
# Backoff schedule for 503 responses (in seconds). Exhausting these falls
# back to text-only verify; the workflow-level fallback is graceful.
_BUSY_RETRY_SCHEDULE_S = (1.0, 2.0, 4.0, 8.0)


class RunnerBusy503(Exception):
    """Raised by a dispatch fn when the runner returned HTTP 503.

    Signals the retry loop in `run_test_command` to back off and try
    again rather than bailing immediately. Other transport-level
    failures (ConnectionError, Timeout, etc.) keep the existing
    "runner unreachable" semantics — retry only buys us anything when
    the runner is up but holding the semaphore."""


def _default_dispatch_test(
    runner_url: str,
    fork_slug: str,
    branch: str,
    command: str,
    timeout_s: float,
) -> dict:
    """POST to the cktest sandbox runner. Returns a dict shaped like
    `{stdout, stderr, exit_code, duration_ms, error?}`.

    Uses `requests` (already in requirements.txt). 503 raises
    `RunnerBusy503` so the caller can back off; other non-2xx
    responses raise via `raise_for_status()` and surface as
    `runner unreachable` (caller bug or auth failure — retrying
    won't help)."""
    import requests  # type: ignore

    bearer = os.environ.get("CKTEST_RUNNER_BEARER", "")
    headers = {"Authorization": f"Bearer {bearer}"}

    r = requests.post(
        f"{runner_url}/run",
        json={
            "fork_slug": fork_slug,
            "branch": branch,
            "command": command,
        },
        headers=headers,
        timeout=timeout_s,
    )
    if r.status_code == 503:
        retry_after = r.headers.get("Retry-After", "")
        raise RunnerBusy503(f"runner busy (Retry-After={retry_after!r})")
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
    sleep: Optional[Callable[[float], None]] = None,
    busy_retry_schedule: Optional[tuple[float, ...]] = None,
) -> dict:
    """Read `05-fixed/test_command.txt`, dispatch to runner, persist output.

    Returns:
      `{ok: True, exit_code, bytes, duration_ms}` on success — the runner
        executed the command and we persisted stdout+stderr to
        06-verified/test_output.txt.
      `{ok: False, reason}` if no test_command.txt, the command is empty,
        the runner is unreachable, the runner stayed busy through every
        retry, or the runner reported an internal failure. Non-fatal:
        workflow proceeds, screenshot stage no-ops, verification body
        falls back to text-only.

    Seam for tests:
      `dispatch(runner_url, fork_slug, branch, command, timeout_s) -> dict`
        is the actual HTTP call. Default uses requests. May raise
        `RunnerBusy503` to trigger backoff; any other exception is
        treated as fatal-for-this-call.
      `sleep(seconds)` is the wait fn between busy retries (default
        `time.sleep`); tests pass a no-op so the suite stays fast.
      `busy_retry_schedule` overrides the default backoff seconds.
    """
    # If Copilot didn't commit 05-fixed/test_command.txt (the common
    # case — Copilot consistently ignores that REQUIRED instruction),
    # synthesize one from the language hint + files_touched. Quiet on
    # failure: stays no-op when we can't infer a sensible command,
    # preserving the prior text-only-verify fallback path.
    from .test_command_synthesizer import synthesize_test_command_if_missing
    synthesize_test_command_if_missing(evidence)

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
    if sleep is None:
        sleep = time.sleep
    if busy_retry_schedule is None:
        busy_retry_schedule = _BUSY_RETRY_SCHEDULE_S

    # Retry on 503 with the configured backoff. Total attempts =
    # len(schedule) + 1 (initial try + one per scheduled wait). After the
    # last attempt we give up and fall back to text-only verify — the
    # runner is genuinely overloaded, not in a transient blip.
    result: Optional[dict] = None
    last_busy: Optional[Exception] = None
    for attempt_idx, wait_s in enumerate((0.0, *busy_retry_schedule)):
        if wait_s > 0:
            logger.info(
                "test-runner busy for %s@%s; backing off %.1fs (attempt %d)",
                fork_slug, branch_name, wait_s, attempt_idx + 1,
            )
            sleep(wait_s)
        try:
            result = dispatch(runner_url, fork_slug, branch_name, command, timeout_s)
            break
        except RunnerBusy503 as e:
            last_busy = e
            continue
        except Exception as e:
            logger.warning(
                "test-runner dispatch failed for %s@%s: %s",
                fork_slug, branch_name, e, exc_info=True,
            )
            return {"ok": False, "reason": f"runner unreachable: {type(e).__name__}: {e}"}
    else:
        # Exhausted the schedule without a successful dispatch.
        return {
            "ok": False,
            "reason": f"runner busy after {len(busy_retry_schedule) + 1} attempts: {last_busy}",
        }
    assert result is not None  # break path above always populates this

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
