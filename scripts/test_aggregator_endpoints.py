#!/usr/bin/env python3
"""Smoke check for the new hadoku-aggregator endpoints crimson-kitty depends on.

Phase 0 step 0.8: hits the 5 new `/recon/{slug}/...` endpoints for 3 known
repos and validates the response schema against `docs/crimson-kitty/components.md`.

Endpoints checked (per components.md):
  GET /recon/{slug}/contributing       → eligibility gate
  GET /recon/{slug}/pr-template        → pr_template_compliance gate
  GET /recon/{slug}/issue-templates    → repro activity (v2)
  GET /recon/{slug}/codeowners         → eligibility (informational)
  GET /recon/{slug}/labels?prefix=ai   → eligibility (ai-policy labels)

Repos checked:
  WolffM-vibedispatch        — own repo, smallest blast radius
  microsoft-markitdown       — SAML org, jade-hare target
  mermaid-js-mermaid         — large OSS project, jade-hare target

All responses MUST be wrapped in the standard `{success, data, _meta}` envelope.
The schema validators below are intentionally lenient on optional fields and
strict on required fields.

Exit codes:
  0 — every endpoint returned a valid envelope and the data shape matches.
  1 — at least one endpoint failed schema validation or returned non-200.
  2 — script could not start (no AGGREGATOR_API_URL etc.)

Usage:
  scripts/test_aggregator_endpoints.py
  scripts/test_aggregator_endpoints.py --base-url https://aggregator.hadoku.me
  scripts/test_aggregator_endpoints.py --slug microsoft-markitdown   # narrow
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

import requests

DEFAULT_REPOS = [
    "WolffM-vibedispatch",
    "microsoft-markitdown",
    "mermaid-js-mermaid",
]


# ── Schema validators ─────────────────────────────────────────────────────────


class SchemaError(ValueError):
    pass


def _require(obj: Any, key: str, kind: type, where: str) -> Any:
    if not isinstance(obj, dict):
        raise SchemaError(f"{where}: expected object, got {type(obj).__name__}")
    if key not in obj:
        raise SchemaError(f"{where}: missing required key {key!r}")
    value = obj[key]
    if not isinstance(value, kind):
        raise SchemaError(
            f"{where}.{key}: expected {kind.__name__}, got {type(value).__name__}"
        )
    return value


def _allow_none(obj: Any, key: str, kind: type, where: str) -> Any:
    if not isinstance(obj, dict):
        raise SchemaError(f"{where}: expected object, got {type(obj).__name__}")
    if key not in obj:
        raise SchemaError(f"{where}: missing key {key!r}")
    value = obj[key]
    if value is not None and not isinstance(value, kind):
        raise SchemaError(
            f"{where}.{key}: expected {kind.__name__} or null, got {type(value).__name__}"
        )
    return value


def validate_envelope(body: Any) -> dict:
    if not isinstance(body, dict):
        raise SchemaError(f"response root: expected object, got {type(body).__name__}")
    if body.get("success") is not True:
        raise SchemaError(f"response.success: expected true, got {body.get('success')!r}")
    data = body.get("data")
    if not isinstance(data, dict):
        raise SchemaError(
            f"response.data: expected object, got {type(data).__name__}"
        )
    return data


def validate_contributing(data: dict) -> None:
    policy = _require(data, "ai_policy", str, "contributing")
    if policy not in {"banned", "allowed", "unknown"}:
        raise SchemaError(f"contributing.ai_policy invalid: {policy!r}")
    _require(data, "dco_required", bool, "contributing")
    _require(data, "license_check_required", bool, "contributing")


def validate_pr_template(data: dict) -> None:
    _allow_none(data, "path", str, "pr-template")
    _allow_none(data, "raw_text", str, "pr-template")
    sections = _require(data, "sections", list, "pr-template")
    for i, section in enumerate(sections):
        _require(section, "heading", str, f"pr-template.sections[{i}]")
        _require(section, "required", bool, f"pr-template.sections[{i}]")


def validate_issue_templates(data: dict) -> None:
    templates = _require(data, "templates", list, "issue-templates")
    for i, t in enumerate(templates):
        _require(t, "name", str, f"issue-templates[{i}]")
        _require(t, "path", str, f"issue-templates[{i}]")
        fmt = _require(t, "format", str, f"issue-templates[{i}]")
        if fmt not in {"yaml", "markdown"}:
            raise SchemaError(f"issue-templates[{i}].format invalid: {fmt!r}")
        required_fields = _require(
            t, "required_fields", list, f"issue-templates[{i}]"
        )
        for j, field in enumerate(required_fields):
            if not isinstance(field, str):
                raise SchemaError(
                    f"issue-templates[{i}].required_fields[{j}]: expected string"
                )


def validate_codeowners(data: dict) -> None:
    _allow_none(data, "path", str, "codeowners")
    rules = _require(data, "rules", list, "codeowners")
    for i, rule in enumerate(rules):
        _require(rule, "pattern", str, f"codeowners.rules[{i}]")
        owners = _require(rule, "owners", list, f"codeowners.rules[{i}]")
        for j, owner in enumerate(owners):
            if not isinstance(owner, str):
                raise SchemaError(
                    f"codeowners.rules[{i}].owners[{j}]: expected string"
                )


def validate_labels(data: dict) -> None:
    _require(data, "prefix", str, "labels")
    labels = _require(data, "labels", list, "labels")
    for i, label in enumerate(labels):
        _require(label, "name", str, f"labels[{i}]")
        _require(label, "color", str, f"labels[{i}]")
        _allow_none(label, "description", str, f"labels[{i}]")


# ── Endpoint registry ─────────────────────────────────────────────────────────


Validator = Callable[[dict], None]

ENDPOINTS: list[tuple[str, str, Validator]] = [
    ("contributing",   "/recon/{slug}/contributing",       validate_contributing),
    ("pr-template",    "/recon/{slug}/pr-template",        validate_pr_template),
    ("issue-templates", "/recon/{slug}/issue-templates",   validate_issue_templates),
    ("codeowners",     "/recon/{slug}/codeowners",         validate_codeowners),
    ("labels (ai)",    "/recon/{slug}/labels?prefix=ai",   validate_labels),
]


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _http_get(url: str, timeout: float = 15.0) -> tuple[int, Any]:
    """Return (status_code, parsed_json_or_text). Isolated for tests."""
    resp = requests.get(url, timeout=timeout)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def check_endpoint(base_url: str, slug: str, path_tmpl: str, validator: Validator) -> str | None:
    """Hit one endpoint. Return None on pass, an error string on fail."""
    url = f"{base_url.rstrip('/')}{path_tmpl.format(slug=slug)}"
    try:
        status, body = _http_get(url)
    except requests.RequestException as e:
        return f"GET {url}: connection error: {e}"

    if status != 200:
        snippet = json.dumps(body)[:160] if not isinstance(body, str) else body[:160]
        return f"GET {url}: HTTP {status}: {snippet}"

    try:
        data = validate_envelope(body)
        validator(data)
    except SchemaError as e:
        return f"GET {url}: schema error: {e}"
    return None


# ── main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AGGREGATOR_API_URL", ""),
        help="aggregator base URL (env: AGGREGATOR_API_URL)",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=None,
        help="repo slug to test (hyphenated owner-repo). May be repeated. Default: 3 known repos.",
    )
    args = parser.parse_args(argv)

    if not args.base_url:
        print(
            "ERROR: --base-url not provided and AGGREGATOR_API_URL is unset.",
            file=sys.stderr,
        )
        return 2

    slugs = args.slug or DEFAULT_REPOS
    print(f"[smoke] base_url={args.base_url}", file=sys.stderr)
    print(f"[smoke] repos={slugs}", file=sys.stderr)

    failures: list[str] = []
    passed = 0

    for slug in slugs:
        for label, tmpl, validator in ENDPOINTS:
            err = check_endpoint(args.base_url, slug, tmpl, validator)
            tag = f"{slug:30s}  {label:18s}"
            if err is None:
                passed += 1
                print(f"  PASS  {tag}", file=sys.stderr)
            else:
                failures.append(f"{tag}  →  {err}")
                print(f"  FAIL  {tag}", file=sys.stderr)

    print(
        f"[smoke] passed={passed}  failed={len(failures)}  "
        f"of {len(slugs) * len(ENDPOINTS)} total",
        file=sys.stderr,
    )

    if failures:
        print("\nFailures:", file=sys.stderr)
        for f in failures:
            print(f"  • {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
