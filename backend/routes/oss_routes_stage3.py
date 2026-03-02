"""
Stage 3 routes — Fork & Assign.

Endpoints for selecting issues, forking repos, and assigning Copilot.
"""

import time

from flask import request, jsonify

from . import bp

try:
    from ..config import PLATFORM_PREFIX, COPILOT_ASSIGNEE
    from ..services import run_gh_command, get_authenticated_user, OSSService
except ImportError:
    from config import PLATFORM_PREFIX, COPILOT_ASSIGNEE
    from services import run_gh_command, get_authenticated_user, OSSService


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
    issue_id = f"{PLATFORM_PREFIX}-{origin_owner}-{repo}-{issue_number}"

    dossier_meta = None
    brief_meta = None
    dossier_completeness = None

    if not dossier_context:
        dossier_data, dossier_meta = svc.get_dossier(hyphenated_slug, include_meta=True)
        if dossier_data and dossier_data.get("sections"):
            dossier_context = dossier_data["sections"]
            dossier_completeness = dossier_data.get("completeness")

    issue_brief, brief_meta = svc.get_issue_brief(hyphenated_slug, issue_id, include_meta=True)

    # If both are missing (pending), trigger compute and retry once
    if not dossier_context and not issue_brief:
        svc.trigger_compute(hyphenated_slug)
        time.sleep(2)
        dossier_data, dossier_meta = svc.get_dossier(hyphenated_slug, include_meta=True)
        if dossier_data and dossier_data.get("sections"):
            dossier_context = dossier_data["sections"]
            dossier_completeness = dossier_data.get("completeness")
        issue_brief, brief_meta = svc.get_issue_brief(hyphenated_slug, issue_id, include_meta=True)

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

    # Extract language and toolchain from issue brief (used for workflows + assignment metadata)
    language = None
    toolchain_profile = None
    if issue_brief and issue_brief.get("repoHealth"):
        language = issue_brief["repoHealth"].get("language")
        toolchain_profile = issue_brief["repoHealth"].get("toolchainProfile")

    if not is_self_owned:
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

        # 3b. Configure fork settings (issues, Actions permissions)
        svc.configure_fork_settings(my_user, repo)

        # 3c. Ensure .github/copilot-instructions.md exists on fork
        svc.ensure_copilot_instructions(my_user, repo)

        # 3d. Ensure CI workflow exists on fork for deterministic quality checks
        svc.ensure_ci_workflow(my_user, repo, language=language)

        # 3e. Ensure static analysis workflow exists on fork for Stage 4b
        svc.ensure_static_analysis_workflow(my_user, repo,
                                            toolchain_profile=toolchain_profile,
                                            language=language)

        # 3f. Approve any pending workflow runs from previous setups
        svc.approve_pending_workflow_runs(my_user, repo)

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
        is_self_owned=is_self_owned, dossier_completeness=dossier_completeness
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
        "--add-assignee", COPILOT_ASSIGNEE
    ])

    # 8. Track locally
    default_branch = svc.get_default_branch(
        origin_owner, repo, issue_brief=issue_brief, dossier_context=dossier_context
    )
    svc.save_assignment(
        origin_owner, repo, issue_number, fork_issue_number, fork_issue_url,
        is_self_owned=is_self_owned, default_branch=default_branch
    )

    # 8b. Persist aggregator metadata to assignment
    aggregator_meta = {}
    if dossier_meta:
        aggregator_meta["dossier"] = dossier_meta
    if brief_meta:
        aggregator_meta["brief"] = brief_meta
    meta_updates = {
        "context_tier": context_metadata.get("context_tier"),
        "context_sources": context_metadata.get("sources", []),
    }
    if language:
        meta_updates["language"] = language
    if toolchain_profile:
        meta_updates["toolchain_profile"] = toolchain_profile
    if aggregator_meta:
        meta_updates["aggregator_meta"] = aggregator_meta
    if dossier_completeness:
        meta_updates["dossier_completeness"] = dossier_completeness
    svc.update_assignment(repo, int(fork_issue_number), meta_updates)

    # 9. Report claim to aggregator (best-effort)
    issue_id = f"{PLATFORM_PREFIX}-{origin_owner}-{repo}-{issue_number}"
    svc.report_claim(origin_slug, issue_id, my_user, fork_issue_url)

    response = {
        "success": True,
        "fork_issue_url": fork_issue_url,
        "owner": my_user,
        "is_self_owned": is_self_owned,
        "context_sources": context_metadata["sources"],
        "context_tier": context_metadata.get("context_tier"),
        "aggregator_freshness": dossier_meta,
    }
    if overlap_warning:
        response["overlap_warning"] = overlap_warning
    return jsonify(response)
