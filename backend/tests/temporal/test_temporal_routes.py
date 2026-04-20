"""Route tests for routes/temporal_routes.py — Phase 1D.4.

Drives the Flask blueprint with a test client. Reads/writes go directly
against a temp evidence directory — no Temporal cluster needed for the
read endpoints. The dispatch + signal endpoints are tested with the
async helpers monkeypatched to capture inputs without hitting Temporal.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Mount the existing app and point the routes at a temp state dir.

    Routes read CRIMSON_STATE_ROOT lazily (per-request), so monkeypatching
    the env var here is sufficient — no module reload needed.
    """
    monkeypatch.setenv("CRIMSON_STATE_ROOT", str(tmp_path / "state"))

    # Import once to populate the shared Blueprint with route handlers.
    import routes  # noqa: F401  (registers handlers on the bp blueprint)

    from flask import Flask

    from routes import bp

    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/dispatch")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def state_root(tmp_path) -> Path:
    return tmp_path / "state"


# ── seed helpers ──────────────────────────────────────────────────────────


def _seed_issue(
    state_root: Path,
    batch_id: str,
    issue_id: str,
    *,
    transitions=None,
    gates=None,
    inbox=None,
    events=None,
):
    issue_dir = state_root / batch_id / issue_id
    issue_dir.mkdir(parents=True, exist_ok=True)
    if transitions is not None:
        with (issue_dir / "transitions.jsonl").open("w") as f:
            for t in transitions:
                f.write(json.dumps(t) + "\n")
    if gates is not None:
        with (issue_dir / "gates.jsonl").open("w") as f:
            for g in gates:
                f.write(json.dumps(g) + "\n")
    if events is not None:
        with (issue_dir / "events.jsonl").open("w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
    if inbox is not None:
        (issue_dir / "awaiting").mkdir(parents=True, exist_ok=True)
        (issue_dir / "awaiting" / "inbox_entry.json").write_text(json.dumps(inbox))


# ── 1. /api/temporal/health ───────────────────────────────────────────────


def test_health_returns_envelope(client, state_root):
    state_root.mkdir(parents=True, exist_ok=True)
    resp = client.get("/dispatch/api/temporal/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "state_root" in body["data"]
    assert body["data"]["batch_count"] == 0


# ── 2. /api/temporal/batches ──────────────────────────────────────────────


def test_batches_empty_when_no_state(client):
    resp = client.get("/dispatch/api/temporal/batches")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["batches"] == []


def test_batches_lists_seeded_batches(client, state_root):
    _seed_issue(state_root, "batch-a", "issue-1", transitions=[{"from": "candidate", "to": "eligible"}])
    _seed_issue(state_root, "batch-a", "issue-2", transitions=[])
    _seed_issue(state_root, "batch-b", "issue-3", transitions=[])

    resp = client.get("/dispatch/api/temporal/batches")
    body = resp.get_json()
    batches = {b["batch_id"]: b["issue_count"] for b in body["data"]["batches"]}
    assert batches == {"batch-a": 2, "batch-b": 1}


# ── 3. /api/temporal/batch/<batch_id> ─────────────────────────────────────


def test_batch_404_when_missing(client):
    resp = client.get("/dispatch/api/temporal/batch/nope")
    assert resp.status_code == 404


def test_batch_returns_issue_summaries(client, state_root):
    _seed_issue(
        state_root, "batch-a", "issue-1",
        transitions=[
            {"from": "candidate", "to": "eligible", "ts": "t0"},
            {"from": "eligible", "to": "forked", "ts": "t1"},
        ],
        gates=[{"gate": "eligibility", "verdict": "pass"}],
    )
    resp = client.get("/dispatch/api/temporal/batch/batch-a")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["batch_id"] == "batch-a"
    assert data["issue_count"] == 1
    assert data["issues"][0]["current_state"] == "forked"
    assert data["issues"][0]["transition_count"] == 2
    assert data["issues"][0]["is_deferred"] is False


# ── 4. /api/temporal/issue/<batch>/<issue> ────────────────────────────────


def test_issue_404_when_missing(client):
    resp = client.get("/dispatch/api/temporal/issue/none/none")
    assert resp.status_code == 404


def test_issue_returns_full_evidence(client, state_root):
    _seed_issue(
        state_root, "batch-a", "issue-1",
        transitions=[
            {"from": "candidate", "to": "eligible", "ts": "t0"},
            {"from": "eligible", "to": "forked", "ts": "t1"},
        ],
        gates=[
            {"gate": "eligibility", "verdict": "pass"},
            {"gate": "input_context_clean", "verdict": "pass"},
        ],
        events=[{"event": "human_comment", "user": "alice"}],
    )
    resp = client.get("/dispatch/api/temporal/issue/batch-a/issue-1")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["current_state"] == "forked"
    assert len(data["transitions"]) == 2
    assert len(data["gates"]) == 2
    assert len(data["events"]) == 1


# ── 5. /api/temporal/inbox ────────────────────────────────────────────────


def test_inbox_empty_when_no_defers(client):
    resp = client.get("/dispatch/api/temporal/inbox")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["count"] == 0


def test_inbox_lists_deferred_issues(client, state_root):
    _seed_issue(
        state_root, "batch-a", "issue-1",
        transitions=[{"from": "candidate", "to": "fixed", "ts": "t"}],
        inbox={
            "state": "fixed",
            "gate": "relevance",
            "reason": "borderline 0.55",
            "score": 0.55,
            "upstream_slug": "microsoft/markitdown",
            "issue_number": 183,
            "queued_at": "t",
        },
    )
    _seed_issue(
        state_root, "batch-a", "issue-2",
        transitions=[],
        # No inbox file → not deferred
    )

    resp = client.get("/dispatch/api/temporal/inbox")
    data = resp.get_json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["issue_id"] == "issue-1"
    assert data["items"][0]["gate"] == "relevance"
    assert data["items"][0]["score"] == 0.55


def test_inbox_skips_resolved_entries(client, state_root):
    _seed_issue(
        state_root, "batch-a", "issue-1",
        inbox={"state": "fixed", "gate": "relevance"},
    )
    # Mark resolved
    (state_root / "batch-a" / "issue-1" / "awaiting" / "resolved").touch()

    resp = client.get("/dispatch/api/temporal/inbox")
    assert resp.get_json()["data"]["count"] == 0


# ── 6. /api/temporal/dispatch (POST) ──────────────────────────────────────


def test_dispatch_validates_input(client):
    resp = client.post(
        "/dispatch/api/temporal/dispatch",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_dispatch_calls_temporal_client(client, monkeypatch):
    """Mock the asyncio dispatch helper to capture inputs without a cluster."""
    captured = {}

    async def fake_dispatch(batch_id, issues_raw, max_concurrency=2):
        captured["batch_id"] = batch_id
        captured["issues_raw"] = issues_raw
        captured["max_concurrency"] = max_concurrency
        return {
            "batch_id": batch_id,
            "workflow_id": f"batch-{batch_id}",
            "issue_count": len(issues_raw),
            "max_concurrency": max_concurrency,
        }

    import routes.temporal_routes as tr
    monkeypatch.setattr(tr, "_dispatch_batch", fake_dispatch)

    resp = client.post(
        "/dispatch/api/temporal/dispatch",
        data=json.dumps({
            "batch_id": "test-batch",
            "issues": [
                {"upstream_slug": "microsoft/markitdown", "issue_number": 183, "raw_brief": "fix it"},
            ],
            "max_concurrency": 3,
        }),
        content_type="application/json",
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["workflow_id"] == "batch-test-batch"
    assert body["data"]["max_concurrency"] == 3
    assert captured["batch_id"] == "test-batch"
    assert len(captured["issues_raw"]) == 1
    assert captured["max_concurrency"] == 3


def test_dispatch_defaults_max_concurrency_to_2(client, monkeypatch):
    """Omitting max_concurrency defaults to 2 — the Copilot coding-agent cap."""
    captured = {}

    async def fake_dispatch(batch_id, issues_raw, max_concurrency=2):
        captured["max_concurrency"] = max_concurrency
        return {"batch_id": batch_id, "workflow_id": "x", "issue_count": 1, "max_concurrency": max_concurrency}

    import routes.temporal_routes as tr
    monkeypatch.setattr(tr, "_dispatch_batch", fake_dispatch)

    client.post(
        "/dispatch/api/temporal/dispatch",
        data=json.dumps({
            "batch_id": "b",
            "issues": [{"upstream_slug": "a/b", "issue_number": 1}],
        }),
        content_type="application/json",
    )
    assert captured["max_concurrency"] == 2


# ── 7. /api/temporal/issue/<workflow_id>/signal (POST) ────────────────────


def test_signal_rejects_invalid_decision(client):
    resp = client.post(
        "/dispatch/api/temporal/issue/wf-1/signal",
        data=json.dumps({"decision": "maybe"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_signal_calls_temporal_client(client, monkeypatch):
    captured = {}

    async def fake_send(workflow_id, decision):
        captured["workflow_id"] = workflow_id
        captured["decision"] = decision

    import routes.temporal_routes as tr
    monkeypatch.setattr(tr, "_send_signal", fake_send)

    resp = client.post(
        "/dispatch/api/temporal/issue/issue-183/signal",
        data=json.dumps({"decision": "approve"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert captured == {"workflow_id": "issue-183", "decision": "approve"}
