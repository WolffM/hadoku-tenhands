"""The hadoku health contract (v1): /health and its /tenhands/api/healthcheck alias."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app import app
from extensions import limiter

REPO_DIR = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def client():
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c
    limiter.enabled = True


@pytest.mark.parametrize("path", ["/health", "/tenhands/api/healthcheck"])
def test_health_body(client, path):
    head = subprocess.run(
        ["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        resp = client.get(path)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["service"] == "tenhands"
    assert body["commit"] == head
    assert "commit_error" not in body
    assert body["owner"] == "WolffM"


def test_alias_is_identical(client):
    with patch("routes.health_routes.get_authenticated_user", return_value="WolffM"):
        a = client.get("/health").get_json()
        b = client.get("/tenhands/api/healthcheck").get_json()
    assert a == b


def test_unreadable_commit_is_null_with_reason(tmp_path):
    from routes import health_routes

    with patch.object(health_routes, "_REPO_DIR", tmp_path):
        commit, error = health_routes._read_commit()
    assert commit is None
    assert "rev-parse" in error
