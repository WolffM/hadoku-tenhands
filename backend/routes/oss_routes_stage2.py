"""
Stage 2 routes — Scored Issues.

Endpoints for fetching scored issues, dossiers, and issue briefs.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..config import PLATFORM_PREFIX
    from ..services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint
    from ..helpers.oss_helpers import score_issue_fallback
    from ..helpers.notifications import notify_go_tier_issue
except ImportError:
    from config import PLATFORM_PREFIX
    from services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint
    from helpers.oss_helpers import score_issue_fallback
    from helpers.notifications import notify_go_tier_issue

# Track GO-tier issue IDs already notified (avoid re-firing on cache refresh)
_notified_go_issues = set()


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

        issue_id = f"{PLATFORM_PREFIX}-{owner}-{repo}-{issue['number']}"

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


def _normalize_aggregator_issues(issues):
    """Normalize aggregator-provided issues to match the frontend ScoredIssue shape.

    The aggregator uses 'project' (owner/repo) and 'repoSlug' (owner-repo) but
    the frontend expects 'repo' (owner/repo) and 'number' (int).  Mutates in-place.
    """
    for issue in issues:
        # repo: prefer 'project' (already owner/repo), else derive from repoSlug
        if not issue.get("repo"):
            project = issue.get("project")
            if project:
                issue["repo"] = project
            else:
                slug = issue.get("repoSlug", "")
                # repoSlug is owner-repo; extract owner/repo from the issue URL
                url = issue.get("url", "")
                if "github.com/" in url:
                    parts = url.split("github.com/")[1].split("/")
                    if len(parts) >= 2:
                        issue["repo"] = f"{parts[0]}/{parts[1]}"
                elif slug:
                    issue["repo"] = slug  # last resort

        # number: parse from URL or id
        if not issue.get("number"):
            url = issue.get("url", "")
            if "/issues/" in url:
                try:
                    issue["number"] = int(url.rstrip("/").split("/")[-1])
                except (ValueError, IndexError):
                    pass
            if not issue.get("number"):
                # id format: github-owner-repo-NUMBER
                issue_id = issue.get("id", "")
                parts = issue_id.rsplit("-", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    issue["number"] = int(parts[1])

        # Defaults for optional list/scalar fields the frontend expects
        issue.setdefault("assignees", [])
        issue.setdefault("likelyFiles", [])
        issue.setdefault("relatedIssues", [])


@bp.route("/api/oss/stage2-issues", methods=["GET"])
@cached_endpoint("oss-stage2-issues", normalize=_normalize_aggregator_issues)
def api_oss_stage2_issues():
    """Get scored issues across all target repos.

    Tries aggregator for CVS-scored issues.
    Falls back to gh CLI + heuristic scoring.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Try aggregator first
    aggregator_issues, issues_meta = svc.get_scored_issues(include_meta=True)
    if aggregator_issues:
        resp = {"success": True, "issues": aggregator_issues, "owner": my_user}
        if issues_meta:
            resp["_meta"] = issues_meta
        return resp

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
            except Exception as e:
                logger.warning("Failed to fetch fallback issues for a target repo: %s", e)

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
