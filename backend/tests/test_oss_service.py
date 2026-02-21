"""Tests for OSSService local watchlist methods."""

import json
import os
import tempfile

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
