"""Pipeline session analysis helpers — subprocess calls to copilot-sessions.py.

Module-level functions that fetch Copilot agent session data from GitHub.
These are pure functions (no class state) that take explicit arguments.
"""

import json
import logging
import os
import subprocess
import sys

try:
    from services.github_api import run_gh_command
except ImportError:
    from .github_api import run_gh_command

logger = logging.getLogger(__name__)


def fetch_workflow_analysis(my_user, repo, pr_number):
    """Fetch Copilot agent workflow analysis for a PR.

    Calls scripts/copilot-sessions.py compare --json to get
    reproduced/verified/tools/step_count data. Returns a dict
    with workflow metrics, or an empty dict on failure.
    """
    if not pr_number or not my_user or not repo:
        return {}

    script = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "copilot-sessions.py"
    )
    script = os.path.normpath(script)

    if not os.path.exists(script):
        logger.error("copilot-sessions.py not found at %s — workflow analysis unavailable", script)
        return {}

    try:
        result = subprocess.run(
            [sys.executable, script, "compare",
             "-R", f"{my_user}/{repo}",
             "--prs", str(pr_number),
             "--json"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("Workflow analysis failed for PR #%s: %s", pr_number, exc)
        return {}

    # The JSON block is printed after the table — find the top-level array
    # Use "\n[" to avoid matching "[" inside JSON values (e.g. empty arrays)
    output = result.stdout
    json_start = output.rfind("\n[")
    if json_start == -1:
        return {}
    json_start += 1  # skip the newline itself

    try:
        entries = json.loads(output[json_start:])
    except (json.JSONDecodeError, ValueError):
        return {}

    if not entries or "error" in entries[0]:
        return {}

    analysis = entries[0]
    return {
        "reproduced": analysis.get("reproduced", False),
        "verified": analysis.get("verified", False),
        "tool_installed": analysis.get("tool_installed", False),
        "code_review": analysis.get("code_review", False),
        "codeql": analysis.get("codeql", False),
        "self_corrected": analysis.get("self_corrected", False),
        "tools_used": analysis.get("tools_used", []),
        "step_count": analysis.get("step_count", 0),
        "session_count": analysis.get("session_count", 1),
    }


def fetch_session_log(my_user, repo, pr_number):
    """Fetch full Copilot session thinking log via copilot-sessions.py summary.

    Returns the raw log text, or empty string on failure.
    """
    script = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "copilot-sessions.py"
    )
    script = os.path.normpath(script)
    if not os.path.exists(script):
        return ""
    try:
        result = subprocess.run(
            [sys.executable, script, "summary",
             "-R", f"{my_user}/{repo}",
             "--pr", str(pr_number)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def fetch_fork_diff(my_user, repo, pr_number):
    """Fetch the full diff of the fork PR via gh pr diff.

    Returns the patch text, or empty string on failure.
    """
    result = run_gh_command([
        "pr", "diff", str(pr_number),
        "-R", f"{my_user}/{repo}",
    ])
    return result.get("output", "").strip() if result.get("success") else ""
