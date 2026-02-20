"""
Workflow routes - vibecheck installation, updates, and triggering.
"""

import base64
import subprocess
import sys

from flask import request, jsonify

from . import bp

try:
    from ..services import (
        run_gh_command,
        get_authenticated_user,
        get_repos,
        check_vibecheck_installed_batch,
        clear_vibecheck_cache,
        get_cached,
        set_cached,
    )
    from ..config import VIBECHECK_WORKFLOW
except ImportError:
    from services import (
        run_gh_command,
        get_authenticated_user,
        get_repos,
        check_vibecheck_installed_batch,
        clear_vibecheck_cache,
        get_cached,
        set_cached,
    )
    from config import VIBECHECK_WORKFLOW

# On Windows, prevent subprocess from opening console windows.
# Known duplication with services/github_api.py — these routes call subprocess.run()
# directly (not via run_gh_command) for raw GitHub API PUT operations.
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


@bp.route("/api/install-vibecheck", methods=["POST"])
def api_install_vibecheck():
    """Install vibecheck workflow to a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    content_b64 = base64.b64encode(VIBECHECK_WORKFLOW.encode()).decode()

    result = subprocess.run(
        ["gh", "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
         "-f", "message=Add vibeCheck workflow",
         "-f", f"content={content_b64}"],
        capture_output=True,
        text=True,
        creationflags=_SUBPROCESS_FLAGS
    )

    if result.returncode == 0:
        clear_vibecheck_cache()
        return jsonify({"success": True, "message": "vibeCheck workflow installed!"})
    return jsonify({"success": False, "error": result.stderr})


@bp.route("/api/vibecheck-template", methods=["GET"])
def api_vibecheck_template():
    """Fetch the latest vibecheck workflow template from the vibecheck repo."""
    try:
        result = subprocess.run(
            ["gh", "api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )

        if result.returncode == 0:
            try:
                content = base64.b64decode(result.stdout.strip()).decode()
                return jsonify({"success": True, "template": content})
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to decode template: {e}"})
    except subprocess.TimeoutExpired:
        pass  # Fall through to local template

    # Fallback to local template
    return jsonify({"success": True, "template": VIBECHECK_WORKFLOW, "source": "local"})


@bp.route("/api/update-vibecheck", methods=["POST"])
def api_update_vibecheck():
    """Update existing vibecheck workflow in a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    template = data.get("template")  # Optional custom template

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    # Get the current file SHA (required for updates)
    try:
        sha_result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml", "--jq", ".sha"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timed out checking workflow file"})

    if sha_result.returncode != 0:
        return jsonify({"success": False, "error": "Workflow not found - use install instead"})

    sha = sha_result.stdout.strip()

    # Use provided template or fetch latest from vibecheck repo
    if template:
        workflow_content = template
    else:
        # Fetch latest from vibecheck repo
        try:
            template_result = subprocess.run(
                ["gh", "api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
                capture_output=True,
                text=True,
                creationflags=_SUBPROCESS_FLAGS,
                timeout=30
            )
            if template_result.returncode == 0:
                try:
                    workflow_content = base64.b64decode(template_result.stdout.strip()).decode()
                except Exception:
                    workflow_content = VIBECHECK_WORKFLOW
            else:
                workflow_content = VIBECHECK_WORKFLOW
        except subprocess.TimeoutExpired:
            workflow_content = VIBECHECK_WORKFLOW

    content_b64 = base64.b64encode(workflow_content.encode()).decode()

    try:
        result = subprocess.run(
            ["gh", "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
             "-f", "message=Update vibeCheck workflow to latest version",
             "-f", f"content={content_b64}",
             "-f", f"sha={sha}"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timed out updating workflow file"})

    if result.returncode == 0:
        return jsonify({"success": True, "message": "vibeCheck workflow updated!"})
    return jsonify({"success": False, "error": result.stderr})


@bp.route("/api/repos-with-vibecheck", methods=["GET"])
def api_repos_with_vibecheck():
    """Get repos that have vibecheck installed (for updating)."""
    cache_key = "repos-with-vibecheck"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

    owner = get_authenticated_user()
    repos = get_repos()

    if not repos:
        result = {"owner": owner, "repos": []}
        set_cached(cache_key, result)
        return jsonify(result)

    status_dict = check_vibecheck_installed_batch(owner, repos)

    repos_with_vibecheck = [
        {"name": r["name"], "isPrivate": r.get("isPrivate", False)}
        for r in repos
        if status_dict.get(r["name"], False)
    ]

    result = {"owner": owner, "repos": repos_with_vibecheck}
    set_cached(cache_key, result)
    return jsonify(result)


@bp.route("/api/run-vibecheck", methods=["POST"])
def api_run_vibecheck():
    """Trigger the vibecheck workflow."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    result = run_gh_command(["workflow", "run", "vibecheck.yml", "-R", f"{owner}/{repo}"])

    if result["success"]:
        return jsonify({"success": True, "message": "vibeCheck workflow triggered!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})
