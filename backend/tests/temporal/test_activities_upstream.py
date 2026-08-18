"""submit_upstream_pr and the per-repo contribution conventions

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

import pytest

from tests.temporal.conftest import _conventions_envelope


def test_submit_upstream_pr_omits_close_keyword_when_in_body_false(ev):
    """Phase 5.3 acceptance: a repo whose CONTRIBUTING.md says "do not
    include Fixes in body" → submit_upstream_pr does NOT append the
    close keyword to the body."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(references={"in_body": False})["data"])

    captured_body: list[str] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/u/r/pull/100\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=42, run_gh=fake_gh,
    )

    assert len(captured_body) == 1
    assert "Fixes #42" not in captured_body[0]
    assert "Closes #42" not in captured_body[0]
    assert "## Summary" in captured_body[0]


def test_submit_upstream_pr_uses_custom_close_keyword(ev):
    """A `Resolves #N`-style upstream → footer uses Resolves, not Fixes."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(references={
                      "close_keyword": "Resolves",
                      "syntax": "Resolves #N",
                      "in_body": True,
                  })["data"])

    captured_body: list[str] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/u/r/pull/100\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=42, run_gh=fake_gh,
    )

    assert len(captured_body) == 1
    assert "Resolves #42" in captured_body[0]
    assert "Fixes #42" not in captured_body[0]


def test_load_conventions_falls_back_to_defaults_on_aggregator_failure(ev):
    """Defensive: aggregator outage / 5xx → activities use safe defaults
    (freeform, Fixes #N, no signoff) rather than crashing the workflow."""
    from temporal.activities.submission import _load_conventions

    def failing_aggregator(endpoint: str):
        return None  # simulating _call_aggregator's None-on-error contract

    result = _load_conventions(ev, failing_aggregator, "any/repo")
    assert result["commit_style"] == "freeform"
    assert result["signoff_required"] is False
    assert result["references"]["close_keyword"] == "Fixes"
    assert result["references"]["in_body"] is True
    # Persisted to evidence so subsequent activities see the same defaults
    assert ev.exists("09-submittable/contribution_conventions.json")


def test_submit_upstream_pr_writes_evidence_on_success(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix\n")

    captured_body = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            # Capture the --body arg for the close-keyword assertion below
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/microsoft/markitdown/pull/9999\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "microsoft/markitdown", "WolffM/markitdown", "fix-x", "main", ev,
        issue_number=183,
        run_gh=fake_gh,
    )
    assert result["pr_number"] == 9999
    assert "9999" in result["pr_url"]
    assert ev.read_text("10-submitted/upstream_pr_url").strip().endswith("9999")

    # The intentional close keyword was appended to the body at submit time
    # (not present in the on-disk pr_body.md, which is what no_upstream_refs scanned)
    assert len(captured_body) == 1
    assert "Fixes #183" in captured_body[0]
    assert "Fixes #183" not in ev.read_text("09-submittable/pr_body.md")


def test_submit_upstream_pr_reads_live_fork_preview_when_present(ev):
    """Phase 4.5 — when `09-submittable/operator_pr_number` is recorded
    (the operator-signoff flow), submit_upstream_pr fetches the LIVE
    title and body from the fork preview PR via gh api. The operator
    may have edited the preview between submittable gates passing and
    signaling approve; their edits MUST flow upstream verbatim."""
    from temporal.activities.submission import submit_upstream_pr

    # Stale evidence — the operator edited the live PR after this was written
    ev.write_text("09-submittable/pr_title.txt", "Stale title from before edits")
    ev.write_text("09-submittable/pr_body.md", "Stale rendered body.")
    # The replicate step records the fork preview PR number
    ev.write_text("09-submittable/operator_pr_number", "42")

    captured_create = []
    edited_title = "Operator's edited title — much better"
    edited_body = (
        "## Summary\n\nThe operator added a screenshot and tightened the\n"
        "repro narrative here. This is the source of truth for upstream.\n"
    )

    def fake_gh(args, stdin_data=None):
        # Live preview PR fetch
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": edited_title, "body": edited_body}),
            }
        if args[:2] == ["pr", "create"]:
            captured_create.append(list(args))
            return {"success": True, "output": "https://github.com/u/r/pull/77\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=99,
        run_gh=fake_gh,
    )
    assert result["pr_number"] == 77

    # The upstream PR was created with the LIVE title + body, not the
    # stale evidence-file content
    assert len(captured_create) == 1
    create_args = captured_create[0]
    title_idx = create_args.index("--title")
    body_idx = create_args.index("--body")
    assert create_args[title_idx + 1] == edited_title
    submitted_body = create_args[body_idx + 1]
    assert "operator added a screenshot" in submitted_body
    # Stale content must NOT appear
    assert "Stale title from before edits" not in submitted_body
    assert "Stale rendered body." not in submitted_body
    # Close keyword still appended at submit time
    assert "Fixes #99" in submitted_body


def test_submit_upstream_pr_blocks_when_operator_edit_introduces_upstream_ref(ev):
    """Defense in depth: an operator who pastes an upstream URL into the
    fork preview PR's body must NOT bypass the no_upstream_refs gate
    just because that gate already ran before signoff. submit_upstream_pr
    re-scans the live content right before opening the upstream PR."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "x")
    ev.write_text("09-submittable/operator_pr_number", "42")
    ev.write_json("01-eligible/issue_brief.json", {"issue": {"number": 100, "title": "Fix"}})

    leaky_body = (
        "## Summary\n\nOperator added context: see "
        "https://github.com/upstream/repo/issues/100 — same as that issue.\n"
    )

    def fake_gh(args, stdin_data=None):
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": "Fix x", "body": leaky_body}),
            }
        if args[:2] == ["pr", "create"]:
            raise AssertionError("gh pr create must NOT run when sanitizer trips")
        return {"success": True, "output": "{}"}

    with pytest.raises(RuntimeError, match="upstream ref"):
        submit_upstream_pr(
            "upstream/repo", "WolffM/repo", "branch", "main", ev,
            issue_number=100,
            run_gh=fake_gh,
        )


def test_submit_upstream_pr_edits_existing_upstream_pr_on_remediation(ev):
    """Phase 5.1: when 10-submitted/upstream_pr_number is already recorded
    (i.e. this is a remediation cycle), submit_upstream_pr does NOT call
    `gh pr create` — it calls `gh pr edit` to refresh the existing
    upstream PR's title/body. The branch was already force-pushed by
    replicate_fix_as_operator, so GitHub auto-refreshes the diff."""
    from temporal.activities.submission import submit_upstream_pr

    # Stale evidence + recorded existing upstream PR + recorded operator preview
    ev.write_text("09-submittable/pr_title.txt", "stale title")
    ev.write_text("09-submittable/pr_body.md", "stale body")
    ev.write_text("09-submittable/operator_pr_number", "42")
    ev.write_text("10-submitted/upstream_pr_number", "888")
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/u/r/pull/888")

    edited_title = "Operator's refined title (after remediation)"
    edited_body = "## Summary\n\nAddressed maintainer's feedback on src/x.py.\n"

    captured_edit: list[list[str]] = []

    def fake_gh(args, stdin_data=None):
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": edited_title, "body": edited_body}),
            }
        if args[:2] == ["pr", "create"]:
            raise AssertionError("must not call `gh pr create` on remediation re-submit")
        if args[:2] == ["pr", "edit"]:
            captured_edit.append(list(args))
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=999,
        run_gh=fake_gh,
    )

    assert result["pr_number"] == 888
    assert result["updated"] is True
    assert "888" in result["pr_url"]

    assert len(captured_edit) == 1
    edit_args = captured_edit[0]
    assert edit_args[2] == "888"  # the existing upstream PR number
    title_idx = edit_args.index("--title")
    body_idx = edit_args.index("--body")
    assert edit_args[title_idx + 1] == edited_title
    submitted_body = edit_args[body_idx + 1]
    assert "Addressed maintainer's feedback" in submitted_body
    # Close keyword still appended at submit time
    assert "Fixes #999" in submitted_body
    # Stale evidence content NOT used
    assert "stale title" not in submitted_body
    assert "stale body" not in submitted_body


def test_submit_upstream_pr_raises_on_failure(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "x")
    ev.write_text("09-submittable/pr_body.md", "y")

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "pr already exists"}

    with pytest.raises(RuntimeError, match="gh pr create failed"):
        submit_upstream_pr("u/r", "WolffM/r", "b", "main", ev, run_gh=fake_gh)
