"""
Shared Flask extensions — initialized here, attached to app in app.py.

Avoids circular imports between app.py and route modules.
"""

from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _client_key() -> str:
    """Rate-limit bucket key = the real client, not the tunnel.

    The backend is reachable only through the cloudflared tunnel, so
    `remote_addr` is the tunnel's local connection for EVERY caller — keying on
    it would put all clients in one shared bucket, letting a single caller
    exhaust a limit for everyone. Cloudflare stamps the real client IP in
    `CF-Connecting-IP` (trustworthy here because the only inbound path is via
    Cloudflare), so bucket on that, falling back to remote_addr off-tunnel.
    """
    return request.headers.get("CF-Connecting-IP") or get_remote_address()


limiter = Limiter(
    _client_key,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
