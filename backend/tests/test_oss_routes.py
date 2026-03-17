"""Tests for OSS routes — all stages and polling endpoints."""

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


PREFIX = "/dispatch"


# ============ Stage 1: Target Repos ============


class TestDispatchedReposEndpoint:
    """Tests for GET /api/oss/dispatched-repos."""

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_returns_dispatched_list(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dispatched_repos.return_value = [
            {"origin_slug": "fastify/fastify", "aggregator_slug": "fastify-fastify",
             "dispatch_count": 2},
        ]

        resp = client.get(f"{PREFIX}/api/oss/dispatched-repos")
        data = resp.get_json()

        assert data["success"] is True
        assert len(data["dispatched_repos"]) == 1
        assert data["dispatched_repos"][0]["origin_slug"] == "fastify/fastify"
        assert data["owner"] == "testuser"

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_returns_empty_list_when_none_dispatched(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dispatched_repos.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/dispatched-repos")
        data = resp.get_json()

        assert data["success"] is True
        assert data["dispatched_repos"] == []


class TestStage1AlreadyDispatched:
    """Tests for already_dispatched flag in stage1 targets."""

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_true_for_matching_slug(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "fastify-fastify"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = [
            {"aggregator_slug": "fastify-fastify"},
        ]

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        assert data["success"] is True
        target = next(t for t in data["targets"] if t["slug"] == "fastify-fastify")
        assert target["already_dispatched"] is True

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_false_for_unmatched_slug(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "vercel-next.js"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = [
            {"aggregator_slug": "fastify-fastify"},
        ]

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        target = next(t for t in data["targets"] if t["slug"] == "vercel-next.js")
        assert target["already_dispatched"] is False

    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_already_dispatched_false_when_no_dispatches(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = [{"repoSlug": "fastify-fastify"}]
        svc.get_health.return_value = (None, None)
        svc.get_dossier.return_value = (None, None)
        svc.get_dispatched_repos.return_value = []

        resp = client.get(f"{PREFIX}/api/oss/stage1-targets")
        data = resp.get_json()

        target = data["targets"][0]
        assert target["already_dispatched"] is False


class TestRefreshTarget:
    """Tests for POST /api/oss/refresh-target."""

    @patch("routes.oss_routes_stage1.clear_cache")
    @patch("routes.oss_routes_stage1.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage1.OSSService")
    def test_refresh_converts_slash_to_hyphen(self, mock_svc_cls, mock_user, mock_cache, client):
        """Tests the slug.replace('/', '-') conversion logic."""
        svc = mock_svc_cls.return_value

        client.post(
            f"{PREFIX}/api/oss/refresh-target",
            json={"slug": "fastify/fastify"},
            content_type="application/json",
        )

        svc.trigger_refresh.assert_called_once_with("fastify-fastify")


# ============ Stage 2: Scored Issues ============


class TestStage2Issues:
    """Tests for GET /api/oss/stage2-issues."""

    @patch("routes.oss_routes_stage2.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage2.OSSService")
    def test_returns_empty_when_aggregator_unavailable(self, mock_svc_cls, mock_user, client):
        """When aggregator returns no issues, route returns empty list."""
        svc = mock_svc_cls.return_value
        svc.get_scored_issues.return_value = ([], None)

        resp = client.get(f"{PREFIX}/api/oss/stage2-issues")
        data = resp.get_json()

        assert data["success"] is True
        assert data["issues"] == []


# ============ Poll Submitted PRs ============


class TestPollSubmittedPRs:
    """Tests for POST /api/oss/poll-submitted-prs — state detection and notifications."""

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_detects_state_transition_to_merged(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_submitted_prs.return_value = [{
            "origin_slug": "fastify/fastify",
            "pr_url": "https://github.com/fastify/fastify/pull/100",
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
            "origin_slug": "fastify/fastify",
            "pr_url": "https://github.com/fastify/fastify/pull/50",
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


# ============ Stage 3: Fork & Assign ============


class TestSelectIssue:
    """Tests for POST /api/oss/select-issue."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_select_issue_already_selected_returns_flag(self, mock_svc_cls, mock_user, client):
        """Tests the dedup branch — different response shape when already selected."""
        svc = mock_svc_cls.return_value
        svc.find_selected_issue.return_value = {"origin_slug": "fastify/fastify", "issue_number": 42}

        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_selected"] is True
        svc.select_issue.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    def test_select_issue_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/select-issue",
            json={"origin_owner": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()


class TestForkAndAssign:
    """Tests for POST /api/oss/fork-and-assign."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_dedup_returns_existing_assignment(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/fastify/issues/1"
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_assigned"] is True
        assert data["fork_issue_url"] == "https://github.com/testuser/fastify/issues/1"

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={"origin_owner": "fastify", "repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_fork_creation_failure(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = False
        svc.fork_repo.return_value = {"success": False, "error": "Rate limited"}
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "rate limit" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_fork_timeout(self, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = False
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "timed out" in data["error"].lower()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_auto_fetches_dossier_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (
            {"slug": "fastify-fastify", "sections": {"contributionRules": "Follow the style guide"}},
            {"scraped_at": "2026-02-24T00:00:00Z"},
        )
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/fastify/issues/1", "number": 1}\n',
        }

        client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )

        svc.get_dossier.assert_called_once_with("fastify-fastify", include_meta=True)
        call_args = svc.build_agent_context.call_args
        assert call_args[0][5] == {"contributionRules": "Follow the style guide"}

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_self_owned_skips_fork_and_sync(self, mock_gh, mock_svc_cls, mock_user, client):
        """When origin_owner == my_user, fork/sync steps are skipped."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/myrepo/issues/1", "number": 1}\n',
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "testuser",
                "repo": "myrepo",
                "issue_number": 42,
                "issue_title": "Fix bug",
                "issue_url": "https://github.com/testuser/myrepo/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["is_self_owned"] is True
        # Fork/sync methods should NOT have been called
        svc.check_fork_exists.assert_not_called()
        svc.fork_repo.assert_not_called()
        svc.wait_for_fork.assert_not_called()
        svc.sync_fork.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_third_party_uses_fork_flow(self, mock_gh, mock_svc_cls, mock_user, client):
        """When origin_owner != my_user, the full fork flow runs."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": ["gh-issue-view"]})

        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/fastify/issues/1", "number": 1}\n',
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["is_self_owned"] is False
        svc.check_fork_exists.assert_called_once()
        svc.wait_for_fork.assert_called_once()
        svc.sync_fork.assert_called_once()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_response_includes_context_sources(self, mock_gh, mock_svc_cls, mock_user, client):
        """Response should include context_sources from metadata."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = (
            "## Context",
            {"sources": ["gh-issue-view", "gh-contributing-md"]},
        )

        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/fastify/issues/1", "number": 1}\n',
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "context_sources" in data
        assert "gh-issue-view" in data["context_sources"]
        assert "gh-contributing-md" in data["context_sources"]

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_tracks_dispatched_repo_on_success(self, mock_gh, mock_svc_cls, mock_user, client):
        """Successful dispatch must call track_dispatched_repo with origin_slug."""
        svc = mock_svc_cls.return_value
        svc.find_assignment.return_value = None
        svc.check_fork_exists.return_value = True
        svc.wait_for_fork.return_value = True
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.build_agent_context.return_value = ("## Context", {"sources": []})

        mock_gh.return_value = {
            "success": True,
            "output": '{"html_url": "https://github.com/testuser/fastify/issues/1", "number": 1}\n',
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )

        assert resp.get_json()["success"] is True
        svc.track_dispatched_repo.assert_called_once_with("fastify/fastify")

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_does_not_track_dispatched_repo_on_dedup(self, mock_svc_cls, mock_user, client):
        """Dedup early-return must NOT call track_dispatched_repo."""
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/fastify/issues/1"
        }

        client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "fastify",
                "repo": "fastify",
                "issue_number": 42,
                "issue_title": "Fix docs",
                "issue_url": "https://github.com/fastify/fastify/issues/42",
            },
            content_type="application/json",
        )

        svc.track_dispatched_repo.assert_not_called()

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    def test_dedup_response_includes_is_self_owned(self, mock_svc_cls, mock_user, client):
        """Dedup (already_assigned) response should include is_self_owned."""
        svc = mock_svc_cls.return_value
        svc.get_dossier.return_value = (None, None)
        svc.get_issue_brief.return_value = (None, None)
        svc.find_assignment.return_value = {
            "fork_issue_url": "https://github.com/testuser/myrepo/issues/1"
        }

        resp = client.post(
            f"{PREFIX}/api/oss/fork-and-assign",
            json={
                "origin_owner": "testuser",
                "repo": "myrepo",
                "issue_number": 42,
                "issue_title": "Fix bug",
                "issue_url": "https://github.com/testuser/myrepo/issues/42",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["already_assigned"] is True
        assert data["is_self_owned"] is True
        assert data["context_sources"] == []


# ============ Rate Limiting ============


class TestRateLimiting:
    """Verify rate limiting works when enabled."""

    @patch("routes.oss_routes_stage3.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage3.OSSService")
    @patch("routes.oss_routes_stage3.run_gh_command")
    def test_fork_and_assign_rate_limit(self, mock_gh, mock_svc_cls, mock_user):
        """Hitting fork-and-assign more than 5x/min should return 429."""
        limiter.enabled = True
        try:
            with app.test_client() as client:
                svc = mock_svc_cls.return_value
                svc.find_assignment.return_value = {"fork_issue_url": "https://github.com/testuser/r/issues/1"}
                svc.get_dossier.return_value = (None, None)
                svc.get_issue_brief.return_value = (None, None)

                statuses = []
                for i in range(6):
                    resp = client.post(
                        f"{PREFIX}/api/oss/fork-and-assign",
                        json={
                            "origin_owner": "fastify",
                            "repo": "fastify",
                            "issue_number": i + 1,
                            "issue_title": "Fix",
                            "issue_url": f"https://github.com/fastify/fastify/issues/{i + 1}",
                        },
                        content_type="application/json",
                    )
                    statuses.append(resp.status_code)

                # First 5 should succeed, 6th should be rate-limited
                assert statuses[:5] == [200] * 5
                assert statuses[5] == 429
        finally:
            limiter.enabled = False


# ============ Stage 4: Review on Fork ============


class TestStage4ForkPRs:
    """Tests for GET /api/oss/stage4-fork-prs."""

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_injects_repo_and_origin_slug_into_prs(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests that _get_fork_prs adds repo/originSlug fields to each PR dict."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 1, "title": "Fix docs",
                "url": "https://github.com/testuser/fastify/pull/1",
                "headRefName": "fix-docs", "additions": 10, "deletions": 2,
                "changedFiles": 1, "reviewDecision": None, "isDraft": False,
                "createdAt": "2026-02-19T00:00:00Z",
            }]),
        }

        resp = client.get(f"{PREFIX}/api/oss/stage4-fork-prs")
        data = resp.get_json()

        assert len(data["prs"]) == 1
        assert data["prs"][0]["repo"] == "fastify"
        assert data["prs"][0]["originSlug"] == "fastify/fastify"

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_deduplicates_forked_repos_via_set(self, mock_gh, mock_svc_cls, mock_user, client):
        """Two assignments for same repo should only fetch PRs once."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
            {"origin_slug": "fastify/fastify", "repo": "fastify"},
        ]

        mock_gh.return_value = {"success": True, "output": json.dumps([])}

        client.get(f"{PREFIX}/api/oss/stage4-fork-prs")

        assert mock_gh.call_count == 1


class TestForkPRDetails:
    """Tests for POST /api/oss/fork-pr-details."""

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_merges_diff_into_pr_data(self, mock_gh, mock_user, client):
        """Tests that the route makes 2 gh calls and injects diff into pr_data."""
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"number": 1, "title": "Fix docs", "state": "OPEN"})},
            {"success": True, "output": "diff --git a/README.md b/README.md\n+fixed"},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/fork-pr-details",
            json={"repo": "fastify", "pr_number": 1},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["pr"]["title"] == "Fix docs"
        assert "diff" in data["pr"]
        assert "+fixed" in data["pr"]["diff"]

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/fork-pr-details",
            json={"repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert "missing" in data["error"].lower()


class TestApproveForkPR:
    """Tests for POST /api/oss/approve-fork-pr."""

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/approve-fork-pr",
            json={"repo": "fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False


class TestMergeForkPR:
    """Tests for POST /api/oss/merge-fork-pr."""

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_merge_extracts_branch_info_and_saves_to_stage5(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the multi-step merge flow: view → draft check → merge → sanitize → save."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify", "issue_number": 42,
             "default_branch": "main", "fork_issue_number": 3}
        ]
        svc.create_clean_branch.return_value = {"success": True, "sha": "abc123"}
        svc.delete_branch.return_value = {"success": True}
        svc.close_fork_issue.return_value = {"success": True}

        mock_gh.side_effect = [
            # 1. pr view (combined: branch info + isDraft)
            {"success": True, "output": json.dumps({"headRefName": "copilot/fix-docs", "title": "Fix docs", "baseRefName": "main", "isDraft": False})},
            # 2. pr merge
            {"success": True, "output": "Merged"},
            # 3. git ref HEAD (squash SHA)
            {"success": True, "output": "deadbeef123"},
            # 4. pr list (conflict check)
            {"success": True, "output": json.dumps([])},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1, "origin_slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "clean_branch" in data
        assert data["clean_branch"].startswith("fix/42-")
        svc.create_clean_branch.assert_called_once()
        svc.delete_branch.assert_called_once_with("testuser", "fastify", "copilot/fix-docs")
        svc.close_fork_issue.assert_called_once_with("testuser", "fastify", 3)
        svc.save_ready_to_submit.assert_called_once()
        call_kwargs = svc.save_ready_to_submit.call_args[1]
        assert call_kwargs["issue_number"] == 42
        assert call_kwargs["branch"].startswith("fix/42-")

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_merge_marks_draft_as_ready_before_merge(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the isDraft branch — should call 'pr ready' before 'pr merge'."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "fastify/fastify", "repo": "fastify", "issue_number": 10,
             "default_branch": "main", "fork_issue_number": 1}
        ]
        svc.create_clean_branch.return_value = {"success": True, "sha": "abc123"}
        svc.delete_branch.return_value = {"success": True}
        svc.close_fork_issue.return_value = {"success": True}

        mock_gh.side_effect = [
            # 1. pr view (combined: branch info + isDraft)
            {"success": True, "output": json.dumps({"headRefName": "fix", "title": "Fix", "baseRefName": "main", "isDraft": True})},
            # 2. pr ready
            {"success": True, "output": ""},
            # 3. pr merge
            {"success": True, "output": "Merged"},
            # 4. git ref HEAD (squash SHA)
            {"success": True, "output": "deadbeef123"},
            # 5. pr list (conflict check)
            {"success": True, "output": json.dumps([])},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1, "origin_slug": "fastify/fastify"},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is True
        # view + ready + merge + HEAD ref + conflict check = 5
        assert mock_gh.call_count == 5

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_merge_falls_back_when_sanitization_fails(self, mock_gh, mock_svc_cls, mock_user, client):
        """When squash SHA lookup fails, merge still succeeds with original branch."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = []

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"headRefName": "copilot/fix", "title": "Fix", "baseRefName": "main", "isDraft": False})},
            {"success": True, "output": "Merged"},
            # HEAD ref lookup fails
            {"success": False, "error": "Not found"},
            # conflict check
            {"success": True, "output": json.dumps([])},
        ]

        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1, "origin_slug": "fastify/fastify"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "warning" in data
        svc.save_ready_to_submit.assert_called_once()
        assert svc.save_ready_to_submit.call_args[1]["branch"] == "copilot/fix"

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    def test_missing_fields(self, mock_user, client):
        resp = client.post(
            f"{PREFIX}/api/oss/merge-fork-pr",
            json={"repo": "fastify", "pr_number": 1},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is False


class TestSignoffAssignmentMatching:
    """Tests for POST /api/oss/signoff — assignment lookup with optional issue_number."""

    ASSIGNMENTS = [
        {"origin_slug": "microsoft/PowerToys", "repo": "PowerToys",
         "issue_number": 22315, "default_branch": "main", "fork_issue_number": 1},
        {"origin_slug": "microsoft/PowerToys", "repo": "PowerToys",
         "issue_number": 36805, "default_branch": "main", "fork_issue_number": 2},
    ]

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_issue_number_selects_correct_assignment(self, mock_gh, mock_svc_cls, mock_user, client):
        """When issue_number is provided, the matching assignment is used — not the first one."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = list(self.ASSIGNMENTS)

        # PR view returns MERGED so merge step is skipped (simplifies mocking)
        mock_gh.side_effect = [
            # Step 2: pr view
            {"success": True, "output": json.dumps({
                "headRefName": "copilot/fix-36805", "title": "Fix 36805",
                "baseRefName": "main", "isDraft": False, "state": "MERGED"})},
            # Step 4: sanitize — HEAD ref
            {"success": True, "output": "deadbeef"},
            # Step 4: conflict check
            {"success": True, "output": json.dumps([])},
            # Step 5: submit upstream PR
            {"success": True, "output": "https://github.com/microsoft/PowerToys/pull/999\n"},
        ]
        svc.create_clean_branch.return_value = {"success": True, "sha": "abc123"}
        svc.delete_branch.return_value = {"success": True}
        svc.close_fork_issue.return_value = {"success": True}

        resp = client.post(
            f"{PREFIX}/api/oss/signoff",
            json={"repo": "PowerToys", "pr_number": 5,
                  "origin_slug": "microsoft/PowerToys", "issue_number": 36805},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        # The upstream PR body should reference issue 36805, not 22315
        svc.close_fork_issue.assert_called_once_with("testuser", "PowerToys", 2)

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_no_issue_number_falls_back_to_first_match(self, mock_gh, mock_svc_cls, mock_user, client):
        """When issue_number is omitted, the first matching assignment is returned (backward compat)."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = list(self.ASSIGNMENTS)

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({
                "headRefName": "copilot/fix-22315", "title": "Fix 22315",
                "baseRefName": "main", "isDraft": False, "state": "MERGED"})},
            {"success": True, "output": "deadbeef"},
            {"success": True, "output": json.dumps([])},
            {"success": True, "output": "https://github.com/microsoft/PowerToys/pull/998\n"},
        ]
        svc.create_clean_branch.return_value = {"success": True, "sha": "abc123"}
        svc.delete_branch.return_value = {"success": True}
        svc.close_fork_issue.return_value = {"success": True}

        resp = client.post(
            f"{PREFIX}/api/oss/signoff",
            json={"repo": "PowerToys", "pr_number": 4,
                  "origin_slug": "microsoft/PowerToys"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        # Falls back to first match (issue 22315, fork_issue_number=1)
        svc.close_fork_issue.assert_called_once_with("testuser", "PowerToys", 1)

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    def test_wrong_issue_number_returns_not_found(self, mock_svc_cls, mock_user, client):
        """When issue_number doesn't match any assignment, return error."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = list(self.ASSIGNMENTS)

        resp = client.post(
            f"{PREFIX}/api/oss/signoff",
            json={"repo": "PowerToys", "pr_number": 5,
                  "origin_slug": "microsoft/PowerToys", "issue_number": 99999},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is False
        assert data["error"] == "Assignment not found"


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
            "output": "https://github.com/fastify/fastify/pull/123\n",
        }

        resp = client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "fastify/fastify",
                "repo": "fastify",
                "branch": "fix-docs",
                "title": "Fix docs",
                "body": "## Summary\nFixes docs",
                "base_branch": "main",
            },
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert data["pr_url"] == "https://github.com/fastify/fastify/pull/123"
        svc.save_submitted_pr.assert_called_once_with(
            "fastify/fastify", "https://github.com/fastify/fastify/pull/123", "Fix docs"
        )
        svc.remove_ready_to_submit.assert_called_once_with("fastify/fastify", "fix-docs")

    @patch("routes.oss_routes_stage5.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage5.OSSService")
    @patch("routes.oss_routes_stage5.run_gh_command")
    def test_submit_generates_default_body_when_not_provided(self, mock_gh, mock_svc_cls, mock_user, client):
        """Tests the 'if not body' branch — route should call format_upstream_pr_body."""
        svc = mock_svc_cls.return_value
        svc.get_ready_to_submit.return_value = [
            {"origin_slug": "fastify/fastify", "branch": "fix-docs", "issue_number": 42}
        ]
        mock_gh.return_value = {
            "success": True,
            "output": "https://github.com/fastify/fastify/pull/123\n",
        }

        client.post(
            f"{PREFIX}/api/oss/submit-to-origin",
            json={
                "origin_slug": "fastify/fastify",
                "repo": "fastify",
                "branch": "fix-docs",
                "title": "Fix docs",
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
            json={"origin_slug": "fastify/fastify"},
            content_type="application/json",
        )

        assert resp.get_json()["success"] is False
