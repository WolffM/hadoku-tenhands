"""Tests for temporal/taskauto/github_item.py — re-hydrating a seeded task.

Every test injects `run`, so nothing here touches the network or needs `gh` on
PATH. The failure modes are the point: this module exists because a truncated
issue body and an invented review backlog both looked like success.
"""

from __future__ import annotations

import json

import pytest

from temporal.taskauto import github_item as gi

ISSUE = {
    "number": 19, "title": "app-card assets", "state": "OPEN",
    "url": "https://github.com/WolffM/r/issues/19",
    "author": {"login": "WolffM"}, "labels": [{"name": "chore"}],
    "body": "## Why\n\nfirst part\n\n## Delivery\n\nthe part that got cut off",
    "comments": [],
}

PR = {
    "number": 21, "title": "Wire the icon gate into lint", "state": "OPEN",
    "url": "https://github.com/WolffM/r/pull/21", "isDraft": False,
    "author": {"login": "WolffM"}, "headRefName": "icons/wire-gate",
    "baseRefName": "main", "reviewDecision": "", "statusCheckRollup": [],
    "comments": [], "reviews": [],
    "body": "waive with /* check-icons-disable-next-line */ and a reason",
}


def fake_gh(issue=None, pr=None, review_comments=None, fail=None):
    """A `run` that answers the three calls `render` can make.

    `fail` is a substring: any argv containing it comes back as a gh failure.
    """
    calls = []

    def run(argv):
        calls.append(list(argv))
        joined = " ".join(argv)
        if fail and fail in joined:
            return False, f"gh error: {fail} is unavailable"
        if "issue" in argv:
            return True, json.dumps(issue if issue is not None else ISSUE)
        if "pr" in argv:
            return True, json.dumps(pr if pr is not None else PR)
        if "api" in argv:
            return True, json.dumps(review_comments or [])
        raise AssertionError(f"unexpected gh call: {argv}")

    run.calls = calls
    return run


# ── parsing a seeded title ────────────────────────────────────────────────

@pytest.mark.parametrize("title,kind,number", [
    ("Address #19", "issue", 19),
    ("Address PR #21", "pr", 21),
    ("address pr #7", "pr", 7),
    ("Address pull request #7", "pr", 7),
    ("Address #19 — the app cards", "issue", 19),
])
def test_seeded_titles_are_recognised(title, kind, number):
    ref = gi.parse_seeded_ref(title)
    assert ref == gi.ItemRef(kind, number)


@pytest.mark.parametrize("title", [
    "make coffee theme default",
    "bug- crash at line #3",
    "readdress #19",
    "the fix for #19 needs addressing",
    "",
])
def test_titles_that_merely_mention_a_number_are_not_seeded(title):
    """Hydrating the WRONG issue is worse than hydrating none: a plausible but
    irrelevant body is far harder for a human to spot than a missing one."""
    assert gi.parse_seeded_ref(title) is None


def test_a_task_with_no_item_costs_no_gh_call():
    run = fake_gh()
    assert gi.hydrate("WolffM/r", "make coffee theme default", run=run) == ""
    assert run.calls == []


# ── the body arrives whole ────────────────────────────────────────────────

def test_the_issue_body_is_rendered_in_full():
    """The 280-char preview cut issue #19 at 7%, taking the section that named
    the deliverables and the repo they land in."""
    out = gi.hydrate("WolffM/r", "Address #19", run=fake_gh())
    assert "the part that got cut off" in out
    assert "…" not in out


def test_the_pr_body_is_rendered_in_full():
    out = gi.hydrate("WolffM/r", "Address PR #21", run=fake_gh())
    assert "/* check-icons-disable-next-line */" in out
    assert "icons/wire-gate → main" in out


def test_an_oversized_body_reports_how_much_it_dropped():
    """A bare ellipsis is what made the original loss invisible."""
    huge = dict(ISSUE, body="x" * (gi.MAX_ITEM_CHARS + 500))
    out = gi.hydrate("WolffM/r", "Address #19", run=fake_gh(issue=huge))
    assert "[cut here — 500 more characters not shown]" in out


# ── absent status is stated, never left to inference ──────────────────────

def test_a_pr_with_no_checks_and_no_reviews_says_so_in_as_many_words():
    """The failure this prevents: handed a bare `Address PR #21`, the planner
    invented an outstanding review backlog and a failing-CI story for a PR
    that has neither, then wrote plan steps and an acceptance check against
    what it had imagined."""
    out = gi.hydrate("WolffM/r", "Address PR #21", run=fake_gh())
    assert "NONE REPORTED" in out
    assert "nobody has reviewed this PR" in out
    assert "inline review comments: none" in out
    assert "no failing CI to" in out  # the provenance block's instruction


def test_real_checks_are_listed_with_their_conclusions():
    pr = dict(PR, statusCheckRollup=[
        {"__typename": "CheckRun", "name": "backend pytest",
         "status": "COMPLETED", "conclusion": "FAILURE"},
        {"__typename": "StatusContext", "context": "legacy/ci",
         "state": "SUCCESS"},
    ])
    out = gi.hydrate("WolffM/r", "Address PR #21", run=fake_gh(pr=pr))
    assert "backend pytest: FAILURE" in out
    assert "legacy/ci: SUCCESS" in out
    assert "NONE REPORTED" not in out


def test_inline_review_comments_carry_their_file_and_line():
    """`gh pr view --json comments` returns only the conversation tab, so
    these need their own call — and they are the likeliest meaning of
    "address PR #N"."""
    out = gi.hydrate("WolffM/r", "Address PR #21", run=fake_gh(
        review_comments=[{"path": "src/a.ts", "line": 12,
                          "user": {"login": "octo"}, "body": "drop this"}]))
    assert "[octo] src/a.ts:12 — drop this" in out


def test_reviews_are_listed_with_their_verdicts():
    pr = dict(PR, reviewDecision="CHANGES_REQUESTED", reviews=[
        {"author": {"login": "octo"}, "state": "CHANGES_REQUESTED",
         "body": "not yet"}])
    out = gi.hydrate("WolffM/r", "Address PR #21", run=fake_gh(pr=pr))
    assert "[octo] CHANGES_REQUESTED not yet" in out


# ── failure is announced, never silent ────────────────────────────────────

def test_a_failed_fetch_says_the_notes_are_a_preview_rather_than_returning_nothing():
    """An empty block and "there is nothing more" read identically to the
    agent. Only one of them is true."""
    out = gi.hydrate("WolffM/r", "Address #19", run=fake_gh(fail="issue view"))
    assert out  # not silence
    assert "COULD NOT BE FETCHED" in out
    assert "280-character PREVIEW" in out
    assert "is unavailable" in out  # the underlying gh error, named


def test_unparseable_json_is_a_failure_not_an_empty_item():
    def run(argv):
        return True, "not json at all"
    out = gi.hydrate("WolffM/r", "Address #19", run=run)
    assert "COULD NOT BE FETCHED" in out
    assert "unparseable" in out


def test_hydrate_never_raises_even_on_an_unexpected_error():
    """Planning is not worth failing over a gh hiccup — but the hiccup still
    has to reach the prompt."""
    def run(argv):
        raise OSError("boom")
    out = gi.hydrate("WolffM/r", "Address PR #21", run=run)
    assert "COULD NOT BE FETCHED" in out
    assert "OSError" in out


def test_losing_the_inline_comments_does_not_lose_the_body():
    """The inline-comment call is best-effort; the body it would otherwise
    discard is the whole point of the module."""
    out = gi.hydrate("WolffM/r", "Address PR #21",
                     run=fake_gh(fail="pulls/21/comments"))
    assert "/* check-icons-disable-next-line */" in out
    assert "inline review comments: none" in out
    assert "COULD NOT BE FETCHED" not in out
