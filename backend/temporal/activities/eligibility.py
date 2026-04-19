"""Eligibility activity — fetches dossier + brief + contributing scan.

Wraps the existing aggregator API calls from `services/oss_service.py`.
Writes four JSON files into `01-eligible/` so the eligibility gate can
read them. No GitHub side effects — purely aggregator HTTP (with a
GH API fallback for aged-out issues).

Brief fetch has three fallback rungs so eligibility survives issues
that have dropped out of the aggregator's top-100 scored window:
  1. GET /recon/{slug}/issue-brief/{id}        (fast path — top-100)
  2. GET /recon/{slug}/scored-issues + find    (issue exists but top-100 moved)
     POST /recon/{slug}/compose-brief
  3. gh api repos/{slug}/issues/{n} → build    (aged fully out; reconstruct from GH)
     ExtendedIssue snapshot →
     POST /recon/{slug}/compose-brief
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def _slug_to_aggregator(upstream_slug: str) -> str:
    """Convert `owner/repo` to the aggregator's hyphenated form `owner-repo`."""
    return upstream_slug.replace("/", "-")


def check_eligibility(
    upstream_slug: str,
    issue_number: int,
    evidence,
    *,
    aggregator_get=None,
    aggregator_post=None,
    gh_issue_fetcher=None,
) -> dict:
    """Fetch dossier, issue brief, and contributing-check from the aggregator.

    Writes:
      - 01-eligible/dossier.json
      - 01-eligible/health.json
      - 01-eligible/issue_brief.json     (may be composed from snapshot)
      - 01-eligible/contributing_check.json
      - 01-eligible/brief_source.txt     (which rung fired: "direct" / "scored-snapshot" / "gh-snapshot")

    Returns a small status dict the orchestrator can log.

    Seams for tests:
      `aggregator_get(endpoint) -> dict` — GET request
      `aggregator_post(endpoint, body: dict) -> dict` — POST request
      `gh_issue_fetcher(slug, number) -> dict` — raw issue JSON from GH
    """
    if aggregator_get is None:
        aggregator_get = _default_aggregator_get
    if aggregator_post is None:
        aggregator_post = _default_aggregator_post
    if gh_issue_fetcher is None:
        gh_issue_fetcher = _default_gh_issue_fetcher

    slug_h = _slug_to_aggregator(upstream_slug)

    dossier_envelope = aggregator_get(f"/recon/{slug_h}/dossier")
    dossier = _unwrap(dossier_envelope, "dossier")
    evidence.write_json("01-eligible/dossier.json", dossier)

    health_envelope = aggregator_get(f"/recon/{slug_h}/health")
    health = _unwrap(health_envelope, "health")
    evidence.write_json("01-eligible/health.json", health)

    brief, brief_source = _fetch_brief_with_fallback(
        upstream_slug, issue_number, slug_h,
        aggregator_get=aggregator_get,
        aggregator_post=aggregator_post,
        gh_issue_fetcher=gh_issue_fetcher,
    )
    evidence.write_json("01-eligible/issue_brief.json", brief)
    evidence.write_text("01-eligible/brief_source.txt", brief_source)

    contrib_envelope = aggregator_get(f"/recon/{slug_h}/contributing")
    contrib = _unwrap(contrib_envelope, "contributing")
    evidence.write_json("01-eligible/contributing_check.json", contrib)

    return {
        "ok": True,
        "brief_source": brief_source,
        "ai_policy": contrib.get("ai_policy") if isinstance(contrib, dict) else None,
        "issue_state": (brief.get("issue") or {}).get("state") if isinstance(brief, dict) else None,
    }


def _fetch_brief_with_fallback(
    upstream_slug: str,
    issue_number: int,
    slug_h: str,
    *,
    aggregator_get,
    aggregator_post,
    gh_issue_fetcher,
) -> tuple[dict, str]:
    """Try the three brief-fetch rungs in order. Returns (brief_dict, source_label)."""
    issue_id = f"github-{slug_h}-{issue_number}"

    # Rung 1: fast path — aggregator serves pre-composed brief from top-100
    try:
        env = aggregator_get(f"/recon/{slug_h}/issue-brief/{issue_id}")
        if isinstance(env, dict) and env.get("success") is True:
            data = env.get("data")
            if isinstance(data, dict):
                return data, "direct"
    except Exception as e:
        logger.info("issue-brief direct fetch raised %s; falling back", type(e).__name__)

    # Rung 2: issue might still be in scored-issues; lift the snapshot from there
    snapshot = _find_scored_snapshot(aggregator_get, slug_h, issue_number)
    if snapshot is not None:
        composed = aggregator_post(f"/recon/{slug_h}/compose-brief", {"issue": snapshot})
        data = _unwrap(composed, "compose-brief (scored snapshot)")
        return data, "scored-snapshot"

    # Rung 3: issue fully aged out; reconstruct a minimal ExtendedIssue from GH directly
    gh_issue = gh_issue_fetcher(upstream_slug, issue_number)
    if not isinstance(gh_issue, dict):
        raise RuntimeError(
            f"issue-brief: every fallback exhausted for {upstream_slug}#{issue_number} "
            f"— gh_issue_fetcher returned {type(gh_issue).__name__}"
        )
    snapshot = _build_snapshot_from_gh(upstream_slug, slug_h, issue_number, gh_issue)
    composed = aggregator_post(f"/recon/{slug_h}/compose-brief", {"issue": snapshot})
    data = _unwrap(composed, "compose-brief (gh snapshot)")
    return data, "gh-snapshot"


def _find_scored_snapshot(aggregator_get, slug_h: str, issue_number: int) -> Optional[dict]:
    try:
        env = aggregator_get(f"/recon/{slug_h}/scored-issues")
    except Exception:
        return None
    if not isinstance(env, dict) or env.get("success") is not True:
        return None
    issues = (env.get("data") or {}).get("issues") or []
    needle = f"/{issue_number}"
    for i in issues:
        if isinstance(i, dict) and i.get("url", "").rstrip("/").endswith(needle):
            return i
    return None


def _build_snapshot_from_gh(
    upstream_slug: str, slug_h: str, issue_number: int, gh: dict,
) -> dict:
    """Construct an ExtendedIssue-shaped payload from raw `gh api` output.

    Only fills fields needed by the aggregator's compose-brief composer.
    Missing fields default to None/empty; dataCompleteness gets 'raw'.
    """
    return {
        "id": f"github-{slug_h}-{issue_number}",
        "platform": "github",
        "project": upstream_slug,
        "title": gh.get("title", ""),
        "url": gh.get("html_url") or f"https://github.com/{upstream_slug}/issues/{issue_number}",
        "body": gh.get("body") or "",
        "bodyPreview": (gh.get("body") or "")[:500],
        "labels": [l.get("name") for l in (gh.get("labels") or []) if isinstance(l, dict) and l.get("name")],
        "createdAt": gh.get("created_at"),
        "updatedAt": gh.get("updated_at"),
        "author": (gh.get("user") or {}).get("login"),
        "authorAssociation": gh.get("author_association", "NONE"),
        "commentCount": gh.get("comments", 0),
        "thumbsUpCount": (gh.get("reactions") or {}).get("+1", 0),
        "assignees": [a.get("login") for a in (gh.get("assignees") or []) if isinstance(a, dict) and a.get("login")],
        "milestone": None,
        "lastCommentAt": None,
        "lastCommentAuthor": None,
        "lastCommentAuthorAssociation": None,
        "linkedPrUrls": [],
        "difficulty": "intermediate",
        "difficultyScore": 50,
        "difficultySignals": [],
        "repoSlug": slug_h,
        "dataCompleteness": "raw",
        "repoKilled": False,
        "likelyFiles": [],
        "relatedIssues": [],
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


def _default_aggregator_post(endpoint: str, body: dict):
    from services.oss_service import _call_aggregator  # type: ignore
    return _call_aggregator(endpoint, method="POST", data=body)


def _default_gh_issue_fetcher(upstream_slug: str, issue_number: int) -> dict:
    """Fetch raw issue JSON via `gh api repos/{slug}/issues/{n}`."""
    import json as _json
    from services.github_api import run_gh_command  # type: ignore
    r = run_gh_command(["api", f"repos/{upstream_slug}/issues/{issue_number}"])
    if not r.get("success"):
        raise RuntimeError(
            f"gh issue fetch failed for {upstream_slug}#{issue_number}: "
            f"{r.get('error') or r.get('output', '')[:200]}"
        )
    try:
        return _json.loads(r["output"])
    except (ValueError, KeyError) as e:
        raise RuntimeError(f"gh issue fetch returned non-JSON: {e}") from e
