"""
Stage 2 routes — Scored Issues.

Endpoints for fetching scored issues, dossiers, and issue briefs.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint
    from ..helpers.oss_helpers import score_issue_fallback
    from ..helpers.notifications import notify_go_tier_issue
except ImportError:
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

        issue_id = f"github-{owner}-{repo}-{issue['number']}"

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


@bp.route("/api/oss/stage2-issues", methods=["GET"])
@cached_endpoint("oss-stage2-issues")
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
            except Exception:
                pass

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
