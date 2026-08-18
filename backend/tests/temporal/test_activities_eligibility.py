"""the eligibility activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

import pytest

def test_eligibility_activity_writes_evidence_files(ev):
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {"sections": []}}
        if "health" in endpoint:
            return {"success": True, "data": {"maintainerHealthScore": 80}}
        if "issue-brief" in endpoint:
            return {"success": True, "data": {"issue": {"state": "open", "title": "x", "body": "y"}}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown", "dco_required": False, "license_check_required": False}}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    result = check_eligibility(
        "microsoft/markitdown", 183, ev,
        aggregator_get=fake_get,
    )
    assert result["ok"] is True
    assert ev.exists("01-eligible/dossier.json")
    assert ev.exists("01-eligible/health.json")
    assert ev.exists("01-eligible/issue_brief.json")
    assert ev.exists("01-eligible/contributing_check.json")


def test_eligibility_activity_raises_on_envelope_failure(ev):
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        return {"success": False, "data": None}

    with pytest.raises(RuntimeError, match="success=false"):
        check_eligibility("microsoft/markitdown", 183, ev, aggregator_get=fake_get)


def test_eligibility_activity_uses_hyphenated_slug(ev):
    from temporal.activities.eligibility import check_eligibility

    seen = []

    def fake_get(endpoint: str):
        seen.append(endpoint)
        if "issue-brief" in endpoint:
            # force fallback attempts to exercise the scored-issues path
            return {"success": True, "data": {"issue": {}}}
        return {"success": True, "data": {}}

    check_eligibility("mermaid-js/mermaid", 4099, ev, aggregator_get=fake_get)
    assert any("mermaid-js-mermaid" in e for e in seen)
    assert not any("mermaid-js/mermaid" in e for e in seen)


def test_eligibility_falls_back_to_scored_snapshot(ev):
    """When /issue-brief/{id} returns success=false, find snapshot in
    /scored-issues and POST /compose-brief."""
    from temporal.activities.eligibility import check_eligibility

    get_calls = []
    post_calls = []

    def fake_get(endpoint: str):
        get_calls.append(endpoint)
        if "dossier" in endpoint:
            return {"success": True, "data": {"sections": []}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            # Aged out of top-100
            return {"success": False, "error": "issue not found: ..."}
        if "scored-issues" in endpoint:
            return {"success": True, "data": {"issues": [
                {"url": "https://github.com/cli/cli/issues/9569", "title": "foo", "body": "bar"},
                {"url": "https://github.com/cli/cli/issues/1234", "title": "other"},
            ]}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        post_calls.append((endpoint, body))
        assert endpoint == "/recon/cli-cli/compose-brief"
        assert body["issue"]["url"].endswith("/9569")
        return {"success": True, "data": {"issue": {"state": "open"}, "brief": "composed text"}}

    def fake_gh(slug, num):
        raise AssertionError("should not fall through to gh fetcher when snapshot is in scored-issues")

    result = check_eligibility(
        "cli/cli", 9569, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "scored-snapshot"
    assert ev.read_text("01-eligible/brief_source.txt") == "scored-snapshot"
    assert len(post_calls) == 1


def test_eligibility_falls_back_to_gh_snapshot(ev):
    """When issue isn't in scored-issues either, fetch from gh api, build
    snapshot, and POST /compose-brief."""
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            return {"success": False, "error": "issue not found"}
        if "scored-issues" in endpoint:
            # Not in scored-issues either
            return {"success": True, "data": {"issues": []}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        assert endpoint == "/recon/shadcn-ui-ui/compose-brief"
        # snapshot built from gh API
        assert body["issue"]["id"] == "github-shadcn-ui-ui-6843"
        assert body["issue"]["title"] == "Cursor pointer issue"
        assert body["issue"]["dataCompleteness"] == "raw"
        return {"success": True, "data": {"issue": {"state": "open"}, "brief": "composed text"}}

    def fake_gh(slug, num):
        assert slug == "shadcn-ui/ui"
        assert num == 6843
        return {
            "title": "Cursor pointer issue",
            "body": "body text",
            "html_url": "https://github.com/shadcn-ui/ui/issues/6843",
            "labels": [{"name": "bug"}],
            "user": {"login": "someone"},
            "created_at": "2025-03-03T18:53:16Z",
            "updated_at": "2025-03-03T18:53:16Z",
            "comments": 47,
            "reactions": {"+1": 121},
            "author_association": "NONE",
        }

    result = check_eligibility(
        "shadcn-ui/ui", 6843, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "gh-snapshot"


def test_eligibility_direct_path_still_works(ev):
    """When the aggregator's pre-composed brief is available, no fallback fires."""
    from temporal.activities.eligibility import check_eligibility

    post_calls = []

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            return {"success": True, "data": {"issue": {"state": "open"}, "brief": "pre-composed"}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        post_calls.append((endpoint, body))
        return None

    def fake_gh(slug, num):
        raise AssertionError("should not be called on direct-path success")

    result = check_eligibility(
        "jestjs/jest", 2070, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "direct"
    assert post_calls == []
