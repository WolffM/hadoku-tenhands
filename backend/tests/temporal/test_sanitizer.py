"""Unit tests for backend.temporal.sanitizer — Phase 1B.1.

Per the test plan in phase-1-plan.md step 1B.1:
  scrub_brief:
    - URL stripping
    - short ref stripping
    - bare slug stripping
    - keyword stripping
    - idempotent (clean text in → clean text out, empty report)
    - preserves code-like content that isn't an upstream ref
  scan_outputs:
    - catches all 3 jade-hare leak fixtures
    - tolerates hallucinated refs (no false positive on invented numbers)
    - catches commit-message leaks specifically
"""

from __future__ import annotations

import pytest

from temporal.sanitizer import (
    SanitizerError,
    ScrubReport,
    Substitution,
    scan_outputs,
    scrub_brief,
)


UPSTREAM = "microsoft/markitdown"
ISSUE_NUM = 183


# ── scrub_brief ───────────────────────────────────────────────────────────


def test_scrub_brief_strips_full_url():
    brief = "See https://github.com/microsoft/markitdown/issues/183 for context."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)

    assert "https://github.com/microsoft/markitdown" not in out
    assert "[upstream issue URL]" in out
    assert report.count == 1
    assert report.substitutions[0].pattern == "url"
    assert report.substitutions[0].matched.endswith("/183")


def test_scrub_brief_strips_pull_url():
    brief = "Related: https://github.com/microsoft/markitdown/pull/9"
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "github.com/microsoft/markitdown" not in out
    assert report.count == 1


def test_scrub_brief_strips_short_ref():
    brief = "Fixed in microsoft/markitdown#183 last week."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "microsoft/markitdown#183" not in out
    assert "[upstream issue]" in out
    assert any(s.pattern == "short_ref" for s in report.substitutions)


def test_scrub_brief_strips_bare_slug():
    brief = "This bug is from microsoft/markitdown originally."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "microsoft/markitdown" not in out
    assert "the upstream project" in out
    assert any(s.pattern == "bare_slug" for s in report.substitutions)


def test_scrub_brief_strips_keyword_phrase_with_hash_number():
    brief = "Fixes #183. Related work coming."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "Fixes #183" not in out
    assert any(s.pattern == "keyword_ref" for s in report.substitutions)


def test_scrub_brief_strips_keyword_phrase_with_slug_form():
    brief = "Closes microsoft/markitdown#183 — this PR addresses it."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "Closes microsoft/markitdown#183" not in out
    assert any(s.pattern == "keyword_ref" for s in report.substitutions)


def test_scrub_brief_idempotent_on_clean_text():
    brief = "Nothing to scrub here. Just some prose about a bug.\nLine 2."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert out == brief
    assert report.count == 0


def test_scrub_brief_preserves_unrelated_repo_refs():
    """Refs to OTHER upstreams should not be touched."""
    brief = "Compare to python/cpython#9999 for the analogous case."
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert "python/cpython#9999" in out
    assert report.count == 0


def test_scrub_brief_preserves_code_block_with_unrelated_imports():
    """A code block containing other slugs / refs should pass through."""
    brief = (
        "Reproduce with:\n"
        "```python\n"
        "import requests\n"
        "from python.cpython import something\n"
        "# see issue 12345\n"
        "```"
    )
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    assert out == brief
    assert report.count == 0


def test_scrub_brief_handles_multiple_leaks_in_one_brief():
    brief = (
        "Issue: https://github.com/microsoft/markitdown/issues/183\n"
        "Also referenced as microsoft/markitdown#183\n"
        "Originally from microsoft/markitdown.\n"
        "Closes #183 when merged."
    )
    out, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    # All four pattern kinds should appear in the report
    kinds = {s.pattern for s in report.substitutions}
    assert {"url", "short_ref", "bare_slug", "keyword_ref"}.issubset(kinds)
    # And the scrubbed text should contain none of the originals
    assert "github.com/microsoft/markitdown" not in out
    assert "microsoft/markitdown#183" not in out
    assert "microsoft/markitdown" not in out
    assert "Closes #183" not in out


def test_scrub_brief_empty_input():
    out, report = scrub_brief("", UPSTREAM, ISSUE_NUM)
    assert out == ""
    assert report.count == 0


def test_scrub_report_to_dict_shape():
    brief = "See https://github.com/microsoft/markitdown/issues/183 for details."
    _, report = scrub_brief(brief, UPSTREAM, ISSUE_NUM)
    d = report.to_dict()
    assert d["count"] == 1
    assert d["substitutions"][0]["pattern"] == "url"
    assert d["substitutions"][0]["replacement"] == "[upstream issue URL]"
    assert "span" in d["substitutions"][0]


# ── scan_outputs — jade-hare leak fixtures ────────────────────────────────


def test_scan_outputs_catches_markitdown_183_url_in_pr_body():
    """jade-hare leak #1: a github.com URL to microsoft/markitdown#183
    survived the existing _sanitize_upstream_refs and reached the public
    fork PR body."""
    pr_body = (
        "## Summary\n\n"
        "This addresses the issue described at\n"
        "https://github.com/microsoft/markitdown/issues/183\n\n"
        "The fix updates the cell-coalescing logic.\n"
    )
    with pytest.raises(SanitizerError) as exc_info:
        scan_outputs(
            pr_title="Fix blank cells",
            pr_body=pr_body,
            commit_messages=[],
            upstream_slug=UPSTREAM,
            issue_number=ISSUE_NUM,
        )
    assert any(l.kind == "url" for l in exc_info.value.leaks)


def test_scan_outputs_catches_mermaid_4099_short_ref_in_title():
    """jade-hare leak #2: Copilot wrote upstream ref into a public PR title.

    The exact jade-hare title was `Document Mermaid PR #7511 intent and its
    mapping to issue #4099`. The slash-form variant we test here is what
    a more careful regex would have caught:
    `Document mermaid-js/mermaid#7511 intent for #4099`.
    """
    pr_title = "Document mermaid-js/mermaid#7511 intent and its mapping"
    with pytest.raises(SanitizerError) as exc_info:
        scan_outputs(
            pr_title=pr_title,
            pr_body="(empty)",
            commit_messages=[],
            upstream_slug="mermaid-js/mermaid",
            issue_number=4099,
        )
    assert any(l.kind == "short_ref" for l in exc_info.value.leaks)


def test_scan_outputs_catches_hoppscotch_3331_url_in_commit_message():
    """jade-hare leak #3: the leak was in a commit message, which the
    old sanitizer didn't inspect."""
    commits = [
        {
            "sha": "abc1234",
            "message": (
                "fix: handle null env vars\n\n"
                "See https://github.com/hoppscotch/hoppscotch/issues/3331\n"
                "for the original report."
            ),
        }
    ]
    with pytest.raises(SanitizerError) as exc_info:
        scan_outputs(
            pr_title="Handle null env vars",
            pr_body="Clean PR body with no leaks.",
            commit_messages=commits,
            upstream_slug="hoppscotch/hoppscotch",
            issue_number=3331,
        )
    assert any(l.kind == "url" for l in exc_info.value.leaks)
    assert any(l.source == "commit:abc1234" for l in exc_info.value.leaks)


# ── scan_outputs — tolerates hallucinated refs ────────────────────────────


def test_scan_outputs_tolerates_hallucinated_keyword_ref():
    """`Fixes #99999` against an upstream that has no #99999 fires no
    cross-reference and is acceptable as cosmetic noise."""
    pr_body = "Closes #99999 — fixes the bug."
    # Should NOT raise
    scan_outputs(
        pr_title="Clean title",
        pr_body=pr_body,
        commit_messages=[],
        upstream_slug=UPSTREAM,
        issue_number=ISSUE_NUM,
    )


def test_scan_outputs_tolerates_unrelated_upstream_ref():
    """A ref to a different upstream is also tolerated — no link to OUR
    upstream's issue."""
    pr_body = "See python/cpython#42 for an unrelated discussion."
    scan_outputs(
        pr_title="Clean title",
        pr_body=pr_body,
        commit_messages=[],
        upstream_slug=UPSTREAM,
        issue_number=ISSUE_NUM,
    )


def test_scan_outputs_clean_passes():
    scan_outputs(
        pr_title="Fix XLSX merged-range header handling",
        pr_body=(
            "## Summary\n\nThe XLSX converter dropped header text from "
            "merged ranges.\n\n## Fix\n\nResolved the merge anchor.\n"
        ),
        commit_messages=[
            {"sha": "deadbe", "message": "fix: resolve merged range anchor before reading"}
        ],
        upstream_slug=UPSTREAM,
        issue_number=ISSUE_NUM,
    )


# ── SanitizerError carries leaks ──────────────────────────────────────────


def test_sanitizer_error_carries_leak_list():
    pr_body = "https://github.com/microsoft/markitdown/issues/183 here"
    with pytest.raises(SanitizerError) as exc_info:
        scan_outputs(
            pr_title="t",
            pr_body=pr_body,
            commit_messages=[],
            upstream_slug=UPSTREAM,
            issue_number=ISSUE_NUM,
        )
    err = exc_info.value
    assert isinstance(err.leaks, list)
    assert len(err.leaks) >= 1
    assert all(hasattr(l, "kind") for l in err.leaks)
