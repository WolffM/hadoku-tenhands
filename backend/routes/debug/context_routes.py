"""
Debug context endpoints: build-context, create-context-issue.
"""

import json as _json

from flask import request, jsonify

try:
    from .. import bp
    from ...config import PLATFORM_PREFIX
    from ...services import run_gh_command, get_authenticated_user, OSSService
    from ...helpers.validation import (
        validate_owner, validate_repo_name, validate_required_fields,
        to_aggregator_slug, error_response,
    )
    from ...routes.debug._middleware import require_admin
except ImportError:
    from routes import bp
    from config import PLATFORM_PREFIX
    from services import run_gh_command, get_authenticated_user, OSSService
    from helpers.validation import (
        validate_owner, validate_repo_name, validate_required_fields,
        to_aggregator_slug, error_response,
    )
    from routes.debug._middleware import require_admin


@bp.route("/api/oss/debug/build-context", methods=["POST"])
@require_admin
def api_oss_debug_build_context():
    """Build agent context markdown and return it for inspection (does NOT create an issue)."""
    data = request.json
    my_user = get_authenticated_user()
    req_err = validate_required_fields(data, ["origin_owner", "repo", "issue_number", "issue_title", "issue_url"])
    if req_err:
        return jsonify({"success": False, "error": req_err, "owner": my_user})

    origin_owner = data.get("origin_owner", "").strip()
    repo = data.get("repo", "").strip()
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "").strip()
    issue_url = data.get("issue_url", "").strip()

    owner_err = validate_owner(origin_owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err, "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    svc = OSSService()

    # Try to get dossier and issue-brief for context building
    dossier_data = svc.get_dossier(to_aggregator_slug(f"{origin_owner}/{repo}"))
    dossier = dossier_data.get("sections") if dossier_data else None

    issue_id = f"{PLATFORM_PREFIX}-{origin_owner}-{repo}-{issue_number}"
    issue_brief = svc.get_issue_brief(to_aggregator_slug(f"{origin_owner}/{repo}"), issue_id)

    context_body, metadata = svc.build_agent_context(
        origin_owner, repo, issue_number, issue_title, issue_url,
        dossier, issue_brief, return_metadata=True
    )

    return jsonify({
        "success": True,
        "context_markdown": context_body,
        "sources": metadata,
        "owner": my_user,
    })


@bp.route("/api/oss/debug/create-context-issue", methods=["POST"])
@require_admin
def api_oss_debug_create_context_issue():
    """Create an issue on a fork (does NOT assign Copilot or track in JSON)."""
    data = request.json
    my_user = get_authenticated_user()
    req_err = validate_required_fields(data, ["repo", "title", "body"])
    if req_err:
        return jsonify({"success": False, "error": req_err, "owner": my_user})

    repo = data.get("repo", "").strip()
    title = data.get("title", "").strip()
    body = data.get("body", "").strip()

    result = run_gh_command([
        "api", f"repos/{my_user}/{repo}/issues",
        "-X", "POST",
        "-f", f"title={title}",
        "-f", f"body={body}"
    ])

    if result["success"]:
        create_data = _json.loads(result["output"])
        issue_url = create_data["html_url"]
        issue_number = str(create_data["number"])
        return jsonify({
            "success": True,
            "issue_url": issue_url,
            "issue_number": int(issue_number),
            "owner": my_user,
        })

    return error_response(result.get("error"), "Failed to create issue", my_user)
