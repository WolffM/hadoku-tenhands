"""crimson-kitty test runner — Phase 5.6 sandbox service.

Single-endpoint HTTP service that runs a test command on a freshly-cloned
fork branch in an isolated tmp directory, capturing stdout+stderr and
returning to the caller. Runs as a systemd service on `claw-3` (claw fleet,
Debian Trixie); called by `temporal/activities/test_runner.py`'s
`run_test_command` over Tailscale (`http://claw-3:5500`).

Why this exists: in the v4 batch every workflow's verify phase failed
to produce `06-verified/test_output.txt` because Copilot is bad at
shell-ops sidecars to its coding work. We split it: Copilot identifies
the test command + commits it to `05-fixed/test_command.txt`, the
pipeline calls this service to run it.

Endpoint:
  POST /run
  Header: Authorization: Bearer <CKTEST_RUNNER_BEARER>
  Body: {"fork_slug": "WolffM/foo", "branch": "crimson-kitty-42",
         "command": "go test ./pkg -run TestFoo -v"}
  Response 200: {"stdout": "...", "stderr": "...", "exit_code": 0,
                 "duration_ms": 1234, "language": "go"}
  Response 200 with error: {"error": "...", "stdout": "", ...} —
                 caller treats as ok=False
  Response 401: missing/mismatched bearer
  Response 503: server already running a job (semaphore full); response
                includes `Retry-After: 60` header — caller backs off.
  Response 4xx: input validation failure (caller bug)
  Response 5xx: server-side runtime error

Auth: `Authorization: Bearer <secret>` on `/run`. Secret read from
`CKTEST_RUNNER_BEARER` env at request time (populated by systemd's
`ExecStartPre=fetch-bearer.sh`, which curls the vault broker). `/health`
remains unauth'd so monitoring can probe liveness without the secret.
The command-allowlist downstream is a hygiene check, not the auth boundary.

Concurrency: `threading.Semaphore(CKTEST_MAX_CONCURRENT)` (default 1) gates
`/run`. claw-3's 16 GB RAM ceiling + Ollama co-tenancy makes >1 concurrent
job genuinely risky for big-monorepo cases. Worker retries 503 with
exponential backoff before falling back to text-only verify.

Toolchains assumed pre-installed by `provision.sh`: git, go, python3
(+pytest), node 20+ (+pnpm), rustc/cargo, gh CLI. See README.md.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("cktest-runner")

app = Flask(__name__)


# ── Per-job timeout (seconds). Hard cap on a single test run; longer
#    than this the worker treats it as a failure and the workflow falls
#    back to text-only verify. The caller's timeout (default 600s) is
#    the upper bound; this can be tighter for runner-side hygiene.
_PER_JOB_TIMEOUT_S = int(os.environ.get("CKTEST_PER_JOB_TIMEOUT_S", "300"))

# Whitelist of command shapes we'll execute. Loose check — first token
# must be in this set. Defense against accidentally executing arbitrary
# shell commands the agent might commit; not a security boundary
# (anyone with localhost:5500 access can already reach this).
_ALLOWED_FIRST_TOKENS = {
    "pytest", "python", "python3", "py.test",
    "go", "go.exe",
    "npm", "pnpm", "yarn", "npx",
    "cargo", "rustc",
    "make",
    "bash", "sh",
}

# Slug shape: `owner/repo` with letters, digits, hyphens, underscores,
# dots. Defense against path-traversal / command-injection via the
# fork_slug field.
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")
# Branch names are git ref-name compliant — tighter than slugs to
# avoid `-foo` flags being interpreted as command options.
_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/][a-zA-Z0-9._/-]*$")

# Concurrency gate — claw-3's 16 GB RAM ceiling + Ollama co-tenancy
# makes >1 concurrent job risky for big-monorepo cases. Sized via env so
# a beefier replacement host can lift the ceiling without code change.
_MAX_CONCURRENT = int(os.environ.get("CKTEST_MAX_CONCURRENT", "1"))
_CONCURRENCY_SEM = threading.Semaphore(_MAX_CONCURRENT)
# Retry-After hint when 503'd. Covers the typical job wall-time of
# 30s–8min badly, but it's a hint — the worker has its own backoff
# schedule and may retry sooner.
_RETRY_AFTER_S = int(os.environ.get("CKTEST_RETRY_AFTER_S", "60"))


def _check_bearer() -> bool:
    """Constant-time compare of `Authorization: Bearer <secret>` header
    against `CKTEST_RUNNER_BEARER` env. Returns False (→ 401) when:

    - Server has no bearer configured (misconfig — fail closed)
    - Header is missing or not `Bearer <token>` shape
    - Token mismatches the configured secret

    Reads env at request time so a `systemctl reload` / unit restart
    picks up rotated secrets without a code change."""
    expected = os.environ.get("CKTEST_RUNNER_BEARER", "")
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    presented = header[len(prefix):].strip()
    return hmac.compare_digest(presented, expected)


def _detect_language(workdir: Path) -> str:
    """Heuristic: which lockfile/manifest is present at the repo root.
    Tells the dep-installer which toolchain to invoke."""
    if (workdir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (workdir / "yarn.lock").exists():
        return "yarn"
    if (workdir / "package-lock.json").exists() or (workdir / "package.json").exists():
        return "npm"
    if (workdir / "go.mod").exists():
        return "go"
    if (workdir / "Cargo.toml").exists():
        return "cargo"
    if (workdir / "pyproject.toml").exists() or (workdir / "requirements.txt").exists():
        return "python"
    return "unknown"


def _install_deps(workdir: Path, language: str, timeout_s: int) -> tuple[int, str]:
    """Install dependencies based on detected language. Returns
    (exit_code, output_log). Non-zero → caller bails with a useful
    error; we want a clean install before running the test."""
    cmd: list[str] | None = None
    if language == "pnpm":
        cmd = ["pnpm", "install", "--frozen-lockfile"]
    elif language == "yarn":
        cmd = ["yarn", "install", "--frozen-lockfile"]
    elif language == "npm":
        cmd = ["npm", "ci"] if (workdir / "package-lock.json").exists() else ["npm", "install"]
    elif language == "go":
        cmd = ["go", "mod", "download"]
    elif language == "cargo":
        cmd = ["cargo", "fetch"]
    elif language == "python":
        # Best-effort: pip install -e if there's a pyproject, else
        # requirements.txt if it exists. No virtualenv — runs in the
        # cktest distro's system python (acceptable since the distro
        # is dedicated to one job at a time).
        if (workdir / "pyproject.toml").exists():
            cmd = ["pip", "install", "-e", "."]
        elif (workdir / "requirements.txt").exists():
            cmd = ["pip", "install", "-r", "requirements.txt"]
    if cmd is None:
        return 0, f"(no install needed for language={language})"

    logger.info("install: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        log = (
            f"$ {' '.join(cmd)}\n"
            f"--- stdout ---\n{proc.stdout[-2000:]}\n"
            f"--- stderr ---\n{proc.stderr[-2000:]}"
        )
        return proc.returncode, log
    except subprocess.TimeoutExpired:
        return 124, f"install timed out after {timeout_s}s"


def _run_test(
    workdir: Path,
    command: str,
    timeout_s: int,
) -> tuple[int, str, str, int]:
    """Execute `command` in `workdir` via shell, capture stdout+stderr,
    return (exit_code, stdout, stderr, duration_ms).

    Uses shell=True deliberately — the agent commits a real shell
    command (e.g. `pytest -k test_x -v`) that may include flags,
    pipes, etc. The whitelist check against the first token before
    we get here keeps this from being arbitrary-code-exec.
    """
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(workdir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            # Force ANSI codes through — many test runners auto-detect
            # tty and skip them otherwise. Screenshot renderer strips
            # ANSI on its end so this is fine.
            env={**os.environ, "FORCE_COLOR": "1", "CLICOLOR_FORCE": "1"},
        )
        duration_ms = int((time.time() - started) * 1000)
        return proc.returncode, proc.stdout, proc.stderr, duration_ms
    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.time() - started) * 1000)
        partial_stdout = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        partial_stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        return (
            124,
            partial_stdout,
            partial_stderr + f"\n[runner: command timed out after {timeout_s}s]\n",
            duration_ms,
        )


def _cleanup(workdir: Path) -> None:
    """Best-effort tmp-dir removal. Leak ok in worst case (cktest
    distro is dedicated; tmp gets reaped on reboot)."""
    try:
        shutil.rmtree(workdir)
    except Exception as e:
        logger.warning("cleanup of %s failed: %s", workdir, e)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "cktest-runner"})


@app.route("/run", methods=["POST"])
def run():
    # Log every incoming request before any gate so unauth'd hammering
    # is visible in journald (auth abuse detection). bearer_present
    # without the value — auth value is never logged.
    remote = request.headers.get("X-Forwarded-For") or request.remote_addr or "?"
    auth_header = request.headers.get("Authorization", "")
    has_bearer = auth_header.startswith("Bearer ")
    bearer_chars = len(auth_header[7:]) if has_bearer else 0
    logger.info(
        "/run ← from=%s bearer_present=%s bearer_chars=%d ua=%r",
        remote, has_bearer, bearer_chars,
        (request.headers.get("User-Agent") or "")[:60],
    )

    # ── Auth gate (bearer). Reject before parsing the body so a leaky
    #    error message can't surface validation details to unauth'd callers.
    if not _check_bearer():
        logger.warning(
            "/run → 401 unauthorized from=%s bearer_present=%s bearer_chars=%d",
            remote, has_bearer, bearer_chars,
        )
        return jsonify({"error": "unauthorized"}), 401

    # ── Concurrency gate. Non-blocking acquire — if another job holds
    #    the semaphore, return 503 with Retry-After so the worker backs
    #    off rather than queueing here (queueing inside Flask would tie
    #    up worker threads + RAM with no upper bound).
    if not _CONCURRENCY_SEM.acquire(blocking=False):
        logger.info("/run → 503 busy from=%s retry_after=%ds", remote, _RETRY_AFTER_S)
        resp = jsonify({"error": "runner busy", "retry_after_s": _RETRY_AFTER_S})
        resp.status_code = 503
        resp.headers["Retry-After"] = str(_RETRY_AFTER_S)
        return resp

    job_id = uuid.uuid4().hex[:8]
    overall_started = time.time()
    workdir: Optional[Path] = None
    try:
        body = request.get_json(silent=True) or {}
        fork_slug = (body.get("fork_slug") or "").strip()
        branch = (body.get("branch") or "").strip()
        command = (body.get("command") or "").strip()

        # ── Input validation
        if not _SLUG_RE.match(fork_slug):
            logger.warning("job %s: 400 invalid fork_slug=%r from=%s", job_id, fork_slug, remote)
            return jsonify({"error": f"invalid fork_slug: {fork_slug!r}"}), 400
        if not _BRANCH_RE.match(branch):
            logger.warning("job %s: 400 invalid branch=%r from=%s", job_id, branch, remote)
            return jsonify({"error": f"invalid branch: {branch!r}"}), 400
        if not command:
            logger.warning("job %s: 400 empty command from=%s", job_id, remote)
            return jsonify({"error": "empty command"}), 400
        first_token = command.split(None, 1)[0]
        if first_token not in _ALLOWED_FIRST_TOKENS:
            logger.warning(
                "job %s: 400 disallowed token=%r from=%s",
                job_id, first_token, remote,
            )
            return jsonify({
                "error": (
                    f"command first token {first_token!r} not in allowlist; "
                    f"allowed: {sorted(_ALLOWED_FIRST_TOKENS)}"
                )
            }), 400

        # ── Stage tmp clone dir
        workdir = Path(tempfile.gettempdir()) / f"cktest-{job_id}"
        logger.info(
            "job %s START fork=%s branch=%s cmd=%r tmp=%s",
            job_id, fork_slug, branch, command[:120], workdir,
        )

        # ── Clone (shallow, single branch — fastest)
        clone_url = f"https://github.com/{fork_slug}.git"
        clone_started = time.time()
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, clone_url, str(workdir)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        clone_ms = int((time.time() - clone_started) * 1000)
        if clone.returncode != 0:
            logger.warning(
                "job %s CLONE FAILED rc=%d in %dms — %s",
                job_id, clone.returncode, clone_ms, clone.stderr[-300:].strip(),
            )
            return jsonify({
                "error": f"clone failed: {clone.stderr[-500:]}",
                "stdout": "", "stderr": "", "exit_code": -1, "duration_ms": 0,
            }), 200  # 200 with error field — non-fatal to caller
        logger.info("job %s clone OK in %dms", job_id, clone_ms)

        # ── Detect language + install deps
        language = _detect_language(workdir)
        logger.info("job %s detected language=%s", job_id, language)
        install_started = time.time()
        install_rc, install_log = _install_deps(workdir, language, timeout_s=240)
        install_ms = int((time.time() - install_started) * 1000)
        if install_rc != 0:
            logger.warning(
                "job %s INSTALL FAILED rc=%d in %dms — %s",
                job_id, install_rc, install_ms, install_log[-300:].strip(),
            )
            return jsonify({
                "error": f"install failed (rc={install_rc}): {install_log[-1000:]}",
                "stdout": "", "stderr": "", "exit_code": -1, "duration_ms": 0,
                "language": language,
            }), 200
        logger.info("job %s install OK in %dms (language=%s)", job_id, install_ms, language)

        # ── Run the test
        exit_code, stdout, stderr, duration_ms = _run_test(
            workdir, command, timeout_s=_PER_JOB_TIMEOUT_S,
        )
        logger.info(
            "job %s DONE exit=%d duration_ms=%d stdout_bytes=%d stderr_bytes=%d (total=%dms)",
            job_id, exit_code, duration_ms, len(stdout), len(stderr),
            int((time.time() - overall_started) * 1000),
        )
        return jsonify({
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "language": language,
        }), 200

    except Exception:
        logger.exception("job %s UNHANDLED EXCEPTION", job_id)
        raise
    finally:
        if workdir is not None:
            _cleanup(workdir)
        _CONCURRENCY_SEM.release()
        logger.info(
            "/run → response sent for job %s (total=%dms)",
            job_id, int((time.time() - overall_started) * 1000),
        )


if __name__ == "__main__":
    port = int(os.environ.get("CKTEST_PORT", "5500"))
    if not os.environ.get("CKTEST_RUNNER_BEARER"):
        # Fail closed at startup. Systemd's ExecStartPre=fetch-bearer.sh
        # populates this from the vault; if it didn't run or the vault
        # was sealed, refuse to start so the failure surfaces as a unit
        # restart loop in journald rather than a silently-open service.
        raise SystemExit(
            "cktest-runner: refusing to start — CKTEST_RUNNER_BEARER unset. "
            "On claw-3 this means fetch-bearer.sh did not populate "
            "/run/cktest-runner/env (vault sealed? service-key invalid?)."
        )
    logger.info(
        "cktest-runner starting on 0.0.0.0:%d (max_concurrent=%d)",
        port, _MAX_CONCURRENT,
    )
    # Threaded=True so the semaphore actually gates parallel /run calls;
    # default Flask dev server is single-threaded and the semaphore would
    # be no-op decoration. For prod we should front this with gunicorn,
    # but a single Flask process is fine at MAX_CONCURRENT=1.
    app.run(host="0.0.0.0", port=port, threaded=True)
