"""
Stage 3 routes — Fork & Assign.

Endpoints for selecting issues, forking repos, and assigning Copilot.
"""

from flask import request, jsonify

from . import bp

try:
    from ..config import PLATFORM_PREFIX, COPILOT_ASSIGNEE, MAX_REPO_SIZE_KB, MIN_CORE_REMAINING
    from ..services import run_gh_command, get_authenticated_user, OSSService
    from ..services.github_api import set_saml_token_override, is_saml_org
    from ..services.oss_fork import get_fork_lock
    from ..services.oss_state import save_session_artifact
    from ..helpers.validation import validate_owner, validate_repo_name, validate_issue_number, validate_request_or_error, to_aggregator_slug, error_response
    from ..extensions import limiter
    from ..services.pipeline_logger import logger as plog, log_event, StepTimer
except ImportError:
    from config import PLATFORM_PREFIX, COPILOT_ASSIGNEE, MAX_REPO_SIZE_KB, MIN_CORE_REMAINING
    from services import run_gh_command, get_authenticated_user, OSSService
    from services.github_api import set_saml_token_override, is_saml_org
    from services.oss_fork import get_fork_lock
    from services.oss_state import save_session_artifact
    from helpers.validation import validate_owner, validate_repo_name, validate_issue_number, validate_request_or_error, to_aggregator_slug, error_response
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
    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")
    err = validate_request_or_error(data, ["origin_owner", "repo", "issue_number"], [
        (origin_owner, validate_owner), (repo, validate_repo_name), (issue_number, validate_issue_number)
    ])
    if err:
        return err

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
    origin_owner = data.get("origin_owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    issue_title = data.get("issue_title")
    issue_url = data.get("issue_url")
    err = validate_request_or_error(
        data, ["origin_owner", "repo", "issue_number", "issue_title", "issue_url"], [
            (origin_owner, validate_owner), (repo, validate_repo_name),
            (issue_number, validate_issue_number),
        ]
    )
    if err:
        return err

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

    # Preflight: repo size gate (large repos stress memory on resource-constrained hosts during sync/configure)
    # Threshold: 500MB compressed (GitHub reports size in KB) — override via MAX_REPO_SIZE_KB env var
    if not is_self_owned:
        size_result = run_gh_command([
            "api", f"repos/{origin_owner}/{repo}", "--jq", ".size"
        ])
        if size_result["success"]:
            try:
                repo_size_kb = int(size_result["output"].strip())
                if repo_size_kb > MAX_REPO_SIZE_KB:
                    plog.warning(
                        "fork-and-assign BLOCKED (repo too large): %s — %dMB > %dMB limit",
                        origin_slug, repo_size_kb // 1024, MAX_REPO_SIZE_KB // 1024
                    )
                    return jsonify({
                        "success": False,
                        "error": f"Repo too large ({repo_size_kb // 1024}MB) — exceeds {MAX_REPO_SIZE_KB // 1024}MB limit",
                        "repo_size_mb": repo_size_kb // 1024,
                        "owner": my_user,
                    })
            except (ValueError, TypeError) as e:
                plog.error(
                    "fork-and-assign BLOCKED (size check parse failure): %s — raw: %r error: %s",
                    origin_slug, size_result["output"], e
                )
                return jsonify({
                    "success": False,
                    "error": "Could not parse repo size from GitHub API response",
                    "owner": my_user,
                })

    # Preflight: rate limit check — override via MIN_CORE_REMAINING env var
    rl_result = run_gh_command(["api", "rate_limit", "--jq", ".resources.core.remaining"])
    if rl_result["success"]:
        try:
            core_remaining = int(rl_result["output"].strip())
            if core_remaining < MIN_CORE_REMAINING:
                plog.warning(
                    "fork-and-assign BLOCKED (rate limit): %s — only %d core calls remaining",
                    origin_slug, core_remaining
                )
                return jsonify({
                    "success": False,
                    "error": f"GitHub rate limit too low ({core_remaining} remaining) — try again later",
                    "rate_limit_remaining": core_remaining,
                    "owner": my_user,
                })
        except (ValueError, TypeError) as e:
            plog.error(
                "fork-and-assign BLOCKED (rate limit parse failure): %s — raw: %r error: %s",
                origin_slug, rl_result["output"], e
            )
            return jsonify({
                "success": False,
                "error": "Could not parse rate limit from GitHub API response",
                "owner": my_user,
            })

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
        # Third-party repo — fork, wait, and sync.
        # Acquire a per-repo lock to serialize concurrent dispatches for the
        # same upstream repo. Prevents the race where two parallel dispatches
        # both call fork_repo() simultaneously and the second fails with 422.
        with get_fork_lock(origin_slug):
            # 1. Fork if needed
            with StepTimer("stage3", "fork", origin_slug, issue_number) as t:
                if not svc.check_fork_exists(my_user, repo):
                    fork_result = svc.fork_repo(origin_owner, repo)
                    if not fork_result["success"]:
                        t.status = "error"
                        t.detail = fork_result.get("error", "fork failed")
                        plog.error("fork-and-assign FAIL at fork: %s #%s — %s",
                                   origin_slug, issue_number, t.detail)
                        return error_response(fork_result.get("error"), "Failed to fork", my_user)
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
            # For non-SAML orgs this also starts the async Copilot firewall disable.
            # SAML orgs keep the firewall ON — Copilot runs on
            # github-hosted runners where the firewall is required and expected.
            with StepTimer("stage3", "configure", origin_slug, issue_number) as t:
                svc.configure_fork_settings(my_user, repo, origin_owner=origin_owner)
                t.detail = "settings configured + upstream workflows disabled"

            # 3b2. Confirm Copilot firewall is disabled (non-SAML only).
            # configure_fork_settings fires _disable_copilot_firewall asynchronously.
            # Poll until the Actions variable confirms disabled (max 30s).
            # SAML orgs intentionally keep the firewall ON — skip this check.
            if not is_saml_org(origin_owner):
                import time as _fw_time
                with StepTimer("stage3", "firewall_check", origin_slug, issue_number) as t:
                    _fw_disabled = False
                    for _ in range(7):  # up to ~30s (0 + 6×5s)
                        fw_result = run_gh_command([
                            "api",
                            f"repos/{my_user}/{repo}/actions/variables/COPILOT_AGENT_FIREWALL_ENABLED",
                            "--jq", ".value",
                        ])
                        if fw_result.get("success") and fw_result["output"].strip().strip('"') == "false":
                            _fw_disabled = True
                            break
                        _fw_time.sleep(5)
                    if _fw_disabled:
                        t.detail = "firewall disabled (confirmed)"
                    else:
                        t.status = "warn"
                        t.detail = "firewall not confirmed disabled after 30s — Copilot session may fail"
                        plog.warning(
                            "fork-and-assign WARN: Copilot firewall not confirmed disabled for %s — "
                            "Copilot may fail at 'Validate firewall settings' step. "
                            "Retry disable manually at: https://github.com/%s/%s/settings/copilot/coding_agent",
                            origin_slug, my_user, repo
                        )

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

    # Persist the agent context for retrospective analysis
    save_session_artifact(f"{origin_owner}/{repo}", issue_number, "context.md", context_body)

    # 6. Create context issue on target repo (fork or self-owned)
    # Use REST API (gh api POST) instead of gh issue create (GraphQL) to avoid GraphQL rate limits.
    with StepTimer("stage3", "create_issue", origin_slug, issue_number) as t:
        import json as _json
        create_result = run_gh_command([
            "api", f"repos/{my_user}/{repo}/issues",
            "-X", "POST",
            "-f", f"title=[OSS] Fix: {issue_title}",
            "-f", f"body={context_body}"
        ])

        if not create_result["success"]:
            t.status = "error"
            t.detail = create_result.get("error", "issue creation failed")
            plog.error("fork-and-assign FAIL at create_issue: %s #%s — %s",
                       origin_slug, issue_number, t.detail)
            return error_response(create_result.get("error"), "Failed to create issue", my_user)
        create_data = _json.loads(create_result["output"])
        fork_issue_url = create_data["html_url"]
        fork_issue_number = str(create_data["number"])
        t.detail = f"created fork issue #{fork_issue_number}"

    # 7. Assign Copilot (retry once — API lags behind issue creation)
    # Use REST API instead of gh issue edit (GraphQL) to avoid GraphQL rate limits.
    # After POST, re-fetch the issue to confirm Copilot actually appears in assignees.
    # GitHub returns HTTP 200 but silently ignores the assignment on some repos/orgs.
    with StepTimer("stage3", "assign_copilot", origin_slug, issue_number) as t:
        import time as _time
        import json as _json2
        _assignees_payload = _json2.dumps({"assignees": [COPILOT_ASSIGNEE]})
        _assigned = False
        for _attempt in range(2):
            if _attempt > 0:
                _time.sleep(3)
            assign_result = run_gh_command([
                "api", f"repos/{my_user}/{repo}/issues/{fork_issue_number}/assignees",
                "-X", "POST", "--input", "-"
            ], stdin_data=_assignees_payload)
            if not assign_result.get("success"):
                continue
            # Verify the assignee actually stuck — GitHub silently drops unknown assignees
            verify_result = run_gh_command([
                "api", f"repos/{my_user}/{repo}/issues/{fork_issue_number}",
                "--jq", "[.assignees[].login]",
            ])
            if verify_result.get("success"):
                try:
                    _assignees = _json2.loads(verify_result["output"].strip())
                    if any("copilot" in a.lower() for a in _assignees):
                        _assigned = True
                        break
                except (ValueError, TypeError):
                    pass
        if _assigned:
            t.detail = f"assigned {COPILOT_ASSIGNEE} to #{fork_issue_number}"
        else:
            t.status = "error"
            t.detail = f"assign failed: Copilot not in assignees after POST (assignee rejected by GitHub)"
            plog.error(
                "fork-and-assign FAIL at assign_copilot: %s #%s — "
                "GitHub accepted the request but Copilot was not added as assignee. "
                "Check that the Copilot coding agent is available for this repo.",
                origin_slug, issue_number
            )

    # 8. Track locally
    with StepTimer("stage3", "save_assignment", origin_slug, issue_number) as t:
        default_branch = svc.get_default_branch(
            origin_owner, repo, issue_brief=issue_brief, dossier_context=dossier_context
        )
        if default_branch is None:
            plog.error(
                "fork-and-assign ERROR: could not determine default branch for %s — "
                "fork was created but assignment not saved",
                origin_slug
            )
            return jsonify({
                "success": False,
                "error": f"Could not determine default branch for {origin_slug}",
                "owner": my_user,
            })
        svc.save_assignment(
            origin_owner, repo, issue_number, fork_issue_number, fork_issue_url,
            is_self_owned=is_self_owned, default_branch=default_branch
        )
        t.detail = f"saved (branch={default_branch})"

    # 8b. Track that this repo has been dispatched (for Stage 1 dedup display)
    svc.track_dispatched_repo(origin_slug)

    # 8c. Persist aggregator metadata to assignment
    aggregator_meta = {}
    if dossier_meta:
        aggregator_meta["dossier"] = dossier_meta
    if brief_meta:
        aggregator_meta["brief"] = brief_meta
    meta_updates = {
        "stage4_status": "swe_agent_working",
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
