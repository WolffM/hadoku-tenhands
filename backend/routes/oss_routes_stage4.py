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


@bp.route("/api/oss/retrospective-logs", methods=["GET"])
def api_oss_retrospective_logs():
    """Get all retrospective log entries for pipeline report display.

    Returns raw retrospective data (snake_case) matching the structure
    used by pipeline-report.html and gen_report.py.
    """
    my_user = get_authenticated_user()
    svc = OSSService()
    logs = svc.get_retrospective_logs()
    return jsonify({"success": True, "logs": logs, "owner": my_user})


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
            clean_branch = f"{CLEAN_BRANCH_PREFIX}{upstream_issue_number}-{title_slug}"

            # 4.5.3: Create re-authored commit + clean branch (strip pipeline files)
            clean_commit_msg = pr_title
            clean_result = svc.create_clean_branch(
                my_user, repo, squash_sha, clean_branch, clean_commit_msg,
                origin_slug=origin_slug, base_branch=base_branch,
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

                notify_fork_merged(
                    origin_slug, upstream_issue_number, pr_title, clean_branch,
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

    clean_branch = copilot_branch  # fallback
    if squash_sha:
        title_slug = re.sub(r"[^a-z0-9]+", "-", pr_title.lower()).strip("-")[:50]
        clean_branch = f"{CLEAN_BRANCH_PREFIX}{upstream_issue_number}-{title_slug}"
        clean_result = svc.create_clean_branch(
            my_user, repo, squash_sha, clean_branch, pr_title,
            origin_slug=origin_slug, base_branch=base_branch,
        )
        steps["sanitize"] = clean_result

        if clean_result.get("success"):
            if copilot_branch:
                svc.delete_branch(my_user, repo, copilot_branch)
            if fork_issue_number:
                svc.close_fork_issue(my_user, repo, fork_issue_number)
        else:
            clean_branch = copilot_branch
            steps["sanitize"]["warning"] = "Fallback to original branch"
    else:
        steps["sanitize"] = {"skipped": True, "reason": "No squash SHA"}

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


_retro_batches_cache: dict = {}  # key "batches" → (timestamp, response_dict)
_RETRO_BATCHES_CACHE_TTL = 30  # seconds


@bp.route("/api/oss/retro/batches", methods=["GET"])
def api_oss_retro_batches():
    """List all batches with funnel summary counts.

    Returns { success, owner, batches: [BatchSummary] }.
    Response is cached for 30 s to avoid repeated file reads during serial E2E runs.
    """
    import time as _time

    cached = _retro_batches_cache.get("batches")
    if cached and (_time.time() - cached[0]) < _RETRO_BATCHES_CACHE_TTL:
        return jsonify(cached[1])

    my_user = get_authenticated_user()
    svc = OSSService()
    batches_raw = svc.get_batches()
    submitted_prs = svc.get_submitted_prs()
    assignments = svc.get_assigned_issues()

    summaries = []
    for batch in batches_raw:
        batch_id = batch.get("batch_id")
        issue_refs = batch.get("issues", [])
        issue_count = len(issue_refs)

        # Build set of origin_slug#issue_number refs in this batch.
        # For pre-tracking batches with no assignments, fall back to batch.issues list.
        import re as _re
        batch_assignments = [
            a for a in assignments if a.get("batch_id") == batch_id
        ]
        if batch_assignments:
            batch_slugs_issues = {
                (a.get("origin_slug"), a.get("issue_number"))
                for a in batch_assignments
            }
        else:
            batch_slugs_issues = set()
            for ref in issue_refs:
                m = _re.match(r"^(.+)#(\d+)$", ref)
                if m:
                    batch_slugs_issues.add((m.group(1), int(m.group(2))))

        # Count upstream PRs for issues in this batch
        batch_prs = [
            p for p in submitted_prs
            if (p.get("origin_slug"), p.get("issue_number")) in batch_slugs_issues
        ]

        summaries.append({
            "batch_id": batch_id,
            "created_at": batch.get("created_at"),
            "note": batch.get("note", ""),
            "issue_count": issue_count,
            "upstream_pr_count": len(batch_prs),
            "upstream_merged": sum(1 for p in batch_prs if p.get("state") == "merged"),
            "upstream_closed": sum(1 for p in batch_prs if p.get("state") == "closed"),
            "upstream_open": sum(1 for p in batch_prs if p.get("state") == "open"),
            "has_fork_pr": sum(1 for a in batch_assignments if a.get("stage4_pr_number")),
        })

    result = {"success": True, "owner": my_user, "batches": summaries}
    _retro_batches_cache["batches"] = (_time.time(), result)
    return jsonify(result)


_retro_batch_cache: dict = {}  # batch_id → (timestamp, response_dict)
_RETRO_BATCH_CACHE_TTL = 30  # seconds — fast enough for dev, stale-safe for tests


@bp.route("/api/oss/retro/batch/<batch_id>", methods=["GET"])
def api_oss_retro_batch(batch_id):
    """Full batch detail: assignments + submitted PRs + retro logs.

    Returns { success, owner, batch, issues: [BatchIssue] }.
    Response is cached for 30 s (avoids hammering file I/O during serial E2E runs).
    """
    import time as _time

    cached = _retro_batch_cache.get(batch_id)
    if cached and (_time.time() - cached[0]) < _RETRO_BATCH_CACHE_TTL:
        return jsonify(cached[1])

    my_user = get_authenticated_user()
    svc = OSSService()

    batch = svc.get_batch(batch_id)
    if not batch:
        return jsonify({"success": False, "error": f"Batch '{batch_id}' not found"})

    assignments = svc.get_assigned_issues()
    submitted_prs = svc.get_submitted_prs()
    retro_logs = svc.get_retrospective_logs()

    batch_assignments = [a for a in assignments if a.get("batch_id") == batch_id]

    # For pre-tracking batches with no assignments, build stub entries from batch.issues list.
    # Format: "owner/repo#N"
    if not batch_assignments:
        import re as _re
        for ref in batch.get("issues", []):
            m = _re.match(r"^(.+)#(\d+)$", ref)
            if not m:
                continue
            batch_assignments.append({
                "origin_slug": m.group(1),
                "issue_number": int(m.group(2)),
                "batch_id": batch_id,
                "pre_tracking": True,
            })

    issues = []
    for assignment in batch_assignments:
        origin_slug = assignment.get("origin_slug")
        issue_number = assignment.get("issue_number")

        # Find most recent upstream PR for this issue
        upstream_pr = next(
            (p for p in reversed(submitted_prs)
             if p.get("origin_slug") == origin_slug
             and p.get("issue_number") == issue_number),
            None
        )

        # Find most recent retro log for this issue
        retro = next(
            (r for r in reversed(retro_logs)
             if r.get("origin_slug") == origin_slug
             and r.get("issue_number") == issue_number),
            {}
        )

        # Enrich retro with session artifacts (comments, PR body, context)
        retro = dict(retro)  # copy so we don't mutate the original

        # PR comments — upstream first, fall back to fork PR comments
        upstream_comments_json = get_session_artifact(origin_slug, issue_number, "upstream-pr-comments.json")
        fork_comments_json = get_session_artifact(origin_slug, issue_number, "fork-pr-comments.json")
        try:
            upstream_comments = json.loads(upstream_comments_json) if upstream_comments_json else []
        except (ValueError, TypeError):
            upstream_comments = []
        try:
            fork_comments = json.loads(fork_comments_json) if fork_comments_json else []
        except (ValueError, TypeError):
            fork_comments = []
        if upstream_comments or fork_comments:
            retro["raw_comments"] = {"upstream_pr": upstream_comments, "fork_pr": fork_comments}

        # Upstream PR body
        upstream_pr_body = get_session_artifact(origin_slug, issue_number, "upstream-pr-body.md")
        if upstream_pr_body:
            retro["upstream_pr_body"] = upstream_pr_body

        # Context issue body (fork issue)
        context_body = get_session_artifact(origin_slug, issue_number, "context.md")
        if context_body:
            retro["context_issue_body"] = context_body

        # Copilot workflow analysis (pre-computed by batch scrape)
        workflow_json = get_session_artifact(origin_slug, issue_number, "workflow.json")
        if workflow_json:
            try:
                retro["workflow"] = json.loads(workflow_json)
            except (ValueError, TypeError):
                pass

        # Cross-reference leaks — fork PRs that triggered mentions on the upstream issue
        mentions_json = get_session_artifact(origin_slug, issue_number, "upstream-issue-mentions.json")
        if mentions_json:
            try:
                retro["upstream_issue_mentions"] = json.loads(mentions_json)
            except (ValueError, TypeError):
                pass

        issues.append({
            "assignment": assignment,
            "upstream_pr": upstream_pr,
            "retro": retro,
        })

    result = {
        "success": True,
        "owner": my_user,
        "batch": batch,
        "issues": issues,
    }
    _retro_batch_cache[batch_id] = (_time.time(), result)
    return jsonify(result)


@bp.route("/api/oss/retro/pr-commits/<path:origin_slug>/<int:pr_number>", methods=["GET"])
def api_oss_retro_pr_commits(origin_slug, pr_number):
    """Fetch post-submission commits for an upstream PR.

    Returns { success, commits: [{sha, date, author, message}] } sorted by date asc.
    Only returns commits pushed after the PR was created (i.e. follow-up fix commits).
    """
    submitted_after = request.args.get("submitted_after", "")

    result = run_gh_command([
        "api",
        f"repos/{origin_slug}/pulls/{pr_number}/commits",
        "--jq",
        '[.[] | {sha: .sha[:7], date: .commit.author.date, '
        'author: (.author.login // .commit.author.name), '
        'message: (.commit.message | split("\\n")[0])}]',
    ], timeout=15)

    if not result["success"]:
        logger.warning("Failed to fetch PR commits for %s#%d: %s", origin_slug, pr_number, result.get("error"))
        return jsonify({"success": True, "commits": []})

    try:
        commits = json.loads(result["output"])
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse PR commits for %s#%d: %s", origin_slug, pr_number, exc)
        return jsonify({"success": True, "commits": []})

    if submitted_after:
        commits = [c for c in commits if c["date"] > submitted_after]
    return jsonify({"success": True, "commits": commits})


@bp.route("/api/oss/issue-report/<repo>/<int:issue_number>", methods=["GET"])
def api_oss_issue_report(repo, issue_number):
    """Generate a self-contained pipeline report HTML for a single issue.

    Returns Content-Type: text/html suitable for embedding in an iframe.
    """
    from flask import make_response

    try:
        from ..helpers.report_generator import generate_issue_report_html
    except ImportError:
        from helpers.report_generator import generate_issue_report_html

    svc = OSSService()
    try:
        html = generate_issue_report_html(svc, repo, issue_number)
    except Exception as exc:
        logger.exception("Failed to generate issue report for %s#%d", repo, issue_number)
        return jsonify({"success": False, "error": str(exc)}), 500

    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response
