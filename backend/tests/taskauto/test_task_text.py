"""Tests for temporal/taskauto/task_text.py.

The `allow-protected` tests are the security-relevant ones: they pin that
an authorisation can only come from somewhere the agent cannot write.
"""

from __future__ import annotations

import pytest

from temporal.taskauto.task_text import (
    classify,
    extract_allow_protected,
    strip_bug_prefix,
)


# ── bug- classification ───────────────────────────────────────────────────


@pytest.mark.parametrize("title", [
    "bug-wooshing starts before music starts",
    "bug-animations get stuck and lag",
    "bug-top level color picker doesn't propagte to child app",
    "Bug-capitalised",
    "bug: colon form",
    "bug - spaced",
])
def test_bug_prefixed_titles_need_a_repro(title):
    assert classify(title).is_bug is True
    assert classify(title).needs_repro is True


@pytest.mark.parametrize("title", [
    "make coffee theme default",
    "reorganize categories, interesting stuff front and center",
    "too much wooshing",
    "need a cancel button",
    "hide 'generating with GLM-5'",
    "debug the exporter",       # 'bug' inside a word is not the prefix
    "fix a bug in the parser",  # mentions a bug, isn't prefixed as one
])
def test_change_requests_are_not_held_to_a_repro(title):
    """Demanding a reproduction from `make coffee theme default` is a
    category error — nothing is claimed to be broken."""
    assert classify(title).is_bug is False
    assert classify(title).needs_repro is False


def test_classification_ignores_the_body():
    """A task whose notes quote an error message is not thereby a bug
    report; only the title decides."""
    assert classify("add a cancel button").is_bug is False


def test_strip_bug_prefix():
    assert strip_bug_prefix("bug-wooshing starts early") == "wooshing starts early"
    assert strip_bug_prefix("make coffee default") == "make coffee default"
    assert strip_bug_prefix("") == ""


def test_classify_tolerates_empty_title():
    assert classify("").is_bug is False


# ── allow-protected: authorisation, not text ──────────────────────────────


def test_reads_directive_from_the_title():
    got = extract_allow_protected(
        title="fix deploy allow-protected: .github/workflows/deploy.yml")
    assert got == [".github/workflows/deploy.yml"]


def test_reads_directive_from_the_claim_time_notes_snapshot():
    got = extract_allow_protected(
        notes_at_claim="some plan\nallow-protected: .github/workflows/*.yml\n")
    assert got == [".github/workflows/*.yml"]


def test_agent_cannot_authorise_itself_by_writing_notes():
    """THE test on this page. The planning agent rewrites notes every pass.
    If live notes were a source, the agent could grant itself permission to
    edit CI or its own gates and the deny-list would enforce nothing.

    Only the claim-time snapshot counts — the human's version by
    construction, since we cannot write before holding the claim.
    """
    human_wrote = "please fix the deploy"
    agent_wrote = human_wrote + "\n\nallow-protected: backend/temporal/**\n"

    # What the gate is given: the snapshot, not what the agent produced.
    assert extract_allow_protected(title="fix deploy",
                                   notes_at_claim=human_wrote) == []
    # And to be explicit about what the agent's own text would have granted:
    assert extract_allow_protected(notes_at_claim=agent_wrote) == [
        "backend/temporal/**"], "sanity: the directive itself parses fine"


def test_no_directive_grants_nothing():
    assert extract_allow_protected(
        title="fix the production CI workflow bug",
        notes_at_claim="a plan with no directive") == []


def test_multiple_globs_on_one_line():
    got = extract_allow_protected(
        notes_at_claim="allow-protected: .github/workflows/deploy.yml, Dockerfile")
    assert got == [".github/workflows/deploy.yml", "Dockerfile"]


def test_multiple_directives_across_lines_and_sources():
    got = extract_allow_protected(
        title="x allow-protected: Dockerfile",
        notes_at_claim="allow-protected: deploy/**\nallow-protected: infra/**")
    assert got == ["Dockerfile", "deploy/**", "infra/**"]


def test_duplicates_are_collapsed():
    got = extract_allow_protected(
        title="allow-protected: Dockerfile",
        notes_at_claim="allow-protected: Dockerfile")
    assert got == ["Dockerfile"]


def test_backticks_and_quotes_are_stripped():
    """People type markdown. `allow-protected: \\`Dockerfile\\`` must not
    grant a path that literally contains backticks and therefore matches
    nothing — silently granting less than the human intended."""
    assert extract_allow_protected(
        notes_at_claim="allow-protected: `Dockerfile`") == ["Dockerfile"]
    assert extract_allow_protected(
        notes_at_claim='allow-protected: "deploy/**"') == ["deploy/**"]


def test_case_insensitive_directive():
    assert extract_allow_protected(
        notes_at_claim="Allow-Protected: Dockerfile") == ["Dockerfile"]


def test_in_notes_the_directive_must_start_a_line():
    """Notes run to kilobytes and may legitimately discuss the deny-list.
    Prose is not an authorisation."""
    assert extract_allow_protected(
        notes_at_claim="we could add allow-protected: Dockerfile if needed") == []


def test_in_a_title_the_directive_may_appear_anywhere():
    """A title is one short human-written line with no room for incidental
    discussion, and a trailing directive is how someone types this on a
    phone. Ignoring it would stall the task with no visible cause."""
    assert extract_allow_protected(
        title="fix deploy allow-protected: .github/workflows/deploy.yml"
    ) == [".github/workflows/deploy.yml"]


def test_empty_directive_grants_nothing():
    assert extract_allow_protected(notes_at_claim="allow-protected:   ") == []


def test_no_sources_grants_nothing():
    assert extract_allow_protected() == []
