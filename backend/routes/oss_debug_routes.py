"""
OSS debug routes — 14 synchronous diagnostic endpoints for pipeline debugging.

Each endpoint does ONE thing and returns data directly. Enables manual pipeline
stepping and validation without going through the monolithic stage endpoints.
"""

import json
import os
import time

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..services.oss_service import _call_aggregator, OSS_DATA_DIR, AGGREGATOR_API_URL
    from ..helpers.oss_helpers import score_issue_with_breakdown
    from .oss_routes import _notified_go_issues
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService
    from services.oss_service import _call_aggregator, OSS_DATA_DIR, AGGREGATOR_API_URL
    from helpers.oss_helpers import score_issue_with_breakdown
    from routes.oss_routes import _notified_go_issues


# ============ Group A: Health Checks ============


@bp.route("/api/oss/debug/gh-health", methods=["GET"])
def api_oss_debug_gh_health():
    """Check gh CLI health: authentication, API access, rate limits."""
    my_user = get_authenticated_user()
    start = time.time()

    result = {
        "authenticated": False,
        "user": my_user,
        "api_working": False,
        "rate_limit": None,
        "response_time_ms": 0,
    }

    # Check auth
    auth_result = run_gh_command(["auth", "status"])
    result["authenticated"] = auth_result["success"]

    # Check API access
    api_result = run_gh_command(["api", "user", "--jq", ".login"])
    result["api_working"] = api_result["success"]

    # Check rate limit
    rate_result = run_gh_command(["api", "rate_limit", "--jq", ".rate"])
    if rate_result["success"]:
        try:
            rate_data = json.loads(rate_result["output"])
            result["rate_limit"] = {
                "remaining": rate_data.get("remaining"),
                "limit": rate_data.get("limit"),
                "reset_at": rate_data.get("reset"),
            }
        except (json.JSONDecodeError, KeyError):
            pass

    result["response_time_ms"] = round((time.time() - start) * 1000)
    return jsonify({"success": True, **result, "owner": my_user})


@bp.route("/api/oss/debug/aggregator-health", methods=["GET"])
def api_oss_debug_aggregator_health():
    """Check aggregator API availability and response time."""
    my_user = get_authenticated_user()
    start = time.time()

    result = {
        "configured": bool(AGGREGATOR_API_URL),
        "base_url": AGGREGATOR_API_URL or "(not configured)",
        "reachable": False,
        "response_time_ms": 0,
        "watchlist_count": 0,
        "error": None,
    }

    if AGGREGATOR_API_URL:
        data = _call_aggregator("/recon/watchlist")
        result["response_time_ms"] = round((time.time() - start) * 1000)
        if data is not None:
            result["reachable"] = True
            if isinstance(data, dict) and "slugs" in data:
                result["watchlist_count"] = len(data["slugs"])
        else:
            result["error"] = "Aggregator unreachable or returned error"
    else:
        result["error"] = "AGGREGATOR_API_URL not configured"

    return jsonify({"success": True, **result, "owner": my_user})


@bp.route("/api/oss/debug/state-dump", methods=["GET"])
def api_oss_debug_state_dump():
    """Dump all local pipeline state (JSON files) with counts."""
    my_user = get_authenticated_user()

    files = {
        "watchlist": "watchlist.json",
        "selected_issues": "selected-issues.json",
        "assignments": "assignments.json",
        "ready_to_submit": "ready-to-submit.json",
        "submitted_prs": "submitted-prs.json",
    }

    state = {}
    counts = {}
    files_on_disk = []

    for key, filename in files.items():
        path = os.path.join(OSS_DATA_DIR, filename)
        if os.path.exists(path):
            files_on_disk.append(filename)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                state[key] = data
                counts[key] = len(data) if isinstance(data, list) else 1
            except (json.JSONDecodeError, OSError):
                state[key] = None
                counts[key] = 0
        else:
            state[key] = []
            counts[key] = 0

    return jsonify({
        "success": True,
        "state": state,
        "counts": counts,
        "files_on_disk": files_on_disk,
        "data_dir": OSS_DATA_DIR,
        "owner": my_user,
    })


# ============ Group B: Fork & Assign Decomposition ============


@bp.route("/api/oss/debug/fork-exists", methods=["GET"])
def api_oss_debug_fork_exists():
    """Check if a fork exists for the authenticated user."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()

    if not repo:
        return jsonify({"success": False, "error": "Missing 'repo' query param", "owner": my_user})

    svc = OSSService()
    exists = svc.check_fork_exists(my_user, repo)

    fork_url = f"https://github.com/{my_user}/{repo}" if exists else None
    return jsonify({"success": True, "exists": exists, "fork_url": fork_url, "owner": my_user})


@bp.route("/api/oss/debug/fork-repo", methods=["POST"])
def api_oss_debug_fork_repo():
    """Fork a repo (just fork, don't wait or sync)."""
    data = request.json
    origin_owner = data.get("origin_owner", "").strip()
    repo = data.get("repo", "").strip()
    my_user = get_authenticated_user()

    if not origin_owner or not repo:
        return jsonify({"success": False, "error": "Missing origin_owner or repo", "owner": my_user})

    svc = OSSService()
    result = svc.fork_repo(origin_owner, repo)

    return jsonify({
        "success": True,
        "forked": result["success"],
        "message": "Fork initiated — poll /api/oss/debug/fork-ready to check status" if result["success"] else result.get("error", "Fork failed"),
        "owner": my_user,
    })


@bp.route("/api/oss/debug/fork-ready", methods=["GET"])
def api_oss_debug_fork_ready():
    """Single poll check for fork readiness (no blocking loop)."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()

    if not repo:
        return jsonify({"success": False, "error": "Missing 'repo' query param", "owner": my_user})

    svc = OSSService()
    ready = svc.check_fork_exists(my_user, repo)

    return jsonify({"success": True, "ready": ready, "owner": my_user})


@bp.route("/api/oss/debug/sync-fork", methods=["POST"])
def api_oss_debug_sync_fork():
    """Sync a fork with its upstream."""
    data = request.json
    repo = data.get("repo", "").strip()
    my_user = get_authenticated_user()

    if not repo:
        return jsonify({"success": False, "error": "Missing repo", "owner": my_user})

    svc = OSSService()
    result = svc.sync_fork(my_user, repo)

    return jsonify({
        "success": True,
        "synced": result["success"],
        "error": result.get("error") if not result["success"] else None,
        "owner": my_user,
    })


@bp.route("/api/oss/debug/build-context", methods=["POST"])
def api_oss_debug_build_context():
    """Build agent context markdown and return it for inspection (does NOT create an issue)."""
    data = request.json
    origin_owner = data.get("origin_owner", "").strip()
    repo = data.get("repo", "").strip()
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title", "").strip()
    issue_url = data.get("issue_url", "").strip()
    my_user = get_authenticated_user()

    if not all([origin_owner, repo, issue_number, issue_title, issue_url]):
        return jsonify({"success": False, "error": "Missing required fields", "owner": my_user})

    svc = OSSService()

    # Try to get dossier and issue-brief for context building
    dossier_data = svc.get_dossier(f"{origin_owner}-{repo}")
    dossier = dossier_data.get("sections") if dossier_data else None

    issue_id = f"github-{origin_owner}-{repo}-{issue_number}"
    issue_brief = svc.get_issue_brief(f"{origin_owner}-{repo}", issue_id)

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
def api_oss_debug_create_context_issue():
    """Create an issue on a fork (does NOT assign Copilot or track in JSON)."""
    data = request.json
    repo = data.get("repo", "").strip()
    title = data.get("title", "").strip()
    body = data.get("body", "").strip()
    my_user = get_authenticated_user()

    if not all([repo, title, body]):
        return jsonify({"success": False, "error": "Missing repo, title, or body", "owner": my_user})

    result = run_gh_command([
        "issue", "create", "-R", f"{my_user}/{repo}",
        "--title", title,
        "--body", body
    ])

    if result["success"]:
        issue_url = result["output"].strip()
        issue_number = issue_url.split("/")[-1]
        return jsonify({
            "success": True,
            "issue_url": issue_url,
            "issue_number": int(issue_number),
            "owner": my_user,
        })

    return jsonify({
        "success": False,
        "error": result.get("error", "Failed to create issue"),
        "owner": my_user,
    })


@bp.route("/api/oss/debug/assign-copilot", methods=["POST"])
def api_oss_debug_assign_copilot():
    """Assign Copilot to an issue on a fork."""
    data = request.json
    repo = data.get("repo", "").strip()
    issue_number = data.get("issue_number")
    my_user = get_authenticated_user()

    if not repo or not issue_number:
        return jsonify({"success": False, "error": "Missing repo or issue_number", "owner": my_user})

    result = run_gh_command([
        "issue", "edit", str(issue_number),
        "-R", f"{my_user}/{repo}",
        "--add-assignee", "@Copilot"
    ])

    return jsonify({
        "success": True,
        "assigned": result["success"],
        "error": result.get("error") if not result["success"] else None,
        "owner": my_user,
    })


# ============ Group C: Scoring & Tracking ============


@bp.route("/api/oss/debug/score-issue", methods=["GET"])
def api_oss_debug_score_issue():
    """Score a single issue with full breakdown."""
    my_user = get_authenticated_user()
    owner = request.args.get("owner", "").strip()
    repo = request.args.get("repo", "").strip()
    issue_number = request.args.get("issue_number", "").strip()

    if not all([owner, repo, issue_number]):
        return jsonify({"success": False, "error": "Missing owner, repo, or issue_number", "owner": my_user})

    # Fetch issue data via gh CLI
    result = run_gh_command([
        "issue", "view", issue_number, "-R", f"{owner}/{repo}",
        "--json", "number,title,labels,createdAt,updatedAt,comments,assignees,url,reactionGroups"
    ])

    if not result["success"]:
        return jsonify({
            "success": False,
            "error": f"Failed to fetch issue: {result.get('error', 'Unknown')}",
            "owner": my_user,
        })

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


@bp.route("/api/oss/debug/fork-pr-status", methods=["GET"])
def api_oss_debug_fork_pr_status():
    """Get status of a single fork PR."""
    my_user = get_authenticated_user()
    repo = request.args.get("repo", "").strip()
    pr_number = request.args.get("pr_number", "").strip()

    if not repo or not pr_number:
        return jsonify({"success": False, "error": "Missing repo or pr_number", "owner": my_user})

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
        "go_tier_notified_count": len(_notified_go_issues),
        "submitted_pr_count": len(submitted),
        "pr_scenarios": pr_scenarios,
        "owner": my_user,
    })
