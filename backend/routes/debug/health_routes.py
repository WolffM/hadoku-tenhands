"""
Debug health-check endpoints: gh-health, aggregator-health, state-dump.
"""

import json
import os
import time

from flask import jsonify

try:
    from .. import bp
    from ...services import run_gh_command, get_authenticated_user
    from ...services.oss_service import _call_aggregator, OSS_DATA_DIR, AGGREGATOR_API_URL
    from ...routes.debug._middleware import require_admin_key
except ImportError:
    from routes import bp
    from services import run_gh_command, get_authenticated_user
    from services.oss_service import _call_aggregator, OSS_DATA_DIR, AGGREGATOR_API_URL
    from routes.debug._middleware import require_admin_key


@bp.route("/api/oss/debug/gh-health", methods=["GET"])
@require_admin_key
def api_oss_debug_gh_health():
    """Check gh CLI health: authentication, API access, rate limits."""
    my_user = get_authenticated_user()
    start = time.time()

    result = {
        "authenticated": False,
        "user": my_user,
        "api_working": False,
        "rate_limit": None,
        "response_time_ms": 0,
    }

    # Check auth
    auth_result = run_gh_command(["auth", "status"])
    result["authenticated"] = auth_result["success"]

    # Check API access
    api_result = run_gh_command(["api", "user", "--jq", ".login"])
    result["api_working"] = api_result["success"]

    # Check rate limit
    rate_result = run_gh_command(["api", "rate_limit", "--jq", ".rate"])
    if rate_result["success"]:
        try:
            rate_data = json.loads(rate_result["output"])
            result["rate_limit"] = {
                "remaining": rate_data.get("remaining"),
                "limit": rate_data.get("limit"),
                "reset_at": rate_data.get("reset"),
            }
        except (json.JSONDecodeError, KeyError):
            pass

    result["response_time_ms"] = round((time.time() - start) * 1000)
    return jsonify({"success": True, **result, "owner": my_user})


@bp.route("/api/oss/debug/aggregator-health", methods=["GET"])
def api_oss_debug_aggregator_health():
    """Check aggregator API availability and response time."""
    my_user = get_authenticated_user()
    start = time.time()

    result = {
        "configured": bool(AGGREGATOR_API_URL),
        "base_url": AGGREGATOR_API_URL or "(not configured)",
        "reachable": False,
        "response_time_ms": 0,
        "error": None,
    }

    if AGGREGATOR_API_URL:
        data = _call_aggregator("/recon/all-scored-issues")
        result["response_time_ms"] = round((time.time() - start) * 1000)
        if data is not None:
            result["reachable"] = True
        else:
            result["error"] = "Aggregator unreachable or returned error"
    else:
        result["error"] = "AGGREGATOR_API_URL not configured"

    return jsonify({"success": True, **result, "owner": my_user})


@bp.route("/api/oss/debug/state-dump", methods=["GET"])
@require_admin_key
def api_oss_debug_state_dump():
    """Dump all local pipeline state (JSON files) with counts."""
    my_user = get_authenticated_user()

    files = {
        "selected_issues": "selected-issues.json",
        "assignments": "assignments.json",
        "ready_to_submit": "ready-to-submit.json",
        "submitted_prs": "submitted-prs.json",
    }

    state = {}
    counts = {}
    files_on_disk = []

    for key, filename in files.items():
        path = os.path.join(OSS_DATA_DIR, filename)
        if os.path.exists(path):
            files_on_disk.append(filename)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                state[key] = data
                counts[key] = len(data) if isinstance(data, list) else 1
            except (json.JSONDecodeError, OSError):
                state[key] = None
                counts[key] = 0
        else:
            state[key] = []
            counts[key] = 0

    return jsonify({
        "success": True,
        "state": state,
        "counts": counts,
        "files_on_disk": files_on_disk,
        "data_dir": OSS_DATA_DIR,
        "owner": my_user,
    })
