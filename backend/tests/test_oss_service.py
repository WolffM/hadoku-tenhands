"""Tests for OSSService — watchlist, tracking, fork management, agent context, and claims."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService, OSS_DATA_DIR, _load_json, _save_json


@pytest.fixture(autouse=True)
def clean_watchlist(tmp_path, monkeypatch):
    """Point OSS_DATA_DIR to a temp directory for each test."""
    monkeypatch.setattr("services.oss_service.OSS_DATA_DIR", str(tmp_path))
    # Also patch the instance's data_dir attribute
    yield tmp_path


class TestLocalWatchlist:
    """Tests for get/add/remove_local_watchlist."""

    def test_empty_watchlist_returns_empty_list(self, clean_watchlist):
        svc = OSSService()
        svc.data_dir = str(clean_watchlist)
        assert _load_json("watchlist.json") == []

    def test_add_to_watchlist(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("fastify", "fastify")

        items = svc.get_local_watchlist()
        assert len(items) == 1
        assert items[0]["owner"] == "fastify"
        assert items[0]["repo"] == "fastify"
        assert items[0]["slug"] == "fastify-fastify"
        assert "added_at" in items[0]

    def test_add_deduplication(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("vercel", "next.js")
        svc.add_to_local_watchlist("vercel", "next.js")

        items = svc.get_local_watchlist()
        assert len(items) == 1

    def test_add_multiple_repos(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("fastify", "fastify")
        svc.add_to_local_watchlist("vercel", "next.js")

        items = svc.get_local_watchlist()
        assert len(items) == 2
        slugs = {i["slug"] for i in items}
        assert slugs == {"fastify-fastify", "vercel-next.js"}

    def test_remove_existing_repo(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("fastify", "fastify")
        svc.add_to_local_watchlist("vercel", "next.js")

        svc.remove_from_local_watchlist("fastify", "fastify")

        items = svc.get_local_watchlist()
        assert len(items) == 1
        assert items[0]["owner"] == "vercel"

    def test_remove_nonexistent_repo(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("fastify", "fastify")

        # Removing non-existent repo should not error
        svc.remove_from_local_watchlist("vercel", "next.js")

        items = svc.get_local_watchlist()
        assert len(items) == 1

    def test_remove_from_empty_watchlist(self, clean_watchlist):
        svc = OSSService()
        # Should not error on empty list
        svc.remove_from_local_watchlist("fastify", "fastify")
        assert svc.get_local_watchlist() == []

    def test_slug_format_uses_hyphen(self, clean_watchlist):
        """Slug should use hyphen between owner and repo for aggregator compatibility."""
        svc = OSSService()
        svc.add_to_local_watchlist("my-org", "my-repo")

        items = svc.get_local_watchlist()
        assert items[0]["slug"] == "my-org-my-repo"

    def test_owner_repo_stored_separately(self, clean_watchlist):
        """Owner and repo stored as separate fields to avoid slug ambiguity."""
        svc = OSSService()
        svc.add_to_local_watchlist("vercel", "next.js")

        items = svc.get_local_watchlist()
        assert items[0]["owner"] == "vercel"
        assert items[0]["repo"] == "next.js"
        # Slug is hyphenated — can't be split back to owner/repo unambiguously
        assert items[0]["slug"] == "vercel-next.js"

    def test_watchlist_persists_to_json_file(self, clean_watchlist):
        svc = OSSService()
        svc.add_to_local_watchlist("fastify", "fastify")

        # Read the file directly
        path = os.path.join(str(clean_watchlist), "watchlist.json")
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["owner"] == "fastify"


class TestSubmittedPRs:
    """Tests for submitted PR tracking (M3)."""

    def test_save_submitted_pr_parses_pr_number(self, clean_watchlist):
        svc = OSSService()
        svc.save_submitted_pr(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/123",
            "Fix bug",
        )

        items = svc.get_submitted_prs()
        assert len(items) == 1
        assert items[0]["pr_number"] == 123
        assert items[0]["state"] == "open"
        assert items[0]["review_decision"] is None
        assert items[0]["merged_at"] is None
        assert items[0]["last_polled_at"] is None

    def test_save_submitted_pr_handles_invalid_url(self, clean_watchlist):
        svc = OSSService()
        svc.save_submitted_pr("org/repo", "not-a-url", "Title")

        items = svc.get_submitted_prs()
        assert len(items) == 1
        assert items[0]["pr_number"] is None

    def test_update_submitted_prs_overwrites(self, clean_watchlist):
        svc = OSSService()
        svc.save_submitted_pr(
            "fastify/fastify",
            "https://github.com/fastify/fastify/pull/100",
            "Fix bug",
        )

        # Update state to merged
        items = svc.get_submitted_prs()
        items[0]["state"] = "merged"
        items[0]["merged_at"] = "2026-02-19T00:00:00Z"
        svc.update_submitted_prs(items)

        reloaded = svc.get_submitted_prs()
        assert len(reloaded) == 1
        assert reloaded[0]["state"] == "merged"
        assert reloaded[0]["merged_at"] == "2026-02-19T00:00:00Z"

    def test_multiple_submitted_prs(self, clean_watchlist):
        svc = OSSService()
        svc.save_submitted_pr("a/b", "https://github.com/a/b/pull/1", "PR 1")
        svc.save_submitted_pr("c/d", "https://github.com/c/d/pull/2", "PR 2")

        items = svc.get_submitted_prs()
        assert len(items) == 2
        assert items[0]["pr_number"] == 1
        assert items[1]["pr_number"] == 2


class TestSelectedIssues:
    """Tests for issue selection tracking."""

    def test_select_issue_adds_to_list(self, clean_watchlist):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        items = svc.get_selected_issues()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["issue_number"] == 42
        assert "selected_at" in items[0]

    def test_select_issue_deduplicates(self, clean_watchlist):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        items = svc.get_selected_issues()
        assert len(items) == 1

    def test_find_selected_issue_returns_match(self, clean_watchlist):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        found = svc.find_selected_issue("fastify/fastify", 42)
        assert found is not None
        assert found["issue_number"] == 42

    def test_find_selected_issue_returns_none(self, clean_watchlist):
        svc = OSSService()
        assert svc.find_selected_issue("fastify/fastify", 99) is None


class TestAssignments:
    """Tests for assignment tracking and dedup."""

    def test_save_assignment(self, clean_watchlist):
        svc = OSSService()
        svc.save_assignment("fastify", "fastify", 42, 1, "https://github.com/testuser/fastify/issues/1")

        items = svc.get_assigned_issues()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["repo"] == "fastify"
        assert items[0]["fork_issue_number"] == 1
        assert "assigned_at" in items[0]

    def test_find_assignment_returns_match(self, clean_watchlist):
        svc = OSSService()
        svc.save_assignment("fastify", "fastify", 42, 1, "https://github.com/testuser/fastify/issues/1")

        found = svc.find_assignment("fastify/fastify", 42)
        assert found is not None
        assert found["fork_issue_number"] == 1

    def test_find_assignment_returns_none(self, clean_watchlist):
        svc = OSSService()
        assert svc.find_assignment("fastify/fastify", 99) is None


class TestReadyToSubmit:
    """Tests for ready-to-submit tracking."""

    def test_save_ready_to_submit(self, clean_watchlist):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")

        items = svc.get_ready_to_submit()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["branch"] == "fix-docs"
        assert items[0]["base_branch"] == "main"
        assert "merged_at" in items[0]

    def test_remove_ready_to_submit(self, clean_watchlist):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")
        svc.save_ready_to_submit("vercel/next.js", "next.js", "fix-routing", "Fix routing", "canary")

        svc.remove_ready_to_submit("fastify/fastify", "fix-docs")

        items = svc.get_ready_to_submit()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "vercel/next.js"

    def test_remove_nonexistent_ready_to_submit(self, clean_watchlist):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")

        svc.remove_ready_to_submit("nonexistent/repo", "branch")

        items = svc.get_ready_to_submit()
        assert len(items) == 1


class TestForkManagement:
    """Tests for fork_repo, sync_fork, check_fork_exists, wait_for_fork."""

    @patch("services.oss_service.run_gh_command")
    def test_check_fork_exists_true(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": '{"name": "fastify"}'}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "fastify") is True

    @patch("services.oss_service.run_gh_command")
    def test_check_fork_exists_false(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "fastify") is False

    @patch("services.oss_service.run_gh_command")
    def test_wait_for_fork_succeeds_immediately(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "fastify", timeout=6, interval=1)
        assert result is True

    @patch("services.oss_service.time.sleep")
    @patch("services.oss_service.run_gh_command")
    def test_wait_for_fork_retries_then_succeeds(self, mock_gh, mock_sleep):
        mock_gh.side_effect = [
            {"success": False, "error": "Not found"},
            {"success": False, "error": "Not found"},
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "fastify", timeout=9, interval=3)
        assert result is True
        assert mock_sleep.call_count == 2

    @patch("services.oss_service.time.sleep")
    @patch("services.oss_service.run_gh_command")
    def test_wait_for_fork_timeout(self, mock_gh, mock_sleep):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "fastify", timeout=6, interval=3)
        assert result is False


class TestBuildAgentContext:
    """Tests for build_agent_context — markdown body generation for fork issues."""

    @patch("services.oss_service.run_gh_command")
    def test_basic_context_without_dossier(self, mock_gh):
        # First call: issue view, second call: CONTRIBUTING.md
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Original issue body", "labels": []})},
            {"success": False, "output": ""},  # No CONTRIBUTING.md
        ]
        svc = OSSService()

        body = svc.build_agent_context("fastify", "fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        assert "fastify/fastify" in body
        assert "#42" in body
        assert "Fix docs" in body
        assert "Original issue body" in body
        assert "Instructions" in body

    @patch("services.oss_service.run_gh_command")
    def test_context_with_contributing_md(self, mock_gh):
        import base64
        contrib_content = base64.b64encode(b"# Contributing\nPlease follow our style guide.").decode()

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": True, "output": contrib_content},
        ]
        svc = OSSService()

        body = svc.build_agent_context("fastify", "fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        assert "CONTRIBUTING.md" in body
        assert "style guide" in body

    @patch("services.oss_service.run_gh_command")
    def test_context_with_dossier_contribution_rules(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})}
        svc = OSSService()

        dossier = {"contributionRules": "Always add tests", "successPatterns": "Keep PRs small"}
        body = svc.build_agent_context("fastify", "fastify", 42, "Fix", "https://example.com", dossier)

        assert "Contribution Rules" in body
        assert "Always add tests" in body
        assert "Successful PRs" in body
        assert "Keep PRs small" in body
        # Should NOT fetch CONTRIBUTING.md when dossier is provided
        assert mock_gh.call_count == 1  # Only the issue view call

    @patch("services.oss_service.run_gh_command")
    def test_context_with_dossier_quirks(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})}
        svc = OSSService()

        dossier = {
            "detectedQuirks": [
                {"type": "CLA required", "description": "Must sign CLA before merge", "impact": "blocker", "evidence": "CONTRIBUTING.md line 5"},
                {"type": "Commit format", "description": "Use conventional commits", "impact": "important"},
                {"type": "Optional", "description": "Changelog appreciated", "impact": "minor"},
            ]
        }
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", dossier)

        assert "Quirks & Warnings" in body
        assert "[BLOCKER]" in body
        assert "[WARNING]" in body
        assert "[NOTE]" in body
        assert "CLA required" in body
        assert "Evidence: CONTRIBUTING.md line 5" in body

    @patch("services.oss_service.run_gh_command")
    def test_contributing_md_truncated_at_3000_chars(self, mock_gh):
        """CONTRIBUTING.md content longer than 3000 chars should be truncated."""
        import base64
        long_content = "x" * 5000
        contrib_encoded = base64.b64encode(long_content.encode()).decode()

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": True, "output": contrib_encoded},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "CONTRIBUTING.md" in body
        # The 5000-char content should be truncated to 3000
        assert "x" * 3000 in body
        assert "x" * 3001 not in body

    @patch("services.oss_service.run_gh_command")
    def test_context_with_empty_dossier(self, mock_gh):
        """Dossier with no relevant fields should not add extra sections."""
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", {})

        assert "Contribution Rules" not in body
        assert "Quirks" not in body


class TestClaimManagement:
    """Tests for report_claim and report_unclaim."""

    @patch("services.oss_service._call_aggregator")
    def test_report_claim_converts_slug_format(self, mock_agg):
        svc = OSSService()
        svc.report_claim("fastify/fastify", "github-fastify-fastify-42", "testuser", "https://example.com/issues/1")

        mock_agg.assert_called_once_with(
            "/recon/fastify-fastify/claim",
            method="POST",
            data={
                "issueId": "github-fastify-fastify-42",
                "claimedBy": "testuser",
                "forkIssueUrl": "https://example.com/issues/1",
            },
        )

    @patch("services.oss_service._call_aggregator")
    def test_report_unclaim_converts_slug_format(self, mock_agg):
        svc = OSSService()
        svc.report_unclaim("fastify/fastify", "github-fastify-fastify-42")

        mock_agg.assert_called_once_with(
            "/recon/fastify-fastify/unclaim",
            method="POST",
            data={"issueId": "github-fastify-fastify-42"},
        )

    @patch("services.oss_service._call_aggregator")
    def test_report_claim_graceful_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()

        # Should not raise
        svc.report_claim("org/repo", "id", "user", "url")

    @patch("services.oss_service._call_aggregator")
    def test_report_unclaim_graceful_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()

        # Should not raise
        svc.report_unclaim("org/repo", "id")
