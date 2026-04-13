"""Unit tests for scripts/test_aggregator_endpoints.py.

The smoke script's job is to validate the response shape of 5 aggregator
endpoints. These tests exercise the validators and the per-endpoint check
function with mocked HTTP responses — no network required.
"""

import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import test_aggregator_endpoints as tae  # noqa: E402


# ── envelope ──────────────────────────────────────────────────────────────────


def test_envelope_pass():
    data = tae.validate_envelope({"success": True, "data": {"x": 1}, "_meta": {}})
    assert data == {"x": 1}


@pytest.mark.parametrize("body", [
    "not a dict",
    {"success": False, "data": {}},
    {"success": True, "data": "not an object"},
    {"data": {}},
])
def test_envelope_rejects_invalid_shapes(body):
    with pytest.raises(tae.SchemaError):
        tae.validate_envelope(body)


# ── contributing ──────────────────────────────────────────────────────────────


def test_contributing_pass():
    tae.validate_contributing({
        "ai_policy": "banned",
        "dco_required": True,
        "license_check_required": False,
    })


@pytest.mark.parametrize("data, fragment", [
    ({"ai_policy": "maybe", "dco_required": True, "license_check_required": False}, "ai_policy invalid"),
    ({"ai_policy": "allowed", "dco_required": "yes", "license_check_required": False}, "dco_required"),
    ({"ai_policy": "allowed", "license_check_required": False}, "missing required key 'dco_required'"),
])
def test_contributing_rejects(data, fragment):
    with pytest.raises(tae.SchemaError, match=fragment):
        tae.validate_contributing(data)


# ── pr-template ───────────────────────────────────────────────────────────────


def test_pr_template_pass_with_sections():
    tae.validate_pr_template({
        "path": ".github/PULL_REQUEST_TEMPLATE.md",
        "raw_text": "## Summary\n\n## Test plan\n",
        "sections": [
            {"heading": "Summary", "required": True, "placeholder": None},
            {"heading": "Test plan", "required": False, "placeholder": None},
        ],
        "front_matter": None,
    })


def test_pr_template_pass_with_no_template():
    tae.validate_pr_template({
        "path": None,
        "raw_text": None,
        "sections": [],
        "front_matter": None,
    })


def test_pr_template_rejects_bad_section():
    with pytest.raises(tae.SchemaError, match="sections"):
        tae.validate_pr_template({
            "path": None,
            "raw_text": None,
            "sections": [{"heading": "Summary"}],
            "front_matter": None,
        })


# ── issue-templates ───────────────────────────────────────────────────────────


def test_issue_templates_pass():
    tae.validate_issue_templates({
        "templates": [
            {
                "name": "Bug Report",
                "path": ".github/ISSUE_TEMPLATE/bug.yml",
                "format": "yaml",
                "required_fields": ["description", "version"],
            },
            {
                "name": "Feature Request",
                "path": ".github/ISSUE_TEMPLATE/feature.md",
                "format": "markdown",
                "required_fields": [],
            },
        ]
    })


def test_issue_templates_rejects_unknown_format():
    with pytest.raises(tae.SchemaError, match="format invalid"):
        tae.validate_issue_templates({
            "templates": [
                {"name": "x", "path": "p", "format": "json", "required_fields": []}
            ]
        })


def test_issue_templates_empty_list_ok():
    tae.validate_issue_templates({"templates": []})


# ── codeowners ────────────────────────────────────────────────────────────────


def test_codeowners_pass():
    tae.validate_codeowners({
        "path": ".github/CODEOWNERS",
        "rules": [
            {"pattern": "*.py", "owners": ["@WolffM"]},
            {"pattern": "docs/", "owners": ["@docs-team", "@WolffM"]},
        ],
    })


def test_codeowners_pass_when_missing():
    tae.validate_codeowners({"path": None, "rules": []})


def test_codeowners_rejects_non_string_owner():
    with pytest.raises(tae.SchemaError, match="owners"):
        tae.validate_codeowners({
            "path": "CODEOWNERS",
            "rules": [{"pattern": "*", "owners": [123]}],
        })


# ── labels ────────────────────────────────────────────────────────────────────


def test_labels_pass():
    tae.validate_labels({
        "prefix": "ai",
        "labels": [
            {"name": "ai-policy", "color": "ff0000", "description": "AI usage policy"},
            {"name": "ai-generated", "color": "00ff00", "description": None},
        ],
    })


def test_labels_pass_empty():
    tae.validate_labels({"prefix": "ai", "labels": []})


def test_labels_rejects_missing_color():
    with pytest.raises(tae.SchemaError, match="color"):
        tae.validate_labels({
            "prefix": "ai",
            "labels": [{"name": "ai-policy", "description": None}],
        })


# ── check_endpoint with mocked HTTP ───────────────────────────────────────────


@pytest.fixture
def mock_http(monkeypatch):
    responses: dict[str, tuple[int, object]] = {}

    def fake_get(url, timeout=15.0):
        if url not in responses:
            raise AssertionError(f"unexpected URL: {url}")
        return responses[url]

    monkeypatch.setattr(tae, "_http_get", fake_get)
    return responses


def test_check_endpoint_pass(mock_http):
    mock_http["https://agg.test/recon/microsoft-markitdown/contributing"] = (
        200,
        {
            "success": True,
            "data": {
                "ai_policy": "unknown",
                "dco_required": False,
                "license_check_required": True,
            },
            "_meta": {},
        },
    )
    err = tae.check_endpoint(
        "https://agg.test",
        "microsoft-markitdown",
        "/recon/{slug}/contributing",
        tae.validate_contributing,
    )
    assert err is None


def test_check_endpoint_http_500(mock_http):
    mock_http["https://agg.test/recon/microsoft-markitdown/contributing"] = (
        500,
        {"error": "boom"},
    )
    err = tae.check_endpoint(
        "https://agg.test",
        "microsoft-markitdown",
        "/recon/{slug}/contributing",
        tae.validate_contributing,
    )
    assert err is not None and "HTTP 500" in err


def test_check_endpoint_schema_failure(mock_http):
    mock_http["https://agg.test/recon/x/contributing"] = (
        200,
        {"success": True, "data": {"ai_policy": "yes"}, "_meta": {}},
    )
    err = tae.check_endpoint(
        "https://agg.test",
        "x",
        "/recon/{slug}/contributing",
        tae.validate_contributing,
    )
    assert err is not None and "schema error" in err


def test_check_endpoint_query_string_preserved(mock_http):
    mock_http["https://agg.test/recon/x/labels?prefix=ai"] = (
        200,
        {"success": True, "data": {"prefix": "ai", "labels": []}, "_meta": {}},
    )
    err = tae.check_endpoint(
        "https://agg.test",
        "x",
        "/recon/{slug}/labels?prefix=ai",
        tae.validate_labels,
    )
    assert err is None


# ── main: aggregated pass/fail ────────────────────────────────────────────────


def test_main_returns_zero_when_all_pass(monkeypatch):
    def fake_check(base, slug, tmpl, validator):
        return None

    monkeypatch.setattr(tae, "check_endpoint", fake_check)
    rc = tae.main(["--base-url", "https://agg.test", "--slug", "x", "--slug", "y"])
    assert rc == 0


def test_main_returns_one_when_any_fail(monkeypatch):
    def fake_check(base, slug, tmpl, validator):
        if "labels" in tmpl:
            return f"GET .../{slug}/labels: HTTP 404"
        return None

    monkeypatch.setattr(tae, "check_endpoint", fake_check)
    rc = tae.main(["--base-url", "https://agg.test", "--slug", "x"])
    assert rc == 1


def test_main_returns_two_when_no_base_url(monkeypatch):
    monkeypatch.delenv("AGGREGATOR_API_URL", raising=False)
    rc = tae.main([])
    assert rc == 2
