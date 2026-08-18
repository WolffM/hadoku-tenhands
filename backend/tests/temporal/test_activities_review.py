"""the review activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

def test_read_review_summary_returns_zeros_when_missing(ev):
    """No severity_summary file → safe defaults so the workflow's
    branch decision treats it as 'no blockers' rather than aborting."""
    from temporal.activities.review import read_review_summary

    result = read_review_summary(ev)
    assert result == {"blocking": 0, "suggested": 0, "nit": 0}


def test_read_review_summary_passes_through_counts(ev):
    """Real summary file → counts surface verbatim as ints."""
    from temporal.activities.review import read_review_summary

    ev.write_json("07-reviewed/severity_summary.json",
                  {"blocking": 2, "suggested": 5, "nit": 1})
    result = read_review_summary(ev)
    assert result == {"blocking": 2, "suggested": 5, "nit": 1}


def test_read_review_summary_coerces_non_int_values(ev):
    """Defensive: malformed summary (e.g. missing keys, string counts)
    falls back to zero rather than blowing up the workflow."""
    from temporal.activities.review import read_review_summary

    ev.write_json("07-reviewed/severity_summary.json",
                  {"blocking": "3", "suggested": None})
    result = read_review_summary(ev)
    assert result["blocking"] == 3
    assert result["suggested"] == 0
    assert result["nit"] == 0


def test_review_activity_normalizes_comments(ev):
    from temporal.activities.review import run_review

    def fake_runner(fork_slug, pr_number):
        return {
            "comments": [
                {"id": 1, "severity": "BLOCKING", "body": "x", "path": "a.py", "line": 10},
                {"id": 2, "severity": "nit", "body": "y", "path": "b.py", "line": 5},
                {"comment_id": "x3", "severity": None, "body": "z"},  # weird shape
                "not a dict",  # filtered out
            ]
        }

    result = run_review("WolffM/x", 9, ev, review_runner=fake_runner)
    assert result["comment_count"] == 3
    comments = ev.read_json("07-reviewed/comments.json")
    assert comments[0]["severity"] == "blocking"
    assert comments[2]["severity"] == "suggested"  # default
    summary = ev.read_json("07-reviewed/severity_summary.json")
    assert summary["blocking"] == 1
    assert summary["nit"] == 1
