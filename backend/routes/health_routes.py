"""
Health routes - healthcheck and owner identity endpoints.
"""

from flask import jsonify

from . import bp

try:
    from ..services import get_authenticated_user
except ImportError:
    from services import get_authenticated_user


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
