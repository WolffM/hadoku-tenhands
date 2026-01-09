"""
VibeDispatch - Central Dashboard for GitHub Repository Management
"""

from flask import Flask, render_template, request, jsonify
import subprocess
import json
import time
import base64
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import from services
from services import (
    run_gh_command,
    get_authenticated_user,
    get_repos,
    get_repo_details,
    get_repo_issues,
    get_repo_prs,
    get_workflows,
    get_workflow_runs,
    check_vibecheck_installed,
    check_vibecheck_installed_batch,
    clear_vibecheck_cache
)
from config import VIBECHECK_WORKFLOW

app = Flask(__name__)


# ============ Page Routes ============

@app.route("/")
def dashboard():
    """Main dashboard showing all repositories."""
    start = time.time()
    repos = get_repos()
    print(f"[PERF] get_repos: {time.time() - start:.2f}s")
    
    owner = get_authenticated_user()
    
    # Check vibecheck status in parallel
    start = time.time()
    status_dict = check_vibecheck_installed_batch(owner, repos)
    print(f"[PERF] vibecheck batch check: {time.time() - start:.2f}s")
    
    for repo in repos:
        repo["vibecheck_installed"] = status_dict.get(repo["name"], False)
    
    return render_template("dashboard.html", repos=repos, owner=owner)


@app.route("/repo/<owner>/<repo>")
def repo_detail(owner, repo):
    """Detailed view of a single repository."""
    details = get_repo_details(owner, repo)
    issues = get_repo_issues(owner, repo)
    prs = get_repo_prs(owner, repo)
    workflows = get_workflows(owner, repo)
    workflow_runs = get_workflow_runs(owner, repo)
    vibecheck_installed = check_vibecheck_installed(owner, repo)
    
    # Get vibecheck-specific issues
    vibecheck_issues = get_repo_issues(owner, repo, labels="vibeCheck")
    
    # Filter high severity issues
    high_severity_issues = [i for i in vibecheck_issues if any(
        "severity:high" in l.get("name", "").lower() or "severity:critical" in l.get("name", "").lower() 
        for l in i.get("labels", [])
    )]
    
    return render_template("repo_detail.html", 
                         details=details, 
                         issues=issues,
                         prs=prs,
                         workflows=workflows,
                         workflow_runs=workflow_runs,
                         vibecheck_installed=vibecheck_installed,
                         vibecheck_issues=vibecheck_issues,
                         high_severity_issues=high_severity_issues,
                         owner=owner,
                         repo=repo)


@app.route("/global-actions")
def global_actions():
    """Page for running actions across multiple repos."""
    start = time.time()
    repos = get_repos()
    print(f"[PERF] global_actions get_repos: {time.time() - start:.2f}s")
    
    owner = get_authenticated_user()
    
    # Use parallel batch check with caching
    start = time.time()
    status_dict = check_vibecheck_installed_batch(owner, repos)
    print(f"[PERF] global_actions vibecheck batch: {time.time() - start:.2f}s")
    
    for repo in repos:
        repo["vibecheck_installed"] = status_dict.get(repo["name"], False)
    
    return render_template("global_actions.html", repos=repos, owner=owner)


@app.route("/healthcheck")
def healthcheck():
    """Health check page for monitoring workflow runs."""
    owner = get_authenticated_user()
    return render_template("healthcheck.html", owner=owner)


# ============ API Routes ============

@app.route("/api/install-vibecheck", methods=["POST"])
def api_install_vibecheck():
    """Install vibecheck workflow to a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})
    
    content_b64 = base64.b64encode(VIBECHECK_WORKFLOW.encode()).decode()
    
    result = subprocess.run(
        ["gh", "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
         "-f", "message=Add vibeCheck workflow",
         "-f", f"content={content_b64}"],
        capture_output=True,
        text=True,
        shell=True
    )
    
    if result.returncode == 0:
        clear_vibecheck_cache()
        return jsonify({"success": True, "message": "vibeCheck workflow installed!"})
    return jsonify({"success": False, "error": result.stderr})


@app.route("/api/run-vibecheck", methods=["POST"])
def api_run_vibecheck():
    """Trigger the vibecheck workflow."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})
    
    result = run_gh_command(["workflow", "run", "vibecheck.yml", "-R", f"{owner}/{repo}"])
    
    if result["success"]:
        return jsonify({"success": True, "message": "vibeCheck workflow triggered!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})


@app.route("/api/assign-copilot", methods=["POST"])
def api_assign_copilot():
    """Assign GitHub Copilot to an issue."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    issue_number = data.get("issue_number")
    
    if not all([owner, repo, issue_number]):
        return jsonify({"success": False, "error": "Missing required fields"})
    
    result = run_gh_command([
        "issue", "edit", str(issue_number),
        "-R", f"{owner}/{repo}",
        "--add-assignee", "@Copilot"
    ])
    
    if result["success"]:
        return jsonify({"success": True, "message": f"Copilot assigned to issue #{issue_number}!"})
    return jsonify({"success": False, "error": result.get("error", "Failed to assign Copilot")})


@app.route("/api/get-high-severity-issues", methods=["POST"])
def api_get_high_severity_issues():
    """Get high severity vibecheck issues for a repo."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})
    
    issues = get_repo_issues(owner, repo, labels="vibeCheck")
    high_severity = [i for i in issues if any(
        "severity:high" in l.get("name", "").lower() or "severity:critical" in l.get("name", "").lower()
        for l in i.get("labels", [])
    )]
    
    return jsonify({"success": True, "issues": high_severity})


@app.route("/api/approve-pr", methods=["POST"])
def api_approve_pr():
    """Approve a pull request."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")
    
    if not all([owner, repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})
    
    result = run_gh_command([
        "pr", "review", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--approve",
        "-b", "Approved"
    ])
    
    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} approved!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})


@app.route("/api/mark-pr-ready", methods=["POST"])
def api_mark_pr_ready():
    """Mark a draft PR as ready for review."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")
    
    if not all([owner, repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})
    
    result = run_gh_command([
        "pr", "ready", str(pr_number),
        "-R", f"{owner}/{repo}"
    ])
    
    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} marked as ready!"})
    return jsonify({"success": False, "error": result.get("error", "Failed to mark PR as ready")})


@app.route("/api/merge-pr", methods=["POST"])
def api_merge_pr():
    """Merge a pull request."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    pr_number = data.get("pr_number")
    
    if not all([owner, repo, pr_number]):
        return jsonify({"success": False, "error": "Missing required fields"})
    
    # Check if PR is a draft and mark it as ready first
    check_result = run_gh_command([
        "pr", "view", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--json", "isDraft"
    ])
    
    if check_result["success"]:
        try:
            pr_data = json.loads(check_result["output"])
            if pr_data.get("isDraft", False):
                ready_result = run_gh_command([
                    "pr", "ready", str(pr_number),
                    "-R", f"{owner}/{repo}"
                ])
                if not ready_result["success"]:
                    return jsonify({"success": False, "error": f"Failed to mark PR as ready: {ready_result.get('error')}"})
        except:
            pass
    
    result = run_gh_command([
        "pr", "merge", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--squash",
        "--delete-branch"
    ])
    
    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} merged!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})


@app.route("/api/run-full-pipeline", methods=["POST"])
def api_run_full_pipeline():
    """Run the full vibecheck pipeline."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    steps_completed = []
    
    # Install vibecheck if not installed
    if not check_vibecheck_installed(owner, repo):
        content_b64 = base64.b64encode(VIBECHECK_WORKFLOW.encode()).decode()
        result = subprocess.run(
            ["gh", "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
             "-f", "message=Add vibeCheck workflow",
             "-f", f"content={content_b64}"],
            capture_output=True, text=True, shell=True
        )
        if result.returncode != 0:
            return jsonify({"success": False, "error": f"Failed to install: {result.stderr}", "steps_completed": steps_completed})
        steps_completed.append("install")
    else:
        steps_completed.append("install (already done)")
    
    # Trigger vibecheck
    trigger_result = run_gh_command(["workflow", "run", "vibecheck.yml", "-R", f"{owner}/{repo}"])
    if trigger_result["success"]:
        steps_completed.append("trigger")
    else:
        return jsonify({"success": False, "error": f"Failed to trigger: {trigger_result.get('error')}", "steps_completed": steps_completed})
    
    return jsonify({
        "success": True, 
        "message": "Pipeline started! Vibecheck workflow is running.",
        "steps_completed": steps_completed
    })


@app.route("/api/workflow-status", methods=["POST"])
def api_workflow_status():
    """Get the status of the latest vibecheck workflow run."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    runs = get_workflow_runs(owner, repo, "vibeCheck")
    if runs:
        return jsonify({"success": True, "run": runs[0]})
    return jsonify({"success": False, "error": "No workflow runs found"})


@app.route("/api/global-workflow-runs", methods=["GET"])
def api_global_workflow_runs():
    """Get recent workflow runs across all repositories."""
    start_total = time.time()
    owner = get_authenticated_user()
    repos = get_repos()
    
    status_dict = check_vibecheck_installed_batch(owner, repos)
    
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
            # Exclude Copilot coding agent workflows
            if workflow_name == "Copilot coding agent":
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
    
    return jsonify({"success": True, "runs": all_runs[:50], "owner": owner})


@app.route("/api/clear-cache", methods=["POST"])
def api_clear_cache():
    """Clear the vibecheck cache."""
    clear_vibecheck_cache()
    return jsonify({"success": True, "message": "Cache cleared"})


# ============ Stage-based APIs ============

@app.route("/api/stage1-repos", methods=["GET"])
def api_stage1_repos():
    """Get repos that need vibecheck installed."""
    owner = get_authenticated_user()
    repos = get_repos()
    status_dict = check_vibecheck_installed_batch(owner, repos)
    
    needs_install = [
        {"name": r["name"], "description": r.get("description", ""), "isPrivate": r.get("isPrivate", False)}
        for r in repos if not status_dict.get(r["name"], False)
    ]
    
    return jsonify({"success": True, "repos": needs_install, "owner": owner})


@app.route("/api/stage2-repos", methods=["GET"])
def api_stage2_repos():
    """Get repos that have vibecheck installed with run info."""
    start = time.time()
    owner = get_authenticated_user()
    repos = get_repos()
    status_dict = check_vibecheck_installed_batch(owner, repos)
    
    vc_repos = [r for r in repos if status_dict.get(r["name"], False)]
    
    result = []
    
    def get_repo_run_info(repo):
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
                    except:
                        commits_since = 0
        
        return {
            "name": repo_name,
            "description": repo.get("description", ""),
            "isPrivate": repo.get("isPrivate", False),
            "lastRun": last_run,
            "commitsSinceLastRun": commits_since
        }
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_repo_run_info, r) for r in vc_repos[:20]]
        for future in as_completed(futures):
            result.append(future.result())
    
    result.sort(key=lambda x: (x["lastRun"] is None, -x["commitsSinceLastRun"]), reverse=True)
    
    print(f"[PERF] stage2-repos: {time.time() - start:.2f}s")
    return jsonify({"success": True, "repos": result, "owner": owner})


@app.route("/api/stage3-issues", methods=["GET"])
def api_stage3_issues():
    """Get vibecheck issues across repos for Copilot assignment."""
    start = time.time()
    owner = get_authenticated_user()
    repos = get_repos()
    status_dict = check_vibecheck_installed_batch(owner, repos)
    
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
    def get_severity_score(issue):
        labels = [l.get("name", "").lower() for l in issue.get("labels", [])]
        if any("severity:critical" in l for l in labels):
            return 0
        if any("severity:high" in l for l in labels):
            return 1
        if any("severity:medium" in l for l in labels):
            return 2
        return 3
    
    all_issues.sort(key=lambda i: get_severity_score(i))
    
    print(f"[PERF] stage3-issues: {time.time() - start:.2f}s")
    return jsonify({
        "success": True, 
        "issues": all_issues, 
        "labels": sorted(list(label_set)),
        "repos_with_copilot_prs": list(repos_with_copilot_prs),
        "owner": owner
    })


@app.route("/api/stage4-prs", methods=["GET"])
def api_stage4_prs():
    """Get open PRs across repos for review."""
    start = time.time()
    owner = get_authenticated_user()
    repos = get_repos()
    
    all_prs = []
    
    def check_copilot_completed(owner, repo_name, pr_number, pr_title):
        """Check if Copilot has completed work on a PR.
        Returns True if:
        - Title no longer starts with [WIP]
        - OR a comment contains 'completed task' or 'completed work'
        """
        # Check title first (fast)
        if not pr_title.startswith("[WIP]"):
            return True
        
        # Check comments for completion message
        result = run_gh_command([
            "pr", "view", str(pr_number), "-R", f"{owner}/{repo_name}",
            "--json", "comments"
        ])
        if result["success"]:
            try:
                data = json.loads(result["output"])
                comments = data.get("comments", [])
                for comment in comments:
                    body = (comment.get("body") or "").lower()
                    if "completed task" in body or "completed work" in body:
                        return True
            except:
                pass
        return False
    
    def get_repo_prs_with_info(repo):
        repo_name = repo["name"]
        prs = get_repo_prs(owner, repo_name)
        for pr in prs:
            pr["repo"] = repo_name
            # Check if this is a Copilot PR and determine completion status
            author = pr.get("author", {}).get("login", "").lower() if pr.get("author") else ""
            if "copilot" in author:
                pr["copilotCompleted"] = check_copilot_completed(
                    owner, repo_name, pr.get("number"), pr.get("title", "")
                )
            else:
                pr["copilotCompleted"] = None  # Not a Copilot PR
        return prs
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_repo_prs_with_info, r) for r in repos[:20]]
        for future in as_completed(futures):
            all_prs.extend(future.result())
    
    all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    
    print(f"[PERF] stage4-prs: {time.time() - start:.2f}s")
    return jsonify({"success": True, "prs": all_prs, "owner": owner})


@app.route("/api/pr-details", methods=["POST"])
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


if __name__ == "__main__":
    # Use environment variable to control debug mode (defaults to False for security)
    # Set FLASK_ENV=development to enable debug mode in local development
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    app.run(debug=debug_mode, port=5000)
