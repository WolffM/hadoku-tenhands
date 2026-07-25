"""
Automation preset routes — `GET /automation/presets`.

The lane contracts this repo publishes, so hadoku-task can fetch them at
activation time instead of a human pasting a copy that goes stale. Rationale
and the on-disk source of truth are in `services/automation_presets.py`;
the consumer side is hadoku-task's `worker/src/routes/board-presets.ts`.

Deliberately unauthenticated — a lane vocabulary is public information and
there is nothing in it to leak — so the path is listed in `_PUBLIC_PATHS` in
`app.py`, which is what actually admits it past the tier gate. Adding a route
here without adding it there gets you a 401.
"""

import logging

from flask import jsonify, request, current_app

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services.automation_presets import load_presets, PresetInvalid
    from ..extensions import limiter
except ImportError:
    from services.automation_presets import load_presets, PresetInvalid
    from extensions import limiter


@bp.route("/automation/presets", methods=["GET"])
@limiter.limit("60 per minute")
def automation_presets():
    """Publish our activation payloads, with a strong ETag.

    hadoku-task caches the response for 5 minutes and then revalidates with
    `If-None-Match`, so the steady state is a 304 with no body — which is why
    the ETag hashes the exact bytes served rather than, say, a file mtime that
    changes on every deploy whether or not the contract did.

    Failing to build the document is a 503, not an empty `presets` array: they
    keep serving their last good copy on a non-2xx, and "we're broken" should
    not be indistinguishable from "we have no lane sets".
    """
    try:
        document = load_presets()
    except PresetInvalid as exc:
        logger.error("cannot serve automation presets: %s", exc)
        return jsonify({"error": "no publishable automation presets"}), 503

    response = current_app.response_class(
        document.body, mimetype="application/json")
    response.set_etag(document.etag, weak=False)
    # Their TTL is 5 minutes; matching it here keeps any cache in between from
    # holding a staler copy than the consumer would have kept itself.
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response.make_conditional(request)
