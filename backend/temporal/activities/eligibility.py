"""Eligibility activity — fetches dossier + brief + contributing scan.

Wraps the existing aggregator API calls from `services/oss_service.py`.
Writes three JSON files into `01-eligible/` so the eligibility gate can
read them. No GitHub side effects — purely aggregator HTTP.

Phase 1C.1.
"""

from __future__ import annotations

from typing import Any


def _slug_to_aggregator(upstream_slug: str) -> str:
    """Convert `owner/repo` to the aggregator's hyphenated form `owner-repo`."""
    return upstream_slug.replace("/", "-")


def check_eligibility(
    upstream_slug: str,
    issue_number: int,
    evidence,
    *,
    aggregator_get=None,
) -> dict:
    """Fetch dossier, issue brief, and contributing-check from the aggregator.

    Writes:
      - 01-eligible/dossier.json
      - 01-eligible/issue_brief.json
      - 01-eligible/contributing_check.json

    Returns a small status dict the orchestrator can log. Does NOT decide
    pass/fail — that's the eligibility gate's job. Network failures here
    surface as exceptions; the orchestrator turns them into a gate
    deferral via the registry's exception handler.

    `aggregator_get` is a constructor seam: tests pass a fake
    `(endpoint) -> dict` callable. Default uses
    `backend.services.oss_service._call_aggregator`.
    """
    if aggregator_get is None:
        aggregator_get = _default_aggregator_get

    slug_h = _slug_to_aggregator(upstream_slug)

    dossier_envelope = aggregator_get(f"/recon/{slug_h}/dossier")
    dossier = _unwrap(dossier_envelope, "dossier")
    evidence.write_json("01-eligible/dossier.json", dossier)

    health_envelope = aggregator_get(f"/recon/{slug_h}/health")
    health = _unwrap(health_envelope, "health")
    evidence.write_json("01-eligible/health.json", health)

    issue_id = f"github-{slug_h}-{issue_number}"
    brief_envelope = aggregator_get(f"/recon/{slug_h}/issue-brief/{issue_id}")
    brief = _unwrap(brief_envelope, "issue_brief")
    evidence.write_json("01-eligible/issue_brief.json", brief)

    contrib_envelope = aggregator_get(f"/recon/{slug_h}/contributing")
    contrib = _unwrap(contrib_envelope, "contributing")
    evidence.write_json("01-eligible/contributing_check.json", contrib)

    return {
        "ok": True,
        "ai_policy": contrib.get("ai_policy") if isinstance(contrib, dict) else None,
        "issue_state": (brief.get("issue") or {}).get("state") if isinstance(brief, dict) else None,
    }


def _unwrap(envelope: Any, label: str) -> dict:
    """Strip the `{success, data, _meta}` envelope and return `data`."""
    if not isinstance(envelope, dict):
        raise RuntimeError(f"{label}: aggregator returned non-object: {type(envelope).__name__}")
    if envelope.get("success") is not True:
        raise RuntimeError(f"{label}: aggregator success=false: {envelope!r}")
    data = envelope.get("data")
    if data is None:
        raise RuntimeError(f"{label}: aggregator response has no data field")
    return data if isinstance(data, dict) else {"value": data}


def _default_aggregator_get(endpoint: str):
    from services.oss_service import _call_aggregator  # type: ignore
    return _call_aggregator(endpoint)
