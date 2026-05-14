"""
Stage 5 routes — Submit Upstream.

Endpoints for submitting PRs to upstream repos and tracking their status.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..services.oss_state import save_session_artifact
    from ..services.pipeline_retrospective import fetch_pr_comments
    from ..helpers.oss_helpers import format_upstream_pr_body
    from ..helpers.bot_filter import filter_human_comments
    from ..helpers.notifications import notify_upstream_merged, notify_upstream_feedback, notify_upstream_closed, notify_upstream_submitted, notify_upstream_comment
    from ..helpers.validation import validate_slug, validate_repo_name, validate_required_fields, safe_error_message, error_response
    from ..extensions import limiter
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService
    from services.oss_state import save_session_artifact
    from services.pipeline_retrospective import fetch_pr_comments
    from helpers.oss_helpers import format_upstream_pr_body
    from helpers.bot_filter import filter_human_comments
    from helpers.notifications import notify_upstream_merged, notify_upstream_feedback, notify_upstream_closed, notify_upstream_submitted, notify_upstream_comment
    from helpers.validation import validate_slug, validate_repo_name, validate_required_fields, safe_error_message, error_response
    from extensions import limiter


@bp.route("/api/oss/stage5-submit", methods=["GET"])
def api_oss_stage5_submit():
    """Get items ready to submit upstream."""
    my_user = get_authenticated_user()
    svc = OSSService()
    items = svc.get_ready_to_submit()
    return jsonify({"success": True, "ready": items, "owner": my_user})


@bp.route("/api/oss/admin/archive-ready-to-submit", methods=["POST"])
def api_oss_admin_archive_ready_to_submit():
    """One-time cleanup: move stale ready-to-submit records into
    submitted-prs.json under `state="merged-in-fork-only"`.

    Used for entries whose fork PR merged but where the upstream
    submission never happened (and the fork may now be deleted, making
    submission impossible anyway). Dedups duplicate rows on the way.

    The records stay queryable in submitted-prs.json for retrospective,
    they just disappear from the actionable "Ready to submit" panel.
    Idempotent — calling again on an empty ready-to-submit returns
    {archived: 0, cleared: 0}.
    """
    svc = OSSService()
    result = svc.archive_ready_to_submit_as_fork_merged_only()
    return jsonify({"success": True, **result})


@bp.route("/api/oss/submit-to-origin", methods=["POST"])
@limiter.limit("5 per minute")
def api_oss_submit_to_origin():
    """Submit a PR from fork to upstream origin repo."""
    data = request.json
    req_err = validate_required_fields(data, ["origin_slug", "repo", "branch", "title"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    origin_slug = data.get("origin_slug")
    repo = data.get("repo")
    branch = data.get("branch")
    title = data.get("title")
    body = data.get("body")
    base_branch = data.get("base_branch", "main")

    slug_err = validate_slug(origin_slug)
    if slug_err:
        return jsonify({"success": False, "error": slug_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})

    my_user = get_authenticated_user()

    # Look up ready-to-submit data (used for body generation + notification)
    svc_lookup = OSSService()
    ready_items = svc_lookup.get_ready_to_submit()
    ready_item = next(
        (r for r in ready_items
         if r["origin_slug"] == origin_slug and r.get("branch") == branch),
        None
    )

    # Generate default body if not provided
    issue_num = ready_item.get("issue_number", 0) if ready_item else 0
    if not body:
        parts = origin_slug.split("/")
        if len(parts) == 2:
            body = format_upstream_pr_body(origin_slug, issue_num, title, branch)
        else:
            body = f"Fixes issue in {origin_slug}"

    # Save PR body for retrospective before submitting
    if issue_num:
        save_session_artifact(origin_slug, issue_num, "upstream-pr-body.md", body)

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
        svc.save_submitted_pr(origin_slug, pr_url, title, issue_number=issue_num)
        svc.remove_ready_to_submit(origin_slug, branch)
        notify_upstream_submitted(origin_slug, issue_num, pr_url, title)

        return jsonify({"success": True, "pr_url": pr_url, "owner": my_user})

    return error_response(result.get("error"), "Failed to create PR", my_user)


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
        logger.warning("Cannot parse PR URL for polling: %r", pr_url)
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

    # Fetch comments: used for both retrospective archiving and new-comment detection
    all_comments = []
    try:
        all_comments = fetch_pr_comments(f"{repo_owner}/{repo_name}", int(pr_number))
        issue_num = pr.get("issue_number")
        origin_slug = pr.get("origin_slug", "")
        if all_comments and issue_num and origin_slug:
            save_session_artifact(
                origin_slug, issue_num,
                "upstream-pr-comments.json", json.dumps(all_comments, indent=2)
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("Upstream PR comment capture failed for %s#%s: %s", f"{repo_owner}/{repo_name}", pr_number, e)

    # Detect new human comments and notify.
    # Baseline: last_notified_comment_at (updated each poll), falling back to
    # submitted_at so we don't spam comments that existed before we started tracking.
    last_seen = pr.get("last_notified_comment_at") or pr.get("submitted_at", "")
    human_comments = filter_human_comments(all_comments)
    new_comments = [c for c in human_comments if c.get("created_at", "") > last_seen]
    for comment in new_comments:
        notify_upstream_comment(
            pr.get("origin_slug", ""), pr_url,
            comment.get("author", "unknown"),
            comment.get("body", ""),
        )
    if human_comments:
        pr["last_notified_comment_at"] = max(c.get("created_at", "") for c in human_comments)

    # Trigger notifications on state changes
    if old_state == "open" and pr["state"] == "merged":
        notify_upstream_merged(pr.get("origin_slug", ""), pr_url, pr.get("title", ""))
    elif old_state == "open" and pr["state"] == "closed":
        notify_upstream_closed(pr.get("origin_slug", ""), pr_url, pr.get("title", ""))
    if (pr["review_decision"] == "CHANGES_REQUESTED"
            and pr["review_decision"] != old_review):
        notify_upstream_feedback(
            pr.get("origin_slug", ""), pr_url, pr["review_decision"],
        )

    return pr


@bp.route("/api/oss/poll-submitted-prs", methods=["POST"])
@limiter.limit("60 per minute")
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
                except Exception as e:
                    logger.warning("Failed to poll submitted PR: %s", e)
            items = updated_open + closed_prs

    svc.update_submitted_prs(items)
    return jsonify({"success": True, "submitted": items, "owner": my_user})
