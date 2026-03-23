"""Tests for OSSService state tracking — submitted PRs, selected issues, assignments, ready-to-submit."""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService, OSS_DATA_DIR, _load_json, _save_json, _sanitize_upstream_refs


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
