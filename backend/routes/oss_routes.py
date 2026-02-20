"""
OSS routes — all endpoints for the OSS contribution pipeline (Stages 1-5).
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..helpers.oss_helpers import format_upstream_pr_body
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService
    from helpers.oss_helpers import format_upstream_pr_body


# ============ Stage 1: Target Repos (stubs — M2 aggregator integration) ============

@bp.route("/api/oss/stage1-targets", methods=["GET"])
def api_oss_stage1_targets():
    """Get target repos from aggregator watchlist. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": True, "targets": [], "owner": my_user})


@bp.route("/api/oss/add-target", methods=["POST"])
def api_oss_add_target():
    """Add a repo to the aggregator watchlist. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": False, "error": "Aggregator not configured", "owner": my_user})


@bp.route("/api/oss/remove-target", methods=["POST"])
def api_oss_remove_target():
    """Remove a repo from the aggregator watchlist. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": False, "error": "Aggregator not configured", "owner": my_user})


@bp.route("/api/oss/refresh-target", methods=["POST"])
def api_oss_refresh_target():
    """Trigger re-scrape for a target repo. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": False, "error": "Aggregator not configured", "owner": my_user})


# ============ Stage 2: Scored Issues (stubs — M2 aggregator integration) ============

@bp.route("/api/oss/stage2-issues", methods=["GET"])
def api_oss_stage2_issues():
    """Get scored issues from aggregator. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": True, "issues": [], "owner": my_user})


@bp.route("/api/oss/dossier/<slug>", methods=["GET"])
def api_oss_dossier(slug):
    """Get a repo dossier from aggregator. Stub for M1."""
    my_user = get_authenticated_user()
    return jsonify({"success": True, "dossier": None, "owner": my_user})


# ============ Stage 3: Fork & Assign ============

@bp.route("/api/oss/stage3-assigned", methods=["GET"])
def api_oss_stage3_assigned():
    """Get all fork issues that have been created and assigned."""
    my_user = get_authenticated_user()
    svc = OSSService()
    assignments = svc.get_assigned_issues()
    return jsonify({"success": True, "assignments": assignments, "owner": my_user})


@bp.route("/api/oss/select-issue", methods=["POST"])
def api_oss_select_issue():
    """Mark an issue as selected for work."""
    data = request.json
    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")

    if not all([origin_owner, repo, issue_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()
    origin_slug = f"{origin_owner}/{repo}"
    svc = OSSService()

    existing = svc.find_selected_issue(origin_slug, issue_number)
    if existing:
        return jsonify({"success": True, "already_selected": True, "owner": my_user})

    svc.select_issue(origin_slug, issue_number, issue_title, issue_url)
    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/fork-and-assign", methods=["POST"])
def api_oss_fork_and_assign():
    """Fork a repo, create a context issue, and assign Copilot.

    This is the critical Stage 3 endpoint. The flow:
    1. Dedup guard — don't create duplicate context issues
    2. Fork the upstream repo (if not already forked)
    3. Wait for fork to be ready (GitHub fork creation is async)
    4. Sync fork with upstream
    5. Build agent context (issue body + CONTRIBUTING.md + dossier)
    6. Create context issue on fork
    7. Assign Copilot to the fork issue
    8. Track locally in assignments.json
    9. Report claim to aggregator (best-effort)
    """
    data = request.json
    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")
    dossier_context = data.get("dossier")

    if not all([origin_owner, repo, issue_number, issue_title, issue_url]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()
    origin_slug = f"{origin_owner}/{repo}"
    svc = OSSService()

    # 0. Dedup guard
    existing = svc.find_assignment(origin_slug, issue_number)
    if existing:
        return jsonify({
            "success": True,
            "fork_issue_url": existing["fork_issue_url"],
            "owner": my_user,
            "already_assigned": True,
        })

    # 1. Fork if needed
    if not svc.check_fork_exists(my_user, repo):
        fork_result = svc.fork_repo(origin_owner, repo)
        if not fork_result["success"]:
            return jsonify({
                "success": False,
                "error": f"Failed to fork: {fork_result.get('error', 'Unknown error')}",
                "owner": my_user,
            })

    # 2. Wait for fork to be ready
    if not svc.wait_for_fork(my_user, repo, timeout=60, interval=3):
        return jsonify({
            "success": False,
            "error": "Fork creation timed out",
            "owner": my_user,
        })

    # 3. Sync fork
    svc.sync_fork(my_user, repo)

    # 4. Build agent context
    context_body = svc.build_agent_context(
        origin_owner, repo, issue_number, issue_title, issue_url, dossier_context
    )

    # 5. Create context issue on fork
    create_result = run_gh_command([
        "issue", "create", "-R", f"{my_user}/{repo}",
        "--title", f"[OSS] Fix {origin_owner}/{repo}#{issue_number}: {issue_title}",
        "--body", context_body
    ])

    if not create_result["success"]:
        return jsonify({
            "success": False,
            "error": f"Failed to create issue: {create_result.get('error', 'Unknown error')}",
            "owner": my_user,
        })

    # 6. Assign Copilot
    fork_issue_url = create_result["output"].strip()
    fork_issue_number = fork_issue_url.split("/")[-1]

    run_gh_command([
        "issue", "edit", fork_issue_number,
        "-R", f"{my_user}/{repo}",
        "--add-assignee", "@Copilot"
    ])

    # 7. Track locally
    svc.save_assignment(origin_owner, repo, issue_number, fork_issue_number, fork_issue_url)

    # 8. Report claim to aggregator (best-effort)
    issue_id = f"github-{origin_owner}-{repo}-{issue_number}"
    svc.report_claim(origin_slug, issue_id, my_user, fork_issue_url)

    return jsonify({
        "success": True,
        "fork_issue_url": fork_issue_url,
        "owner": my_user,
    })


# ============ Stage 4: Review on Fork ============

def _get_fork_prs(my_user, repo, origin_slug):
    """Fetch PRs from a single forked repo. Used by ThreadPoolExecutor."""
    result = run_gh_command([
        "pr", "list", "-R", f"{my_user}/{repo}",
        "--json", "number,title,url,headRefName,additions,deletions,changedFiles,reviewDecision,isDraft,createdAt"
    ])
    if result["success"]:
        try:
            prs = json.loads(result["output"])
            for pr in prs:
                pr["repo"] = repo
                pr["originSlug"] = origin_slug
            return prs
        except (json.JSONDecodeError, KeyError):
            pass
    return []


@bp.route("/api/oss/stage4-fork-prs", methods=["GET"])
def api_oss_stage4_fork_prs():
    """Get PRs from all forked repos where we've assigned work."""
    my_user = get_authenticated_user()
    svc = OSSService()

    assignments = svc.get_assigned_issues()
    forked_repos = {(a["origin_slug"], a["repo"]) for a in assignments}

    all_prs = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_get_fork_prs, my_user, repo, origin_slug)
            for origin_slug, repo in forked_repos
        ]
        for future in as_completed(futures):
            all_prs.extend(future.result())

    all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return jsonify({"success": True, "prs": all_prs, "owner": my_user})


@bp.route("/api/oss/fork-pr-details", methods=["POST"])
def api_oss_fork_pr_details():
    """Get detailed info about a PR on a fork, including diff."""
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    if not all([repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()

    result = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
        "--json", "number,title,body,author,createdAt,headRefName,baseRefName,files,commits,reviewDecision,state,url,isDraft,additions,deletions,changedFiles,assignees"
    ])

    if result["success"]:
        pr_data = json.loads(result["output"])

        diff_result = run_gh_command([
            "pr", "diff", str(pr_number), "-R", f"{my_user}/{repo}"
        ])
        if diff_result["success"]:
            pr_data["diff"] = diff_result["output"]

        return jsonify({"success": True, "pr": pr_data, "owner": my_user})

    return jsonify({
        "success": False,
        "error": result.get("error", "Failed to fetch PR"),
        "owner": my_user,
    })


@bp.route("/api/oss/approve-fork-pr", methods=["POST"])
def api_oss_approve_fork_pr():
    """Approve a PR on a fork."""
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    if not all([repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()

    result = run_gh_command([
        "pr", "review", str(pr_number),
        "-R", f"{my_user}/{repo}",
        "--approve",
        "-b", "Approved"
    ])

    if result["success"]:
        return jsonify({
            "success": True,
            "message": f"PR #{pr_number} approved!",
            "owner": my_user,
        })
    return jsonify({
        "success": False,
        "error": result.get("error", "Failed to approve PR"),
        "owner": my_user,
    })


@bp.route("/api/oss/merge-fork-pr", methods=["POST"])
def api_oss_merge_fork_pr():
    """Merge a PR on a fork. Captures branch info and transitions to Stage 5."""
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")
    origin_slug = data.get("origin_slug")

    if not all([repo, pr_number, origin_slug]):
        return jsonify({"success": False, "error": "Missing required fields"})

    my_user = get_authenticated_user()
    svc = OSSService()

    # Capture branch name before merge (can't read it after)
    pr_info = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
        "--json", "headRefName,title,baseRefName"
    ])
    pr_data = {}
    if pr_info["success"]:
        try:
            pr_data = json.loads(pr_info["output"])
        except (json.JSONDecodeError, KeyError):
            pass

    # Check if PR is a draft and mark it as ready first
    check_result = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
        "--json", "isDraft"
    ])
    if check_result["success"]:
        try:
            draft_data = json.loads(check_result["output"])
            if draft_data.get("isDraft", False):
                run_gh_command([
                    "pr", "ready", str(pr_number),
                    "-R", f"{my_user}/{repo}"
                ])
        except (json.JSONDecodeError, KeyError):
            pass

    # Merge on fork
    result = run_gh_command([
        "pr", "merge", str(pr_number),
        "-R", f"{my_user}/{repo}",
        "--squash"
    ], timeout=60)

    if result["success"]:
        # Move to Stage 5: ready to submit
        svc.save_ready_to_submit(
            origin_slug=origin_slug,
            repo=repo,
            branch=pr_data.get("headRefName", ""),
            title=pr_data.get("title", ""),
            base_branch=pr_data.get("baseRefName", "main"),
        )
        return jsonify({"success": True, "message": f"PR #{pr_number} merged!", "owner": my_user})

    return jsonify({
        "success": False,
        "error": result.get("error", "Failed to merge PR"),
        "owner": my_user,
    })


# ============ Stage 5: Submit Upstream ============

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
        parts = origin_slug.split("/")
        if len(parts) == 2:
            body = format_upstream_pr_body(origin_slug, 0, title, branch)
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
