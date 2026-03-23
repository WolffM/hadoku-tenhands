"""
Debug assignment endpoints: assign-copilot, score-issue.
"""

import json

from flask import request, jsonify

try:
    from .. import bp
    from ...config import COPILOT_ASSIGNEE
    from ...services import run_gh_command, get_authenticated_user
    from ...helpers.oss_helpers import score_issue_with_breakdown
    from ...helpers.validation import (
        validate_owner, validate_repo_name, validate_required_fields, error_response,
    )
    from ...routes.debug._middleware import require_admin_key
except ImportError:
    from routes import bp
    from config import COPILOT_ASSIGNEE
    from services import run_gh_command, get_authenticated_user
    from helpers.oss_helpers import score_issue_with_breakdown
    from helpers.validation import (
        validate_owner, validate_repo_name, validate_required_fields, error_response,
    )
    from routes.debug._middleware import require_admin_key


@bp.route("/api/oss/debug/assign-copilot", methods=["POST"])
@require_admin_key
def api_oss_debug_assign_copilot():
    """Assign Copilot to an issue on a fork."""
    data = request.json
    repo = data.get("repo", "").strip()
    issue_number = data.get("issue_number")
    my_user = get_authenticated_user()

    if not repo or not issue_number:
        return jsonify({"success": False, "error": "Missing repo or issue_number", "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    result = run_gh_command([
        "issue", "edit", str(issue_number),
        "-R", f"{my_user}/{repo}",
        "--add-assignee", COPILOT_ASSIGNEE
    ])

    return jsonify({
        "success": True,
        "assigned": result["success"],
        "error": result.get("error") if not result["success"] else None,
        "owner": my_user,
    })


@bp.route("/api/oss/debug/score-issue", methods=["GET"])
@require_admin_key
def api_oss_debug_score_issue():
    """Score a single issue with full breakdown."""
    my_user = get_authenticated_user()
    req_err = validate_required_fields(request.args, ["owner", "repo", "issue_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err, "owner": my_user})

    owner = request.args.get("owner", "").strip()
    repo = request.args.get("repo", "").strip()
    issue_number = request.args.get("issue_number", "").strip()

    owner_err = validate_owner(owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err, "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    # Fetch issue data via gh CLI
    result = run_gh_command([
        "issue", "view", issue_number, "-R", f"{owner}/{repo}",
        "--json", "number,title,labels,createdAt,updatedAt,comments,assignees,url"
    ])

    if not result["success"]:
        return error_response(result.get("error"), "Failed to fetch issue", my_user)

    try:
        issue = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return jsonify({"success": False, "error": "Failed to parse issue data", "owner": my_user})

    score_result = score_issue_with_breakdown(issue)

    return jsonify({
        "success": True,
        "issue": issue,
        "score": {
            "cvs": score_result["cvs"],
            "cvsTier": score_result["cvsTier"],
        },
        "breakdown": score_result["breakdown"],
        "owner": my_user,
    })
