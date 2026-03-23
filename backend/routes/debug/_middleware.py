"""
Shared middleware for debug routes.
"""

import os
from functools import wraps

from flask import request, jsonify


def require_admin_key(fn):
    """Gate debug endpoints behind ADMIN_KEY when set.

    When ADMIN_KEY env var is set, requests must provide the key via
    X-Admin-Key header or admin_key query param. When unset (local dev),
    no gating — zero friction.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        admin_key = os.environ.get("ADMIN_KEY")
        if admin_key:
            provided = request.headers.get("X-Admin-Key") or request.args.get("admin_key")
            if provided != admin_key:
                return jsonify({"success": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper
