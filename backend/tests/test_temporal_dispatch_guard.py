"""Tests for the demo/preview brake on POST /api/temporal/dispatch.

Two invariants:
  1. `demo-` batches and the sandbox allowlist are mutually exclusive — a demo
     batch may only target sandbox repos, and sandbox repos may only be
     dispatched in a demo batch.
  2. A demo batch forces `submit_to_upstream=False` on every issue, and a
     batch-level `submit_to_upstream` is honored (the bug retry_aborted.py hit
     when the route silently dropped it).

The guard rejects before any Temporal connection, so the 400 cases need no
cluster; the pass-through cases mock `_dispatch_batch` to capture the flags.
"""

import pytest

import routes.temporal_routes as tr
from app import app
from extensions import limiter

PREFIX = "/tenhands"
SANDBOX = "WolffM/tenhands-demo-target"


@pytest.fixture
def client(monkeypatch):
    app.config["TESTING"] = True
    limiter.enabled = False
    monkeypatch.setenv("CRIMSON_DEMO_REPOS", SANDBOX)
    with app.test_client() as c:
        yield c
    limiter.enabled = True


@pytest.fixture
def captured(monkeypatch):
    """Replace _dispatch_batch with a recorder so pass-through cases assert the
    resolved submit flags without needing a Temporal cluster."""
    calls = {}

    async def fake_dispatch(batch_id, issues_raw, submit_flags=None):
        calls["batch_id"] = batch_id
        calls["issues_raw"] = issues_raw
        calls["submit_flags"] = submit_flags
        return {"batch_id": batch_id, "workflow_id": f"batch-{batch_id}",
                "issue_count": len(issues_raw)}

    monkeypatch.setattr(tr, "_dispatch_batch", fake_dispatch)
    return calls


def _issue(slug, n=1):
    return {"upstream_slug": slug, "issue_number": n}


def test_demo_batch_rejects_non_sandbox_repo(client):
    resp = client.post(f"{PREFIX}/api/temporal/dispatch", json={
        "batch_id": "demo-20260812-0900",
        "issues": [_issue("microsoft/markitdown", 183)],
    })
    assert resp.status_code == 400
    assert "sandbox" in resp.get_json()["error"]


def test_non_demo_batch_rejects_sandbox_repo(client):
    resp = client.post(f"{PREFIX}/api/temporal/dispatch", json={
        "batch_id": "crimson-kitty-real",
        "issues": [_issue(SANDBOX, 1)],
    })
    assert resp.status_code == 400
    assert "demo-" in resp.get_json()["error"]


def test_demo_batch_forces_preview_only(client, captured):
    resp = client.post(f"{PREFIX}/api/temporal/dispatch", json={
        "batch_id": "demo-20260812-0900",
        # Even an explicit request to submit upstream is overridden to False.
        "submit_to_upstream": True,
        "issues": [_issue(SANDBOX, 1), _issue(SANDBOX, 2)],
    })
    assert resp.status_code == 202
    assert captured["submit_flags"] == [False, False]


def test_batch_level_submit_flag_is_honored(client, captured):
    # retry_aborted.py sends {"submit_to_upstream": False} at the batch level;
    # the route used to drop it. It must reach every issue now.
    resp = client.post(f"{PREFIX}/api/temporal/dispatch", json={
        "batch_id": "crimson-kitty-real",
        "submit_to_upstream": False,
        "issues": [_issue("microsoft/markitdown", 183)],
    })
    assert resp.status_code == 202
    assert captured["submit_flags"] == [False]


def test_default_batch_submits_upstream(client, captured):
    resp = client.post(f"{PREFIX}/api/temporal/dispatch", json={
        "batch_id": "crimson-kitty-real",
        "issues": [_issue("microsoft/markitdown", 183)],
    })
    assert resp.status_code == 202
    assert captured["submit_flags"] == [True]
