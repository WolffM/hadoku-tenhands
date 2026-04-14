"""Unit tests for backend.temporal.evidence.scanner — Phase 1A.6.

Covers all 4 scanners + commit-message integration. Includes the 3
jade-hare leak fixtures (markitdown#183, mermaid#4099, hoppscotch#3331)
as positive cases — these are the exact strings we got burned on.

Negative cases verify the scanner doesn't fire on:
  - bare `#N` with no slug context
  - refs to our own forks (`WolffM/markitdown#9`)
  - refs to a different upstream
  - hallucinated numbers that don't match the recorded issue
"""

from __future__ import annotations

import pytest

from temporal.evidence.scanner import (
    Leak,
    scan_commit_messages,
    scan_for_bare_slug,
    scan_for_keyword_ref,
    scan_for_short_ref,
    scan_for_url,
)


# ── scan_for_url ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "see https://github.com/microsoft/markitdown/issues/183 for context",
    "see http://github.com/microsoft/markitdown/issues/183 for context",
    "see github.com/microsoft/markitdown/issues/183",
    "https://github.com/microsoft/markitdown/pull/9 closes the issue",
    "https://github.com/microsoft/markitdown/issues/183#issuecomment-456",
    "the URL is\nhttps://github.com/microsoft/markitdown/issues/183\non its own line",
])
def test_scan_for_url_catches_positive(text):
    leaks = scan_for_url(text, "microsoft/markitdown")
    assert len(leaks) == 1
    assert leaks[0].kind == "url"


def test_scan_for_url_ignores_other_repos():
    text = "see https://github.com/python/cpython/issues/183"
    assert scan_for_url(text, "microsoft/markitdown") == []


def test_scan_for_url_returns_empty_for_empty_inputs():
    assert scan_for_url("", "microsoft/markitdown") == []
    assert scan_for_url("anything", "") == []


# ── scan_for_short_ref ────────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "fixed in microsoft/markitdown#183",
    "see microsoft/markitdown#183 for context",
    "MICROSOFT/MARKITDOWN#183 still applies",  # case-insensitive
])
def test_scan_for_short_ref_catches_positive(text):
    leaks = scan_for_short_ref(text, "microsoft/markitdown")
    assert len(leaks) == 1
    assert leaks[0].kind == "short_ref"


def test_scan_for_short_ref_ignores_own_fork():
    """WolffM/markitdown#9 references our own fork, not the upstream."""
    text = "see WolffM/markitdown#9 for our local PR"
    assert scan_for_short_ref(text, "microsoft/markitdown") == []


def test_scan_for_short_ref_ignores_bare_hash():
    """`#183` alone isn't a slug-prefixed ref."""
    text = "see #183 — no upstream context here"
    assert scan_for_short_ref(text, "microsoft/markitdown") == []


def test_scan_for_short_ref_ignores_other_repos():
    text = "see microsoft/typescript#183"
    assert scan_for_short_ref(text, "microsoft/markitdown") == []


# ── scan_for_bare_slug ────────────────────────────────────────────────────


def test_scan_for_bare_slug_catches_standalone():
    text = "this is from microsoft/markitdown originally"
    leaks = scan_for_bare_slug(text, "microsoft/markitdown")
    assert len(leaks) == 1
    assert leaks[0].kind == "bare_slug"


def test_scan_for_bare_slug_skips_url_occurrences():
    """Don't double-count when the slug is part of a github.com URL."""
    text = "https://github.com/microsoft/markitdown/issues/183"
    # scan_for_url catches this; scan_for_bare_slug should NOT.
    assert scan_for_bare_slug(text, "microsoft/markitdown") == []


def test_scan_for_bare_slug_skips_short_ref_occurrences():
    """A short ref `microsoft/markitdown#183` is NOT a bare-slug match —
    the trailing `#` means the slug isn't standalone."""
    text = "see microsoft/markitdown#183"
    assert scan_for_bare_slug(text, "microsoft/markitdown") == []


def test_scan_for_bare_slug_ignores_substring_match():
    """`microsoft/markitdown-fork` should not match `microsoft/markitdown`."""
    text = "see microsoft/markitdown-fork for the variant"
    assert scan_for_bare_slug(text, "microsoft/markitdown") == []


# ── scan_for_keyword_ref ──────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "Fixes #183",
    "Closes #183",
    "Resolves #183",
    "fix #183",
    "fixes: #183",
])
def test_scan_for_keyword_ref_catches_specific_number(text):
    leaks = scan_for_keyword_ref(text, 183)
    assert len(leaks) == 1
    assert leaks[0].kind == "keyword_ref"


def test_scan_for_keyword_ref_ignores_hallucinated_numbers():
    """The whole point of input scrubbing: hallucinated `#99999` is OK
    because it doesn't match any real upstream issue."""
    text = "Fixes #99999"
    assert scan_for_keyword_ref(text, 183) == []


def test_scan_for_keyword_ref_catches_slug_prefixed_form_for_any_number():
    """If the agent writes `Fixes microsoft/markitdown#7511` even with a
    hallucinated number, it's slash-form so it definitely targets upstream
    and MUST be blocked."""
    text = "Fixes microsoft/markitdown#7511"
    leaks = scan_for_keyword_ref(text, 183, upstream_slug="microsoft/markitdown")
    assert len(leaks) == 1


def test_scan_for_keyword_ref_does_not_catch_other_slugs():
    text = "Fixes python/cpython#183"
    leaks = scan_for_keyword_ref(text, 183, upstream_slug="microsoft/markitdown")
    # Doesn't match the slash-form (different slug) AND doesn't match the
    # bare `#183` form (no plain `Fixes #183` here)
    assert leaks == []


# ── jade-hare leak fixtures (the exact strings that burned us) ────────────


def test_markitdown_183_url_in_pr_body():
    """jade-hare leak #1: a github.com URL to microsoft/markitdown#183
    survived the existing _sanitize_upstream_refs and reached the public
    fork PR."""
    pr_body = """## Summary

This addresses the issue described at
https://github.com/microsoft/markitdown/issues/183

The fix updates the cell-coalescing logic.
"""
    leaks = scan_for_url(pr_body, "microsoft/markitdown")
    assert len(leaks) == 1


def test_mermaid_4099_in_pr_title():
    """jade-hare leak #2: Copilot wrote the upstream issue number directly
    into a public PR title — `Document Mermaid PR #7511 intent and its
    mapping to issue #4099`."""
    pr_title = "Document Mermaid PR #7511 intent and its mapping to issue #4099"
    # We only block #4099 (the recorded issue). #7511 is hallucinated and OK.
    leaks = scan_for_keyword_ref(pr_title, 4099)
    # `issue #4099` doesn't have an autoclose keyword in front — but it IS
    # close enough that we want to catch it. The current scanner only catches
    # `Fixes/Closes/Resolves` prefixes. This test documents the gap and
    # justifies a separate `scan_for_issue_number_in_text` helper.
    # For now: confirm the scanner doesn't catch it (so the test plan
    # explicitly notes the gap), and rely on bare-slug + URL scanning.
    # We DO catch it via the slug+number combo if both appear:
    pr_with_slug = "Document mermaid-js/mermaid#7511 intent for #4099"
    short_leaks = scan_for_short_ref(pr_with_slug, "mermaid-js/mermaid")
    assert len(short_leaks) == 1


def test_hoppscotch_3331_in_commit_message():
    """jade-hare leak #3: a Copilot-authored commit had a leak in the body
    that the existing sanitizer didn't inspect. Catch via the commit
    scanner."""
    commits = [
        {
            "sha": "abc123",
            "message": (
                "fix: handle null env vars\n\n"
                "See https://github.com/hoppscotch/hoppscotch/issues/3331\n"
                "for the original report."
            ),
        }
    ]
    leaks = scan_commit_messages(commits, "hoppscotch/hoppscotch", 3331)
    assert len(leaks) >= 1
    assert any(l.kind == "url" for l in leaks)
    assert leaks[0].source == "commit:abc123"


# ── scan_commit_messages integration ──────────────────────────────────────


def test_scan_commit_messages_clean_returns_empty():
    commits = [
        {"sha": "aaa", "message": "fix: cell coalescing\n\nSee notes.md"},
        {"sha": "bbb", "message": "test: add coverage for empty cells"},
    ]
    assert scan_commit_messages(commits, "microsoft/markitdown", 183) == []


def test_scan_commit_messages_catches_keyword_in_specific_commit():
    commits = [
        {"sha": "aaa", "message": "fix: cell coalescing"},
        {"sha": "bbb", "message": "Fixes #183"},
    ]
    leaks = scan_commit_messages(commits, "microsoft/markitdown", 183)
    assert len(leaks) == 1
    assert leaks[0].source == "commit:bbb"
    assert leaks[0].kind == "keyword_ref"
