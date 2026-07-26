"""Tests for `GET /automation/presets` — the lane contract we publish.

Two different jobs here, and the first matters more than the second:

  - **The drift guard.** The lane set we serve has to be the lane set the
    runner implements and the one hadoku-task would accept on commit. If those
    ever disagree, a human picks our preset, activates a board from it, and
    tasks land in lanes nothing claims from. Those tests read the real file on
    disk, not a fixture.
  - **The HTTP contract.** Strong ETag, 304 on revalidation, reachable with no
    key.
"""

import json

import pytest

from app import app
from extensions import limiter
from middleware.whoami import clear_cache
from services import automation_presets
from services.automation_presets import (
    PresetInvalid,
    load_presets,
    validate_lane_set,
)
from temporal.taskauto import selection

PRESETS_PATH = "/tenhands/automation/presets"

GOOD_LANES = [
    {"tag": "triage", "label": "Triage", "order": 0, "editableBy": "user"},
    {"tag": "planning", "label": "Planning", "order": 1, "editableBy": "agent"},
]


@pytest.fixture(autouse=True)
def admit_authed_by_default():
    """Override conftest's admit-all shim — this endpoint is public for real."""
    yield


@pytest.fixture(autouse=True)
def real_whoami(monkeypatch):
    """Keep the gate hermetic: no key resolves to public with no network."""
    monkeypatch.setenv("WHOAMI_TEST_OVERRIDES", json.dumps({"friend-key": "friend"}))
    clear_cache()
    yield
    clear_cache()


@pytest.fixture(autouse=True)
def clear_preset_cache():
    """The document cache is module-level and outlives a test otherwise."""
    automation_presets.clear_caches()
    yield
    automation_presets.clear_caches()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c
    limiter.enabled = True


# ---- The contract we actually ship ----------------------------------------


def test_shipped_schemas_are_publishable():
    """Every payload in docs/.../schemas is one hadoku-task would accept.

    This is the test that fails when someone edits a lane set by hand and gets
    it subtly wrong — before the endpoint starts dropping it in production.
    """
    presets = json.loads(load_presets().body)["presets"]
    assert presets
    for preset in presets:
        validate_lane_set(preset["lanes"])


def test_autoland_lanes_match_the_lanes_the_runner_claims_from():
    """The published vocabulary is the one `selection.py` implements.

    Advertising a lane the runner has no constant for means a task can rest
    somewhere nothing ever picks it up.
    """
    autoland = _preset_by_schema_id("autoland")
    served = {lane["tag"] for lane in autoland["lanes"]}
    implemented = {
        selection.LANE_PLANNING,
        selection.LANE_PLAN_REVIEW,
        selection.LANE_REPLAN,
        selection.LANE_APPROVED,
        selection.LANE_WORKING,
        selection.LANE_LANDING,
        selection.LANE_LANDED,
        selection.LANE_STALLED,
    }
    assert served == implemented


def test_repo_is_stripped_but_the_human_facing_fields_survive():
    """`repo` is per-board; label/description are what a human picks from."""
    autoland = _preset_by_schema_id("autoland")
    assert "repo" not in autoland
    # Not pinned to a number: the version is meant to move when the lane set
    # changes shape, and a test that has to be edited alongside it teaches
    # people to edit tests rather than to think about the bump.
    assert isinstance(autoland["schemaVersion"], int)
    assert autoland["schemaVersion"] >= 1
    assert autoland["label"]
    assert autoland["description"]


def _preset_by_schema_id(schema_id):
    presets = json.loads(load_presets().body)["presets"]
    matches = [p for p in presets if p["schemaId"] == schema_id]
    assert matches, f"no preset with schemaId {schema_id!r}"
    return matches[0]


# ---- HTTP contract ---------------------------------------------------------


def test_presets_are_public(client):
    """hadoku-task fetches with no credential — a 401 here breaks the picker."""
    assert client.get(PRESETS_PATH).status_code == 200


def test_response_is_the_documented_envelope(client):
    resp = client.get(PRESETS_PATH)
    assert resp.mimetype == "application/json"
    body = json.loads(resp.data)
    assert isinstance(body["presets"], list) and body["presets"]
    assert {"schemaId", "lanes"} <= set(body["presets"][0])


def test_etag_is_strong_and_hashes_the_body(client):
    resp = client.get(PRESETS_PATH)
    etag = resp.headers["ETag"]
    assert not etag.startswith("W/"), "a weak validator defeats the point"
    assert etag == f'"{load_presets().etag}"'


def test_matching_if_none_match_is_a_304_with_no_body(client):
    etag = client.get(PRESETS_PATH).headers["ETag"]
    resp = client.get(PRESETS_PATH, headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.data == b""
    assert resp.headers["ETag"] == etag


def test_stale_if_none_match_gets_the_full_body(client):
    resp = client.get(PRESETS_PATH, headers={"If-None-Match": '"not-our-etag"'})
    assert resp.status_code == 200
    assert json.loads(resp.data)["presets"]


def test_broken_schemas_are_a_503_not_an_empty_list(client, monkeypatch, tmp_path):
    """"We're broken" must not be indistinguishable from "we have no lanes"."""
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)
    resp = client.get(PRESETS_PATH)
    assert resp.status_code == 503
    assert "presets" not in json.loads(resp.data)


# ---- Loading ---------------------------------------------------------------


def test_one_broken_file_does_not_take_down_the_good_ones(monkeypatch, tmp_path):
    (tmp_path / "good.json").write_text(json.dumps(
        {"schemaId": "good", "schemaVersion": 1, "lanes": GOOD_LANES}))
    (tmp_path / "broken.json").write_text(json.dumps(
        {"schemaId": "broken", "lanes": [{"tag": "x"}]}))
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)

    presets = json.loads(load_presets().body)["presets"]
    assert [p["schemaId"] for p in presets] == ["good"]


def test_no_usable_payload_raises(monkeypatch, tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)
    with pytest.raises(PresetInvalid):
        load_presets()


def test_edited_schema_is_picked_up_without_a_restart(monkeypatch, tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(
        {"schemaId": "good", "schemaVersion": 1, "lanes": GOOD_LANES}))
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)
    before = load_presets()

    relabelled = [dict(GOOD_LANES[0], label="Inbox"), GOOD_LANES[1]]
    path.write_text(json.dumps(
        {"schemaId": "good", "schemaVersion": 1, "lanes": relabelled}))
    after = load_presets()

    assert after.etag != before.etag
    assert json.loads(after.body)["presets"][0]["lanes"][0]["label"] == "Inbox"


def test_identical_content_keeps_the_same_etag(monkeypatch, tmp_path):
    """A redeploy that changes nothing must still answer 304."""
    payload = json.dumps({"schemaId": "good", "schemaVersion": 1, "lanes": GOOD_LANES})
    (tmp_path / "good.json").write_text(payload)
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)
    first = load_presets()

    automation_presets.clear_caches()
    (tmp_path / "good.json").write_text(payload)
    assert load_presets().etag == first.etag


# ---- validate_lane_set: hadoku-task's rules, ported ------------------------


@pytest.mark.parametrize("lanes, why", [
    ([], "empty"),
    ("planning", "not a list"),
    ([{"label": "L", "order": 0, "editableBy": "user"}], "no tag"),
    ([{"tag": "", "label": "L", "order": 0, "editableBy": "user"}], "empty tag"),
    ([{"tag": "plan review", "label": "L", "order": 0, "editableBy": "user"}],
     "whitespace in tag — a tag column is space-separated"),
    ([{"tag": "a", "label": "A", "order": 0, "editableBy": "user"},
      {"tag": "a", "label": "B", "order": 1, "editableBy": "user"}], "duplicate tag"),
    ([{"tag": "a", "order": 0, "editableBy": "user"}], "no label"),
    ([{"tag": "a", "label": "", "order": 0, "editableBy": "user"}], "empty label"),
    ([{"tag": "a", "label": "A", "editableBy": "user"}], "no order"),
    ([{"tag": "a", "label": "A", "order": "0", "editableBy": "user"}], "string order"),
    ([{"tag": "a", "label": "A", "order": True, "editableBy": "user"}], "bool order"),
    ([{"tag": "a", "label": "A", "order": 0, "editableBy": "robot"}], "bad editableBy"),
    ([{"tag": "a", "label": "A", "order": 0}], "no editableBy"),
    ([{"tag": "a", "label": "A", "order": 0, "editableBy": "user"},
      {"tag": "b", "label": "B", "order": 0, "editableBy": "user"}], "duplicate order"),
])
def test_validate_lane_set_rejects(lanes, why):
    with pytest.raises(PresetInvalid):
        validate_lane_set(lanes)


def test_validate_lane_set_accepts_extra_keys():
    """Unknown lane keys are preserved verbatim on their side — ours carry
    `description`, and rejecting them would mean dropping our own preset."""
    validate_lane_set([dict(GOOD_LANES[0], description="Untagged capture.")])
