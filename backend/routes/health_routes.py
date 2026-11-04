"""
Health routes - healthcheck and owner identity endpoints.

The health body follows the hadoku health contract (v1): ``status: "ok"``,
``service`` (this app's id in hadoku_site scripts/child-apps.json) and
``commit`` (the sha of the running code). It is served at ``/health`` and,
for the probes that still use it, ``/tenhands/api/healthcheck``.
"""

import logging
import subprocess
from pathlib import Path

from flask import jsonify

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import get_authenticated_user
except ImportError:
    from services import get_authenticated_user

SERVICE_ID = "tenhands"

# The repo checkout this module runs from — the deploy resets it to the pushed sha.
_REPO_DIR = Path(__file__).resolve().parent.parent.parent


def _read_commit() -> tuple[str | None, str | None]:
    """The running checkout's HEAD, or (None, why) when it cannot be read."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git rev-parse HEAD failed: {exc}"
    if out.returncode != 0:
        return None, f"git rev-parse HEAD exited {out.returncode}: {out.stderr.strip()}"
    return out.stdout.strip(), None


# Read ONCE at startup: the sha of the code this process loaded, not of
# whatever the checkout holds by the time someone asks.
COMMIT, COMMIT_ERROR = _read_commit()
if COMMIT_ERROR:
    logger.warning("health: commit unknown (%s)", COMMIT_ERROR)


def health_response():
    """The contract body: always 200 — tenhands has no dependency it waits on."""
    body = {
        "success": True,
        "status": "ok",
        "service": SERVICE_ID,
        "commit": COMMIT,
        "owner": get_authenticated_user(),
        "apiVersion": "2.0.0",
    }
    if COMMIT_ERROR:
        body["commit_error"] = COMMIT_ERROR
    return jsonify(body)


@bp.route("/api/healthcheck", methods=["GET"])
def api_healthcheck():
    """Health check endpoint for monitoring (alias of ``/health``)."""
    return health_response()


@bp.route("/api/owner", methods=["GET"])
def api_owner():
    """Get the authenticated GitHub owner/user."""
    owner = get_authenticated_user()
    return jsonify({"success": True, "owner": owner})
