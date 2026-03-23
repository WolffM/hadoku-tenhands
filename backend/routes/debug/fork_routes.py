"""
Debug fork endpoints: fork-exists, fork-repo, fork-ready, sync-fork.
"""

from flask import request, jsonify

try:
    from .. import bp
    from ...services import run_gh_command, get_authenticated_user, OSSService
    from ...helpers.validation import validate_repo_name, validate_owner, safe_error_message
    from ...routes.debug._middleware import require_admin_key
except ImportError:
    from routes import bp
    from services import run_gh_command, get_authenticated_user, OSSService
    from helpers.validation import validate_repo_name, validate_owner, safe_error_message
    from routes.debug._middleware import require_admin_key


@bp.route("/api/oss/debug/fork-exists", methods=["GET"])
@require_admin_key
def api_oss_debug_fork_exists():
    """Check if a fork exists for the authenticated user."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()

    if not repo:
        return jsonify({"success": False, "error": "Missing 'repo' query param", "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    svc = OSSService()
    exists = svc.check_fork_exists(my_user, repo)

    fork_url = f"https://github.com/{my_user}/{repo}" if exists else None
    return jsonify({"success": True, "exists": exists, "fork_url": fork_url, "owner": my_user})


@bp.route("/api/oss/debug/fork-repo", methods=["POST"])
@require_admin_key
def api_oss_debug_fork_repo():
    """Fork a repo (just fork, don't wait or sync)."""
    data = request.json
    origin_owner = data.get("origin_owner", "").strip()
    repo = data.get("repo", "").strip()
    my_user = get_authenticated_user()

    if not origin_owner or not repo:
        return jsonify({"success": False, "error": "Missing origin_owner or repo", "owner": my_user})
    owner_err = validate_owner(origin_owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err, "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    svc = OSSService()
    result = svc.fork_repo(origin_owner, repo)

    return jsonify({
        "success": True,
        "forked": result["success"],
        "message": "Fork initiated — poll /api/oss/debug/fork-ready to check status" if result["success"] else safe_error_message(result.get("error"), "Fork failed"),
        "owner": my_user,
    })


@bp.route("/api/oss/debug/fork-ready", methods=["GET"])
@require_admin_key
def api_oss_debug_fork_ready():
    """Single poll check for fork readiness (no blocking loop)."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()

    if not repo:
        return jsonify({"success": False, "error": "Missing 'repo' query param", "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    svc = OSSService()
    ready = svc.check_fork_exists(my_user, repo)

    return jsonify({"success": True, "ready": ready, "owner": my_user})


@bp.route("/api/oss/debug/sync-fork", methods=["POST"])
@require_admin_key
def api_oss_debug_sync_fork():
    """Sync a fork with its upstream."""
    data = request.json
    repo = data.get("repo", "").strip()
    my_user = get_authenticated_user()

    if not repo:
        return jsonify({"success": False, "error": "Missing repo", "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    svc = OSSService()
    result = svc.sync_fork(my_user, repo)

    return jsonify({
        "success": True,
        "synced": result["success"],
        "error": result.get("error") if not result["success"] else None,
        "owner": my_user,
    })
