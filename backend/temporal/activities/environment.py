"""Environment activity — Phase 1C.3.

Clones the fork (or shallow-fetches it), runs an install command, then
reports `installable` / `runnable` into evidence. The `environment_works`
gate reads the resulting health.json and aborts the workflow if anything
failed.

The activity itself is purely a wrapper — actual install/run logic is
delegated to a callable so tests can mock it without subprocess.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _default_runner(cmd: list[str], cwd: str, timeout: int) -> dict:
    """Run a shell command and return {success, output, error}."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": f"timeout after {timeout}s"}


def setup_environment(
    fork_slug: str,
    branch_name: str,
    workdir: str,
    install_cmd: list[str],
    evidence,
    *,
    dev_server_cmd: list[str] | None = None,
    install_timeout_s: int = 600,
    dev_server_timeout_s: int = 30,
    runner=None,
) -> dict:
    """Run the install (and optionally start the dev server briefly), then
    write `03-environment/health.json` for the environment_works gate.

    `workdir` should already contain the cloned fork at the right branch —
    this activity does NOT clone, since the clone strategy is environment-
    specific (could be local checkout, could be CI runner). The orchestrator
    does the clone and passes the path here.
    """
    if runner is None:
        runner = _default_runner

    install_result = runner(install_cmd, workdir, install_timeout_s)
    evidence.write_text("03-environment/install_log.txt", _format_log(install_result))

    runnable = None
    if dev_server_cmd:
        dev_result = runner(dev_server_cmd, workdir, dev_server_timeout_s)
        evidence.write_text("03-environment/dev_server_log.txt", _format_log(dev_result))
        runnable = bool(dev_result.get("success"))

    health = {
        "installable": bool(install_result.get("success")),
    }
    if runnable is not None:
        health["runnable"] = runnable

    evidence.write_json("03-environment/health.json", health)
    return {"ok": True, **health}


def _format_log(result: dict) -> str:
    parts = [
        f"returncode={result.get('returncode', '?')}",
        f"success={result.get('success')}",
        "--- stdout ---",
        result.get("output", ""),
        "--- stderr ---",
        result.get("error", ""),
    ]
    return "\n".join(parts)
