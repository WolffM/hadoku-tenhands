"""
Stage 2 routes — Scored Issues.

Endpoints for fetching scored issues, dossiers, and issue briefs.
"""

import logging

from flask import jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import get_authenticated_user, OSSService, cached_endpoint
except ImportError:
    from services import get_authenticated_user, OSSService, cached_endpoint


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

    # Aggregator unavailable — no fallback
    logger.warning("Aggregator unavailable, returning empty issues for %s", my_user)
    return {"success": True, "issues": [], "owner": my_user}


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
