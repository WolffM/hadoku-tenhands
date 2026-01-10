"""
GitHub API Service - Wrapper functions for GitHub CLI commands
"""

import subprocess
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from .cache import get_cached_vibecheck_status, set_cached_vibecheck_status


def run_gh_command(args, capture_output=True):
    """Run a gh CLI command and return the result."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=capture_output,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr}
        return {"success": True, "output": result.stdout}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_authenticated_user():
    """Get the currently authenticated GitHub user."""
    result = run_gh_command(["api", "user", "--jq", ".login"])
    if result["success"]:
        return result["output"].strip()
    return "unknown"


def get_repos(limit=100):
    """Get all repositories for the authenticated user."""
    result = run_gh_command(["repo", "list", "--limit", str(limit), "--json", "name,url,isPrivate,description,updatedAt"])
    if result["success"]:
        return json.loads(result["output"])
    return []


def get_repo_details(owner, repo):
    """Get detailed information about a specific repository."""
    result = run_gh_command(["repo", "view", f"{owner}/{repo}", "--json", "name,description,url,isPrivate,defaultBranchRef,updatedAt,stargazerCount,forkCount"])
    if result["success"]:
        return json.loads(result["output"])
    return None


def get_repo_issues(owner, repo, labels=None):
    """Get issues for a repository, optionally filtered by labels."""
    cmd = ["issue", "list", "-R", f"{owner}/{repo}", "--json", "number,title,labels,state,createdAt,assignees,url"]
    if labels:
        cmd.extend(["--label", labels])
    result = run_gh_command(cmd)
    if result["success"]:
        return json.loads(result["output"])
    return []


def get_repo_prs(owner, repo):
    """Get pull requests for a repository."""
    result = run_gh_command(["pr", "list", "-R", f"{owner}/{repo}", "--json", "number,title,state,createdAt,author,url,headRefName,isDraft,reviewDecision"])
    if result["success"]:
        return json.loads(result["output"])
    return []


def get_workflows(owner, repo):
    """Get workflows for a repository."""
    result = run_gh_command(["workflow", "list", "-R", f"{owner}/{repo}", "--json", "name,id,state"])
    if result["success"]:
        return json.loads(result["output"])
    return []


def get_workflow_runs(owner, repo, workflow_name=None, limit=10):
    """Get recent workflow runs."""
    cmd = ["run", "list", "-R", f"{owner}/{repo}", "--json", "databaseId,displayTitle,status,conclusion,createdAt,workflowName", "--limit", str(limit)]
    if workflow_name:
        cmd.extend(["-w", workflow_name])
    result = run_gh_command(cmd)
    if result["success"]:
        return json.loads(result["output"])
    return []


def check_vibecheck_installed(owner, repo):
    """Check if vibecheck workflow is installed in a repo."""
    result = run_gh_command(["api", f"/repos/{owner}/{repo}/contents/.github/workflows/vibecheck.yml"])
    return result["success"]


def check_vibecheck_installed_batch(owner, repos, max_workers=10):
    """Check vibecheck status for multiple repos in parallel."""
    # Check cache first
    cached = get_cached_vibecheck_status()
    if cached:
        print(f"[PERF] Using cached vibecheck status for {len(cached)} repos")
        return cached
    
    print(f"[PERF] Checking vibecheck status for {len(repos)} repos in parallel...")
    start = time.time()
    
    status_dict = {}
    
    def check_single(repo_name):
        return repo_name, check_vibecheck_installed(owner, repo_name)
    
    # Use thread pool for parallel execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_single, r["name"]): r["name"] for r in repos}
        for future in as_completed(futures):
            repo_name, installed = future.result()
            status_dict[repo_name] = installed
    
    elapsed = time.time() - start
    print(f"[PERF] Checked {len(repos)} repos in {elapsed:.2f}s")
    
    # Cache the results
    set_cached_vibecheck_status(status_dict)
    
    return status_dict
