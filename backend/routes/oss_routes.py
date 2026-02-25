"""
OSS routes — all endpoints for the OSS contribution pipeline (Stages 1-5).
"""

import json
import re
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
            health_resp = _call_aggregator(f"/recon/{slug}/health")
            # Unwrap: { success, data: { maintainerHealthScore, ... } }
            health = health_resp.get("data", health_resp) if isinstance(health_resp, dict) else None
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
    # Trigger pre-computation so scored issues/dossier are available
    svc.trigger_compute(hyphenated_slug)

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
    # Trigger pre-computation so scored issues/dossier are available
    svc.trigger_compute(hyphenated_slug)

    # Invalidate cache regardless of aggregator response
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "message": "Cache invalidated, compute triggered", "owner": my_user})


# ============ Stage 2: Scored Issues ============


def _fetch_repo_issues_fallback(entry):
    """Fetch and score issues for a single repo via gh CLI fallback."""
    owner, repo = entry["owner"], entry["repo"]
    result = run_gh_command([
        "issue", "list", "-R", f"{owner}/{repo}",
        "--state", "open",
        "--limit", "50",
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
            "difficulty": "unknown",
            "difficultyScore": 0,
            "likelyFiles": [],
            "relatedIssues": [],
            "sentimentScore": 0,
            "contentQualityScore": 0,
            "competitionLevel": "unknown",
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


@bp.route("/api/oss/issue-brief/<slug>/<issue_id>", methods=["GET"])
def api_oss_issue_brief(slug, issue_id):
    """Get a pre-built issue brief from the aggregator.

    Returns the full ScoredIssue, RepoHealth, and a ready-to-use brief markdown string.
    """
    my_user = get_authenticated_user()
    svc = OSSService()
    brief = svc.get_issue_brief(slug, issue_id)
    return jsonify({"success": True, "data": brief, "owner": my_user})


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

    # Detect self-owned repos (can't fork your own repo)
    is_self_owned = (origin_owner.lower() == my_user.lower())

    # Auto-fetch dossier and issue-brief from aggregator
    hyphenated_slug = f"{origin_owner}-{repo}"
    issue_id = f"github-{origin_owner}-{repo}-{issue_number}"

    if not dossier_context:
        dossier_data = svc.get_dossier(hyphenated_slug)
        if dossier_data and dossier_data.get("sections"):
            dossier_context = dossier_data["sections"]

    issue_brief = svc.get_issue_brief(hyphenated_slug, issue_id)

    # If both are missing (pending), trigger compute and retry once
    if not dossier_context and not issue_brief:
        svc.trigger_compute(hyphenated_slug)
        time.sleep(2)
        dossier_data = svc.get_dossier(hyphenated_slug)
        if dossier_data and dossier_data.get("sections"):
            dossier_context = dossier_data["sections"]
        issue_brief = svc.get_issue_brief(hyphenated_slug, issue_id)

    # 0. Dedup guard
    existing = svc.find_assignment(origin_slug, issue_number)
    if existing:
        return jsonify({
            "success": True,
            "fork_issue_url": existing["fork_issue_url"],
            "owner": my_user,
            "already_assigned": True,
            "is_self_owned": is_self_owned,
            "context_sources": [],
        })

    if is_self_owned:
        # Self-owned repo — no fork needed, create issue directly on the repo
        pass
    else:
        # Third-party repo — fork, wait, and sync
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

        # 3b. Enable issues on fork (forks inherit has_issues=false from parent)
        svc.enable_fork_issues(my_user, repo)

        # 3c. Ensure .github/copilot-instructions.md exists on fork
        svc.ensure_copilot_instructions(my_user, repo)

        # 3d. Ensure CI workflow exists on fork for deterministic quality checks
        language = None
        if issue_brief and issue_brief.get("repoHealth"):
            language = issue_brief["repoHealth"].get("language")
        svc.ensure_ci_workflow(my_user, repo, language=language)

    # 4. Check for same-repo overlap with existing assignments
    existing_assignments = svc.get_assigned_issues()
    same_repo = [a for a in existing_assignments
                 if a["repo"] == repo and a["origin_slug"] == origin_slug
                 and a.get("issue_number") != issue_number]
    overlap_warning = None
    if same_repo:
        overlap_warning = (
            f"Warning: {len(same_repo)} other issue(s) from {origin_slug} "
            f"already assigned. Parallel work on the same repo may cause merge conflicts."
        )

    # 5. Build agent context (issue_brief takes priority over dossier)
    context_body, context_metadata = svc.build_agent_context(
        origin_owner, repo, issue_number, issue_title, issue_url,
        dossier_context, issue_brief, return_metadata=True,
        is_self_owned=is_self_owned
    )

    # 6. Create context issue on target repo (fork or self-owned)
    create_result = run_gh_command([
        "issue", "create", "-R", f"{my_user}/{repo}",
        "--title", f"[OSS] Fix: {issue_title}",
        "--body", context_body
    ])

    if not create_result["success"]:
        return jsonify({
            "success": False,
            "error": f"Failed to create issue: {create_result.get('error', 'Unknown error')}",
            "owner": my_user,
        })

    # 7. Assign Copilot
    fork_issue_url = create_result["output"].strip()
    fork_issue_number = fork_issue_url.split("/")[-1]

    run_gh_command([
        "issue", "edit", fork_issue_number,
        "-R", f"{my_user}/{repo}",
        "--add-assignee", "@Copilot"
    ])

    # 8. Track locally
    default_branch = svc.get_default_branch(
        origin_owner, repo, issue_brief=issue_brief, dossier_context=dossier_context
    )
    svc.save_assignment(
        origin_owner, repo, issue_number, fork_issue_number, fork_issue_url,
        is_self_owned=is_self_owned, default_branch=default_branch
    )

    # 9. Report claim to aggregator (best-effort)
    issue_id = f"github-{origin_owner}-{repo}-{issue_number}"
    svc.report_claim(origin_slug, issue_id, my_user, fork_issue_url)

    response = {
        "success": True,
        "fork_issue_url": fork_issue_url,
        "owner": my_user,
        "is_self_owned": is_self_owned,
        "context_sources": context_metadata["sources"],
    }
    if overlap_warning:
        response["overlap_warning"] = overlap_warning
    return jsonify(response)


# ============ Stage 4: Review on Fork ============

def _get_fork_prs(my_user, repo, origin_slug):
    """Fetch PRs from a single forked repo. Used by ThreadPoolExecutor."""
    result = run_gh_command([
        "pr", "list", "-R", f"{my_user}/{repo}",
        "--json", "number,title,url,headRefName,additions,deletions,changedFiles,reviewDecision,isDraft,createdAt,mergeable"
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

    # Normalize: if caller passes "owner/repo", extract just the repo name
    if "/" in str(repo):
        repo = repo.split("/")[-1]

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


@bp.route("/api/oss/run-review-pipeline", methods=["POST"])
def api_oss_run_review_pipeline():
    """Run the review pipeline on a fork PR: request Copilot code review.

    Called after Copilot has created a PR on the fork. This triggers the
    Copilot review agent as a separate reviewer. CI checks run automatically
    via the workflow pushed during Stage 3.

    Input: { "repo": "email-verifier", "pr_number": 42 }
    """
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    if not all([repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    if "/" in str(repo):
        repo = repo.split("/")[-1]

    my_user = get_authenticated_user()
    svc = OSSService()

    # Request Copilot code review
    review_result = svc.request_copilot_review(my_user, repo, int(pr_number))

    # Get current CI check status
    checks = svc.get_pr_check_runs(my_user, repo, int(pr_number))

    return jsonify({
        "success": True,
        "copilot_review_requested": review_result.get("success", False),
        "ci_checks": checks,
        "owner": my_user,
    })


@bp.route("/api/oss/review-status", methods=["POST"])
def api_oss_review_status():
    """Get the review pipeline status for a fork PR.

    Returns CI check results and Copilot review status so the caller
    can determine if the PR is ready for merge.
    """
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    if not all([repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    if "/" in str(repo):
        repo = repo.split("/")[-1]

    my_user = get_authenticated_user()
    svc = OSSService()

    checks = svc.get_pr_check_runs(my_user, repo, int(pr_number))
    reviews = svc.get_pr_reviews(my_user, repo, int(pr_number))

    # Determine readiness
    ci_passed = all(
        c.get("conclusion") == "success"
        for c in checks
        if c.get("status") == "completed"
    )
    ci_pending = any(c.get("status") != "completed" for c in checks)

    copilot_review = next(
        (r for r in reviews if "copilot" in (r.get("user") or "").lower()),
        None
    )

    return jsonify({
        "success": True,
        "ci_checks": checks,
        "ci_passed": ci_passed,
        "ci_pending": ci_pending,
        "reviews": reviews,
        "copilot_review": copilot_review,
        "ready_for_merge": ci_passed and not ci_pending and copilot_review is not None,
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

    # Normalize: if caller passes "owner/repo", extract just the repo name
    if "/" in str(repo):
        repo = repo.split("/")[-1]

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


def _check_remaining_pr_conflicts(my_user, repo, merged_pr_number):
    """After merging a PR, check if remaining open PRs now have merge conflicts."""
    result = run_gh_command([
        "pr", "list", "-R", f"{my_user}/{repo}",
        "--json", "number,title,mergeable"
    ])
    if not result["success"]:
        return []
    try:
        prs = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        return []
    return [
        {"number": pr["number"], "title": pr["title"], "mergeable": pr.get("mergeable", "UNKNOWN")}
        for pr in prs
        if pr["number"] != int(merged_pr_number) and pr.get("mergeable") == "CONFLICTING"
    ]


@bp.route("/api/oss/merge-fork-pr", methods=["POST"])
def api_oss_merge_fork_pr():
    """Merge a PR on a fork. Captures branch info and transitions to Stage 5."""
    data = request.json
    repo = data.get("repo")
    pr_number = data.get("pr_number")
    origin_slug = data.get("origin_slug")

    if not all([repo, pr_number, origin_slug]):
        return jsonify({"success": False, "error": "Missing required fields"})

    # Normalize: if caller passes "owner/repo", extract just the repo name
    if "/" in str(repo):
        repo = repo.split("/")[-1]

    my_user = get_authenticated_user()
    svc = OSSService()

    # Capture branch name + draft status in a single call (can't read after merge)
    pr_info = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
        "--json", "headRefName,title,baseRefName,isDraft"
    ])
    pr_data = {}
    if pr_info["success"]:
        try:
            pr_data = json.loads(pr_info["output"])
        except (json.JSONDecodeError, KeyError):
            pass

    # Mark draft as ready before merge
    if pr_data.get("isDraft", False):
        run_gh_command([
            "pr", "ready", str(pr_number),
            "-R", f"{my_user}/{repo}"
        ])

    # Merge on fork
    result = run_gh_command([
        "pr", "merge", str(pr_number),
        "-R", f"{my_user}/{repo}",
        "--squash"
    ], timeout=60)

    if result["success"]:
        # Look up assignment for issue_number, default_branch, fork_issue_number
        assignments = svc.get_assigned_issues()
        assignment = next(
            (a for a in assignments
             if a.get("origin_slug") == origin_slug and a.get("repo") == repo),
            None
        )
        upstream_issue_number = assignment.get("issue_number", 0) if assignment else 0
        stored_default = assignment.get("default_branch", "main") if assignment else "main"
        fork_issue_number = assignment.get("fork_issue_number") if assignment else None
        copilot_branch = pr_data.get("headRefName", "")
        pr_title = pr_data.get("title", "")
        base_branch = pr_data.get("baseRefName", stored_default)

        # --- Stage 4.5: Clean & Prepare ---
        # Rewrite the squash commit with user's identity, create a clean branch,
        # delete the Copilot branch, and close the fork context issue.
        sanitization_log = {}

        # 4.5.1: Get the squash commit SHA from fork's default branch HEAD
        head_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/ref/heads/{base_branch}",
            "--jq", ".object.sha"
        ])
        squash_sha = head_result["output"].strip() if head_result["success"] else None

        if squash_sha:
            # 4.5.2: Generate clean branch name
            title_slug = re.sub(r"[^a-z0-9]+", "-", pr_title.lower()).strip("-")[:50]
            clean_branch = f"fix/{upstream_issue_number}-{title_slug}"

            # 4.5.3: Create re-authored commit + clean branch
            clean_commit_msg = pr_title
            clean_result = svc.create_clean_branch(
                my_user, repo, squash_sha, clean_branch, clean_commit_msg
            )
            sanitization_log["create_clean_branch"] = clean_result

            if clean_result.get("success"):
                # 4.5.4: Delete Copilot's feature branch
                if copilot_branch:
                    del_result = svc.delete_branch(my_user, repo, copilot_branch)
                    sanitization_log["delete_copilot_branch"] = {
                        "branch": copilot_branch,
                        "success": del_result.get("success", False),
                    }

                # 4.5.5: Close the fork context issue
                if fork_issue_number:
                    close_result = svc.close_fork_issue(my_user, repo, fork_issue_number)
                    sanitization_log["close_fork_issue"] = {
                        "issue": fork_issue_number,
                        "success": close_result.get("success", False),
                    }

                # Save with CLEAN branch name
                svc.save_ready_to_submit(
                    origin_slug=origin_slug,
                    repo=repo,
                    branch=clean_branch,
                    title=pr_title,
                    base_branch=base_branch,
                    issue_number=upstream_issue_number,
                )

                # Check remaining PRs for merge conflicts
                conflict_warnings = _check_remaining_pr_conflicts(my_user, repo, pr_number)

                return jsonify({
                    "success": True,
                    "message": f"PR #{pr_number} merged and sanitized!",
                    "owner": my_user,
                    "sanitization": sanitization_log,
                    "clean_branch": clean_branch,
                    "conflict_warnings": conflict_warnings,
                })

        # Fallback: sanitization failed or no squash SHA — save with original branch
        svc.save_ready_to_submit(
            origin_slug=origin_slug,
            repo=repo,
            branch=copilot_branch,
            title=pr_title,
            base_branch=base_branch,
            issue_number=upstream_issue_number,
        )
        conflict_warnings = _check_remaining_pr_conflicts(my_user, repo, pr_number)
        return jsonify({
            "success": True,
            "message": f"PR #{pr_number} merged! (sanitization skipped)",
            "owner": my_user,
            "sanitization": sanitization_log,
            "warning": "Could not sanitize — saved with original branch name",
            "conflict_warnings": conflict_warnings,
        })

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
