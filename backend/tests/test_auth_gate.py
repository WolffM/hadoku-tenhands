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
# Service tier, but not on tenhands-write: any other service key in the fleet.
OUTSIDER_KEY = "outsider-key-qrs"
ADMIN_OFF_LIST_KEY = "admin-key-off-list"
_OVERRIDES = json.dumps({
    FRIEND_KEY: "friend",
    SERVICE_KEY: "service",
    OUTSIDER_KEY: {"tier": "service", "member": False},
    ADMIN_OFF_LIST_KEY: {"tier": "admin", "member": False},
})


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


# ---- Writing also needs the tenhands-write list ----


def test_service_key_off_the_list_cannot_write(client):
    # Service tier is every service key in the fleet; the list names who
    # operates tenhands.
    resp = client.post(f"{PREFIX}/api/merge-pr", json={},
                       headers={"X-User-Key": OUTSIDER_KEY})
    assert resp.status_code == 403
    assert resp.get_json().get("required_list") == "tenhands-write"


def test_service_key_off_the_list_can_still_read(client):
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        resp = client.get(f"{PREFIX}/api/owner", headers={"X-User-Key": OUTSIDER_KEY})
    assert resp.status_code not in (401, 403)


def test_admin_off_the_list_is_not_exempt(client):
    resp = client.post(f"{PREFIX}/api/merge-pr", json={},
                       headers={"X-User-Key": ADMIN_OFF_LIST_KEY})
    assert resp.status_code == 403



# ---- whoami is asked about the list, and doubt is not membership ----


class _Resp:
    def __init__(self, body):
        self.status = 200
        self._b = json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _serve(monkeypatch, body):
    import middleware.whoami as w

    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        return _Resp(body)

    monkeypatch.delenv("WHOAMI_TEST_OVERRIDES", raising=False)
    monkeypatch.setattr(w.urllib.request, "urlopen", fake)
    clear_cache()
    return w, calls


def test_whoami_is_asked_about_tenhands_write(monkeypatch):
    w, calls = _serve(monkeypatch, {
        "valid": True, "userType": "service",
        "list": {"id": "tenhands-write", "member": True}})
    assert w.resolve_caller("k1") == ("service", True)
    assert calls[0].full_url.endswith("?list=tenhands-write")


@pytest.mark.parametrize("listed", [
    None,
    {"id": "tenhands-write", "member": False},
    {"id": "tenhands-write", "member": "true"},
    {"id": "scraper-service", "member": True},
])
def test_not_a_member_on_any_doubt(monkeypatch, listed):
    body = {"valid": True, "userType": "service"}
    if listed is not None:
        body["list"] = listed
    w, _ = _serve(monkeypatch, body)
    assert w.resolve_caller(f"k-{listed!r}") == ("service", False)
