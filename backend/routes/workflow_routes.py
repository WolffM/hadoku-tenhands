"""
Workflow routes - vibecheck installation, updates, and triggering.
"""

import base64

from flask import request, jsonify

from . import bp

try:
    from ..services import (
        run_gh_command,
        get_repo_context,
        clear_vibecheck_cache,
        cached_endpoint,
    )
    from ..config import VIBECHECK_WORKFLOW
except ImportError:
    from services import (
        run_gh_command,
        get_repo_context,
        clear_vibecheck_cache,
        cached_endpoint,
    )
    from config import VIBECHECK_WORKFLOW


@bp.route("/api/install-vibecheck", methods=["POST"])
def api_install_vibecheck():
    """Install vibecheck workflow to a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    content_b64 = base64.b64encode(VIBECHECK_WORKFLOW.encode()).decode()

    result = run_gh_command([
        "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
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
        ["api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
        timeout=30
    )

    if result["success"]:
        try:
            content = base64.b64decode(result["output"].strip()).decode()
            return jsonify({"success": True, "template": content})
        except Exception as e:
            return jsonify({"success": False, "error": f"Failed to decode template: {e}"})

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
    sha_result = run_gh_command(
        ["api", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml", "--jq", ".sha"],
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
            ["api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
            timeout=30
        )
        if template_result["success"]:
            try:
                workflow_content = base64.b64decode(template_result["output"].strip()).decode()
            except Exception:
                workflow_content = VIBECHECK_WORKFLOW
        else:
            workflow_content = VIBECHECK_WORKFLOW

    content_b64 = base64.b64encode(workflow_content.encode()).decode()

    result = run_gh_command([
        "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
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

    result = run_gh_command(["workflow", "run", "vibecheck.yml", "-R", f"{owner}/{repo}"])

    if result["success"]:
        return jsonify({"success": True, "message": "vibeCheck workflow triggered!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})
