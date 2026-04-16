"""Tests for OSSService claim management, pending status handling, and self-owned assignments."""

from unittest.mock import patch, MagicMock

import pytest

from services.oss_service import OSSService


class TestClaimManagement:
    """Tests for report_claim and report_unclaim."""

    @patch("services.oss_service._call_aggregator")
    def test_report_claim_converts_slug_format(self, mock_agg):
        svc = OSSService()
        svc.report_claim("acme-corp/widget-api", "github-acme-corp-widget-api-42", "testuser", "https://example.com/issues/1")

        mock_agg.assert_called_once_with(
            "/recon/acme-corp-widget-api/claim",
            method="POST",
            data={
                "issueId": "github-acme-corp-widget-api-42",
                "claimedBy": "testuser",
                "forkIssueUrl": "https://example.com/issues/1",
            },
        )

    @patch("services.oss_service._call_aggregator")
    def test_report_unclaim_converts_slug_format(self, mock_agg):
        svc = OSSService()
        svc.report_unclaim("acme-corp/widget-api", "github-acme-corp-widget-api-42")

        mock_agg.assert_called_once_with(
            "/recon/acme-corp-widget-api/unclaim",
            method="POST",
            data={"issueId": "github-acme-corp-widget-api-42"},
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
