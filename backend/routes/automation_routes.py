"""
Automation routes — the public contract hadoku-task consumes.

    GET /automation/presets        the lane vocabularies we publish
    GET /automation/openapi.json   the machine-readable description of both

The lane contracts are fetched rather than pasted so a rename on our side can't
leave a stale copy on theirs. Rationale and the on-disk source of truth are in
`services/automation_presets.py`; the consumer side is hadoku-task's
`worker/src/routes/board-presets.ts`.

Both routes are deliberately unauthenticated — a lane vocabulary is public
information and there is nothing in it to leak — so both paths are listed in
`_PUBLIC_PATHS` in `app.py`, which is what actually admits them past the tier
gate. Adding a route here without adding it there gets you a 401.
"""

import logging

from flask import jsonify, request, current_app

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services.automation_presets import (
        DocumentUnavailable,
        PresetInvalid,
        load_openapi,
        load_presets,
    )
    from ..extensions import limiter
except ImportError:
    from services.automation_presets import (
        DocumentUnavailable,
        PresetInvalid,
        load_openapi,
        load_presets,
    )
    from extensions import limiter


def _serve(document):
    """A cached JSON document with a strong ETag, answering 304 on revalidation.

    The ETag hashes the exact bytes served rather than, say, a file mtime that
    changes on every deploy whether or not the contract did — the steady state
    for a consumer that caches and revalidates should be a 304 with no body.
    """
    response = current_app.response_class(
        document.body, mimetype="application/json")
    response.set_etag(document.etag, weak=False)
    # hadoku-task's own TTL is 5 minutes; matching it keeps any cache in between
    # from holding a staler copy than the consumer would have kept itself.
    response.cache_control.public = True
    response.cache_control.max_age = 300
    return response.make_conditional(request)


@bp.route("/automation/presets", methods=["GET"])
@limiter.limit("60 per minute")
def automation_presets():
    """Publish our activation payloads.

    Failing to build the document is a 503, not an empty `presets` array: they
    keep serving their last good copy on a non-2xx, and "we're broken" should
    not be indistinguishable from "we have no lane sets".
    """
    try:
        document = load_presets()
    except PresetInvalid as exc:
        logger.error("cannot serve automation presets: %s", exc)
        return jsonify({"error": "no publishable automation presets"}), 503
    return _serve(document)


@bp.route("/automation/openapi.json", methods=["GET"])
@limiter.limit("60 per minute")
def automation_openapi():
    """Publish the contract for the route above, and for this one."""
    try:
        document = load_openapi()
    except DocumentUnavailable as exc:
        logger.error("cannot serve the automation OpenAPI document: %s", exc)
        return jsonify({"error": "openapi document unavailable"}), 503
    return _serve(document)
