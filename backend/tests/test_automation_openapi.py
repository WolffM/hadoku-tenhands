"""The OpenAPI document must describe the app, not a memory of it.

hadoku-task's spec is generated from their zod schemas, so it cannot drift.
Ours is hand-written — Flask has no schema layer to generate from — so the
guard has to be a test, and it has to run in both directions:

  - **every documented path exists** in the Flask URL map, with the documented
    method. Catches a spec that outlived a rename.
  - **every automation route is documented.** Catches the more likely failure:
    a route added with `@bp.route` and nothing else, which silently drops out
    of the contract and surfaces as drift at a consumer's runtime.

Then the part a path list can't check: a real response, validated against the
schema the document promises. Modelled on hadoku-task's `openapi-verify.ts`,
which exists for the same reason and guards the other end of this integration.
"""

import json

import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate as validate_openapi
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from app import app
from extensions import limiter
from middleware.whoami import clear_cache
from services import automation_presets
from services.automation_presets import load_openapi, load_presets

PREFIX = "/tenhands"
PRESETS_PATH = f"{PREFIX}/automation/presets"
OPENAPI_PATH = f"{PREFIX}/automation/openapi.json"

#: Every route this document is responsible for. A new one belongs here and in
#: the spec at the same time — that pairing is the whole point of the file.
DOCUMENTED_ROUTES = {
    ("/automation/presets", "get"),
    ("/automation/openapi.json", "get"),
}

#: The spec is registered under a URI so `#/components/...` pointers in the
#: wrapper schemas resolve against the document rather than against themselves.
_SPEC_URI = "urn:tenhands-automation-openapi"


@pytest.fixture(autouse=True)
def admit_authed_by_default():
    """Override conftest's admit-all shim — these endpoints are public for real."""
    yield


@pytest.fixture(autouse=True)
def real_whoami(monkeypatch):
    monkeypatch.setenv("WHOAMI_TEST_OVERRIDES", json.dumps({"friend-key": "friend"}))
    clear_cache()
    yield
    clear_cache()


@pytest.fixture(autouse=True)
def clear_document_cache():
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


@pytest.fixture
def spec():
    return json.loads(load_openapi().body)


def _validator(spec, schema_ref):
    """A validator for one component schema, with `$ref`s resolved against the spec.

    The dialect is stated rather than sniffed: an OpenAPI 3.1 document has no
    `$schema` key to detect, but its schemas *are* JSON Schema 2020-12.
    """
    registry = Registry().with_resource(_SPEC_URI, DRAFT202012.create_resource(spec))
    return Draft202012Validator({"$ref": f"{_SPEC_URI}{schema_ref}"}, registry=registry)


# ---- The document is a document -------------------------------------------


def test_spec_is_a_valid_openapi_31_document(spec):
    """Checked against the real meta-spec, not just "it parses".

    Catches the structural mistakes the assertions below would sail past: a
    `$ref` pointing at nothing, a response missing its `description`, a
    parameter in a place parameters can't go.
    """
    validate_openapi(spec)
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] and spec["info"]["version"]


def test_every_component_schema_is_itself_valid_json_schema(spec):
    """A malformed schema would make every check below vacuously pass."""
    for name, schema in spec["components"]["schemas"].items():
        Draft202012Validator.check_schema(schema)
        assert schema.get("type"), f"{name} has no type"


def test_server_is_the_url_we_handed_hadoku_task(spec):
    urls = [s["url"] for s in spec["servers"]]
    assert "https://dispatch.hadoku.me/tenhands" in urls
    for url in urls:
        assert url.startswith("https://"), \
            "a preset drives a destructive migration — http can be rewritten in transit"


# ---- Drift, both directions ------------------------------------------------


def _flask_automation_routes():
    """Every automation route Flask actually serves, as (path, method) pairs."""
    found = set()
    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if not path.startswith(f"{PREFIX}/automation/"):
            continue
        for method in rule.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            found.add((path[len(PREFIX):], method.lower()))
    return found


def test_documented_paths_all_exist(spec):
    served = _flask_automation_routes()
    documented = {(path, method)
                  for path, ops in spec["paths"].items()
                  for method in ops}
    assert documented <= served, \
        f"documented but not served: {sorted(documented - served)}"


def test_served_routes_are_all_documented(spec):
    served = _flask_automation_routes()
    documented = {(path, method)
                  for path, ops in spec["paths"].items()
                  for method in ops}
    assert served <= documented, \
        f"served but undocumented: {sorted(served - documented)}"


def test_the_route_list_this_file_pins_is_the_one_flask_serves():
    """Guards the guard: keeps DOCUMENTED_ROUTES from quietly emptying out."""
    assert _flask_automation_routes() == DOCUMENTED_ROUTES


def test_documented_status_codes_are_the_ones_we_can_return(spec):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            codes = set(op["responses"])
            assert {"200", "304", "503"} <= codes, f"{method} {path}: {codes}"
            assert op["security"] == [], \
                f"{method} {path} is public — an empty security list says so"


# ---- The response actually matches the schema ------------------------------


def test_live_preset_response_validates_against_the_document(client, spec):
    body = json.loads(client.get(PRESETS_PATH).data)
    _validator(spec, "#/components/schemas/PresetDocument").validate(body)


def test_shipped_payloads_validate_against_the_preset_schema(spec):
    """The files in schemas/ are what activation gets — check them, not a fixture."""
    validator = _validator(spec, "#/components/schemas/AutomationPreset")
    for preset in json.loads(load_presets().body)["presets"]:
        validator.validate(preset)


def test_lane_schema_rejects_what_our_validator_rejects(spec):
    """The two guards agree on a lane, so neither is quietly weaker."""
    validator = _validator(spec, "#/components/schemas/Lane")
    validator.validate({"tag": "planning", "label": "Planning",
                        "order": 0, "editableBy": "agent"})
    for bad in (
        {"tag": "plan review", "label": "L", "order": 0, "editableBy": "user"},
        {"tag": "", "label": "L", "order": 0, "editableBy": "user"},
        {"tag": "a", "label": "", "order": 0, "editableBy": "user"},
        {"tag": "a", "label": "L", "order": 0, "editableBy": "robot"},
        {"tag": "a", "label": "L", "order": 0},
    ):
        assert not validator.is_valid(bad), f"schema accepted {bad}"


def test_error_schema_matches_a_real_error_body(client, spec, monkeypatch, tmp_path):
    monkeypatch.setattr(automation_presets, "SCHEMA_DIR", tmp_path)
    resp = client.get(PRESETS_PATH)
    assert resp.status_code == 503
    _validator(spec, "#/components/schemas/Error").validate(json.loads(resp.data))


# ---- Serving the document itself -------------------------------------------


def test_openapi_is_public_and_served_verbatim(client):
    resp = client.get(OPENAPI_PATH)
    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.data == automation_presets.OPENAPI_PATH.read_bytes(), \
        "the published spec must be byte-identical to the one in the repo"


def test_openapi_etag_revalidates(client):
    etag = client.get(OPENAPI_PATH).headers["ETag"]
    assert not etag.startswith("W/")
    resp = client.get(OPENAPI_PATH, headers={"If-None-Match": etag})
    assert resp.status_code == 304
    assert resp.data == b""


def test_openapi_and_presets_have_different_etags(client):
    """Two documents, two validators — a shared cache would collapse them."""
    assert (client.get(OPENAPI_PATH).headers["ETag"]
            != client.get(PRESETS_PATH).headers["ETag"])


def test_unreadable_openapi_is_a_503(client, monkeypatch, tmp_path):
    broken = tmp_path / "openapi.json"
    broken.write_text("{not json")
    monkeypatch.setattr(automation_presets, "OPENAPI_PATH", broken)
    assert client.get(OPENAPI_PATH).status_code == 503
