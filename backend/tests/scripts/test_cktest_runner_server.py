"""Tests for the cktest-runner Flask service (scripts/cktest-runner/server.py).

Covers the Phase 0 deliverables:
- Bearer auth on /run (401 when missing/mismatch, /health stays open)
- Semaphore + 503 with Retry-After when busy

Uses Flask's test client; no real subprocess execution. The clone +
install + run path is stubbed via monkeypatch so we exercise the gate
logic without needing toolchains or network.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVER_PATH = _REPO_ROOT / "scripts" / "cktest-runner" / "server.py"


def _load_server(monkeypatch, *, bearer: str = "test-bearer-secret",
                 max_concurrent: int = 1, retry_after_s: int = 60):
    """Fresh module load with our env in place. Done per-test so the
    semaphore + bearer env are isolated; Python module cache would
    otherwise share state across tests."""
    monkeypatch.setenv("CKTEST_RUNNER_BEARER", bearer)
    monkeypatch.setenv("CKTEST_MAX_CONCURRENT", str(max_concurrent))
    monkeypatch.setenv("CKTEST_RETRY_AFTER_S", str(retry_after_s))

    # Force a fresh import — the module reads env at top-level.
    sys.modules.pop("cktest_runner_server", None)
    spec = importlib.util.spec_from_file_location(
        "cktest_runner_server", _SERVER_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def server(monkeypatch):
    return _load_server(monkeypatch)


@pytest.fixture
def client(server):
    server.app.config["TESTING"] = True
    return server.app.test_client()


def test_health_does_not_require_bearer(client):
    """Monitoring should be able to probe /health without the secret —
    standard liveness endpoint convention."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "service": "cktest-runner"}


def test_run_returns_401_when_bearer_header_missing(client):
    resp = client.post("/run", json={
        "fork_slug": "WolffM/x", "branch": "b", "command": "pytest",
    })
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_run_returns_401_when_bearer_mismatched(client):
    resp = client.post(
        "/run",
        json={"fork_slug": "WolffM/x", "branch": "b", "command": "pytest"},
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert resp.status_code == 401


def test_run_returns_401_when_bearer_uses_wrong_scheme(client):
    """Basic-auth header or an opaque token without the `Bearer ` prefix
    should still 401 — the prefix check is part of the contract."""
    resp = client.post(
        "/run",
        json={"fork_slug": "WolffM/x", "branch": "b", "command": "pytest"},
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


def test_run_passes_bearer_check_with_correct_secret(client, monkeypatch, server):
    """Valid bearer → bearer gate passes → input validation runs.
    We feed an invalid command first-token to short-circuit before the
    real subprocess.run path. 400 here proves we got past auth."""
    resp = client.post(
        "/run",
        json={"fork_slug": "WolffM/x", "branch": "b", "command": "rm -rf /"},
        headers={"Authorization": "Bearer test-bearer-secret"},
    )
    # Past auth (would have been 401), past semaphore (would have been
    # 503 if it were held), into validation: first-token "rm" is not
    # in the allowlist.
    assert resp.status_code == 400
    body = resp.get_json()
    assert "allowlist" in body["error"]


def test_run_returns_503_when_semaphore_busy(client, server):
    """Hold the semaphore from outside the request — the next /run
    must return 503 with `Retry-After: 60`. Real concurrency in Flask's
    test client is awkward; instead we acquire the semaphore directly
    and observe the gate's effect."""
    assert server._CONCURRENCY_SEM.acquire(blocking=False)
    try:
        resp = client.post(
            "/run",
            json={"fork_slug": "WolffM/x", "branch": "b", "command": "pytest"},
            headers={"Authorization": "Bearer test-bearer-secret"},
        )
    finally:
        server._CONCURRENCY_SEM.release()

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "60"
    body = resp.get_json()
    assert body["error"] == "runner busy"
    assert body["retry_after_s"] == 60


def test_run_releases_semaphore_after_request(client, server, monkeypatch):
    """Even when the request short-circuits on validation, the semaphore
    must be released — otherwise the second call would 503 forever and
    we'd wedge the runner on the first bad input."""
    headers = {"Authorization": "Bearer test-bearer-secret"}
    payload = {"fork_slug": "WolffM/x", "branch": "b", "command": "rm -rf /"}

    for _ in range(3):
        resp = client.post("/run", json=payload, headers=headers)
        assert resp.status_code == 400  # validation reject — not 503

    # Sanity: semaphore still acquirable (no leak)
    assert server._CONCURRENCY_SEM.acquire(blocking=False)
    server._CONCURRENCY_SEM.release()


def test_run_returns_401_before_consuming_semaphore(client, server):
    """An unauth'd attacker hammering /run shouldn't be able to keep
    the semaphore busy and DoS legitimate workers. Bearer check must
    run before the semaphore acquire."""
    bad_headers = {"Authorization": "Bearer wrong"}
    payload = {"fork_slug": "WolffM/x", "branch": "b", "command": "pytest"}

    for _ in range(5):
        resp = client.post("/run", json=payload, headers=bad_headers)
        assert resp.status_code == 401

    # Semaphore must still be fully acquirable (count == _MAX_CONCURRENT)
    assert server._CONCURRENCY_SEM.acquire(blocking=False)
    server._CONCURRENCY_SEM.release()


def test_run_returns_401_when_server_has_no_bearer_configured(monkeypatch):
    """If the bearer env is unset (e.g., fetch-bearer.sh failed silently
    in some pathological case), /run should fail closed rather than
    accept any header. Server startup also refuses this state in __main__."""
    monkeypatch.delenv("CKTEST_RUNNER_BEARER", raising=False)
    server = _load_server(monkeypatch, bearer="")  # noqa: re-set then clear
    monkeypatch.delenv("CKTEST_RUNNER_BEARER", raising=False)

    server.app.config["TESTING"] = True
    client_ = server.app.test_client()
    resp = client_.post(
        "/run",
        json={"fork_slug": "WolffM/x", "branch": "b", "command": "pytest"},
        headers={"Authorization": "Bearer anything"},
    )
    assert resp.status_code == 401
