"""
Debug tracking endpoints: fork-pr-status, poll-submitted-pr, notification-preview.
"""

import json
import os

from flask import request, jsonify

try:
    from .. import bp
    from ...services import run_gh_command, get_authenticated_user, OSSService
    from ...helpers.validation import validate_repo_name
    from ...routes.debug._middleware import require_admin
except ImportError:
    from routes import bp
    from services import run_gh_command, get_authenticated_user, OSSService
    from helpers.validation import validate_repo_name
    from routes.debug._middleware import require_admin


@bp.route("/api/oss/debug/fork-pr-status", methods=["GET"])
@require_admin
def api_oss_debug_fork_pr_status():
    """Get status of a single fork PR."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()
    pr_number = request.args.get("pr_number", "").strip()

    if not repo or not pr_number:
        return jsonify({"success": False, "error": "Missing repo or pr_number", "owner": my_user})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err, "owner": my_user})

    result = run_gh_command([
        "pr", "view", pr_number, "-R", f"{my_user}/{repo}",
        "--json", "number,title,state,reviewDecision,additions,deletions,changedFiles,isDraft,headRefName,baseRefName,createdAt,url"
    ])

    if not result["success"]:
        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to fetch PR"),
            "owner": my_user,
        })

    try:
        pr_data = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return jsonify({"success": False, "error": "Failed to parse PR data", "owner": my_user})

    return jsonify({"success": True, "pr": pr_data, "owner": my_user})


@bp.route("/api/oss/debug/poll-submitted-pr", methods=["GET"])
@require_admin
def api_oss_debug_poll_submitted_pr():
    """Poll a single submitted PR for status changes (read-only preview, no updates)."""
    my_user = get_authenticated_user()
    pr_url = request.args.get("pr_url", "").strip()

    if not pr_url:
        return jsonify({"success": False, "error": "Missing pr_url query param", "owner": my_user})

    # Parse URL: https://github.com/{owner}/{repo}/pull/{number}
    try:
        parts = pr_url.rstrip("/").split("/")
        pr_number = parts[-1]
        repo_owner = parts[-4]
        repo_name = parts[-3]
    except (IndexError, ValueError):
        return jsonify({"success": False, "error": "Invalid PR URL format", "owner": my_user})

    # Fetch current state from GitHub
    result = run_gh_command([
        "pr", "view", pr_number, "-R", f"{repo_owner}/{repo_name}",
        "--json", "state,reviewDecision,mergedAt,closedAt"
    ])

    if not result["success"]:
        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to fetch PR"),
            "owner": my_user,
        })

    try:
        gh_data = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return jsonify({"success": False, "error": "Failed to parse PR data", "owner": my_user})

    # Map state
    raw_state = gh_data.get("state", "OPEN").upper()
    if raw_state == "MERGED":
        current_state = "merged"
    elif raw_state == "CLOSED":
        current_state = "closed"
    else:
        current_state = "open"

    # Look up tracked entry
    svc = OSSService()
    submitted = svc.get_submitted_prs()
    tracked = next((pr for pr in submitted if pr.get("pr_url") == pr_url), None)

    state_changed = False
    changes = {}
    notifications = []

    if tracked:
        old_state = tracked.get("state", "open")
        old_review = tracked.get("review_decision")

        if old_state != current_state:
            state_changed = True
            changes["state"] = {"old": old_state, "new": current_state}

        new_review = gh_data.get("reviewDecision")
        if new_review and new_review != old_review:
            state_changed = True
            changes["review_decision"] = {"old": old_review, "new": new_review}

        # Preview notifications that would fire
        if old_state == "open" and current_state == "merged":
            notifications.append("notify_upstream_merged")
        if new_review and new_review != old_review and new_review in ("CHANGES_REQUESTED", "APPROVED"):
            notifications.append("notify_upstream_feedback")

    return jsonify({
        "success": True,
        "current_state": current_state,
        "review_decision": gh_data.get("reviewDecision"),
        "tracked_entry": tracked,
        "state_changed": state_changed,
        "changes": changes,
        "notifications_that_would_fire": notifications,
        "owner": my_user,
    })


@bp.route("/api/oss/debug/notification-preview", methods=["GET"])
@require_admin
def api_oss_debug_notification_preview():
    """Preview what notifications would fire based on current state."""
    my_user = get_authenticated_user()
    svc = OSSService()

    discord_configured = bool(os.environ.get("DISCORD_WEBHOOK_URL"))
    submitted = svc.get_submitted_prs()

    pr_scenarios = []
    for pr in submitted:
        scenario = {
            "pr_url": pr.get("pr_url"),
            "state": pr.get("state"),
            "review_decision": pr.get("review_decision"),
            "would_poll": pr.get("state") == "open",
            "notifications": [],
        }
        if pr.get("state") == "open":
            scenario["notifications"].append("poll_for_state_change")
        pr_scenarios.append(scenario)

    return jsonify({
        "success": True,
        "discord_webhook_configured": discord_configured,
        "go_tier_notified_count": 0,
        "submitted_pr_count": len(submitted),
        "pr_scenarios": pr_scenarios,
        "owner": my_user,
    })
