"""
Stage 1 routes — Target Repos.

Endpoints for viewing target repositories and triggering aggregator actions.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import request, jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from ..helpers.validation import to_aggregator_slug
except ImportError:
    from services import get_authenticated_user, OSSService, cached_endpoint, clear_cache
    from helpers.validation import to_aggregator_slug


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

    Derives repo list from aggregator scored issues, enriched
    with health data and dossier sections.
    """
    my_user = get_authenticated_user()
    svc = OSSService()

    # Derive all repo slugs from scored issues
    all_slugs = set()
    aggregator_issues = svc.get_scored_issues()
    if aggregator_issues:
        for issue in aggregator_issues:
            rs = issue.get("repoSlug")
            if rs:
                all_slugs.add(rs)

    if not all_slugs:
        return {"success": True, "targets": [], "owner": my_user}

    targets = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_enrich_from_aggregator, svc, slug): slug
            for slug in sorted(all_slugs)
        }
        for future in as_completed(futures):
            try:
                targets.append(future.result())
            except Exception as e:
                logger.warning("Failed to enrich target %s from aggregator: %s", futures[future], e)
                targets.append({"slug": futures[future]})

    # Mark repos that have already been dispatched
    dispatched_agg_slugs = {
        d["aggregator_slug"]
        for d in svc.get_dispatched_repos()
        if "aggregator_slug" in d
    }
    for target in targets:
        target["already_dispatched"] = target["slug"] in dispatched_agg_slugs

    # Sort by overallViability descending (repos with health first)
    targets.sort(
        key=lambda t: t.get("health", {}).get("overallViability", 0),
        reverse=True,
    )

    return {"success": True, "targets": targets, "owner": my_user}


@bp.route("/api/oss/dispatched-repos", methods=["GET"])
def api_oss_dispatched_repos():
    """Get the list of repos that have had at least one successful dispatch."""
    my_user = get_authenticated_user()
    svc = OSSService()
    dispatched = svc.get_dispatched_repos()
    return jsonify({"success": True, "dispatched_repos": dispatched, "owner": my_user})


@bp.route("/api/oss/refresh-target", methods=["POST"])
def api_oss_refresh_target():
    """Trigger re-scrape for a target repo."""
    data = request.json
    slug = data.get("slug", "").strip()
    my_user = get_authenticated_user()

    if not slug:
        return jsonify({"success": False, "error": "Slug is required", "owner": my_user})

    svc = OSSService()

    # Convert to hyphenated format for aggregator
    hyphenated_slug = to_aggregator_slug(slug) if "/" in slug else slug

    if not svc.trigger_refresh(hyphenated_slug):
        logger.warning("trigger_refresh returned falsy for %s", hyphenated_slug)
    # Trigger pre-computation so scored issues/dossier are available
    if not svc.trigger_compute(hyphenated_slug):
        logger.warning("trigger_compute returned falsy for %s", hyphenated_slug)

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

    if not slug:
        return jsonify({"success": False, "error": "Slug is required", "owner": my_user})

    svc = OSSService()

    # Convert to hyphenated format for aggregator
    hyphenated_slug = to_aggregator_slug(slug) if "/" in slug else slug

    svc.trigger_compute(hyphenated_slug)

    # Invalidate cache so next fetch picks up fresh data
    clear_cache("oss-stage1-targets")
    clear_cache("oss-stage2-issues")

    return jsonify({"success": True, "message": "Compute triggered", "owner": my_user})
