"""
Stage 1 routes — Target Repos.

Endpoints for managing the watchlist of target repositories.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

try:
    from ..services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from ..services.oss_service import _call_aggregator
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from services.oss_service import _call_aggregator


def _enrich_target_via_gh(entry):
    """Fetch basic repo metadata via gh CLI for a watchlist entry."""
    owner, repo = entry["owner"], entry["repo"]
    target = {"slug": entry["slug"]}

    result = run_gh_command([
        "api", f"/repos/{owner}/{repo}",
        "--jq", "{stars: .stargazers_count, language: .language, license: .license.spdx_id, openIssueCount: .open_issues_count, hasContributing: false}"
    ])
    if result["success"]:
        try:
            meta = json.loads(result["output"])
            target["meta"] = meta
        except (json.JSONDecodeError, KeyError):
            pass

    return target


@bp.route("/api/oss/stage1-targets", methods=["GET"])
@cached_endpoint("oss-stage1-targets")
def api_oss_stage1_targets():
    """Get target repos with health scores.

    Tries aggregator first for watchlist + health data.
    Falls back to local watchlist with gh CLI metadata enrichment.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Try aggregator first
    aggregator_slugs = svc.get_watchlist()

    if aggregator_slugs:
        targets = []
        for slug in aggregator_slugs:
            target = {"slug": slug}
            health_resp = _call_aggregator(f"/recon/{slug}/health")
            # Unwrap: { success, data: { maintainerHealthScore, ... } }
            health = health_resp.get("data", health_resp) if isinstance(health_resp, dict) else None
            if health:
                target["health"] = {
                    "maintainerHealthScore": health.get("maintainerHealthScore", 0),
                    "mergeAccessibilityScore": health.get("mergeAccessibilityScore", 0),
                    "availabilityScore": health.get("availabilityScore", 0),
                    "overallViability": health.get("overallViability", 0),
                }
            targets.append(target)
        return {"success": True, "targets": targets, "owner": my_user}

    # Fallback: local watchlist + gh CLI metadata
    local_watchlist = svc.get_local_watchlist()
    targets = []

    if local_watchlist:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_enrich_target_via_gh, entry) for entry in local_watchlist]
            for future in as_completed(futures):
                try:
                    targets.append(future.result())
                except Exception:
                    pass

    return {"success": True, "targets": targets, "owner": my_user}


@bp.route("/api/oss/add-target", methods=["POST"])
def api_oss_add_target():
    """Add a repo to the watchlist.

    Accepts {slug: "owner/repo"} in slash format.
    Validates via gh api, saves to local watchlist, proxies to aggregator.
    """
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    if "/" not in slug:
        return jsonify({"success": False, "error": "Format must be owner/repo", "owner": my_user})

    parts = slug.split("/", 1)
    owner, repo = parts[0].strip(), parts[1].strip()

    if not owner or not repo:
        return jsonify({"success": False, "error": "Invalid owner/repo format", "owner": my_user})

    # Validate repo exists
    validate_result = run_gh_command([
        "api", f"/repos/{owner}/{repo}", "--jq", ".full_name"
    ])
    if not validate_result["success"]:
        return jsonify({"success": False, "error": f"Repository {owner}/{repo} not found", "owner": my_user})

    svc = OSSService()

    # Save to local watchlist
    svc.add_to_local_watchlist(owner, repo)

    # Proxy to aggregator (best-effort)
    hyphenated_slug = f"{owner}-{repo}"
    svc.add_to_watchlist(hyphenated_slug)
    svc.trigger_refresh(hyphenated_slug)
    # Trigger pre-computation so scored issues/dossier are available
    svc.trigger_compute(hyphenated_slug)

    # Invalidate cache
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/remove-target", methods=["POST"])
def api_oss_remove_target():
    """Remove a repo from the watchlist."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    svc = OSSService()

    if "/" in slug:
        owner, repo = slug.split("/", 1)
    else:
        # Look up in local watchlist by hyphenated slug
        watchlist = svc.get_local_watchlist()
        entry = next((e for e in watchlist if e["slug"] == slug), None)
        if entry:
            owner, repo = entry["owner"], entry["repo"]
        else:
            return jsonify({"success": False, "error": "Target not found", "owner": my_user})

    svc.remove_from_local_watchlist(owner, repo)

    # Proxy to aggregator (best-effort)
    hyphenated_slug = f"{owner}-{repo}"
    svc.remove_from_watchlist(hyphenated_slug)

    # Invalidate cache
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "owner": my_user})


@bp.route("/api/oss/refresh-target", methods=["POST"])
def api_oss_refresh_target():
    """Trigger re-scrape for a target repo."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    svc = OSSService()

    # Convert to hyphenated format for aggregator
    if "/" in slug:
        hyphenated_slug = slug.replace("/", "-")
    else:
        hyphenated_slug = slug

    svc.trigger_refresh(hyphenated_slug)
    # Trigger pre-computation so scored issues/dossier are available
    svc.trigger_compute(hyphenated_slug)

    # Invalidate cache regardless of aggregator response
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "message": "Cache invalidated, compute triggered", "owner": my_user})
