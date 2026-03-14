"""Tests for OSSService — tracking, fork management, agent context, and claims."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService, OSS_DATA_DIR, _load_json, _save_json, _sanitize_upstream_refs


@pytest.fixture(autouse=True)
def clean_data_dir(tmp_path, monkeypatch):
    """Point OSS_DATA_DIR to a temp directory for each test."""
    monkeypatch.setattr("services.oss_service.OSS_DATA_DIR", str(tmp_path))
    yield tmp_path


class TestSubmittedPRs:
    """Tests for submitted PR tracking (M3)."""

    def test_save_submitted_pr_parses_pr_number(self, clean_data_dir):
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

    def test_save_submitted_pr_handles_invalid_url(self, clean_data_dir):
        svc = OSSService()
        svc.save_submitted_pr("org/repo", "not-a-url", "Title")

        items = svc.get_submitted_prs()
        assert len(items) == 1
        assert items[0]["pr_number"] is None

    def test_update_submitted_prs_overwrites(self, clean_data_dir):
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

    def test_multiple_submitted_prs(self, clean_data_dir):
        svc = OSSService()
        svc.save_submitted_pr("a/b", "https://github.com/a/b/pull/1", "PR 1")
        svc.save_submitted_pr("c/d", "https://github.com/c/d/pull/2", "PR 2")

        items = svc.get_submitted_prs()
        assert len(items) == 2
        assert items[0]["pr_number"] == 1
        assert items[1]["pr_number"] == 2


class TestSelectedIssues:
    """Tests for issue selection tracking."""

    def test_select_issue_adds_to_list(self, clean_data_dir):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        items = svc.get_selected_issues()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["issue_number"] == 42
        assert "selected_at" in items[0]

    def test_select_issue_deduplicates(self, clean_data_dir):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        items = svc.get_selected_issues()
        assert len(items) == 1

    def test_find_selected_issue_returns_match(self, clean_data_dir):
        svc = OSSService()
        svc.select_issue("fastify/fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        found = svc.find_selected_issue("fastify/fastify", 42)
        assert found is not None
        assert found["issue_number"] == 42

    def test_find_selected_issue_returns_none(self, clean_data_dir):
        svc = OSSService()
        assert svc.find_selected_issue("fastify/fastify", 99) is None


class TestAssignments:
    """Tests for assignment tracking and dedup."""

    def test_save_assignment(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("fastify", "fastify", 42, 1, "https://github.com/testuser/fastify/issues/1")

        items = svc.get_assigned_issues()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["repo"] == "fastify"
        assert items[0]["fork_issue_number"] == 1
        assert "assigned_at" in items[0]

    def test_find_assignment_returns_match(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("fastify", "fastify", 42, 1, "https://github.com/testuser/fastify/issues/1")

        found = svc.find_assignment("fastify/fastify", 42)
        assert found is not None
        assert found["fork_issue_number"] == 1

    def test_find_assignment_returns_none(self, clean_data_dir):
        svc = OSSService()
        assert svc.find_assignment("fastify/fastify", 99) is None


class TestReadyToSubmit:
    """Tests for ready-to-submit tracking."""

    def test_save_ready_to_submit(self, clean_data_dir):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")

        items = svc.get_ready_to_submit()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "fastify/fastify"
        assert items[0]["branch"] == "fix-docs"
        assert items[0]["base_branch"] == "main"
        assert "merged_at" in items[0]

    def test_remove_ready_to_submit(self, clean_data_dir):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")
        svc.save_ready_to_submit("vercel/next.js", "next.js", "fix-routing", "Fix routing", "canary")

        svc.remove_ready_to_submit("fastify/fastify", "fix-docs")

        items = svc.get_ready_to_submit()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "vercel/next.js"

    def test_remove_nonexistent_ready_to_submit(self, clean_data_dir):
        svc = OSSService()
        svc.save_ready_to_submit("fastify/fastify", "fastify", "fix-docs", "Fix docs", "main")

        svc.remove_ready_to_submit("nonexistent/repo", "branch")

        items = svc.get_ready_to_submit()
        assert len(items) == 1


class TestForkManagement:
    """Tests for fork_repo, sync_fork, check_fork_exists, wait_for_fork."""

    @patch("services.oss_fork.run_gh_command")
    def test_check_fork_exists_true(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": '{"name": "fastify"}'}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "fastify") is True

    @patch("services.oss_fork.run_gh_command")
    def test_check_fork_exists_false(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "fastify") is False

    @patch("services.oss_fork.run_gh_command")
    def test_wait_for_fork_succeeds_immediately(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "fastify", timeout=6, interval=1)
        assert result is True

    @patch("services.oss_fork.time.sleep")
    @patch("services.oss_fork.run_gh_command")
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

    @patch("services.oss_fork.time.sleep")
    @patch("services.oss_fork.run_gh_command")
    def test_wait_for_fork_timeout(self, mock_gh, mock_sleep):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "fastify", timeout=6, interval=3)
        assert result is False


class TestBuildAgentContext:
    """Tests for build_agent_context — markdown body generation for fork issues."""

    @patch("services.oss_context.run_gh_command")
    def test_basic_context_without_dossier(self, mock_gh):
        # First call: issue view, second call: CONTRIBUTING.md
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Original issue body", "labels": []})},
            {"success": False, "output": ""},  # No CONTRIBUTING.md
        ]
        svc = OSSService()

        body = svc.build_agent_context("fastify", "fastify", 42, "Fix docs", "https://github.com/fastify/fastify/issues/42")

        assert "fastify/fastify" in body
        assert "Fix docs" in body
        assert "Original issue body" in body
        # Workflow section comes FIRST (before issue context)
        assert body.startswith("## Mandatory Workflow")
        assert body.index("Mandatory Workflow") < body.index("Issue Context")
        # Must NOT contain issue number reference (would trigger GitHub cross-reference)
        assert "#42" not in body

    @patch("services.oss_context.run_gh_command")
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

    @patch("services.oss_context.run_gh_command")
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

    @patch("services.oss_context.run_gh_command")
    def test_context_with_quirks_from_issue_brief(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})}
        svc = OSSService()

        issue_brief = {
            "repoHealth": {
                "detectedQuirks": [
                    {"type": "CLA required", "description": "Must sign CLA before merge", "impact": "blocker", "evidence": "CONTRIBUTING.md line 5"},
                    {"type": "Commit format", "description": "Use conventional commits", "impact": "important"},
                    {"type": "Optional", "description": "Changelog appreciated", "impact": "minor"},
                ],
            }
        }
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com",
                                       issue_brief=issue_brief)

        assert "Quirks & Warnings" in body
        assert "[BLOCKER]" in body
        assert "[WARNING]" in body
        assert "[NOTE]" in body
        assert "CLA required" in body
        assert "Evidence: CONTRIBUTING.md line 5" in body

    @patch("services.oss_context.run_gh_command")
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

    @patch("services.oss_context.run_gh_command")
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


class TestContextNewDossierSections:
    """Tests for antiPatterns, environmentSetup, widened gate, and dossier_completeness."""

    @patch("services.oss_context.run_gh_command")
    def test_anti_patterns_with_real_content(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {
            "contributionRules": "Follow the style guide",
            "antiPatterns": "## Anti-Patterns\n\n- Failing CI\n- No tests\n",
        }
        completeness = {"antiPatterns": True}
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com",
                                       dossier, dossier_completeness=completeness)
        assert "Common Rejection Reasons" in body
        assert "Failing CI" in body
        assert "No tests" in body

    @patch("services.oss_context.run_gh_command")
    def test_anti_patterns_skipped_when_boilerplate(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {
            "contributionRules": "Some rules",
            "antiPatterns": "## Anti-Patterns\n\nNo significant anti-patterns detected.\n",
        }
        completeness = {"antiPatterns": False}
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com",
                                       dossier, dossier_completeness=completeness)
        assert "Common Rejection Reasons" not in body

    @patch("services.oss_context.run_gh_command")
    def test_anti_patterns_skipped_when_no_completeness(self, mock_gh):
        """antiPatterns should be skipped when no completeness data is provided (safe default)."""
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {
            "antiPatterns": "## Anti-Patterns\n\n- Failing CI\n",
        }
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", dossier)
        assert "Common Rejection Reasons" not in body

    @patch("services.oss_context.run_gh_command")
    def test_environment_setup_included(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {"environmentSetup": "Run npm install && npm test"}
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", dossier)
        assert "Environment & Setup" in body
        assert "npm install" in body

    @patch("services.oss_context.run_gh_command")
    def test_dev_environment_fallback(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {"devEnvironment": "go mod tidy && go test ./..."}
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", dossier)
        assert "Environment & Setup" in body
        assert "go mod tidy" in body

    @patch("services.oss_context.run_gh_command")
    def test_widened_gate_enters_tier2_on_env_setup_alone(self, mock_gh):
        """Tier 2 should activate even if only environmentSetup is present."""
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {"environmentSetup": "pip install -e ."}
        body, metadata = svc.build_agent_context(
            "org", "repo", 1, "Fix", "https://example.com", dossier, return_metadata=True)
        assert metadata["dossier_used"] is True
        assert "aggregator-dossier" in metadata["sources"]
        # Should NOT have CONTRIBUTING.md since Tier 2 was used
        assert "CONTRIBUTING.md" not in body

    @patch("services.oss_context.run_gh_command")
    def test_dossier_completeness_in_metadata(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {"contributionRules": "rules"}
        completeness = {"overview": True, "contributionRules": True, "score": 2, "total": 6}
        body, metadata = svc.build_agent_context(
            "org", "repo", 1, "Fix", "https://example.com", dossier,
            return_metadata=True, dossier_completeness=completeness)
        assert metadata["dossier_completeness"] == completeness
        assert metadata["dossier_completeness"]["score"] == 2

    @patch("services.oss_context.run_gh_command")
    def test_dossier_completeness_absent_when_not_provided(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "body", "labels": []})}
        svc = OSSService()
        dossier = {"contributionRules": "rules"}
        body, metadata = svc.build_agent_context(
            "org", "repo", 1, "Fix", "https://example.com", dossier, return_metadata=True)
        assert "dossier_completeness" not in metadata


class TestIssueBrief:
    """Tests for get_issue_brief and issue-brief integration with build_agent_context."""

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_returns_data(self, mock_agg):
        mock_agg.return_value = {
            "success": True,
            "data": {
                "issue": {"id": "github-org-repo-42", "cvs": 85},
                "repoHealth": {"overallViability": 80},
                "brief": "# Task: Fix bug\n\nContribution rules...",
            },
        }
        svc = OSSService()
        result = svc.get_issue_brief("org-repo", "github-org-repo-42")
        assert result is not None
        assert result["brief"] == "# Task: Fix bug\n\nContribution rules..."

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_returns_none_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()
        result = svc.get_issue_brief("org-repo", "github-org-repo-42")
        assert result is None

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_returns_none_on_error_response(self, mock_agg):
        mock_agg.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()
        result = svc.get_issue_brief("org-repo", "github-org-repo-42")
        assert result is None

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_returns_none_on_pending(self, mock_agg):
        """When pre-computed data is missing, aggregator returns status: pending."""
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}}
        svc = OSSService()
        result = svc.get_issue_brief("org-repo", "github-org-repo-42")
        assert result is None

    def test_context_with_issue_brief_uses_brief_as_primary(self):
        """When brief is available, workflow comes first, then the brief content."""
        svc = OSSService()

        issue_brief = {
            "issue": {"id": "github-org-repo-42", "body": "Original issue body"},
            "repoHealth": {},
            "brief": "# Task: Fix bug\n\n## CRITICAL RULES\n- No cross refs\n\n## Issue Details\nThe bug details.",
        }
        body = svc.build_agent_context("org", "repo", 42, "Fix", "https://example.com", issue_brief=issue_brief)

        # Mandatory Workflow comes FIRST
        assert body.startswith("## Mandatory Workflow")
        # Brief content appears after the workflow section
        assert "CRITICAL RULES" in body
        assert "The bug details" in body
        # Phase-gate language is present
        assert "Do NOT proceed to Phase 2" in body
        assert "Do NOT commit until all tests pass" in body
        assert "If You Cannot Complete This Task" in body
        # Workflow appears before brief content
        assert body.index("Mandatory Workflow") < body.index("# Task: Fix bug")

    def test_context_with_issue_brief_skips_dossier(self):
        svc = OSSService()

        dossier = {"contributionRules": "Dossier rules"}
        issue_brief = {"brief": "Brief rules", "issue": {"body": ""}}
        body = svc.build_agent_context("org", "repo", 42, "Fix", "https://example.com", dossier, issue_brief)

        # issue_brief takes priority over dossier
        assert "Brief rules" in body
        assert "Dossier rules" not in body

    @patch("services.oss_context.run_gh_command")
    def test_context_falls_back_to_dossier_when_brief_missing(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})}
        svc = OSSService()

        dossier = {"contributionRules": "Dossier rules"}
        body = svc.build_agent_context("org", "repo", 42, "Fix", "https://example.com", dossier, issue_brief=None)

        assert "Dossier rules" in body

    def test_context_return_metadata_with_brief(self):
        svc = OSSService()

        issue_brief = {"brief": "Brief content", "issue": {"body": "Issue body"}}
        body, metadata = svc.build_agent_context(
            "org", "repo", 42, "Fix", "https://example.com",
            issue_brief=issue_brief, return_metadata=True
        )

        assert isinstance(body, str)
        assert isinstance(metadata, dict)
        assert metadata["issue_brief_used"] is True
        assert metadata["issue_body_fetched"] is True
        assert "aggregator-issue-brief" in metadata["sources"]

    def test_brief_with_tool_detected_in_issue_body(self):
        """When brief is available and issue body has a tool table, TDD steps are tool-specific."""
        svc = OSSService()

        issue_brief = {
            "issue": {"body": "| Tool | `ruff` |\n| Rule | F841 |"},
            "brief": "# Task: Fix ruff issue\n\n## Issue Details\nRuff finding.",
        }
        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", issue_brief=issue_brief)

        assert "Run `ruff`" in body
        assert "Re-run `ruff`" in body

    def test_brief_no_gh_cli_calls(self):
        """When brief is available, no gh CLI calls should be made."""
        svc = OSSService()

        issue_brief = {
            "issue": {"body": "Issue body"},
            "brief": "# Task\n\nBrief content here.",
        }
        # No mock_gh needed — if it tries to call run_gh_command it would fail
        body = svc.build_agent_context("org", "repo", 42, "Fix", "https://example.com", issue_brief=issue_brief)

        assert "Brief content here" in body


class TestToolDetection:
    """Tests for _detect_tool_from_issue helper."""

    def test_detects_ruff_from_vibecheck_table(self):
        from services.oss_service import _detect_tool_from_issue
        body = "| Tool | `ruff` |\n| Rule | F841 |"
        assert _detect_tool_from_issue(body) == "ruff"

    def test_detects_bandit_from_vibecheck_table(self):
        from services.oss_service import _detect_tool_from_issue
        body = "| Tool | `bandit` |"
        assert _detect_tool_from_issue(body) == "bandit"

    def test_detects_mypy(self):
        from services.oss_service import _detect_tool_from_issue
        body = "| Tool | `mypy` |"
        assert _detect_tool_from_issue(body) == "mypy"

    def test_detects_checkov(self):
        from services.oss_service import _detect_tool_from_issue
        body = "| Tool | `checkov` |"
        assert _detect_tool_from_issue(body) == "checkov"

    def test_detects_osv_scanner(self):
        from services.oss_service import _detect_tool_from_issue
        body = "| Tool | `osv-scanner` |"
        assert _detect_tool_from_issue(body) == "osv-scanner"

    def test_returns_none_for_no_tool(self):
        from services.oss_service import _detect_tool_from_issue
        body = "This is a regular issue with no tool table."
        assert _detect_tool_from_issue(body) is None

    def test_returns_none_for_empty_body(self):
        from services.oss_service import _detect_tool_from_issue
        assert _detect_tool_from_issue("") is None
        assert _detect_tool_from_issue(None) is None


class TestTDDInstructions:
    """Tests for TDD workflow instructions in build_agent_context."""

    @patch("services.oss_context.run_gh_command")
    def test_tool_specific_reproduce_step(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "| Tool | `ruff` |", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "Run `ruff`" in body
        assert "Re-run `ruff`" in body

    @patch("services.oss_context.run_gh_command")
    def test_generic_reproduce_when_no_tool_detected(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Just a plain bug.", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "Write a failing test" in body
        assert "Re-run the test or tool" in body

    @patch("services.oss_context.run_gh_command")
    def test_tdd_workflow_section_present(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "Mandatory Workflow" in body
        assert "Phase 1: Reproduce" in body
        assert "Implement the fix" in body
        assert "Phase 3: Verify" in body
        assert "Do NOT proceed to Phase 2" in body
        assert "Do NOT commit until all tests pass" in body

    @patch("services.oss_context.run_gh_command")
    def test_rules_section_present(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "DO NOT" in body
        assert "modify or weaken a test" in body
        assert "disable linter rules" in body
        assert "GitHub MCP tools" in body
        assert "__pycache__" in body

    @patch("services.oss_context.run_gh_command")
    def test_failure_reporting_section_present(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com")

        assert "If You Cannot Complete This Task" in body
        assert "Add a comment on this issue" in body
        assert "Do **NOT** create a PR with no meaningful changes" in body

    @patch("services.oss_context.run_gh_command")
    def test_self_owned_pr_target_text(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", is_self_owned=True)

        assert "reviewed as a PR on" in body

    @patch("services.oss_context.run_gh_command")
    def test_third_party_pr_target_text(self, mock_gh):
        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": False, "output": ""},
        ]
        svc = OSSService()

        body = svc.build_agent_context("org", "repo", 1, "Fix", "https://example.com", is_self_owned=False)

        assert "submitted as a PR to" in body


class TestSelfOwnedAssignment:
    """Tests for is_self_owned field in assignments."""

    def test_save_assignment_with_self_owned_true(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("me", "myrepo", 42, 1, "https://example.com/issues/1", is_self_owned=True)

        items = svc.get_assigned_issues()
        assert len(items) == 1
        assert items[0]["is_self_owned"] is True

    def test_save_assignment_default_is_self_owned_false(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("other", "repo", 42, 1, "https://example.com/issues/1")

        items = svc.get_assigned_issues()
        assert len(items) == 1
        assert items[0]["is_self_owned"] is False


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


class TestPendingStatus:
    """Tests for handling aggregator 'pending' status when pre-computed data is missing."""

    @patch("services.oss_service._call_aggregator")
    def test_get_scored_issues_returns_empty_on_pending(self, mock_agg):
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}}
        svc = OSSService()
        result = svc.get_scored_issues("org-repo")
        assert result == []

    @patch("services.oss_service._call_aggregator")
    def test_get_dossier_returns_none_on_pending(self, mock_agg):
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}}
        svc = OSSService()
        result = svc.get_dossier("org-repo")
        assert result is None

    @patch("services.oss_service._call_aggregator")
    def test_trigger_compute_calls_correct_endpoint(self, mock_agg):
        mock_agg.return_value = {"success": True}
        svc = OSSService()
        result = svc.trigger_compute("org-repo")
        assert result is True
        mock_agg.assert_called_once_with(
            "/recon/org-repo/compute", method="POST", timeout=30
        )

    @patch("services.oss_service._call_aggregator")
    def test_trigger_compute_graceful_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()
        result = svc.trigger_compute("org-repo")
        assert result is False


class TestIncludeMeta:
    """Tests for include_meta parameter on aggregator methods."""

    _META = {"scraped_at": "2026-02-24T00:00:00Z", "computed_at": "2026-02-26T00:00:00Z", "served_at": "2026-02-26T01:00:00Z"}

    @patch("services.oss_service._call_aggregator")
    def test_get_dossier_include_meta_returns_tuple(self, mock_agg):
        mock_agg.return_value = {
            "success": True,
            "data": {"slug": "org-repo", "sections": {"overview": "hi"}},
            "_meta": self._META,
        }
        svc = OSSService()
        data, meta = svc.get_dossier("org-repo", include_meta=True)
        assert data["slug"] == "org-repo"
        assert meta == self._META

    @patch("services.oss_service._call_aggregator")
    def test_get_dossier_default_returns_bare_data(self, mock_agg):
        mock_agg.return_value = {
            "success": True,
            "data": {"slug": "org-repo", "sections": {}},
            "_meta": self._META,
        }
        svc = OSSService()
        result = svc.get_dossier("org-repo")
        assert isinstance(result, dict)
        assert result["slug"] == "org-repo"

    @patch("services.oss_service._call_aggregator")
    def test_get_dossier_include_meta_pending(self, mock_agg):
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}, "_meta": self._META}
        svc = OSSService()
        data, meta = svc.get_dossier("org-repo", include_meta=True)
        assert data is None
        assert meta is None

    @patch("services.oss_service._call_aggregator")
    def test_get_scored_issues_include_meta_returns_tuple(self, mock_agg):
        issues = [{"id": "1", "cvs": 80}]
        mock_agg.return_value = {
            "success": True,
            "data": {"issues": issues},
            "_meta": self._META,
        }
        svc = OSSService()
        result_issues, meta = svc.get_scored_issues("org-repo", include_meta=True)
        assert result_issues == issues
        assert meta == self._META

    @patch("services.oss_service._call_aggregator")
    def test_get_scored_issues_default_returns_list(self, mock_agg):
        issues = [{"id": "1"}]
        mock_agg.return_value = {"success": True, "data": {"issues": issues}, "_meta": self._META}
        svc = OSSService()
        result = svc.get_scored_issues("org-repo")
        assert result == issues

    @patch("services.oss_service._call_aggregator")
    def test_get_scored_issues_include_meta_pending(self, mock_agg):
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}, "_meta": self._META}
        svc = OSSService()
        result_issues, meta = svc.get_scored_issues("org-repo", include_meta=True)
        assert result_issues == []
        assert meta is None

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_include_meta_returns_tuple(self, mock_agg):
        brief_data = {"issue": {}, "repoHealth": {}, "brief": "markdown"}
        mock_agg.return_value = {
            "success": True,
            "data": brief_data,
            "_meta": self._META,
        }
        svc = OSSService()
        data, meta = svc.get_issue_brief("org-repo", "github-org-repo-1", include_meta=True)
        assert data == brief_data
        assert meta == self._META

    @patch("services.oss_service._call_aggregator")
    def test_get_issue_brief_default_returns_bare_data(self, mock_agg):
        brief_data = {"issue": {}, "repoHealth": {}, "brief": "md"}
        mock_agg.return_value = {"success": True, "data": brief_data, "_meta": self._META}
        svc = OSSService()
        result = svc.get_issue_brief("org-repo", "github-org-repo-1")
        assert result == brief_data

    @patch("services.oss_service._call_aggregator")
    def test_get_health_returns_data(self, mock_agg):
        health_data = {
            "maintainerHealthScore": 80, "mergeAccessibilityScore": 70,
            "prPatterns": {"medianFilesChanged": 3}, "detectedQuirks": [],
            "analyzedAt": "2026-02-26T00:00:00Z",
        }
        mock_agg.return_value = {"success": True, "data": health_data, "_meta": self._META}
        svc = OSSService()
        result = svc.get_health("org-repo")
        assert result["maintainerHealthScore"] == 80
        assert result["prPatterns"]["medianFilesChanged"] == 3

    @patch("services.oss_service._call_aggregator")
    def test_get_health_include_meta(self, mock_agg):
        health_data = {"maintainerHealthScore": 80}
        mock_agg.return_value = {"success": True, "data": health_data, "_meta": self._META}
        svc = OSSService()
        data, meta = svc.get_health("org-repo", include_meta=True)
        assert data["maintainerHealthScore"] == 80
        assert meta == self._META

    @patch("services.oss_service._call_aggregator")
    def test_get_health_returns_none_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()
        assert svc.get_health("org-repo") is None

    @patch("services.oss_service._call_aggregator")
    def test_get_health_include_meta_when_aggregator_down(self, mock_agg):
        mock_agg.return_value = None
        svc = OSSService()
        data, meta = svc.get_health("org-repo", include_meta=True)
        assert data is None
        assert meta is None

    @patch("services.oss_service._call_aggregator")
    def test_get_health_pending(self, mock_agg):
        mock_agg.return_value = {"success": True, "data": {"status": "pending"}}
        svc = OSSService()
        assert svc.get_health("org-repo") is None


class TestSanitizeUpstreamRefs:
    """Tests for _sanitize_upstream_refs — preventing cross-linking to upstream repos."""

    def test_strips_github_issue_url(self):
        text = "Issue: https://github.com/reisepass/email-verifier/issues/4"
        result = _sanitize_upstream_refs(text)
        assert "https://github.com" not in result
        assert "reisepass/email-verifier issue 4" in result

    def test_strips_github_pr_url(self):
        text = "See https://github.com/fastify/fastify/pull/123 for details"
        result = _sanitize_upstream_refs(text)
        assert "https://github.com" not in result
        assert "fastify/fastify PR 123" in result

    def test_strips_cross_repo_ref(self):
        text = "This fixes reisepass/email-verifier#4"
        result = _sanitize_upstream_refs(text)
        assert "reisepass/email-verifier#4" not in result
        assert "reisepass/email-verifier issue 4" in result

    def test_neutralizes_closes_keyword(self):
        text = "Closes #4"
        result = _sanitize_upstream_refs(text)
        assert "Closes #4" not in result
        assert "Related to issue 4" in result

    def test_neutralizes_fixes_keyword(self):
        text = "Fixes #7"
        result = _sanitize_upstream_refs(text)
        assert "Fixes #7" not in result
        assert "Related to issue 7" in result

    def test_neutralizes_resolves_keyword(self):
        text = "Resolves #12"
        result = _sanitize_upstream_refs(text)
        assert "Resolves #12" not in result
        assert "Related to issue 12" in result

    def test_handles_none_input(self):
        assert _sanitize_upstream_refs(None) is None

    def test_handles_empty_string(self):
        assert _sanitize_upstream_refs("") == ""

    def test_preserves_normal_text(self):
        text = "Fix the broken test suite by updating imports"
        assert _sanitize_upstream_refs(text) == text

    def test_sanitizes_multiple_refs_in_one_string(self):
        text = (
            "Issue: https://github.com/owner/repo/issues/1\n"
            "Related: owner/repo#2\n"
            "Closes #3"
        )
        result = _sanitize_upstream_refs(text)
        assert "https://github.com" not in result
        assert "owner/repo#" not in result
        assert "Closes #3" not in result

    def test_brief_sanitization_in_context(self):
        """End-to-end: brief content with upstream URL gets sanitized in build_agent_context."""
        svc = OSSService()
        brief = {
            "brief": "# Task\n\nIssue: https://github.com/reisepass/email-verifier/issues/4\nRepo: reisepass/email-verifier",
            "issue": {"body": "test body"},
        }
        body = svc.build_agent_context(
            "reisepass", "email-verifier", 4, "Running the tests",
            "https://github.com/reisepass/email-verifier/issues/4",
            issue_brief=brief,
        )
        assert "https://github.com/reisepass/email-verifier/issues/4" not in body
        assert "reisepass/email-verifier issue 4" in body


class TestCIWorkflow:
    """Tests for ensure_ci_workflow and _build_ci_workflow."""

    def test_build_ci_workflow_go(self):
        workflow = OSSService._build_ci_workflow("Go")
        assert "go vet" in workflow
        assert "go test" in workflow
        assert "on: [push]" in workflow

    def test_build_ci_workflow_python(self):
        workflow = OSSService._build_ci_workflow("Python")
        assert "pytest" in workflow
        assert "ruff" in workflow
        assert "setup-python" in workflow

    def test_build_ci_workflow_javascript(self):
        workflow = OSSService._build_ci_workflow("JavaScript")
        assert "npm ci" in workflow
        assert "npm test" in workflow
        assert "eslint" in workflow
        assert "setup-node" in workflow

    def test_build_ci_workflow_typescript(self):
        workflow = OSSService._build_ci_workflow("TypeScript")
        assert "npm ci" in workflow
        assert "setup-node" in workflow

    def test_build_ci_workflow_unknown_language(self):
        workflow = OSSService._build_ci_workflow("Rust")
        assert "No language-specific CI configured" in workflow
        assert "checkout@v4" in workflow

    def test_build_ci_workflow_none_language(self):
        workflow = OSSService._build_ci_workflow(None)
        assert "No language-specific CI configured" in workflow

    @patch("services.oss_fork.run_gh_command")
    def test_ensure_ci_workflow_creates_new_file(self, mock_gh):
        mock_gh.side_effect = [
            # Language detection skipped (language provided)
            # Check if workflow exists — not found
            {"success": False, "output": ""},
            # PUT to create file
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()
        svc.ensure_ci_workflow("myuser", "myrepo", language="Go")

        # Should have called PUT without sha
        put_call = mock_gh.call_args_list[-1]
        cmd = put_call[0][0]
        assert "ci.yml" in " ".join(cmd)
        assert "sha=" not in " ".join(cmd)

    @patch("services.oss_fork.run_gh_command")
    def test_ensure_ci_workflow_updates_existing_file(self, mock_gh):
        mock_gh.side_effect = [
            # Check if workflow exists — found with sha
            {"success": True, "output": "abc123sha"},
            # PUT to update file
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()
        svc.ensure_ci_workflow("myuser", "myrepo", language="Python")

        # Should have called PUT with sha
        put_call = mock_gh.call_args_list[-1]
        cmd = put_call[0][0]
        assert "sha=abc123sha" in " ".join(cmd)

    @patch("services.oss_fork.run_gh_command")
    def test_ensure_ci_workflow_uses_generic_when_no_language(self, mock_gh):
        """When no language is provided, should use generic workflow (no detection API calls)."""
        mock_gh.side_effect = [
            # Check if workflow exists — not found
            {"success": False, "output": ""},
            # PUT to create file
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()
        svc.ensure_ci_workflow("myuser", "myrepo")  # No language

        # Should only make 2 calls: check existence + create file (no language detection)
        assert mock_gh.call_count == 2


class TestPipelineFileStripping:
    """Tests for pipeline file stripping during create_clean_branch."""

    def test_pipeline_files_constant_contains_expected_files(self):
        svc = OSSService()
        assert ".github/copilot-instructions.md" in svc.PIPELINE_FILES
        assert ".github/workflows/ci.yml" in svc.PIPELINE_FILES
        assert ".github/workflows/static-analysis.yml" in svc.PIPELINE_FILES
        assert ".github/workflows/copilot-setup-steps.yml" in svc.PIPELINE_FILES

    @patch("services.oss_fork.run_gh_command")
    def test_strip_pipeline_files_removes_nonexistent_upstream(self, mock_gh):
        """Files that don't exist upstream should be deleted from tree."""
        svc = OSSService()

        mock_gh.side_effect = [
            # Fetch upstream tree SHA
            {"success": True, "output": "upstream-tree-sha\n"},
            # For each PIPELINE_FILE: upstream tree lookup returns empty (file doesn't exist)
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            # Create new tree
            {"success": True, "output": "new-tree-sha\n"},
        ]

        new_tree, stripped = svc._strip_pipeline_files(
            "myuser", "myrepo", "orig-tree-sha", "upstream/repo", "main"
        )
        assert new_tree == "new-tree-sha"
        assert len(stripped) == 4
        assert all("removed" in s for s in stripped)

    @patch("services.oss_fork.run_gh_command")
    def test_strip_pipeline_files_restores_upstream_version(self, mock_gh):
        """Files that exist upstream should be restored to upstream blob."""
        svc = OSSService()

        upstream_entry = json.dumps({"path": "copilot-instructions.md", "sha": "upstream-blob-sha", "mode": "100644"})
        mock_gh.side_effect = [
            # Fetch upstream tree SHA
            {"success": True, "output": "upstream-tree-sha\n"},
            # First file exists upstream
            {"success": True, "output": upstream_entry},
            # Remaining 3 don't exist
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            # Create new tree
            {"success": True, "output": "new-tree-sha\n"},
        ]

        new_tree, stripped = svc._strip_pipeline_files(
            "myuser", "myrepo", "orig-tree-sha", "upstream/repo", "main"
        )
        assert new_tree == "new-tree-sha"
        assert any("restored" in s for s in stripped)
        assert any("removed" in s for s in stripped)

    @patch("services.oss_fork.run_gh_command")
    def test_strip_pipeline_files_no_origin_returns_original(self, mock_gh):
        """Without origin_slug, should return the original tree unchanged."""
        svc = OSSService()

        new_tree, stripped = svc._strip_pipeline_files(
            "myuser", "myrepo", "orig-tree-sha", None, "main"
        )
        assert new_tree == "orig-tree-sha"
        assert stripped == []
        mock_gh.assert_not_called()

    @patch("services.oss_fork.run_gh_command")
    def test_create_clean_branch_passes_origin_to_strip(self, mock_gh):
        """create_clean_branch should call _strip_pipeline_files with origin info."""
        svc = OSSService()

        mock_gh.side_effect = [
            # 1. Get squash commit tree + parents
            {"success": True, "output": json.dumps({"tree": "tree-sha", "parents": ["parent-sha"]})},
            # 2-7. _strip_pipeline_files calls (upstream tree + 4 file lookups + create tree)
            {"success": True, "output": "upstream-tree-sha\n"},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": ""},
            {"success": True, "output": "filtered-tree-sha\n"},
            # 3. Get user identity
            {"success": True, "output": json.dumps({"name": "Test", "email": "test@example.com", "login": "testuser"})},
            # 4. Create commit
            {"success": True, "output": json.dumps({"sha": "new-commit-sha"})},
            # 5. Create branch ref
            {"success": True, "output": "{}"},
        ]

        result = svc.create_clean_branch(
            "myuser", "myrepo", "squash-sha", "fix/42-test",
            "Test commit", origin_slug="upstream/repo", base_branch="main"
        )
        assert result["success"] is True
        assert result["sha"] == "new-commit-sha"
        assert len(result["files_stripped"]) == 4


class TestForkSettings:
    """Tests for configure_fork_settings and approve_pending_workflow_runs."""

    @patch("services.oss_fork.run_gh_command")
    def test_configure_fork_settings_enables_issues(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()
        svc.configure_fork_settings("myuser", "myrepo")

        # First call should enable issues
        issues_call = mock_gh.call_args_list[0]
        cmd = " ".join(issues_call[0][0])
        assert "repos/myuser/myrepo" in cmd
        assert "PATCH" in cmd
        assert "has_issues=true" in cmd

    @patch("services.oss_fork.run_gh_command")
    def test_configure_fork_settings_enables_actions(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()
        svc.configure_fork_settings("myuser", "myrepo")

        # Second call should enable Actions with allow all
        actions_call = mock_gh.call_args_list[1]
        cmd = " ".join(actions_call[0][0])
        assert "repos/myuser/myrepo/actions/permissions" in cmd
        assert "PUT" in cmd
        assert "enabled=true" in cmd
        assert "allowed_actions=all" in cmd

    @patch("services.oss_fork.run_gh_command")
    def test_approve_pending_workflow_runs_approves_action_required(self, mock_gh):
        mock_gh.side_effect = [
            # List runs with action_required
            {"success": True, "output": "111\n222\n333\n"},
            # Approve run 111
            {"success": True, "output": "{}"},
            # Approve run 222
            {"success": True, "output": "{}"},
            # Approve run 333
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()
        approved = svc.approve_pending_workflow_runs("myuser", "myrepo")

        assert approved == 3
        # Verify approve calls
        for i, run_id in enumerate(["111", "222", "333"]):
            approve_call = mock_gh.call_args_list[1 + i]
            cmd = " ".join(approve_call[0][0])
            assert f"actions/runs/{run_id}/approve" in cmd

    @patch("services.oss_fork.run_gh_command")
    def test_approve_falls_back_to_rerun_on_403(self, mock_gh):
        mock_gh.side_effect = [
            # List runs with action_required
            {"success": True, "output": "111\n222\n"},
            # Approve run 111 fails (403 — not a fork PR)
            {"success": False, "error": "HTTP 403"},
            # Rerun run 111 succeeds
            {"success": True, "output": "{}"},
            # Approve run 222 succeeds directly
            {"success": True, "output": "{}"},
        ]
        svc = OSSService()
        unblocked = svc.approve_pending_workflow_runs("myuser", "myrepo")

        assert unblocked == 2
        # run 111: approve failed, then rerun
        rerun_call = mock_gh.call_args_list[2]
        cmd = " ".join(rerun_call[0][0])
        assert "actions/runs/111/rerun" in cmd

    @patch("services.oss_fork.run_gh_command")
    def test_approve_pending_workflow_runs_returns_zero_on_no_pending(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "\n"}
        svc = OSSService()
        approved = svc.approve_pending_workflow_runs("myuser", "myrepo")

        assert approved == 0
        assert mock_gh.call_count == 1  # Only the list call

    @patch("services.oss_fork.run_gh_command")
    def test_approve_pending_workflow_runs_returns_zero_on_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "output": ""}
        svc = OSSService()
        approved = svc.approve_pending_workflow_runs("myuser", "myrepo")

        assert approved == 0


class TestCopilotReview:
    """Tests for request_copilot_review and review helpers."""

    @patch("services.oss_fork.run_gh_command")
    def test_request_copilot_review_calls_correct_api(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()
        result = svc.request_copilot_review("myuser", "myrepo", 42)

        assert result["success"] is True
        mock_gh.assert_called_once()
        cmd = mock_gh.call_args[0][0]
        assert "repos/myuser/myrepo/pulls/42/requested_reviewers" in " ".join(cmd)
        assert "copilot-pull-request-reviewer[bot]" in " ".join(cmd)

    @patch("services.oss_fork.run_gh_command")
    def test_get_pr_check_runs_returns_checks(self, mock_gh):
        mock_gh.side_effect = [
            # Get head SHA
            {"success": True, "output": "abc123\n"},
            # Get check runs
            {"success": True, "output": '{"name":"CI","status":"completed","conclusion":"success"}\n{"name":"CodeQL","status":"completed","conclusion":"failure"}\n'},
        ]
        svc = OSSService()
        checks = svc.get_pr_check_runs("myuser", "myrepo", 42)

        assert len(checks) == 2
        assert checks[0]["name"] == "CI"
        assert checks[0]["conclusion"] == "success"
        assert checks[1]["name"] == "CodeQL"
        assert checks[1]["conclusion"] == "failure"

    @patch("services.oss_fork.run_gh_command")
    def test_get_pr_check_runs_returns_empty_on_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "output": ""}
        svc = OSSService()
        checks = svc.get_pr_check_runs("myuser", "myrepo", 42)
        assert checks == []

    @patch("services.oss_fork.run_gh_command")
    def test_get_pr_reviews_returns_reviews(self, mock_gh):
        mock_gh.return_value = {
            "success": True,
            "output": '{"user":"copilot-pull-request-reviewer[bot]","state":"APPROVED","body":"LGTM"}\n',
        }
        svc = OSSService()
        reviews = svc.get_pr_reviews("myuser", "myrepo", 42)

        assert len(reviews) == 1
        assert reviews[0]["user"] == "copilot-pull-request-reviewer[bot]"
        assert reviews[0]["state"] == "APPROVED"

    @patch("services.oss_fork.run_gh_command")
    def test_get_pr_reviews_returns_empty_on_failure(self, mock_gh):
        mock_gh.return_value = {"success": False, "output": ""}
        svc = OSSService()
        reviews = svc.get_pr_reviews("myuser", "myrepo", 42)
        assert reviews == []


class TestAssignmentUpdate:
    """Tests for find_assignment and update_assignment."""

    def test_find_by_fork_issue_returns_match(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("org", "myrepo", 42, 1,
                            "https://github.com/me/myrepo/issues/1")
        result = svc.find_assignment_by_fork_issue("myrepo", 1)
        assert result is not None
        assert result["issue_number"] == 42
        assert result["fork_issue_number"] == 1

    def test_find_by_fork_issue_returns_none_for_missing(self, clean_data_dir):
        svc = OSSService()
        result = svc.find_assignment_by_fork_issue("myrepo", 999)
        assert result is None

    def test_update_assignment_merges_fields(self, clean_data_dir):
        svc = OSSService()
        svc.save_assignment("org", "myrepo", 42, 1,
                            "https://github.com/me/myrepo/issues/1")

        updated = svc.update_assignment("myrepo", 1, {
            "stage4_status": "swe_agent_done",
            "stage4_pr_number": 5,
        })
        assert updated is True

        item = svc.find_assignment_by_fork_issue("myrepo", 1)
        assert item["stage4_status"] == "swe_agent_done"
        assert item["stage4_pr_number"] == 5
        # Original fields preserved
        assert item["issue_number"] == 42

    def test_update_assignment_returns_false_for_missing(self, clean_data_dir):
        svc = OSSService()
        updated = svc.update_assignment("myrepo", 999, {"stage4_status": "done"})
        assert updated is False


class TestFileLocking:
    """Tests for concurrent file access safety in _load_json/_save_json."""

    def test_concurrent_writes_produce_valid_json(self, clean_data_dir):
        """Multiple threads writing simultaneously should not corrupt the file."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def write_item(i):
            _save_json("concurrent.json", [{"id": i, "value": f"item-{i}"}])
            return i

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(write_item, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()  # Raise any exceptions

        # File should contain valid JSON (one of the writes)
        data = _load_json("concurrent.json")
        assert isinstance(data, list)
        assert len(data) == 1
        assert "id" in data[0]

    def test_load_returns_empty_on_missing_file(self, clean_data_dir):
        assert _load_json("nonexistent.json") == []

    def test_save_then_load_roundtrip(self, clean_data_dir):
        _save_json("roundtrip.json", [{"a": 1}, {"b": 2}])
        data = _load_json("roundtrip.json")
        assert data == [{"a": 1}, {"b": 2}]
