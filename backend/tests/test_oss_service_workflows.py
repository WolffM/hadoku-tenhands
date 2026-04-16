"""Tests for OSSService CI workflows, pipeline file stripping, and upstream ref sanitization."""

import json
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService, _sanitize_upstream_refs


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


class TestSanitizeUpstreamRefs:
    """Tests for _sanitize_upstream_refs — preventing cross-linking to upstream repos."""

    def test_strips_github_issue_url(self):
        text = "Issue: https://github.com/reisepass/email-verifier/issues/4"
        result = _sanitize_upstream_refs(text)
        assert "https://github.com" not in result
        assert "reisepass/email-verifier issue 4" in result

    def test_strips_github_pr_url(self):
        text = "See https://github.com/acme-corp/widget-api/pull/123 for details"
        result = _sanitize_upstream_refs(text)
        assert "https://github.com" not in result
        assert "acme-corp/widget-api PR 123" in result

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
