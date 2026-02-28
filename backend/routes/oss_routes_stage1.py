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
except ImportError:
    from services import run_gh_command, get_authenticated_user, OSSService, cached_endpoint, clear_cache


def _fetch_dossier_for_target(svc, slug):
    """Fetch dossier sections + completeness for a single target. Returns dict."""
    dossier_data, dossier_meta = svc.get_dossier(slug, include_meta=True)
    if not dossier_data:
        return {}
    result = {}
    if dossier_data.get("sections"):
        result["sections"] = dossier_data["sections"]
    if dossier_data.get("completeness"):
        result["completeness"] = dossier_data["completeness"]
    if dossier_meta:
        result["_meta"] = dossier_meta
    return result


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


def _enrich_from_aggregator(svc, slug):
    """Fetch health + dossier for one slug. Returns enriched target dict."""
    target = {"slug": slug}
    health, health_meta = svc.get_health(slug, include_meta=True)
    if health:
        target["health"] = {
            "maintainerHealthScore": health.get("maintainerHealthScore", 0),
            "mergeAccessibilityScore": health.get("mergeAccessibilityScore", 0),
            "availabilityScore": health.get("availabilityScore", 0),
            "overallViability": health.get("overallViability", 0),
            "prPatterns": health.get("prPatterns"),
            "detectedQuirks": health.get("detectedQuirks"),
            "analyzedAt": health.get("analyzedAt"),
        }
        if health_meta:
            target["_meta"] = health_meta
    dossier = _fetch_dossier_for_target(svc, slug)
    if dossier:
        target["dossier"] = dossier
    return target


@bp.route("/api/oss/stage1-targets", methods=["GET"])
@cached_endpoint("oss-stage1-targets")
def api_oss_stage1_targets():
    """Get target repos with health scores.

    Shows all repos that have scored issues in the aggregator, enriched
    with health data and dossier sections.
    Falls back to local watchlist with gh CLI metadata enrichment.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Derive all repo slugs from scored issues (covers everything
    # the aggregator has computed, not just the 3-repo watchlist)
    all_slugs = set()
    aggregator_issues = svc.get_scored_issues()
    if aggregator_issues:
        for issue in aggregator_issues:
            rs = issue.get("repoSlug")
            if rs:
                all_slugs.add(rs)

    # Also include explicit watchlist (may have repos without scored issues yet)
    watchlist_slugs = svc.get_watchlist()
    if watchlist_slugs:
        all_slugs.update(watchlist_slugs)

    if all_slugs:
        targets = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(_enrich_from_aggregator, svc, slug): slug
                for slug in sorted(all_slugs)
            }
            for future in as_completed(futures):
                try:
                    targets.append(future.result())
                except Exception:
                    targets.append({"slug": futures[future]})

        # Sort by overallViability descending (repos with health first)
        targets.sort(
            key=lambda t: t.get("health", {}).get("overallViability", 0),
            reverse=True,
        )

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


@bp.route("/api/oss/compute-target", methods=["POST"])
def api_oss_compute_target():
    """Trigger pre-computation for a target repo (without re-scraping)."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    svc = OSSService()

    # Convert to hyphenated format for aggregator
    if "/" in slug:
        hyphenated_slug = slug.replace("/", "-")
    else:
        hyphenated_slug = slug

    svc.trigger_compute(hyphenated_slug)

    # Invalidate cache so next fetch picks up fresh data
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "message": "Compute triggered", "owner": my_user})
