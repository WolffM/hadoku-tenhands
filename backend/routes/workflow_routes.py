"""
Workflow routes - vibecheck installation, updates, and triggering.
"""

import base64
import logging

from flask import request, jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import (
        run_gh_command,
        get_repo_context,
        clear_vibecheck_cache,
        cached_endpoint,
    )
    from ..config import get_vibecheck_workflow, VIBECHECK_REPO, VIBECHECK_WORKFLOW_FILE, VIBECHECK_WORKFLOW_NAME
except ImportError:
    from services import (
        run_gh_command,
        get_repo_context,
        clear_vibecheck_cache,
        cached_endpoint,
    )
    from config import get_vibecheck_workflow, VIBECHECK_REPO, VIBECHECK_WORKFLOW_FILE, VIBECHECK_WORKFLOW_NAME


@bp.route("/api/install-vibecheck", methods=["POST"])
def api_install_vibecheck():
    """Install vibecheck workflow to a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    content_b64 = base64.b64encode(get_vibecheck_workflow().encode()).decode()

    result = run_gh_command([
        "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/{VIBECHECK_WORKFLOW_FILE}",
        "-f", "message=Add vibeCheck workflow",
        "-f", f"content={content_b64}"
    ])

    if result["success"]:
        clear_vibecheck_cache()
        return jsonify({"success": True, "message": "vibeCheck workflow installed!"})
    return jsonify({"success": False, "error": result["error"]})


@bp.route("/api/vibecheck-template", methods=["GET"])
def api_vibecheck_template():
    """Fetch the latest vibecheck workflow template from the vibecheck repo."""
    result = run_gh_command(
        ["api", f"repos/{VIBECHECK_REPO}/contents/examples/{VIBECHECK_WORKFLOW_FILE}", "--jq", ".content"],
        timeout=30
    )

    if result["success"]:
        try:
            content = base64.b64decode(result["output"].strip()).decode()
            return jsonify({"success": True, "template": content})
        except Exception as e:
            return jsonify({"success": False, "error": f"Failed to decode template: {e}"})

    # Fallback to local template
    return jsonify({"success": True, "template": get_vibecheck_workflow(), "source": "local"})


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
    sha_result = run_gh_command(
        ["api", f"/repos/{owner}/{repo}/contents/.github/workflows/{VIBECHECK_WORKFLOW_FILE}", "--jq", ".sha"],
        timeout=30
    )

    if not sha_result["success"]:
        return jsonify({"success": False, "error": "Workflow not found - use install instead"})

    sha = sha_result["output"].strip()

    # Use provided template or fetch latest from vibecheck repo
    if template:
        workflow_content = template
    else:
        template_result = run_gh_command(
            ["api", f"repos/{VIBECHECK_REPO}/contents/examples/{VIBECHECK_WORKFLOW_FILE}", "--jq", ".content"],
            timeout=30
        )
        if template_result["success"]:
            try:
                workflow_content = base64.b64decode(template_result["output"].strip()).decode()
            except Exception as e:
                logger.warning("Failed to decode vibecheck template: %s", e)
                workflow_content = get_vibecheck_workflow()
        else:
            workflow_content = get_vibecheck_workflow()

    content_b64 = base64.b64encode(workflow_content.encode()).decode()

    result = run_gh_command([
        "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/{VIBECHECK_WORKFLOW_FILE}",
        "-f", "message=Update vibeCheck workflow to latest version",
        "-f", f"content={content_b64}",
        "-f", f"sha={sha}"
    ], timeout=30)

    if result["success"]:
        return jsonify({"success": True, "message": "vibeCheck workflow updated!"})
    return jsonify({"success": False, "error": result["error"]})


@bp.route("/api/repos-with-vibecheck", methods=["GET"])
@cached_endpoint("repos-with-vibecheck")
def api_repos_with_vibecheck():
    """Get repos that have vibecheck installed (for updating)."""
    owner, repos, status_dict = get_repo_context()

    if not repos:
        return {"owner": owner, "repos": []}

    repos_with_vibecheck = [
        {"name": r["name"], "isPrivate": r.get("isPrivate", False)}
        for r in repos
        if status_dict.get(r["name"], False)
    ]

    return {"owner": owner, "repos": repos_with_vibecheck}


@bp.route("/api/run-vibecheck", methods=["POST"])
def api_run_vibecheck():
    """Trigger the vibecheck workflow."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    result = run_gh_command(["workflow", "run", VIBECHECK_WORKFLOW_FILE, "-R", f"{owner}/{repo}"])

    if result["success"]:
        return jsonify({"success": True, "message": "vibeCheck workflow triggered!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})
