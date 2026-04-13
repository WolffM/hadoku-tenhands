"""Flask blueprint for crimson-kitty (temporal pipeline).

Routes (see docs/crimson-kitty/pipeline-config.md):

    GET  /dispatch/api/temporal/batches
    GET  /dispatch/api/temporal/batch/<id>
    GET  /dispatch/api/temporal/inbox
    GET  /dispatch/api/temporal/issue/<slug>/<number>
    POST /dispatch/api/temporal/issue/<slug>/<number>/signal
    POST /dispatch/api/temporal/dispatch
    GET  /dispatch/api/temporal/health

Not yet wired into routes/__init__.py — Phase 1 deliverable.

Pseudocode:

    from flask import Blueprint, request, jsonify
    from temporalio.client import Client

    from ..temporal.config import load_config

    bp = Blueprint("temporal", __name__, url_prefix="/api/temporal")

    @bp.get("/batches")
    def list_batches():
        # Read state/ directory + Temporal workflow list, merge.
        ...

    @bp.post("/issue/<slug>/<int:number>/signal")
    def signal_issue(slug, number):
        decision = request.json["decision"]  # approve | abort | retry
        client = await Client.connect(load_config().host)
        handle = client.get_workflow_handle(f"issue-{slug}-{number}")
        await handle.signal(IssueWorkflow.submit_human_decision, decision)
        return jsonify({"success": True})
"""
