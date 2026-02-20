"""
VibeDispatch - API Backend for GitHub Repository Management

This Flask app serves as the API backend for the VibeDispatch React frontend.
All page rendering has been moved to the React microfrontend.
"""

from flask import Flask, Blueprint, request, jsonify
import subprocess
import json
import time
import base64
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Support both direct execution (python backend/app.py) and module execution (python -m backend.app)
try:
    from .services import (
        run_gh_command,
        get_authenticated_user,
        get_repos,
        get_repo_issues,
        get_repo_prs,
        get_workflow_runs,
        check_vibecheck_installed_batch,
        clear_vibecheck_cache,
        get_cached,
        set_cached,
        clear_cache,
        get_cache_stats
    )
    from .config import VIBECHECK_WORKFLOW
except ImportError:
    from services import (
        run_gh_command,
        get_authenticated_user,
        get_repos,
        get_repo_issues,
        get_repo_prs,
        get_workflow_runs,
        check_vibecheck_installed_batch,
        clear_vibecheck_cache,
        get_cached,
        set_cached,
        clear_cache,
        get_cache_stats
    )
    from config import VIBECHECK_WORKFLOW

# On Windows, prevent subprocess from opening console windows
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

# URL prefix for deployment behind edge-router at hadoku.me/dispatch/*
# Set URL_PREFIX="" for local development without prefix
URL_PREFIX = os.environ.get("URL_PREFIX", "/dispatch")

app = Flask(__name__)

# Create blueprint for all routes
bp = Blueprint('dispatch', __name__)



# ============ CORS Support ============
@app.after_request
def add_cors_headers(response):
    """Add CORS headers for development with React frontend."""
    # In production, the React app is served from the same origin
    # In development, React runs on localhost:5173
    origin = request.headers.get('Origin', '')
    if origin in ['http://localhost:5175', 'http://127.0.0.1:5175', 'http://localhost:5173', 'http://localhost:5174']:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Key'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


@app.route('/')
def api_root():
    """API info endpoint."""
    return jsonify({"message": "VibeDispatch API", "docs": "/api/"})


# ============ API Routes ============

@bp.route("/api/install-vibecheck", methods=["POST"])
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
        creationflags=_SUBPROCESS_FLAGS
    )
    
    if result.returncode == 0:
        clear_vibecheck_cache()
        return jsonify({"success": True, "message": "vibeCheck workflow installed!"})
    return jsonify({"success": False, "error": result.stderr})


@bp.route("/api/vibecheck-template", methods=["GET"])
def api_vibecheck_template():
    """Fetch the latest vibecheck workflow template from the vibecheck repo."""
    # Try to fetch from WolffM/vibecheck repo
    try:
        result = subprocess.run(
            ["gh", "api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )

        if result.returncode == 0:
            try:
                content = base64.b64decode(result.stdout.strip()).decode()
                return jsonify({"success": True, "template": content})
            except Exception as e:
                return jsonify({"success": False, "error": f"Failed to decode template: {e}"})
    except subprocess.TimeoutExpired:
        pass  # Fall through to local template

    # Fallback to local template
    return jsonify({"success": True, "template": VIBECHECK_WORKFLOW, "source": "local"})


@bp.route("/api/update-vibecheck", methods=["POST"])
def api_update_vibecheck():
    """Update existing vibecheck workflow in a repository."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    template = data.get("template")  # Optional custom template

    if not owner or not repo:
        return jsonify({"success": False, "error": "Missing owner or repo"})

    # Get the current file SHA (required for updates)
    try:
        sha_result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml", "--jq", ".sha"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timed out checking workflow file"})

    if sha_result.returncode != 0:
        return jsonify({"success": False, "error": "Workflow not found - use install instead"})

    sha = sha_result.stdout.strip()

    # Use provided template or fetch latest from vibecheck repo
    if template:
        workflow_content = template
    else:
        # Fetch latest from vibecheck repo
        try:
            template_result = subprocess.run(
                ["gh", "api", "repos/WolffM/vibecheck/contents/examples/vibecheck.yml", "--jq", ".content"],
                capture_output=True,
                text=True,
                creationflags=_SUBPROCESS_FLAGS,
                timeout=30
            )
            if template_result.returncode == 0:
                try:
                    workflow_content = base64.b64decode(template_result.stdout.strip()).decode()
                except Exception:
                    workflow_content = VIBECHECK_WORKFLOW
            else:
                workflow_content = VIBECHECK_WORKFLOW
        except subprocess.TimeoutExpired:
            workflow_content = VIBECHECK_WORKFLOW

    content_b64 = base64.b64encode(workflow_content.encode()).decode()

    try:
        result = subprocess.run(
            ["gh", "api", "-X", "PUT", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml",
             "-f", "message=Update vibeCheck workflow to latest version",
             "-f", f"content={content_b64}",
             "-f", f"sha={sha}"],
            capture_output=True,
            text=True,
            creationflags=_SUBPROCESS_FLAGS,
            timeout=30
        )
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Timed out updating workflow file"})

    if result.returncode == 0:
        return jsonify({"success": True, "message": "vibeCheck workflow updated!"})
    return jsonify({"success": False, "error": result.stderr})


@bp.route("/api/repos-with-vibecheck", methods=["GET"])
def api_repos_with_vibecheck():
    """Get repos that have vibecheck installed (for updating)."""
    cache_key = "repos-with-vibecheck"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

    owner = get_authenticated_user()
    repos = get_repos()

    if not repos:
        result = {"owner": owner, "repos": []}
        set_cached(cache_key, result)
        return jsonify(result)

    status_dict = check_vibecheck_installed_batch(owner, repos)

    repos_with_vibecheck = [
        {"name": r["name"], "isPrivate": r.get("isPrivate", False)}
        for r in repos
        if status_dict.get(r["name"], False)
    ]

    result = {"owner": owner, "repos": repos_with_vibecheck}
    set_cached(cache_key, result)
    return jsonify(result)


@bp.route("/api/run-vibecheck", methods=["POST"])
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


@bp.route("/api/assign-copilot", methods=["POST"])
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


@bp.route("/api/approve-pr", methods=["POST"])
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


@bp.route("/api/mark-pr-ready", methods=["POST"])
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


@bp.route("/api/merge-pr", methods=["POST"])
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
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    
    # Merge can take a while, use longer timeout (60s)
    result = run_gh_command([
        "pr", "merge", str(pr_number),
        "-R", f"{owner}/{repo}",
        "--squash",
        "--delete-branch"
    ], timeout=60)

    if result["success"]:
        return jsonify({"success": True, "message": f"PR #{pr_number} merged!"})
    return jsonify({"success": False, "error": result.get("error", "Unknown error")})


@bp.route("/api/workflow-status", methods=["POST"])
def api_workflow_status():
    """Get the status of the latest vibecheck workflow run."""
    data = request.json
    owner = data.get("owner")
    repo = data.get("repo")
    
    runs = get_workflow_runs(owner, repo, "vibeCheck")
    if runs:
        return jsonify({"success": True, "run": runs[0]})
    return jsonify({"success": False, "error": "No workflow runs found"})


@bp.route("/api/global-workflow-runs", methods=["GET"])
def api_global_workflow_runs():
    """Get recent workflow runs across all repositories."""
    cache_key = "global-workflow-runs"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

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
            # Exclude Copilot-related workflows (not interesting for health check)
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

    response = {"success": True, "runs": all_runs[:50], "owner": owner}
    set_cached(cache_key, response)
    return jsonify(response)


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


# ============ Stage-based APIs ============

def is_demo_pr(pr):
    """Check if a PR has the 'demo' label (case-insensitive)."""
    pr_labels = [label.get("name", "").lower() for label in pr.get("labels", [])]
    return "demo" in pr_labels


@bp.route("/api/stage1-repos", methods=["GET"])
def api_stage1_repos():
    """Get repos that need vibecheck installed."""
    cache_key = "stage1-repos"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

    owner = get_authenticated_user()
    repos = get_repos()
    status_dict = check_vibecheck_installed_batch(owner, repos)

    needs_install = [
        {"name": r["name"], "description": r.get("description", ""), "isPrivate": r.get("isPrivate", False)}
        for r in repos if not status_dict.get(r["name"], False)
    ]

    result = {"success": True, "repos": needs_install, "owner": owner}
    set_cached(cache_key, result)
    return jsonify(result)


@bp.route("/api/stage2-repos", methods=["GET"])
def api_stage2_repos():
    """Get repos that have vibecheck installed with run info."""
    cache_key = "stage2-repos"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

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
                    except (ValueError, AttributeError, TypeError):
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
    response = {"success": True, "repos": result, "owner": owner}
    set_cached(cache_key, response)
    return jsonify(response)


@bp.route("/api/stage3-issues", methods=["GET"])
def api_stage3_issues():
    """Get vibecheck issues across repos for Copilot assignment."""
    cache_key = "stage3-issues"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

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
            # Skip PRs tagged with 'demo'
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
    def get_severity_score(issue):
        labels = [label.get("name", "").lower() for label in issue.get("labels", [])]
        if any("severity:critical" in label for label in labels):
            return 0
        if any("severity:high" in label for label in labels):
            return 1
        if any("severity:medium" in label for label in labels):
            return 2
        return 3

    all_issues.sort(key=lambda i: get_severity_score(i))

    print(f"[PERF] stage3-issues: {time.time() - start:.2f}s")
    response = {
        "success": True,
        "issues": all_issues,
        "labels": sorted(list(label_set)),
        "repos_with_copilot_prs": list(repos_with_copilot_prs),
        "owner": owner
    }
    set_cached(cache_key, response)
    return jsonify(response)


@bp.route("/api/stage4-prs", methods=["GET"])
def api_stage4_prs():
    """Get open PRs across repos for review."""
    cache_key = "stage4-prs"
    cached = get_cached(cache_key)
    if cached:
        return jsonify(cached)

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
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                pass
        return False

    def get_repo_prs_with_info(repo):
        repo_name = repo["name"]
        prs = get_repo_prs(owner, repo_name)
        filtered_prs = []
        for pr in prs:
            # Skip PRs tagged with 'demo'
            if is_demo_pr(pr):
                continue
            pr["repo"] = repo_name
            # Check if this is a Copilot PR and determine completion status
            author = pr.get("author", {}).get("login", "").lower() if pr.get("author") else ""
            if "copilot" in author:
                pr["copilotCompleted"] = check_copilot_completed(
                    owner, repo_name, pr.get("number"), pr.get("title", "")
                )
            else:
                pr["copilotCompleted"] = None  # Not a Copilot PR
            filtered_prs.append(pr)
        return filtered_prs

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_repo_prs_with_info, r) for r in repos[:20]]
        for future in as_completed(futures):
            all_prs.extend(future.result())

    all_prs.sort(key=lambda x: x.get("createdAt", ""), reverse=True)

    print(f"[PERF] stage4-prs: {time.time() - start:.2f}s")
    response = {"success": True, "prs": all_prs, "owner": owner}
    set_cached(cache_key, response)
    return jsonify(response)


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


# ============ Health Check API ============
@bp.route("/api/healthcheck", methods=["GET"])
def api_healthcheck():
    """Health check endpoint for monitoring."""
    owner = get_authenticated_user()
    return jsonify({
        "success": True,
        "status": "healthy",
        "owner": owner,
        "api_version": "2.0.0"
    })


@bp.route("/api/owner", methods=["GET"])
def api_owner():
    """Get the authenticated GitHub owner/user."""
    owner = get_authenticated_user()
    return jsonify({"success": True, "owner": owner})


# Register blueprint with URL prefix
app.register_blueprint(bp, url_prefix=URL_PREFIX)


if __name__ == "__main__":
    # Use environment variable to control debug mode (defaults to False for security)
    # Set FLASK_ENV=development to enable debug mode in local development
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    app.run(debug=debug_mode, port=5000)
