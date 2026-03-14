"""
Stage 3 routes — Fork & Assign.

Endpoints for selecting issues, forking repos, and assigning Copilot.
"""

from flask import request, jsonify

from . import bp

try:
    from ..config import PLATFORM_PREFIX, COPILOT_ASSIGNEE
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..services.github_api import set_saml_token_override
    from ..helpers.validation import validate_owner, validate_repo_name, validate_issue_number, validate_required_fields, to_aggregator_slug, safe_error_message
    from ..extensions import limiter
    from ..services.pipeline_logger import logger as plog, log_event, StepTimer
except ImportError:
    from config import PLATFORM_PREFIX, COPILOT_ASSIGNEE
    from services import run_gh_command, get_authenticated_user, OSSService
    from services.github_api import set_saml_token_override
    from helpers.validation import validate_owner, validate_repo_name, validate_issue_number, validate_required_fields, to_aggregator_slug, safe_error_message
    from extensions import limiter
    from services.pipeline_logger import logger as plog, log_event, StepTimer


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
    req_err = validate_required_fields(data, ["origin_owner", "repo", "issue_number"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")

    owner_err = validate_owner(origin_owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})
    num_err = validate_issue_number(issue_number)
    if num_err:
        return jsonify({"success": False, "error": num_err})

    my_user = get_authenticated_user()
    origin_slug = f"{origin_owner}/{repo}"
    svc = OSSService()

    existing = svc.find_selected_issue(origin_slug, issue_number)
    if existing:
        return jsonify({"success": True, "already_selected": True, "owner": my_user})

    svc.select_issue(origin_slug, issue_number, issue_title, issue_url)
    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/fork-and-assign", methods=["POST"])
@limiter.limit("5 per minute")
def api_oss_fork_and_assign():
    """Fork a repo, create a context issue, and assign Copilot.

    This is the critical Stage 3 endpoint. Every step is logged to
    pipeline-events.jsonl for post-mortem diagnosis.
    """
    data = request.json
    req_err = validate_required_fields(data, ["origin_owner", "repo", "issue_number", "issue_title", "issue_url"])
    if req_err:
        return jsonify({"success": False, "error": req_err})

    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")

    owner_err = validate_owner(origin_owner)
    if owner_err:
        return jsonify({"success": False, "error": owner_err})
    repo_err = validate_repo_name(repo)
    if repo_err:
        return jsonify({"success": False, "error": repo_err})
    num_err = validate_issue_number(issue_number)
    if num_err:
        return jsonify({"success": False, "error": num_err})

    my_user = get_authenticated_user()
    origin_slug = f"{origin_owner}/{repo}"
    svc = OSSService()

    plog.info("fork-and-assign START: %s #%s", origin_slug, issue_number)

    # Activate SAML token override for the entire pipeline run if the origin
    # org is SAML-protected. This covers fork operations AND all subsequent
    # commands on the fork (which inherits SAML enforcement from upstream).
    set_saml_token_override(origin_owner.lower())

    try:
        return _do_fork_and_assign(
            data, origin_owner, repo, issue_number, issue_title, issue_url,
            my_user, svc
        )
    finally:
        set_saml_token_override(None)


def _do_fork_and_assign(data, origin_owner, repo, issue_number, issue_title,
                        issue_url, my_user, svc):
    """Inner implementation of fork-and-assign (extracted for SAML cleanup)."""
    origin_slug = f"{origin_owner}/{repo}"
    dossier_context = data.get("dossier")

    # Detect self-owned repos (can't fork your own repo)
    is_self_owned = (origin_owner.lower() == my_user.lower())

    # Auto-fetch dossier and issue-brief from aggregator
    hyphenated_slug = to_aggregator_slug(origin_slug)
    issue_id = f"{PLATFORM_PREFIX}-{origin_owner}-{repo}-{issue_number}"

    dossier_meta = None
    brief_meta = None
    dossier_completeness = None

    with StepTimer("stage3", "fetch_dossier", origin_slug, issue_number) as t:
        if not dossier_context:
            dossier_data, dossier_meta = svc.get_dossier(hyphenated_slug, include_meta=True)
            if dossier_data and dossier_data.get("sections"):
                dossier_context = dossier_data["sections"]
                dossier_completeness = dossier_data.get("completeness")
                t.detail = "dossier fetched"
            else:
                t.detail = "no dossier available"
        else:
            t.detail = "dossier provided in request"

    with StepTimer("stage3", "fetch_brief", origin_slug, issue_number) as t:
        issue_brief, brief_meta = svc.get_issue_brief(hyphenated_slug, issue_id, include_meta=True)
        t.detail = "brief fetched" if issue_brief else "no brief available"

    # If both are missing (pending), trigger compute and proceed with fallback context
    if not dossier_context and not issue_brief:
        with StepTimer("stage3", "trigger_compute", origin_slug, issue_number) as t:
            svc.trigger_compute(hyphenated_slug)
            t.detail = "compute triggered (both dossier and brief missing)"

    # 0. Dedup guard
    existing = svc.find_assignment(origin_slug, issue_number)
    if existing:
        log_event("stage3", "dedup", origin_slug, issue_number, status="skip",
                  detail="already assigned")
        plog.info("fork-and-assign SKIP (dedup): %s #%s", origin_slug, issue_number)
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
        with StepTimer("stage3", "fork", origin_slug, issue_number) as t:
            if not svc.check_fork_exists(my_user, repo):
                fork_result = svc.fork_repo(origin_owner, repo)
                if not fork_result["success"]:
                    t.status = "error"
                    t.detail = fork_result.get("error", "fork failed")
                    plog.error("fork-and-assign FAIL at fork: %s #%s — %s",
                               origin_slug, issue_number, t.detail)
                    return jsonify({
                        "success": False,
                        "error": safe_error_message(fork_result.get("error"), "Failed to fork"),
                        "owner": my_user,
                    })
                t.detail = "fork created"
            else:
                t.detail = "fork already exists"

        # 2. Wait for fork to be ready
        with StepTimer("stage3", "wait_for_fork", origin_slug, issue_number) as t:
            if not svc.wait_for_fork(my_user, repo, timeout=60, interval=3):
                t.status = "timeout"
                t.detail = "fork not ready after 60s"
                plog.error("fork-and-assign FAIL at wait: %s #%s — timeout",
                           origin_slug, issue_number)
                return jsonify({
                    "success": False,
                    "error": "Fork creation timed out",
                    "owner": my_user,
                })
            t.detail = "fork ready"

        # 3. Sync fork
        with StepTimer("stage3", "sync", origin_slug, issue_number) as t:
            sync_result = svc.sync_fork(my_user, repo)
            t.detail = "synced" if sync_result.get("success") else f"sync issue: {sync_result.get('error', 'unknown')}"

        # 3b. Configure fork settings (issues, Actions, disable upstream workflows)
        with StepTimer("stage3", "configure", origin_slug, issue_number) as t:
            svc.configure_fork_settings(my_user, repo, origin_owner=origin_owner)
            t.detail = "settings configured + upstream workflows disabled"

        # 3c. Push all pipeline files in a single commit (copilot instructions + CI + SA)
        with StepTimer("stage3", "pipeline_files", origin_slug, issue_number) as t:
            push_result = svc.ensure_pipeline_files(
                my_user, repo, language=language, toolchain_profile=toolchain_profile,
                origin_owner=origin_owner
            )
            if push_result.get("skipped"):
                t.detail = "all files unchanged, no commit needed"
            elif push_result.get("success"):
                t.detail = f"pushed {len(push_result.get('files', []))} files in 1 commit"
            else:
                t.status = "error"
                t.detail = f"push failed: {push_result.get('error', 'unknown')}"

        # 3d. Approve any pending workflow runs from previous setups
        with StepTimer("stage3", "approve_workflows", origin_slug, issue_number) as t:
            unblocked = svc.approve_pending_workflow_runs(my_user, repo)
            t.detail = f"{unblocked} runs approved"

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
        log_event("stage3", "overlap_check", origin_slug, issue_number, status="warn",
                  detail=overlap_warning)

    # 5. Build agent context (issue_brief takes priority over dossier)
    with StepTimer("stage3", "build_context", origin_slug, issue_number) as t:
        context_body, context_metadata = svc.build_agent_context(
            origin_owner, repo, issue_number, issue_title, issue_url,
            dossier_context, issue_brief, return_metadata=True,
            is_self_owned=is_self_owned, dossier_completeness=dossier_completeness
        )
        tier = context_metadata.get("context_tier")
        sources = context_metadata.get("sources", [])
        t.detail = f"tier={tier} sources={sources}"
        t.extra = {"context_tier": tier, "context_sources": sources}

    # 6. Create context issue on target repo (fork or self-owned)
    with StepTimer("stage3", "create_issue", origin_slug, issue_number) as t:
        create_result = run_gh_command([
            "issue", "create", "-R", f"{my_user}/{repo}",
            "--title", f"[OSS] Fix: {issue_title}",
            "--body", context_body
        ])

        if not create_result["success"]:
            t.status = "error"
            t.detail = create_result.get("error", "issue creation failed")
            plog.error("fork-and-assign FAIL at create_issue: %s #%s — %s",
                       origin_slug, issue_number, t.detail)
            return jsonify({
                "success": False,
                "error": safe_error_message(create_result.get("error"), "Failed to create issue"),
                "owner": my_user,
            })
        fork_issue_url = create_result["output"].strip()
        fork_issue_number = fork_issue_url.split("/")[-1]
        t.detail = f"created fork issue #{fork_issue_number}"

    # 7. Assign Copilot (retry once — GraphQL lags behind issue creation)
    with StepTimer("stage3", "assign_copilot", origin_slug, issue_number) as t:
        import time as _time
        assign_result = run_gh_command([
            "issue", "edit", fork_issue_number,
            "-R", f"{my_user}/{repo}",
            "--add-assignee", COPILOT_ASSIGNEE
        ])
        if not assign_result.get("success"):
            _time.sleep(3)
            assign_result = run_gh_command([
                "issue", "edit", fork_issue_number,
                "-R", f"{my_user}/{repo}",
                "--add-assignee", COPILOT_ASSIGNEE
            ])
        if assign_result.get("success"):
            t.detail = f"assigned {COPILOT_ASSIGNEE} to #{fork_issue_number}"
        else:
            t.status = "error"
            t.detail = f"assign failed: {assign_result.get('error', 'unknown')}"

    # 8. Track locally
    with StepTimer("stage3", "save_assignment", origin_slug, issue_number) as t:
        default_branch = svc.get_default_branch(
            origin_owner, repo, issue_brief=issue_brief, dossier_context=dossier_context
        )
        svc.save_assignment(
            origin_owner, repo, issue_number, fork_issue_number, fork_issue_url,
            is_self_owned=is_self_owned, default_branch=default_branch
        )
        t.detail = f"saved (branch={default_branch})"

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
    with StepTimer("stage3", "report_claim", origin_slug, issue_number) as t:
        issue_id = f"{PLATFORM_PREFIX}-{origin_owner}-{repo}-{issue_number}"
        svc.report_claim(origin_slug, issue_id, my_user, fork_issue_url)
        t.detail = "claim reported"

    plog.info("fork-and-assign DONE: %s #%s → %s (tier %s)",
              origin_slug, issue_number, fork_issue_url,
              context_metadata.get("context_tier"))

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
