"""
Pipeline routes - stage-based APIs and cache/monitoring endpoints.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

try:
    from ..services import (
        run_gh_command,
        get_repo_context,
        get_repo_issues,
        get_repo_prs,
        get_workflow_runs,
        clear_vibecheck_cache,
        clear_cache,
        get_cache_stats,
        cached_endpoint,
    )
    from ..helpers.stage_helpers import is_demo_pr, get_severity_score, check_copilot_completed
except ImportError:
    from services import (
        run_gh_command,
        get_repo_context,
        get_repo_issues,
        get_repo_prs,
        get_workflow_runs,
        clear_vibecheck_cache,
        clear_cache,
        get_cache_stats,
        cached_endpoint,
    )
    from helpers.stage_helpers import is_demo_pr, get_severity_score, check_copilot_completed


# --- Module-level helpers for ThreadPoolExecutor usage ---

def _get_repo_run_info(owner, repo):
    """Get run info for a repo (used by stage2). Extracted for executor clarity."""
    repo_name = repo["name"]
    runs = get_workflow_runs(owner, repo_name, "vibeCheck")
    last_run = runs[0] if runs else None

    commits_since = 0
    if last_run:
        last_run_date = last_run.get("createdAt", "")
        if last_run_date:
            commit_result = run_gh_command([
                "api", f"/repos/{owner}/{repo_name}/commits",
                "--jq", f'[.[] | select(.commit.author.date > "{last_run_date}")] | length'
            ])
            if commit_result["success"]:
                try:
                    commits_since = int(commit_result["output"].strip())
                except (ValueError, AttributeError, TypeError):
                    commits_since = 0

    return {
        "name": repo_name,
        "description": repo.get("description", ""),
        "isPrivate": repo.get("isPrivate", False),
        "lastRun": last_run,
        "commitsSinceLastRun": commits_since
    }


def _get_repo_prs_with_info(owner, repo):
    """Get filtered PRs with copilot completion status (used by stage4)."""
    repo_name = repo["name"]
    prs = get_repo_prs(owner, repo_name)
    filtered_prs = []
    for pr in prs:
        if is_demo_pr(pr):
            continue
        pr["repo"] = repo_name
        author = pr.get("author", {}).get("login", "").lower() if pr.get("author") else ""
        if "copilot" in author:
            pr["copilotCompleted"] = check_copilot_completed(
                owner, repo_name, pr.get("number"), pr.get("title", "")
            )
        else:
            pr["copilotCompleted"] = None
        filtered_prs.append(pr)
    return filtered_prs


# --- Cache/Monitoring routes ---

@bp.route("/api/global-workflow-runs", methods=["GET"])
@cached_endpoint("global-workflow-runs")
def api_global_workflow_runs():
    """Get recent workflow runs across all repositories."""
    start_total = time.time()
    owner, repos, status_dict = get_repo_context()

    print(f"[PERF] Fetching workflow runs for {min(len(repos), 15)} repos in parallel...")
    start = time.time()

    all_runs = []

    def fetch_runs_for_repo(repo):
        repo_name = repo["name"]
        runs = get_workflow_runs(owner, repo_name)

        seen_workflows = set()
        result = []
        for run in runs:
            workflow_name = run.get("workflowName", "Unknown")
            if workflow_name in ("Copilot coding agent", "Copilot code review"):
                continue
            if workflow_name not in seen_workflows:
                seen_workflows.add(workflow_name)
                run["repo"] = repo_name
                run["vibecheck_installed"] = status_dict.get(repo_name, False)
                result.append(run)
        return result

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_runs_for_repo, r) for r in repos[:15]]
        for future in as_completed(futures):
            all_runs.extend(future.result())

    print(f"[PERF] Fetched workflow runs in {time.time() - start:.2f}s")

    all_runs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

    print(f"[PERF] Total global-workflow-runs: {time.time() - start_total:.2f}s")

    return {"success": True, "runs": all_runs[:50], "owner": owner}


@bp.route("/api/clear-cache", methods=["POST"])
def api_clear_cache():
    """Clear all caches (file-based and in-memory)."""
    clear_vibecheck_cache()
    cleared = clear_cache()  # Clear file-based cache
    return jsonify({"success": True, "message": f"Cache cleared ({cleared} entries)"})


@bp.route("/api/cache-stats", methods=["GET"])
def api_cache_stats():
    """Get cache statistics for debugging."""
    stats = get_cache_stats()
    return jsonify({"success": True, "stats": stats})


# --- Stage-based routes ---

@bp.route("/api/stage1-repos", methods=["GET"])
@cached_endpoint("stage1-repos")
def api_stage1_repos():
    """Get repos that need vibecheck installed."""
    owner, repos, status_dict = get_repo_context()

    needs_install = [
        {"name": r["name"], "description": r.get("description", ""), "isPrivate": r.get("isPrivate", False)}
        for r in repos if not status_dict.get(r["name"], False)
    ]

    return {"success": True, "repos": needs_install, "owner": owner}


@bp.route("/api/stage2-repos", methods=["GET"])
@cached_endpoint("stage2-repos")
def api_stage2_repos():
    """Get repos that have vibecheck installed with run info."""
    start = time.time()
    owner, repos, status_dict = get_repo_context()

    vc_repos = [r for r in repos if status_dict.get(r["name"], False)]

    result = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_get_repo_run_info, owner, r) for r in vc_repos[:20]]
        for future in as_completed(futures):
            result.append(future.result())

    result.sort(key=lambda x: (x["lastRun"] is None, -x["commitsSinceLastRun"]), reverse=True)

    print(f"[PERF] stage2-repos: {time.time() - start:.2f}s")
    return {"success": True, "repos": result, "owner": owner}


@bp.route("/api/stage3-issues", methods=["GET"])
@cached_endpoint("stage3-issues")
def api_stage3_issues():
    """Get vibecheck issues across repos for Copilot assignment."""
    start = time.time()
    owner, repos, status_dict = get_repo_context()

    vc_repos = [r for r in repos if status_dict.get(r["name"], False)]

    all_issues = []
    repos_with_copilot_prs = set()

    def fetch_repo_issues(repo):
        repo_name = repo["name"]
        issues = get_repo_issues(owner, repo_name, labels="vibeCheck")
        for issue in issues:
            issue["repo"] = repo_name
        return issues

    def check_copilot_prs(repo):
        repo_name = repo["name"]
        prs = get_repo_prs(owner, repo_name)
        for pr in prs:
            if is_demo_pr(pr):
                continue
            author = pr.get("author", {})
            if author and "copilot" in author.get("login", "").lower():
                return repo_name
        return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        issue_futures = [executor.submit(fetch_repo_issues, r) for r in vc_repos[:15]]
        pr_futures = [executor.submit(check_copilot_prs, r) for r in vc_repos[:15]]

        for future in as_completed(issue_futures):
            all_issues.extend(future.result())

        for future in as_completed(pr_futures):
            result = future.result()
            if result:
                repos_with_copilot_prs.add(result)

    # Filter out issues assigned to Copilot
    def has_copilot_assigned(issue):
        for assignee in issue.get("assignees", []):
            if "copilot" in assignee.get("login", "").lower():
                return True
        return False

    all_issues = [i for i in all_issues if not has_copilot_assigned(i)]

    # Extract unique labels
    label_set = set()
    for issue in all_issues:
        for label in issue.get("labels", []):
            label_set.add(label.get("name", ""))

    # Sort by severity
    all_issues.sort(key=lambda i: get_severity_score(i))

    print(f"[PERF] stage3-issues: {time.time() - start:.2f}s")
    return {
        "success": True,
        "issues": all_issues,
        "labels": sorted(list(label_set)),
        "repos_with_copilot_prs": list(repos_with_copilot_prs),
        "owner": owner
    }


@bp.route("/api/stage4-prs", methods=["GET"])
@cached_endpoint("stage4-prs")
def api_stage4_prs():
    """Get open PRs across repos for review."""
    start = time.time()
    owner, repos, _ = get_repo_context()

    all_prs = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_get_repo_prs_with_info, owner, r) for r in repos[:20]]
        for future in as_completed(futures):
            all_prs.extend(future.result())

    all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

    print(f"[PERF] stage4-prs: {time.time() - start:.2f}s")
    return {"success": True, "prs": all_prs, "owner": owner}


@bp.route("/api/pr-details", methods=["POST"])
def api_pr_details():
    """Get detailed info about a specific PR."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")

    if not all([owner, repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})

    result = run_gh_command([
        "pr", "view", str(pr_number), "-R", f"{owner}/{repo}",
        "--json", "number,title,body,author,createdAt,headRefName,baseRefName,files,commits,reviewDecision,state,url,isDraft,additions,deletions,changedFiles,assignees"
    ])

    if result["success"]:
        pr_data = json.loads(result["output"])

        diff_result = run_gh_command([
            "pr", "diff", str(pr_number), "-R", f"{owner}/{repo}"
        ])
        if diff_result["success"]:
            pr_data["diff"] = diff_result["output"]

        return jsonify({"success": True, "pr": pr_data})

    return jsonify({"success": False, "error": result.get("error", "Failed to fetch PR")})
