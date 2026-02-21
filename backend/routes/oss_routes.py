"""
OSS routes — all endpoints for the OSS contribution pipeline (Stages 1-5).
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from ..services.oss_service import _call_aggregator
    from ..helpers.oss_helpers import format_upstream_pr_body, score_issue_fallback
    from ..helpers.notifications import (
        notify_go_tier_issue, notify_pr_ready_for_review,
        notify_upstream_merged, notify_upstream_feedback,
    )
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from services.oss_service import _call_aggregator
    from helpers.oss_helpers import format_upstream_pr_body, score_issue_fallback
    from helpers.notifications import (
        notify_go_tier_issue, notify_pr_ready_for_review,
        notify_upstream_merged, notify_upstream_feedback,
    )

# Track GO-tier issue IDs already notified (avoid re-firing on cache refresh)
_notified_go_issues = set()


# ============ Stage 1: Target Repos ============


def _enrich_target_via_gh(entry):
    """Fetch basic repo metadata via gh CLI for a watchlist entry."""
    owner, repo = entry["owner"], entry["repo"]
    target = {"slug": entry["slug"]}

    result = run_gh_command([
        "api", f"/repos/{owner}/{repo}",
        "--jq", "{stars: .stargazers_count, language: .language, license: .license.spdx_id, openIssueCount: .open_issues_count, hasContributing: false}"
    ])
    if result["success"]:
        try:
            meta = json.loads(result["output"])
            target["meta"] = meta
        except (json.JSONDecodeError, KeyError):
            pass

    return target


@bp.route("/api/oss/stage1-targets", methods=["GET"])
@cached_endpoint("oss-stage1-targets")
def api_oss_stage1_targets():
    """Get target repos with health scores.

    Tries aggregator first for watchlist + health data.
    Falls back to local watchlist with gh CLI metadata enrichment.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Try aggregator first
    aggregator_slugs = svc.get_watchlist()

    if aggregator_slugs:
        targets = []
        for slug in aggregator_slugs:
            target = {"slug": slug}
            health = _call_aggregator(f"/recon/{slug}/health")
            if health:
                target["health"] = {
                    "maintainerHealthScore": health.get("maintainerHealthScore", 0),
                    "mergeAccessibilityScore": health.get("mergeAccessibilityScore", 0),
                    "availabilityScore": health.get("availabilityScore", 0),
                    "overallViability": health.get("overallViability", 0),
                }
            targets.append(target)
        return {"success": True, "targets": targets, "owner": my_user}

    # Fallback: local watchlist + gh CLI metadata
    local_watchlist = svc.get_local_watchlist()
    targets = []

    if local_watchlist:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_enrich_target_via_gh, entry) for entry in local_watchlist]
            for future in as_completed(futures):
                try:
                    targets.append(future.result())
                except Exception:
                    pass

    return {"success": True, "targets": targets, "owner": my_user}


@bp.route("/api/oss/add-target", methods=["POST"])
def api_oss_add_target():
    """Add a repo to the watchlist.

    Accepts {slug: "owner/repo"} in slash format.
    Validates via gh api, saves to local watchlist, proxies to aggregator.
    """
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    if "/" not in slug:
        return jsonify({"success": False, "error": "Format must be owner/repo", "owner": my_user})

    parts = slug.split("/", 1)
    owner, repo = parts[0].strip(), parts[1].strip()

    if not owner or not repo:
        return jsonify({"success": False, "error": "Invalid owner/repo format", "owner": my_user})

    # Validate repo exists
    validate_result = run_gh_command([
        "api", f"/repos/{owner}/{repo}", "--jq", ".full_name"
    ])
    if not validate_result["success"]:
        return jsonify({"success": False, "error": f"Repository {owner}/{repo} not found", "owner": my_user})

    svc = OSSService()

    # Save to local watchlist
    svc.add_to_local_watchlist(owner, repo)

    # Proxy to aggregator (best-effort)
    hyphenated_slug = f"{owner}-{repo}"
    svc.add_to_watchlist(hyphenated_slug)
    svc.trigger_refresh(hyphenated_slug)

    # Invalidate cache
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/remove-target", methods=["POST"])
def api_oss_remove_target():
    """Remove a repo from the watchlist."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    svc = OSSService()

    if "/" in slug:
        owner, repo = slug.split("/", 1)
    else:
        # Look up in local watchlist by hyphenated slug
        watchlist = svc.get_local_watchlist()
        entry = next((e for e in watchlist if e["slug"] == slug), None)
        if entry:
            owner, repo = entry["owner"], entry["repo"]
        else:
            return jsonify({"success": False, "error": "Target not found", "owner": my_user})

    svc.remove_from_local_watchlist(owner, repo)

    # Proxy to aggregator (best-effort)
    hyphenated_slug = f"{owner}-{repo}"
    svc.remove_from_watchlist(hyphenated_slug)

    # Invalidate cache
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/refresh-target", methods=["POST"])
def api_oss_refresh_target():
    """Trigger re-scrape for a target repo."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    svc = OSSService()

    # Convert to hyphenated format for aggregator
    if "/" in slug:
        hyphenated_slug = slug.replace("/", "-")
    else:
        hyphenated_slug = slug

    svc.trigger_refresh(hyphenated_slug)

    # Invalidate cache regardless of aggregator response
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "message": "Cache invalidated", "owner": my_user})


# ============ Stage 2: Scored Issues ============


def _fetch_repo_issues_fallback(entry):
    """Fetch and score issues for a single repo via gh CLI fallback."""
    owner, repo = entry["owner"], entry["repo"]
    result = run_gh_command([
        "issue", "list", "-R", f"{owner}/{repo}",
        "--label", "good first issue",
        "--state", "open",
        "--limit", "30",
        "--json", "number,title,url,labels,createdAt,updatedAt,comments,assignees"
    ])
    if not result["success"]:
        return []

    try:
        issues = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return []

    scored = []
    for issue in issues:
        score_data = score_issue_fallback(issue)
        if score_data["cvsTier"] == "skip":
            continue

        # Normalize labels to string[]
        labels = []
        for label in issue.get("labels", []):
            if isinstance(label, dict):
                labels.append(label.get("name", ""))
            elif isinstance(label, str):
                labels.append(label)

        # Normalize assignees to string[]
        assignees = []
        for a in issue.get("assignees", []):
            if isinstance(a, dict):
                assignees.append(a.get("login", ""))
            elif isinstance(a, str):
                assignees.append(a)

        # Normalize comments to count
        comments = issue.get("comments", 0)
        if isinstance(comments, list):
            comments = len(comments)

        issue_id = f"github-{owner}-{repo}-{issue['number']}"

        # Notify on GO-tier issues (only once per issue)
        if score_data["cvs"] >= 85 and issue_id not in _notified_go_issues:
            _notified_go_issues.add(issue_id)
            notify_go_tier_issue(
                f"{owner}/{repo}", issue["number"],
                issue["title"], score_data["cvs"],
            )

        scored.append({
            "id": issue_id,
            "repo": f"{owner}/{repo}",
            "number": issue["number"],
            "title": issue["title"],
            "url": issue.get("url", f"https://github.com/{owner}/{repo}/issues/{issue['number']}"),
            "cvs": score_data["cvs"],
            "cvsTier": score_data["cvsTier"],
            "lifecycleStage": "unknown",
            "complexity": "unknown",
            "labels": labels,
            "commentCount": comments,
            "assignees": assignees,
            "claimStatus": "unclaimed",
            "createdAt": issue.get("createdAt", ""),
            "dataCompleteness": "partial",
            "repoKilled": False,
        })

    return scored


@bp.route("/api/oss/stage2-issues", methods=["GET"])
@cached_endpoint("oss-stage2-issues")
def api_oss_stage2_issues():
    """Get scored issues across all target repos.

    Tries aggregator for CVS-scored issues.
    Falls back to gh CLI + heuristic scoring.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Try aggregator first
    aggregator_issues = svc.get_scored_issues()
    if aggregator_issues:
        return {"success": True, "issues": aggregator_issues, "owner": my_user}

    # Fallback: fetch from gh CLI for each target in local watchlist
    local_watchlist = svc.get_local_watchlist()
    if not local_watchlist:
        return {"success": True, "issues": [], "owner": my_user}

    all_issues = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_fetch_repo_issues_fallback, entry) for entry in local_watchlist]
        for future in as_completed(futures):
            try:
                all_issues.extend(future.result())
            except Exception:
                pass

    # Sort by CVS score descending
    all_issues.sort(key=lambda x: x["cvs"], reverse=True)

    return {"success": True, "issues": all_issues, "owner": my_user}


@bp.route("/api/oss/dossier/<slug>", methods=["GET"])
def api_oss_dossier(slug):
    """Get a repo dossier from aggregator. No fallback for dossiers."""
    my_user = get_authenticated_user()
    svc = OSSService()
    dossier = svc.get_dossier(slug)
    return jsonify({"success": True, "dossier": dossier, "owner": my_user})


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

    # Auto-fetch dossier from aggregator if not provided by frontend
    if not dossier_context:
        dossier_data = svc.get_dossier(f"{origin_owner}-{repo}")
        if dossier_data and dossier_data.get("sections"):
            dossier_context = dossier_data["sections"]

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
        "--json", "state,reviewDecision,mergedAt,closedAt"
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
