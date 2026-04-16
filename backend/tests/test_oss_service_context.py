"""Tests for OSSService agent context building — dossier sections, issue brief, TDD instructions."""

import json
import base64
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService, _detect_tool_from_issue


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

        body = svc.build_agent_context("acme-corp", "widget-api", 42, "Fix docs", "https://github.com/acme-corp/widget-api/issues/42")

        assert "acme-corp/widget-api" in body
        assert "Fix docs" in body
        assert "Original issue body" in body
        # Workflow section comes FIRST (before issue context)
        assert body.startswith("## Mandatory Workflow")
        assert body.index("Mandatory Workflow") < body.index("Issue Context")
        # Must NOT contain issue number reference (would trigger GitHub cross-reference)
        assert "#42" not in body

    @patch("services.oss_context.run_gh_command")
    def test_context_with_contributing_md(self, mock_gh):
        contrib_content = base64.b64encode(b"# Contributing\nPlease follow our style guide.").decode()

        mock_gh.side_effect = [
            {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})},
            {"success": True, "output": contrib_content},
        ]
        svc = OSSService()

        body = svc.build_agent_context("acme-corp", "widget-api", 42, "Fix docs", "https://github.com/acme-corp/widget-api/issues/42")

        assert "CONTRIBUTING.md" in body
        assert "style guide" in body

    @patch("services.oss_context.run_gh_command")
    def test_context_with_dossier_contribution_rules(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": json.dumps({"body": "Issue body", "labels": []})}
        svc = OSSService()

        dossier = {"contributionRules": "Always add tests", "successPatterns": "Keep PRs small"}
        body = svc.build_agent_context("acme-corp", "widget-api", 42, "Fix", "https://example.com", dossier)

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
        body = "| Tool | `ruff` |\n| Rule | F841 |"
        assert _detect_tool_from_issue(body) == "ruff"

    def test_detects_bandit_from_vibecheck_table(self):
        body = "| Tool | `bandit` |"
        assert _detect_tool_from_issue(body) == "bandit"

    def test_detects_mypy(self):
        body = "| Tool | `mypy` |"
        assert _detect_tool_from_issue(body) == "mypy"

    def test_detects_checkov(self):
        body = "| Tool | `checkov` |"
        assert _detect_tool_from_issue(body) == "checkov"

    def test_detects_osv_scanner(self):
        body = "| Tool | `osv-scanner` |"
        assert _detect_tool_from_issue(body) == "osv-scanner"

    def test_returns_none_for_no_tool(self):
        body = "This is a regular issue with no tool table."
        assert _detect_tool_from_issue(body) is None

    def test_returns_none_for_empty_body(self):
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
