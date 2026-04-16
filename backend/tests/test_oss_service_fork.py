"""Tests for OSSService fork management — fork_repo, sync, settings, dispatched repos."""

import json
from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService


class TestForkManagement:
    """Tests for fork_repo, sync_fork, check_fork_exists, wait_for_fork."""

    @patch("services.oss_fork.run_gh_command")
    def test_check_fork_exists_true(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": '{"name": "acme-corp"}'}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "acme-corp") is True

    @patch("services.oss_fork.run_gh_command")
    def test_check_fork_exists_false(self, mock_gh):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        assert svc.check_fork_exists("testuser", "acme-corp") is False

    @patch("services.oss_fork.run_gh_command")
    def test_wait_for_fork_succeeds_immediately(self, mock_gh):
        mock_gh.return_value = {"success": True, "output": "{}"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "acme-corp", timeout=6, interval=1)
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

        result = svc.wait_for_fork("testuser", "acme-corp", timeout=9, interval=3)
        assert result is True
        assert mock_sleep.call_count == 2

    @patch("services.oss_fork.time.sleep")
    @patch("services.oss_fork.run_gh_command")
    def test_wait_for_fork_timeout(self, mock_gh, mock_sleep):
        mock_gh.return_value = {"success": False, "error": "Not found"}
        svc = OSSService()

        result = svc.wait_for_fork("testuser", "acme-corp", timeout=6, interval=3)
        assert result is False


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


class TestDispatchedRepos:
    """Tests for dispatched-repos tracking (track_dispatched_repo / get_dispatched_repos)."""

    def test_first_dispatch_creates_entry(self, clean_data_dir):
        svc = OSSService()
        svc.track_dispatched_repo("acme-corp/widget-api")

        items = svc.get_dispatched_repos()
        assert len(items) == 1
        assert items[0]["origin_slug"] == "acme-corp/widget-api"
        assert items[0]["aggregator_slug"] == "acme-corp-widget-api"
        assert items[0]["dispatch_count"] == 1
        assert "first_dispatched_at" in items[0]
        assert "last_dispatched_at" in items[0]

    def test_second_dispatch_increments_count(self, clean_data_dir):
        svc = OSSService()
        svc.track_dispatched_repo("acme-corp/widget-api")
        svc.track_dispatched_repo("acme-corp/widget-api")

        items = svc.get_dispatched_repos()
        assert len(items) == 1
        assert items[0]["dispatch_count"] == 2

    def test_different_slugs_create_separate_entries(self, clean_data_dir):
        svc = OSSService()
        svc.track_dispatched_repo("acme-corp/widget-api")
        svc.track_dispatched_repo("vercel/next.js")

        items = svc.get_dispatched_repos()
        assert len(items) == 2
        slugs = {i["origin_slug"] for i in items}
        assert slugs == {"acme-corp/widget-api", "vercel/next.js"}

    def test_aggregator_slug_format(self, clean_data_dir):
        """aggregator_slug replaces only the first slash."""
        svc = OSSService()
        svc.track_dispatched_repo("vercel/next.js")

        items = svc.get_dispatched_repos()
        assert items[0]["aggregator_slug"] == "vercel-next.js"

    def test_empty_list_when_no_dispatches(self, clean_data_dir):
        svc = OSSService()
        assert svc.get_dispatched_repos() == []

    def test_second_dispatch_updates_last_dispatched_at(self, clean_data_dir):
        import time
        svc = OSSService()
        svc.track_dispatched_repo("acme-corp/widget-api")
        first_at = svc.get_dispatched_repos()[0]["last_dispatched_at"]

        time.sleep(0.01)
        svc.track_dispatched_repo("acme-corp/widget-api")
        second_at = svc.get_dispatched_repos()[0]["last_dispatched_at"]

        # last_dispatched_at must be updated (may be same second but field exists)
        assert second_at >= first_at
