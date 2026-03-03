"""
Action routes - PR and issue operations (assign, approve, merge, etc.)
"""

import json

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_workflow_runs
    from ..helpers.validation import validate_owner, validate_repo_name, validate_required_fields, safe_error_message
except ImportError:
    from services import run_gh_command, get_workflow_runs
    from helpers.validation import validate_owner, validate_repo_name, validate_required_fields, safe_error_message


@bp.route("/api/assign-copilot", methods=["POST"])
def api_assign_copilot():
    """Assign GitHub Copilot to an issue."""
    data = request.json
    req_err = validate_required_fields(data, ["owner", "repo", "issue_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    owner = data.get("owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    result = run_gh_command([
        "issue", "edit", str(issue_number),
        "-R", f"{owner}/{repo}",
        "--add-assignee", "@Copilot"
    ])

    if result["success"]:
        return jsonify({"success": True, "message": f"Copilot assigned to issue #{issue_number}!"})
    return jsonify({"success": False, "error": safe_error_message(result.get("error"), "Failed to assign Copilot")})


@bp.route("/api/approve-pr", methods=["POST"])
def api_approve_pr():
    """Approve a pull request."""
    data = request.json
    req_err = validate_required_fields(data, ["owner", "repo", "pr_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    result = run_gh_command([
        "pr", "review", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--approve",
        "-b", "Approved"
    ])

    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} approved!"})
    return jsonify({"success": False, "error": safe_error_message(result.get("error"), "Operation failed")})


@bp.route("/api/mark-pr-ready", methods=["POST"])
def api_mark_pr_ready():
    """Mark a draft PR as ready for review."""
    data = request.json
    req_err = validate_required_fields(data, ["owner", "repo", "pr_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    result = run_gh_command([
        "pr", "ready", str(pr_number),
        "-R", f"{owner}/{repo}"
    ])

    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} marked as ready!"})
    return jsonify({"success": False, "error": safe_error_message(result.get("error"), "Failed to mark PR as ready")})


@bp.route("/api/merge-pr", methods=["POST"])
def api_merge_pr():
    """Merge a pull request."""
    data = request.json
    req_err = validate_required_fields(data, ["owner", "repo", "pr_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    # Check if PR is a draft and mark it as ready first
    check_result = run_gh_command([
        "pr", "view", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--json", "isDraft"
    ])

    if check_result["success"]:
        try:
            pr_data = json.loads(check_result["output"])
            if pr_data.get("isDraft", False):
                ready_result = run_gh_command([
                    "pr", "ready", str(pr_number),
                    "-R", f"{owner}/{repo}"
                ])
                if not ready_result["success"]:
                    return jsonify({"success": False, "error": safe_error_message(ready_result.get("error"), "Failed to mark PR as ready")})
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    # Merge can take a while, use longer timeout (60s)
    result = run_gh_command([
        "pr", "merge", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--squash",
        "--delete-branch"
    ], timeout=60)

    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} merged!"})
    return jsonify({"success": False, "error": safe_error_message(result.get("error"), "Operation failed")})


@bp.route("/api/workflow-status", methods=["POST"])
def api_workflow_status():
    """Get the status of the latest vibecheck workflow run."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    runs = get_workflow_runs(owner, repo, "vibeCheck")
    if runs:
        return jsonify({"success": True, "run": runs[0]})
    return jsonify({"success": False, "error": "No workflow runs found"})
