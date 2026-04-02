"""
Stage 4 routes — Review on Fork.

Endpoints for pipeline advancement, fork PR listing, review, approval, and merge.
"""

import logging
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..services.pipeline_orchestrator import PipelineOrchestrator
    from ..services.oss_state import save_session_artifact, get_session_artifact
    from ..services.pipeline_retrospective import fetch_pr_comments
    from ..helpers.oss_helpers import format_upstream_pr_body
    from ..helpers.validation import normalize_repo_name as _normalize_repo_name, validate_repo_name, validate_slug, validate_required_fields, validate_request_or_error, safe_error_message, error_response
    from ..helpers.notifications import notify_fork_merged, notify_upstream_submitted
    from ..extensions import limiter
    from ..config import CLEAN_BRANCH_PREFIX
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService
    from services.pipeline_orchestrator import PipelineOrchestrator
    from services.oss_state import save_session_artifact, get_session_artifact
    from services.pipeline_retrospective import fetch_pr_comments
    from helpers.oss_helpers import format_upstream_pr_body
    from helpers.validation import normalize_repo_name as _normalize_repo_name, validate_repo_name, validate_slug, validate_required_fields, validate_request_or_error, safe_error_message, error_response
    from helpers.notifications import notify_fork_merged, notify_upstream_submitted
    from extensions import limiter
    from config import CLEAN_BRANCH_PREFIX


def _capture_fork_pr_comments(my_user, repo, pr_number, origin_slug, svc):
    """Fetch and save fork PR comments before merge. Silent on failure."""
    try:
        fork_slug = f"{my_user}/{repo}"
        comments = fetch_pr_comments(fork_slug, int(pr_number))
        if not comments:
            return
        assignments = svc.get_assigned_issues()
        assignment = next(
            (a for a in assignments
             if a.get("origin_slug") == origin_slug and a.get("repo") == repo),
            None
        )
        if assignment and assignment.get("issue_number"):
            save_session_artifact(
                origin_slug, assignment["issue_number"],
                "fork-pr-comments.json", json.dumps(comments, indent=2)
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Comment capture failed for %s/%s PR#%s: %s", my_user, repo, pr_number, e)


@bp.route("/api/oss/advance-pipeline", methods=["POST"])
def api_oss_advance_pipeline():
    """Advance an assignment through the Stage 4 pipeline (4a -> 4b -> 4c -> 4d -> retrospective_complete).

    Idempotent — each call moves the assignment forward at most one step.
    The frontend can poll this endpoint to drive the pipeline.

    Input: { "repo": "email-verifier", "fork_issue_number": 1 }
    """
    data = request.json
    repo = _normalize_repo_name(data.get("repo", ""))
    fork_issue_number = data.get("fork_issue_number")
    err = validate_request_or_error(data, ["repo", "fork_issue_number"], [(repo, validate_repo_name)])
    if err:
        return err

    my_user = get_authenticated_user()
    svc = OSSService()

    assignment = svc.find_assignment_by_fork_issue(repo, int(fork_issue_number))
    if not assignment:
        return jsonify({"success": False, "error": "Assignment not found"})

    orchestrator = PipelineOrchestrator(oss_service=svc)
    result = orchestrator.advance(assignment, {"my_user": my_user})

    result["owner"] = my_user
    return jsonify(result)


def _normalize_assignment(a):
    """Normalize an assignment record to camelCase for frontend consumption."""
    return {
        "originSlug": a.get("origin_slug", ""),
        "repo": a.get("repo", ""),
        "issueNumber": a.get("issue_number", 0),
        "forkIssueNumber": a.get("fork_issue_number", 0),
        "forkIssueUrl": a.get("fork_issue_url", ""),
        "assignedAt": a.get("assigned_at", ""),
        "stage4Status": a.get("stage4_status", "swe_agent_working"),
        "stage4PrNumber": a.get("stage4_pr_number"),
        "stage4PrBranch": a.get("stage4_pr_branch"),
        "stage4ReviewRequested": a.get("stage4_review_requested", False),
        "stage4SweDoneAt": a.get("stage4_swe_done_at"),
        "stage4SaRunId": a.get("stage4_sa_run_id"),
        "stage4SaConclusion": a.get("stage4_sa_conclusion"),
        "stage4SaDoneAt": a.get("stage4_sa_done_at"),
        "stage4ReviewDoneAt": a.get("stage4_review_done_at"),
        "stage4dSkipped": a.get("stage4d_skipped"),
        "stage4dPreCommitCount": a.get("stage4d_pre_commit_count"),
        "stage4dDoneAt": a.get("stage4d_done_at"),
        "language": a.get("language"),
        "contextTier": a.get("context_tier"),
        "contextSources": a.get("context_sources"),
        "dossierCompleteness": a.get("dossier_completeness"),
    }


@bp.route("/api/oss/pipeline-status", methods=["GET"])
def api_oss_pipeline_status():
    """Get Stage 4 pipeline status for all assignments.

    Returns the full assignment record with pipeline state, timing, and
    context data so the frontend can display progress indicators and details.
    """
    my_user = get_authenticated_user()
    svc = OSSService()
    assignments = svc.get_assigned_issues()

    statuses = [_normalize_assignment(a) for a in assignments]

    # Include pipeline loop status
    try:
        from ..services.pipeline_loop import get_loop_status
    except ImportError:
        from services.pipeline_loop import get_loop_status
    loop_status = get_loop_status()

    return jsonify({
        "success": True, "statuses": statuses, "owner": my_user,
        "pipeline_loop": loop_status,
    })


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

    # Enrich PRs with pipeline status from assignment records
    status_lookup = {}
    for a in assignments:
        if a.get("stage4_pr_number"):
            key = (a["repo"], a["stage4_pr_number"])
            status_lookup[key] = a.get("stage4_status", "swe_agent_working")

    for pr in all_prs:
        key = (pr.get("repo"), pr.get("number"))
        pr["pipelineStatus"] = status_lookup.get(key, "swe_agent_working")

    all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    return jsonify({"success": True, "prs": all_prs, "owner": my_user})


@bp.route("/api/oss/fork-pr-details", methods=["POST"])
def api_oss_fork_pr_details():
    """Get detailed info about a PR on a fork, including diff."""
    data = request.json
    repo = _normalize_repo_name(data.get("repo", ""))
    pr_number = data.get("pr_number")
    err = validate_request_or_error(data, ["repo", "pr_number"], [(repo, validate_repo_name)])
    if err:
        return err

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

    return error_response(result.get("error"), "Failed to fetch PR", my_user)


@bp.route("/api/oss/approve-fork-pr", methods=["POST"])
def api_oss_approve_fork_pr():
    """Approve a PR on a fork."""
    data = request.json
    repo = _normalize_repo_name(data.get("repo", ""))
    pr_number = data.get("pr_number")
    err = validate_request_or_error(data, ["repo", "pr_number"], [(repo, validate_repo_name)])
    if err:
        return err

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
    return error_response(result.get("error"), "Failed to approve PR", my_user)


def _run_sanitization(my_user, repo, squash_sha, pr_title, upstream_issue_number,
                       copilot_branch, fork_issue_number, origin_slug, base_branch, svc):
    """Extract squash commit, create a clean branch, delete Copilot's branch, close fork issue.

    Returns (clean_branch, result_dict) where result_dict has a 'success' key.
    Falls back to copilot_branch if squash_sha is missing or sanitization fails.
    """
    if not squash_sha:
        return copilot_branch, {"skipped": True, "reason": "No squash SHA"}

    title_slug = re.sub(r"[^a-z0-9]+", "-", pr_title.lower()).strip("-")[:50]
    clean_branch = f"{CLEAN_BRANCH_PREFIX}{upstream_issue_number}-{title_slug}"
    result = svc.create_clean_branch(
        my_user, repo, squash_sha, clean_branch, pr_title,
        origin_slug=origin_slug, base_branch=base_branch,
    )

    if result.get("success"):
        if copilot_branch:
            svc.delete_branch(my_user, repo, copilot_branch)
        if fork_issue_number:
            svc.close_fork_issue(my_user, repo, fork_issue_number)
        return clean_branch, result

    return copilot_branch, {**result, "warning": "Fallback to original branch"}


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
@limiter.limit("10 per minute")
def api_oss_merge_fork_pr():
    """Merge a PR on a fork. Captures branch info and transitions to Stage 5."""
    data = request.json
    repo = _normalize_repo_name(data.get("repo", ""))
    pr_number = data.get("pr_number")
    origin_slug = data.get("origin_slug")
    err = validate_request_or_error(data, ["repo", "pr_number", "origin_slug"], [
        (repo, validate_repo_name), (origin_slug, validate_slug)
    ])
    if err:
        return err

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

    # Capture fork PR comments before merge (silent on failure)
    _capture_fork_pr_comments(my_user, repo, pr_number, origin_slug, svc)

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
        # Get squash SHA, create clean branch, delete Copilot's branch, close fork issue.
        head_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/git/ref/heads/{base_branch}",
            "--jq", ".object.sha"
        ])
        squash_sha = head_result["output"].strip() if head_result["success"] else None

        clean_branch, sanitization_log = _run_sanitization(
            my_user, repo, squash_sha, pr_title, upstream_issue_number,
            copilot_branch, fork_issue_number, origin_slug, base_branch, svc,
        )

        svc.save_ready_to_submit(
            origin_slug=origin_slug,
            repo=repo,
            branch=clean_branch,
            title=pr_title,
            base_branch=base_branch,
            issue_number=upstream_issue_number,
        )

        if sanitization_log.get("success"):
            notify_fork_merged(origin_slug, upstream_issue_number, pr_title, clean_branch)
            msg = f"PR #{pr_number} merged and sanitized!"
        else:
            msg = f"PR #{pr_number} merged! (sanitization skipped)"

        conflict_warnings = _check_remaining_pr_conflicts(my_user, repo, pr_number)
        response = {
            "success": True,
            "message": msg,
            "owner": my_user,
            "sanitization": sanitization_log,
            "clean_branch": clean_branch,
            "conflict_warnings": conflict_warnings,
        }
        if not sanitization_log.get("success"):
            response["warning"] = "Could not sanitize — saved with original branch name"
        return jsonify(response)

    return error_response(result.get("error"), "Failed to merge PR", my_user)


@bp.route("/api/oss/signoff", methods=["POST"])
@limiter.limit("5 per minute")
def api_oss_signoff():
    """One-click signoff: merge fork PR, sanitize, create upstream PR.

    Combines the merge-fork-pr flow (Stage 4.5) with the submit-to-origin
    flow (Stage 5) into a single idempotent action.

    Input: { "repo": "email-verifier", "pr_number": 2, "origin_slug": "reisepass/email-verifier",
             "issue_number": 123 }  // issue_number is optional but recommended for multi-issue repos
    """
    data = request.json
    repo = _normalize_repo_name(data.get("repo", ""))
    pr_number = data.get("pr_number")
    origin_slug = data.get("origin_slug")
    issue_number = data.get("issue_number")
    err = validate_request_or_error(data, ["repo", "pr_number", "origin_slug"], [
        (repo, validate_repo_name), (origin_slug, validate_slug)
    ])
    if err:
        return err

    my_user = get_authenticated_user()
    svc = OSSService()
    steps = {}

    # --- Step 1: Look up assignment ---
    assignments = svc.get_assigned_issues()
    if issue_number:
        assignment = next(
            (a for a in assignments
             if a.get("origin_slug") == origin_slug and a.get("repo") == repo
             and a.get("issue_number") == issue_number),
            None
        )
    else:
        assignment = next(
            (a for a in assignments
             if a.get("origin_slug") == origin_slug and a.get("repo") == repo),
            None
        )
    if not assignment:
        return jsonify({"success": False, "error": "Assignment not found"})

    upstream_issue_number = assignment.get("issue_number", 0)
    stored_default = assignment.get("default_branch", "main")
    fork_issue_number = assignment.get("fork_issue_number")

    # --- Step 1b: Actionability check ---
    # Verify the upstream issue is still open and we haven't already submitted a PR for it.
    actionability = {}
    if upstream_issue_number:
        issue_check = run_gh_command([
            "api", f"repos/{origin_slug}/issues/{upstream_issue_number}",
            "--jq", "{state: .state, locked: .locked}"
        ])
        if issue_check["success"]:
            try:
                issue_meta = json.loads(issue_check["output"])
                actionability["issue_state"] = issue_meta.get("state")
                if issue_meta.get("state") != "open":
                    return jsonify({
                        "success": False,
                        "error": f"Upstream issue #{upstream_issue_number} is {issue_meta.get('state')} — nothing to fix",
                        "actionability": actionability,
                    })
            except (json.JSONDecodeError, ValueError):
                actionability["issue_check"] = "parse_error"
        else:
            actionability["issue_check"] = "api_error"

        # Check if we already have an open upstream PR for this slug
        submitted_items = svc.get_submitted_prs()
        existing_pr = next(
            (p for p in submitted_items
             if p.get("origin_slug") == origin_slug and p.get("state") == "open"),
            None
        )
        if existing_pr:
            actionability["existing_pr"] = existing_pr.get("pr_url")
            return jsonify({
                "success": False,
                "error": f"Already have an open upstream PR for {origin_slug}: {existing_pr.get('pr_url')}",
                "actionability": actionability,
            })

    steps["actionability"] = actionability

    # --- Step 2: Get PR info before merge (can't read after) ---
    pr_info = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
        "--json", "headRefName,title,baseRefName,isDraft,state"
    ])
    pr_data = {}
    if pr_info["success"]:
        try:
            pr_data = json.loads(pr_info["output"])
        except (json.JSONDecodeError, KeyError):
            pass

    copilot_branch = pr_data.get("headRefName", "")
    pr_title = pr_data.get("title", "")
    base_branch = pr_data.get("baseRefName", stored_default)
    pr_state = pr_data.get("state", "").upper()

    # --- Step 3: Merge the fork PR (if not already merged) ---
    if pr_state == "MERGED":
        steps["merge"] = {"skipped": True, "reason": "PR already merged"}
    else:
        # Capture fork PR comments before merge (silent on failure)
        _capture_fork_pr_comments(my_user, repo, pr_number, origin_slug, svc)

        # Mark draft as ready
        if pr_data.get("isDraft", False):
            run_gh_command([
                "pr", "ready", str(pr_number), "-R", f"{my_user}/{repo}"
            ])

        merge_result = run_gh_command([
            "pr", "merge", str(pr_number), "-R", f"{my_user}/{repo}",
            "--squash"
        ], timeout=60)

        if not merge_result["success"]:
            return jsonify({
                "success": False,
                "error": safe_error_message(merge_result.get("error"), "Merge failed"),
                "owner": my_user,
                "steps": steps,
            })
        steps["merge"] = {"success": True}

    # --- Step 4: Stage 4.5 sanitization ---
    head_result = run_gh_command([
        "api", f"repos/{my_user}/{repo}/git/ref/heads/{base_branch}",
        "--jq", ".object.sha"
    ])
    squash_sha = head_result["output"].strip() if head_result["success"] else None

    clean_branch, steps["sanitize"] = _run_sanitization(
        my_user, repo, squash_sha, pr_title, upstream_issue_number,
        copilot_branch, fork_issue_number, origin_slug, base_branch, svc,
    )

    # --- Step 5: Create upstream PR ---
    body = format_upstream_pr_body(origin_slug, upstream_issue_number, pr_title, clean_branch)

    # Persist the PR body for retrospective analysis before submitting
    save_session_artifact(origin_slug, upstream_issue_number, "upstream-pr-body.md", body)

    submit_result = run_gh_command([
        "pr", "create",
        "-R", origin_slug,
        "--head", f"{my_user}:{clean_branch}",
        "--base", base_branch,
        "--title", pr_title,
        "--body", body
    ], timeout=60)

    if submit_result["success"]:
        pr_url = submit_result["output"].strip()
        svc.save_submitted_pr(origin_slug, pr_url, pr_title, issue_number=upstream_issue_number)
        # Clean up ready-to-submit if it exists
        svc.remove_ready_to_submit(origin_slug, clean_branch)
        steps["submit"] = {"success": True, "pr_url": pr_url}

        notify_upstream_submitted(
            origin_slug, upstream_issue_number, pr_url, pr_title,
        )

        conflict_warnings = _check_remaining_pr_conflicts(my_user, repo, pr_number)

        return jsonify({
            "success": True,
            "pr_url": pr_url,
            "clean_branch": clean_branch,
            "owner": my_user,
            "steps": steps,
            "conflict_warnings": conflict_warnings,
        })

    steps["submit"] = {"success": False, "error": safe_error_message(submit_result.get("error"), "Upstream submit failed")}

    # Merge succeeded but submit failed — save as ready-to-submit for manual retry
    svc.save_ready_to_submit(
        origin_slug=origin_slug,
        repo=repo,
        branch=clean_branch,
        title=pr_title,
        base_branch=base_branch,
        issue_number=upstream_issue_number,
    )

    return jsonify({
        "success": False,
        "error": safe_error_message(submit_result.get("error"), "Merged but upstream submit failed"),
        "owner": my_user,
        "steps": steps,
    })



