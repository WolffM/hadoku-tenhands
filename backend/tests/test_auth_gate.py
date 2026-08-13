"""Tests for the global tier gate (``app._enforce_tier``).

The tunnel origin (``dispatch.hadoku.me``) is publicly routable, so the app
gates itself via whoami-delegation. These tests exercise the REAL gate — they
override the ``admit_authed_by_default`` shim from conftest and drive tier
resolution with ``WHOAMI_TEST_OVERRIDES`` so no network call happens.
"""

import json
from unittest.mock import patch

import pytest

from app import app
from extensions import limiter
from middleware.whoami import clear_cache

PREFIX = "/tenhands"
FRIEND_KEY = "friend-key-abc"
SERVICE_KEY = "service-key-xyz"
_OVERRIDES = json.dumps({FRIEND_KEY: "friend", SERVICE_KEY: "service"})


@pytest.fixture(autouse=True)
def admit_authed_by_default():
    """Override conftest's admit-all shim: this module tests the real gate."""
    yield


@pytest.fixture(autouse=True)
def real_whoami(monkeypatch):
    """Drive tier resolution from WHOAMI_TEST_OVERRIDES, not the network."""
    monkeypatch.setenv("WHOAMI_TEST_OVERRIDES", _OVERRIDES)
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c
    limiter.enabled = True


# ---- Exempt paths stay reachable with no key (monitoring probe) ----


def test_root_is_public(client):
    assert client.get("/").status_code == 200


def test_healthcheck_is_public(client):
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        assert client.get(f"{PREFIX}/api/healthcheck").status_code == 200


# ---- Gated routes reject unauthenticated / unprivileged callers ----


def test_no_key_is_401(client):
    assert client.get(f"{PREFIX}/api/owner").status_code == 401


def test_unrecognized_key_is_403(client):
    resp = client.get(f"{PREFIX}/api/owner", headers={"X-User-Key": "bogus"})
    assert resp.status_code == 403


def test_mutating_route_blocked_without_key(client):
    # The whole reason for this gate: unauthenticated POSTs must not reach the
    # gh-mutating handlers (merge-pr, submit-to-origin, ...).
    resp = client.post(f"{PREFIX}/api/merge-pr", json={})
    assert resp.status_code == 401


# ---- Two-tier access: friend reads, service operates ----


def test_friend_can_read(client):
    # A friend key clears the read floor — the dashboard loads.
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        resp = client.get(f"{PREFIX}/api/owner", headers={"X-User-Key": FRIEND_KEY})
    assert resp.status_code not in (401, 403)


def test_friend_cannot_write(client):
    # A friend key is below the service floor for mutations — look, don't touch.
    resp = client.post(f"{PREFIX}/api/merge-pr", json={},
                       headers={"X-User-Key": FRIEND_KEY})
    assert resp.status_code == 403
    assert resp.get_json().get("required_tier") == "service"


def test_service_can_write(client):
    # A service key clears the write floor — the gate lets the request through
    # to the handler (which may then fail for its own reasons, e.g. a 400 on the
    # empty body, but the gate itself must not 401/403).
    resp = client.post(f"{PREFIX}/api/merge-pr", json={},
                       headers={"X-User-Key": SERVICE_KEY})
    assert resp.status_code not in (401, 403)


def test_service_can_read(client):
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        resp = client.get(f"{PREFIX}/api/owner", headers={"X-User-Key": SERVICE_KEY})
    assert resp.status_code not in (401, 403)
