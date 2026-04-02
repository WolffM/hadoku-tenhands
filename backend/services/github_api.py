"""
GitHub API Service - Wrapper functions for GitHub CLI commands

Token routing: When a command targets a SAML-protected org (e.g., microsoft),
the MSFT_SSO PAT is injected via GH_TOKEN env var. The token is looked up
lazily at call time (not import time) so dotenv has time to load.
"""

import os
import subprocess
import json
import logging
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)
from .cache import get_cached_vibecheck_status, set_cached_vibecheck_status

# On Windows, prevent subprocess from opening console windows
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

# Orgs that require SAML-authorized tokens.
# Maps org name → env var holding the SAML-authorized PAT.
_SAML_ORG_TOKENS = {
    "microsoft": "MSFT_SSO",
}

# Thread-local-ish override: when set, ALL gh commands use this token.
# Used during pipeline runs that target SAML orgs — the fork (WolffM/repo)
# inherits SAML enforcement from the upstream org, so every command in the
# pipeline needs the SAML token, not just the ones targeting microsoft/*.
_force_token = None


def is_saml_org(org):
    """Check if an org requires SAML-authorized tokens.

    Also implies firewall enforcement on forks — GitHub's Copilot infrastructure
    forces COPILOT_AGENT_FIREWALL_ENABLED=true on forks of SAML-protected orgs
    regardless of the repo-level toggle. Self-hosted runners won't work on these
    forks; use github-hosted runners instead.
    """
    return (org or "").lower() in _SAML_ORG_TOKENS


def set_saml_token_override(org_or_token):
    """Force all gh commands to use a SAML token.

    Call with an org name (looks up the token) or a raw token string.
    Call with None to clear the override.
    """
    global _force_token
    if org_or_token is None:
        _force_token = None
        return
    # If it looks like a token, use it directly
    if org_or_token.startswith("gh"):
        _force_token = org_or_token
        return
    # Otherwise treat as org name
    _force_token = _get_saml_token_for_org(org_or_token)


def _get_saml_token_for_org(org):
    """Get the SAML-authorized token for an org, or None.

    Reads from os.environ at call time (lazy) so dotenv has loaded by then.
    """
    env_var = _SAML_ORG_TOKENS.get(org)
    if not env_var:
        return None
    return os.environ.get(env_var) or None


def _extract_org_from_args(args):
    """Extract the target org from gh CLI args.

    Checks -R flags, API paths, and positional owner/repo arguments.
    Returns the lowercased org name, or None.
    """
    for i, arg in enumerate(args):
        # -R owner/repo
        if arg == "-R" and i + 1 < len(args):
            return args[i + 1].split("/")[0].lower()
        # API paths: repos/owner/repo/... or /repos/owner/repo/...
        if arg.startswith("repos/") or arg.startswith("/repos/"):
            parts = arg.lstrip("/").split("/")
            if len(parts) >= 2:
                return parts[1].lower()
        # Positional owner/repo (e.g., "repo fork microsoft/PowerToys")
        if "/" in arg and not arg.startswith("-") and not arg.startswith("repos/") and not arg.startswith("/repos/"):
            owner = arg.split("/")[0].lower()
            if owner in _SAML_ORG_TOKENS:
                return owner
    return None


def _build_env_for_args(args):
    """Build a subprocess env dict with the correct GH_TOKEN if SAML is needed.

    Priority: forced override > arg-based detection > default (no override).
    Returns None if no override is needed (use default env).
    """
    # Check forced override first (set during pipeline runs for SAML orgs)
    if _force_token:
        return {**os.environ, "GH_TOKEN": _force_token}
    # Auto-detect from args
    org = _extract_org_from_args(args)
    if not org:
        return None
    token = _get_saml_token_for_org(org)
    if not token:
        return None
    logger.debug("Using SAML token for org '%s'", org)
    return {**os.environ, "GH_TOKEN": token}


def run_gh_command(args, capture_output=True, timeout=30, stdin_data=None):
    """Run a gh CLI command and return the result.

    Automatically injects the correct SAML-authorized token when the
    command targets a protected org.

    Args:
        args: Command arguments to pass to gh
        capture_output: Whether to capture stdout/stderr
        timeout: Timeout in seconds (default 30s)
        stdin_data: Optional string to send to stdin (for --input -)
    """
    cmd_summary = " ".join(args[:4])  # first 4 args for log readability
    start = time.monotonic()
    env = _build_env_for_args(args)

    try:
        result = subprocess.run(
            ["gh"] + args,
            input=stdin_data,
            capture_output=capture_output,
            text=True,
            encoding='utf-8',
            errors='replace',
            creationflags=_SUBPROCESS_FLAGS,
            timeout=timeout,
            env=env,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        if result.returncode != 0:
            logger.debug("gh %s → FAIL (%dms): %s", cmd_summary, elapsed,
                         result.stderr[:200] if result.stderr else "no stderr")
            return {"success": False, "error": result.stderr}
        logger.debug("gh %s → OK (%dms)", cmd_summary, elapsed)
        return {"success": True, "output": result.stdout}
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("gh %s → TIMEOUT (%dms)", cmd_summary, elapsed)
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("gh %s → ERROR (%dms): %s", cmd_summary, elapsed, e)
        return {"success": False, "error": str(e)}


def get_authenticated_user():
    """Get the currently authenticated GitHub user."""
    result = run_gh_command(["api", "user", "--jq", ".login"])
    if result["success"]:
        return result["output"].strip()
    logger.warning("Could not authenticate GitHub user: %s", result.get("error"))
    return "unknown"


def get_repos(limit=100):
    """Get all repositories for the authenticated user."""
    result = run_gh_command(["repo", "list", "--limit", str(limit), "--json", "name,url,isPrivate,description,updatedAt"])
    if result["success"]:
        return json.loads(result["output"])
    return []


def get_repo_issues(owner, repo, labels=None):
    """Get issues for a repository, optionally filtered by labels.

    Uses REST API to avoid GraphQL rate limits.
    """
    url = f"repos/{owner}/{repo}/issues?state=open&per_page=100"
    if labels:
        url += f"&labels={labels}"
    result = run_gh_command([
        "api", url,
        "--jq",
        '[.[] | select(.pull_request == null) | {'
        'number: .number, title: .title, labels: .labels, '
        'state: .state, createdAt: .created_at, '
        'assignees: .assignees, url: .html_url}]',
    ])
    if result["success"]:
        try:
            return json.loads(result["output"])
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def get_repo_prs(owner, repo):
    """Get pull requests for a repository.

    Uses REST API to avoid GraphQL rate limits.
    reviewDecision is not available from the REST list endpoint — set to null.
    """
    result = run_gh_command([
        "api", f"repos/{owner}/{repo}/pulls?state=open&per_page=100",
        "--jq",
        '[.[] | {number: .number, title: .title, state: .state, '
        'createdAt: .created_at, author: {login: .user.login}, '
        'url: .html_url, headRefName: .head.ref, isDraft: .draft, '
        'reviewDecision: null, labels: .labels}]',
    ])
    if result["success"]:
        try:
            return json.loads(result["output"])
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def get_workflow_runs(owner, repo, workflow_name=None, limit=10):
    """Get recent workflow runs."""
    cmd = ["run", "list", "-R", f"{owner}/{repo}", "--json", "databaseId,displayTitle,status,conclusion,createdAt,workflowName,url", "--limit", str(limit)]
    if workflow_name:
        cmd.extend(["-w", workflow_name])
    result = run_gh_command(cmd)
    if result["success"]:
        return json.loads(result["output"])
    return []


def check_vibecheck_installed(owner, repo):
    """Check if vibecheck workflow is installed in a repo."""
    try:
        from ..config import VIBECHECK_WORKFLOW_FILE
    except ImportError:
        from config import VIBECHECK_WORKFLOW_FILE
    result = run_gh_command(["api", f"/repos/{owner}/{repo}/contents/.github/workflows/{VIBECHECK_WORKFLOW_FILE}"])
    return result["success"]


def check_vibecheck_installed_batch(owner, repos, max_workers=10):
    """Check vibecheck status for multiple repos in parallel."""
    cached = get_cached_vibecheck_status()
    if cached:
        logger.debug("[PERF] Using cached vibecheck status for %d repos", len(cached))
        return cached

    logger.debug("[PERF] Checking vibecheck status for %d repos in parallel...", len(repos))
    start = time.time()

    status_dict = {}

    def check_single(repo_name):
        return repo_name, check_vibecheck_installed(owner, repo_name)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_single, r["name"]): r["name"] for r in repos}
        for future in as_completed(futures):
            repo_name, installed = future.result()
            status_dict[repo_name] = installed

    elapsed = time.time() - start
    logger.debug("[PERF] Checked %d repos in %.2fs", len(repos), elapsed)

    set_cached_vibecheck_status(status_dict)

    return status_dict


def get_repo_context():
    """Get common repo context: (owner, repos, status_dict)."""
    owner = get_authenticated_user()
    repos = get_repos()
    status_dict = check_vibecheck_installed_batch(owner, repos) if repos else {}
    return owner, repos, status_dict
