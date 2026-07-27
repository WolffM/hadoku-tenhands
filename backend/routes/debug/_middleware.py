"""
Shared middleware for debug routes.

**There is no admin secret here, and there is not meant to be one.** TenHands
is not permitted an admin credential — the `TENHANDS_ADMIN_KEY` vault item was
deleted on purpose — so this gate asks the platform *who the caller is* rather
than comparing them against a key we store. `X-User-Key` is resolved through
`/session/whoami`, the same delegation `app.py`'s tier gate uses, and only an
`admin` tier gets in. We hold nothing; the caller brings their own identity and
the key registry decides what it's worth.

That replaces a gate that compared the request against an `ADMIN_KEY` env var
**only when that var was set**, and admitted everyone when it wasn't. Once the
vault item was deleted the variable was unset in production, so a decorator
named `require_admin_key` was letting every caller through — and the suite
asserted that as intended behaviour, so nothing went red.
"""

from functools import wraps

from flask import request, jsonify

try:
    from ...middleware.whoami import resolve_tier_from_key
except ImportError:
    from middleware.whoami import resolve_tier_from_key


def require_admin(fn):
    """Admit only an admin-tier caller. Fails **closed**.

    A whoami outage resolves to `public`, which is refused — the opposite of
    the gate this replaces, which failed open by construction.

    Statuses mirror `app.py`'s tier gate so the two read alike from outside: no
    key at all is 401 (you're signed out), a key resolving below admin is 403
    (you're signed in and it isn't enough). The resolved tier is echoed on the
    403 because otherwise an under-privileged key is indistinguishable from a
    broken one, and a caller's own tier is not a secret from them.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = (request.headers.get("X-User-Key") or "").strip() or None
        tier = resolve_tier_from_key(key)
        if tier == "admin":
            return fn(*args, **kwargs)
        if not key:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return jsonify({"success": False, "error": "Forbidden", "tier": tier}), 403
    return wrapper
