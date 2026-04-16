"""Tests for OSS routes — Stage 4: Review on Fork."""

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
            {"origin_slug": "acme-corp/widget-api", "repo": "widget-api"},
        ]

        mock_gh.return_value = {
            "success": True,
            "output": json.dumps([{
                "number": 1, "title": "Fix docs",
                "url": "https://github.com/testuser/widget-api/pull/1",
                "headRefName": "fix-docs", "additions": 10, "deletions": 2,
                "changedFiles": 1, "reviewDecision": None, "isDraft": False,
                "createdAt": "2026-02-19T00:00:00Z",
            }]),
        }

        resp = client.get(f"{PREFIX}/api/oss/stage4-fork-prs")
        data = resp.get_json()

        assert len(data["prs"]) == 1
        assert data["prs"][0]["repo"] == "widget-api"
        assert data["prs"][0]["originSlug"] == "acme-corp/widget-api"

    @patch("routes.oss_routes_stage4.get_authenticated_user", return_value="testuser")
    @patch("routes.oss_routes_stage4.OSSService")
    @patch("routes.oss_routes_stage4.run_gh_command")
    def test_deduplicates_forked_repos_via_set(self, mock_gh, mock_svc_cls, mock_user, client):
        """Two assignments for same repo should only fetch PRs once."""
        svc = mock_svc_cls.return_value
        svc.get_assigned_issues.return_value = [
            {"origin_slug": "acme-corp/widget-api", "repo": "widget-api"},
            {"origin_slug": "acme-corp/widget-api", "repo": "widget-api"},
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
            json={"repo": "widget-api", "pr_number": 1},
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
            json={"repo": "widget-api"},
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
            json={"repo": "widget-api"},
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
            {"origin_slug": "acme-corp/widget-api", "repo": "widget-api", "issue_number": 42,
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
            json={"repo": "widget-api", "pr_number": 1, "origin_slug": "acme-corp/widget-api"},
            content_type="application/json",
        )
        data = resp.get_json()

        assert data["success"] is True
        assert "clean_branch" in data
        assert data["clean_branch"].startswith("fix/42-")
        svc.create_clean_branch.assert_called_once()
        svc.delete_branch.assert_called_once_with("testuser", "widget-api", "copilot/fix-docs")
        svc.close_fork_issue.assert_called_once_with("testuser", "widget-api", 3)
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
            {"origin_slug": "acme-corp/widget-api", "repo": "widget-api", "issue_number": 10,
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
            json={"repo": "widget-api", "pr_number": 1, "origin_slug": "acme-corp/widget-api"},
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
            json={"repo": "widget-api", "pr_number": 1, "origin_slug": "acme-corp/widget-api"},
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
            json={"repo": "widget-api", "pr_number": 1},
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
            # Step 1b: actionability — issue state check
            {"success": True, "output": json.dumps({"state": "open", "locked": False})},
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
            # Step 1b: actionability — issue state check
            {"success": True, "output": json.dumps({"state": "open", "locked": False})},
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
