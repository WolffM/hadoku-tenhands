"""Tests for OSS routes — Stage 5: Submit Upstream & Poll."""

import json
from unittest.mock import patch, MagicMock

import pytest

from app import app
from extensions import limiter


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as client:
        yield client
    limiter.enabled = True


@pytest.fixture(autouse=True)
def disable_cache(monkeypatch):
    """Disable caching for all route tests."""
    monkeypatch.setenv("CACHE_DISABLED", "1")


PREFIX = "/tenhands"


# ============ Poll Submitted PRs ============


class TestPollSubmittedPRs:
    """Tests for POST /api/oss/poll-submitted-prs — state detection and notifications."""

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_detects_state_transition_to_merged(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "acme-corp/widget-api",
            "pr_url": "https://github.com/acme-corp/widget-api/pull/100",
            "pr_number": 100,
            "title": "Fix bug",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "MERGED",
                "reviewDecision": "APPROVED",
                "mergedAt": "2026-02-19T12:00:00Z",
                "closedAt": None,
            })
        }

        resp = client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                          json={}, content_type="application/json")
        data = resp.get_json()

        assert data["success"] is True
        assert data["submitted"][0]["state"] == "merged"
        assert data["submitted"][0]["review_decision"] == "APPROVED"
        assert data["submitted"][0]["merged_at"] == "2026-02-19T12:00:00Z"
        assert data["submitted"][0]["last_polled_at"] is not None
        svc.update_submitted_prs.assert_called_once()

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    def test_skips_polling_for_already_terminal_prs(self, mock_svc_cls, mock_user, client):
        """PRs in merged/closed state should not trigger gh CLI calls."""
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "acme-corp/widget-api",
            "pr_url": "https://github.com/acme-corp/widget-api/pull/50",
            "pr_number": 50,
            "title": "Old fix",
            "state": "merged",
            "review_decision": "APPROVED",
            "merged_at": "2026-02-10T00:00:00Z",
            "closed_at": None,
            "last_polled_at": "2026-02-15T00:00:00Z",
            "submitted_at": "2026-02-08T00:00:00Z",
        }]

        resp = client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                          json={}, content_type="application/json")
        data = resp.get_json()

        assert data["submitted"][0]["state"] == "merged"

    @patch("routes.oss_routes_stage5.notify_upstream_merged")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_fires_merge_notification_on_state_change(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "MERGED",
                "reviewDecision": "APPROVED",
                "mergedAt": "2026-02-19T12:00:00Z",
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_called_once_with(
            "vercel/next.js",
            "https://github.com/vercel/next.js/pull/200",
            "Fix routing",
        )

    @patch("routes.oss_routes_stage5.notify_upstream_feedback")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_fires_feedback_notification_on_review_change(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": None,
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "OPEN",
                "reviewDecision": "CHANGES_REQUESTED",
                "mergedAt": None,
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_called_once_with(
            "vercel/next.js",
            "https://github.com/vercel/next.js/pull/200",
            "CHANGES_REQUESTED",
        )

    @patch("routes.oss_routes_stage5.notify_upstream_feedback")
    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_no_notification_when_review_unchanged(self, mock_gh, mock_svc_cls, mock_user, mock_notify, client):
        """If review_decision hasn't changed, no notification should fire."""
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "vercel/next.js",
            "pr_url": "https://github.com/vercel/next.js/pull/200",
            "pr_number": 200,
            "title": "Fix routing",
            "state": "open",
            "review_decision": "APPROVED",  # Already approved
            "merged_at": None,
            "closed_at": None,
            "last_polled_at": None,
            "submitted_at": "2026-02-18T00:00:00Z",
        }]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps({
                "state": "OPEN",
                "reviewDecision": "APPROVED",  # Same — no change
                "mergedAt": None,
                "closedAt": None,
            })
        }

        client.post(f"{PREFIX}/api/oss/poll-submitted-prs",
                    json={}, content_type="application/json")

        mock_notify.assert_not_called()


# ============ Stage 5: Submit Upstream ============


class TestSubmitToOrigin:
    """Tests for POST /api/oss/submit-to-origin."""

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_submit_saves_and_removes_ready_item(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/acme-corp/widget-api/pull/123\n",
        }

        resp = client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "acme-corp/widget-api",
                "repo": "widget-api",
                "branch": "fix-docs",
                "title": "Fix docs",
                "body": "## Summary\nFixes docs",
                "base_branch": "main",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["pr_url"] == "https://github.com/acme-corp/widget-api/pull/123"
        svc.save_submitted_pr.assert_called_once_with(
            "acme-corp/widget-api", "https://github.com/acme-corp/widget-api/pull/123", "Fix docs",
            issue_number=0,
        )
        svc.remove_ready_to_submit.assert_called_once_with("acme-corp/widget-api", "fix-docs")

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_submit_generates_default_body_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the 'if not body' branch — route should call format_upstream_pr_body."""
        svc = mock_svc_cls.return_value
        svc.get_ready_to_submit.return_value = [
            {"origin_slug": "acme-corp/widget-api", "branch": "fix-docs", "issue_number": 42}
        ]
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/acme-corp/widget-api/pull/123\n",
        }

        client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "acme-corp/widget-api",
                "repo": "widget-api",
                "branch": "fix-docs",
                "title": "Fix docs",
                # base_branch passed explicitly so the route skips the live
                # _resolve_default_branch gh call (this test exercises the
                # default-body branch, not base-branch resolution).
                "base_branch": "main",
            },
            content_type="application/json",
        )

        call_args = mock_gh.call_args[0][0]
        body_idx = call_args.index("--body") + 1
        assert len(call_args[body_idx]) > 0
        assert "Closes #42" in call_args[body_idx]

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={"origin_slug": "acme-corp/widget-api"},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is False


# ============ Archive Ready-to-Submit ============


class TestArchiveReadyToSubmit:
    """POST /api/oss/admin/archive-ready-to-submit moves stale entries
    out of the ready queue and into submitted-prs.json under
    state="merged-in-fork-only" so they stop showing up as actionable."""

    @patch("routes.oss_routes_stage5.OSSService")
    def test_archive_calls_service_method_and_returns_counts(
        self, mock_svc_cls, client,
    ):
        svc = mock_svc_cls.return_value
        svc.archive_ready_to_submit_as_fork_merged_only.return_value = {
            "archived": 4, "cleared": 7,
        }

        resp = client.post(f"{PREFIX}/api/oss/admin/archive-ready-to-submit")

        body = resp.get_json()
        assert resp.status_code == 200
        assert body["success"] is True
        assert body["archived"] == 4
        assert body["cleared"] == 7
        svc.archive_ready_to_submit_as_fork_merged_only.assert_called_once_with()

    def test_archive_dedups_by_origin_branch_and_keeps_earliest_merged_at(
        self, tmp_path, monkeypatch,
    ):
        """Direct test on the state mixin: 5 dupes of the same fork PR
        collapse to one record using the earliest merged_at."""
        from services import oss_service
        from services.oss_service import OSSService

        monkeypatch.setattr(oss_service, "OSS_DATA_DIR", str(tmp_path))
        # Seed 5 dupes of microsoft/markitdown#183
        ready_path = tmp_path / "ready-to-submit.json"
        ready_path.write_text(json.dumps([
            {"origin_slug": "microsoft/markitdown", "repo": "markitdown",
             "branch": "copilot/fix-x", "title": "Fix x", "base_branch": "main",
             "issue_number": 183, "merged_at": "2026-03-17T19:55:03Z"},
            {"origin_slug": "microsoft/markitdown", "repo": "markitdown",
             "branch": "copilot/fix-x", "title": "Fix x", "base_branch": "main",
             "issue_number": 183, "merged_at": "2026-03-17T18:42:54Z"},  # earliest
            {"origin_slug": "microsoft/markitdown", "repo": "markitdown",
             "branch": "copilot/fix-x", "title": "Fix x", "base_branch": "main",
             "issue_number": 183, "merged_at": "2026-03-17T19:47:56Z"},
            # Distinct entry
            {"origin_slug": "acme/widget", "repo": "widget",
             "branch": "feat/y", "title": "Feat y", "base_branch": "main",
             "issue_number": 7, "merged_at": "2026-04-01T00:00:00Z"},
        ]))
        (tmp_path / "submitted-prs.json").write_text("[]")

        svc = OSSService()
        result = svc.archive_ready_to_submit_as_fork_merged_only()

        assert result["cleared"] == 4  # 4 raw rows
        assert result["archived"] == 2  # 2 unique destinations
        ready_after = json.loads(ready_path.read_text())
        assert ready_after == []

        submitted = json.loads((tmp_path / "submitted-prs.json").read_text())
        assert len(submitted) == 2
        markitdown = next(s for s in submitted
                          if s["origin_slug"] == "microsoft/markitdown")
        assert markitdown["state"] == "merged-in-fork-only"
        assert markitdown["submission_method"] == "merged-in-fork-only"
        assert markitdown["pr_url"] == ""
        assert markitdown["pr_number"] is None
        # Earliest merged_at wins
        assert markitdown["merged_at"] == "2026-03-17T18:42:54Z"
        assert markitdown["submitted_at"] == "2026-03-17T18:42:54Z"

    def test_archive_is_idempotent(self, tmp_path, monkeypatch):
        """Calling twice doesn't duplicate the archived record."""
        from services import oss_service
        from services.oss_service import OSSService

        monkeypatch.setattr(oss_service, "OSS_DATA_DIR", str(tmp_path))
        (tmp_path / "ready-to-submit.json").write_text(json.dumps([
            {"origin_slug": "x/y", "repo": "y", "branch": "br",
             "title": "T", "base_branch": "main", "issue_number": 1,
             "merged_at": "2026-01-01T00:00:00Z"},
        ]))
        (tmp_path / "submitted-prs.json").write_text("[]")

        svc = OSSService()
        first = svc.archive_ready_to_submit_as_fork_merged_only()
        assert first == {"archived": 1, "cleared": 1}

        second = svc.archive_ready_to_submit_as_fork_merged_only()
        assert second == {"archived": 0, "cleared": 0}

        submitted = json.loads((tmp_path / "submitted-prs.json").read_text())
        assert len(submitted) == 1

    def test_archive_on_empty_ready_returns_zeros(self, tmp_path, monkeypatch):
        from services import oss_service
        from services.oss_service import OSSService

        monkeypatch.setattr(oss_service, "OSS_DATA_DIR", str(tmp_path))
        (tmp_path / "ready-to-submit.json").write_text("[]")
        (tmp_path / "submitted-prs.json").write_text("[]")

        svc = OSSService()
        result = svc.archive_ready_to_submit_as_fork_merged_only()
        assert result == {"archived": 0, "cleared": 0}
