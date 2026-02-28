"""
Stage 5 routes — Submit Upstream.

Endpoints for submitting PRs to upstream repos and tracking their status.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..helpers.oss_helpers import format_upstream_pr_body
    from ..helpers.notifications import notify_upstream_merged, notify_upstream_feedback
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService
    from helpers.oss_helpers import format_upstream_pr_body
    from helpers.notifications import notify_upstream_merged, notify_upstream_feedback


@bp.route("/api/oss/stage5-submit", methods=["GET"])
def api_oss_stage5_submit():
    """Get items ready to submit upstream."""
    my_user = get_authenticated_user()
    svc = OSSService()
    items = svc.get_ready_to_submit()
    return jsonify({"success": True, "ready": items, "owner": my_user})


@bp.route("/api/oss/submit-to-origin", methods=["POST"])
def api_oss_submit_to_origin():
    """Submit a PR from fork to upstream origin repo."""
    data = request.json
    origin_slug = data.get("origin_slug")
    repo = data.get("repo")
    branch = data.get("branch")
    title = data.get("title")
    body = data.get("body")
    base_branch = data.get("base_branch", "main")

    if not all([origin_slug, repo, branch, title]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()

    # Generate default body if not provided
    if not body:
        # Look up issue_number from ready-to-submit data
        svc_lookup = OSSService()
        ready_items = svc_lookup.get_ready_to_submit()
        ready_item = next(
            (r for r in ready_items
             if r["origin_slug"] == origin_slug and r.get("branch") == branch),
            None
        )
        issue_number = ready_item.get("issue_number", 0) if ready_item else 0
        parts = origin_slug.split("/")
        if len(parts) == 2:
            body = format_upstream_pr_body(origin_slug, issue_number, title, branch)
        else:
            body = f"Fixes issue in {origin_slug}"

    result = run_gh_command([
        "pr", "create",
        "-R", origin_slug,
        "--head", f"{my_user}:{branch}",
        "--base", base_branch,
        "--title", title,
        "--body", body
    ], timeout=60)

    if result["success"]:
        pr_url = result["output"].strip()
        svc = OSSService()
        svc.save_submitted_pr(origin_slug, pr_url, title)
        svc.remove_ready_to_submit(origin_slug, branch)
        return jsonify({"success": True, "pr_url": pr_url, "owner": my_user})

    return jsonify({
        "success": False,
        "error": result.get("error", "Failed to create PR"),
        "owner": my_user,
    })


@bp.route("/api/oss/stage5-tracking", methods=["GET"])
def api_oss_stage5_tracking():
    """Get submitted PRs for tracking."""
    my_user = get_authenticated_user()
    svc = OSSService()
    items = svc.get_submitted_prs()
    return jsonify({"success": True, "submitted": items, "owner": my_user})


def _poll_single_pr(pr):
    """Poll a single submitted PR for status changes. Returns updated entry."""
    if pr.get("state") != "open":
        return pr  # Already in terminal state

    pr_url = pr.get("pr_url", "")
    # Parse URL: https://github.com/{owner}/{repo}/pull/{number}
    try:
        parts = pr_url.rstrip("/").split("/")
        pr_number = parts[-1]
        repo_owner = parts[-4]
        repo_name = parts[-3]
    except (IndexError, ValueError):
        return pr

    result = run_gh_command([
        "pr", "view", pr_number, "-R", f"{repo_owner}/{repo_name}",
        "--json", "state,reviewDecision,mergedAt,closedAt,comments,labels"
    ])

    if not result["success"]:
        return pr

    try:
        gh_data = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return pr

    old_state = pr.get("state")
    old_review = pr.get("review_decision")

    # Map gh CLI state to our format
    new_state = gh_data.get("state", "OPEN").upper()
    if new_state == "MERGED":
        pr["state"] = "merged"
    elif new_state == "CLOSED":
        pr["state"] = "closed"
    else:
        pr["state"] = "open"

    pr["review_decision"] = gh_data.get("reviewDecision")
    pr["merged_at"] = gh_data.get("mergedAt")
    pr["closed_at"] = gh_data.get("closedAt")
    pr["last_polled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Enhanced fields: comment count + labels
    comments = gh_data.get("comments", [])
    pr["comment_count"] = len(comments) if isinstance(comments, list) else 0
    labels = gh_data.get("labels", [])
    pr["labels"] = [lb.get("name", "") for lb in labels] if isinstance(labels, list) else []

    # Trigger notifications on state changes
    if old_state == "open" and pr["state"] == "merged":
        notify_upstream_merged(pr.get("origin_slug", ""), pr_url, pr.get("title", ""))
    if pr["review_decision"] and pr["review_decision"] != old_review:
        if pr["review_decision"] in ("CHANGES_REQUESTED", "APPROVED"):
            notify_upstream_feedback(
                pr.get("origin_slug", ""), pr_url, pr["review_decision"],
            )

    return pr


@bp.route("/api/oss/poll-submitted-prs", methods=["POST"])
def api_oss_poll_submitted_prs():
    """Poll all submitted PRs for status changes and update tracking."""
    my_user = get_authenticated_user()
    svc = OSSService()
    items = svc.get_submitted_prs()

    if not items:
        return jsonify({"success": True, "submitted": [], "owner": my_user})

    # Poll open PRs in parallel
    open_prs = [pr for pr in items if pr.get("state") == "open"]
    closed_prs = [pr for pr in items if pr.get("state") != "open"]

    if open_prs:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_poll_single_pr, pr) for pr in open_prs]
            updated_open = []
            for future in as_completed(futures):
                try:
                    updated_open.append(future.result())
                except Exception:
                    pass
            items = updated_open + closed_prs

    svc.update_submitted_prs(items)
    return jsonify({"success": True, "submitted": items, "owner": my_user})
