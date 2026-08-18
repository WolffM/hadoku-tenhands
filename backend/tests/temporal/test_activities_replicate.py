"""replicate_fix_as_operator — the squashed fork preview PR

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

from tests.temporal.conftest import _conventions_envelope


def test_replicate_fix_as_operator_squashes_and_opens_preview(ev):
    """Phase 4.5: the core re-authoring step. Agent's fix is harvested
    as a single operator-authored commit on branch_name with no lineage
    to the agent's commits, a fork-internal preview PR is opened, and
    the agent's draft is closed.

    Also verifies that after replicate runs, the operator PR's body
    reflects the new single squashed SHA in its Fix section — NOT the
    agent's pre-replicate SHAs (the leak the user surfaced after v13).
    """
    from temporal.activities.submission import replicate_fix_as_operator

    # Seed evidence the way the upstream activities would write it
    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "number": 183,
            "title": "Fix the merged-cell bug",
            "body": "Spreadsheet anchors get dropped on import.",
        },
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["botA", "botB"],
        "files_touched": ["src/x.py", "tests/test_x.py"],
        "diff_bytes": 100,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [
        {"sha": "botA", "message": "Initial plan"},
        {"sha": "botB", "message": "Fix it"},
    ])
    ev.write_text("05-fixed/commit_shas.txt", "botA\nbotB\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\ntests/test_x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix the merged-cell bug")
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\nThe converter drops merged-cell anchors.\n\n"
        "## Root cause\n\nThe parser skips merged ranges.\n",
    )

    calls: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        calls.append((list(args), stdin_data))

        # GET pulls/7 detail
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"copilot/x","head_sha":"BOT_HEAD_SHA","base_ref":"main"}'}
        # GET commit tree sha
        if "git/commits/BOT_HEAD_SHA" in args[1] if len(args) > 1 else False:
            return {"success": True, "output": "BOT_TREE_SHA\n"}
        # GET tree root entries (notes.md strip pre-pass — 2026-04-30)
        if args[1] == "repos/WolffM/demo/git/trees/BOT_TREE_SHA" and "--jq" in args:
            # No notes.md in the tree — strip should be a no-op
            return {"success": True, "output": '["src/x.py", "tests/test_x.py"]'}
        # GET base ref sha
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_HEAD_SHA\n"}
        # POST git/commits — return the new squashed commit
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SQUASH_SHA"}'}
        # Ref existence check — simulate branch doesn't exist yet
        if args[1] == "repos/WolffM/demo/git/refs/heads/crimson-kitty-183" and "--silent" in args:
            return {"success": False, "error": "404"}
        # POST git/refs — create branch ref
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/crimson-kitty-183"}'}
        # GET pulls?state=open&head=... — stale-preview-PR audit (2026-05-21)
        if (
            args[:2] == ["api"][:1] + [args[1]]
            and "pulls?state=open&head=" in args[1]
        ):
            return {"success": True, "output": "[]"}
        # POST pulls — open operator PR
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        # PATCH pulls/7 — close agent draft
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "-X" in args and "PATCH" in args:
            return {"success": True, "output": "{}"}
        raise AssertionError(f"unexpected gh call: {args}")

    def fake_aggregator_get(endpoint: str):
        # Upstream has no PR template — render_pr_body uses _render_default
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = replicate_fix_as_operator(
        upstream_slug="upstream/demo",
        fork_slug="WolffM/demo",
        branch_name="crimson-kitty-183",
        evidence=ev,
        run_gh=fake_gh,
        aggregator_get=fake_aggregator_get,
    )

    # Returned metadata
    assert result["ok"] is True
    assert result["operator_pr_number"] == 42
    assert result["operator_pr_url"] == "https://github.com/WolffM/demo/pull/42"
    assert result["squashed_commit_sha"] == "NEW_SQUASH_SHA"
    assert result["agent_pr_closed"] == 7

    # The new commit's parent is the fork default HEAD, tree matches the
    # agent's final tree, and the agent's commit SHAs are NOT in the parents
    create_commit_calls = [
        (a, s) for a, s in calls
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit_calls) == 1
    import json as _json
    commit_payload = _json.loads(create_commit_calls[0][1])
    assert commit_payload["tree"] == "BOT_TREE_SHA"
    assert commit_payload["parents"] == ["BASE_HEAD_SHA"]
    assert "BOT_HEAD_SHA" not in commit_payload["parents"]  # lineage severed
    assert "Fix the merged-cell bug" in commit_payload["message"]

    # Evidence: commits.json now has only the new squashed commit, and
    # the agent's original commits are archived for audit.
    new_commits = ev.read_json("05-fixed/commits.json")
    assert new_commits == [{"sha": "NEW_SQUASH_SHA", "message": commit_payload["message"]}]
    agent_archive = ev.read_json("05-fixed/agent_original_commits.json")
    assert {c["sha"] for c in agent_archive} == {"botA", "botB"}

    # Operator PR URL + number persisted
    assert ev.read_text("09-submittable/operator_pr_url") == "https://github.com/WolffM/demo/pull/42"
    assert ev.read_text("09-submittable/operator_pr_number").strip() == "42"

    # The agent's draft was closed (PATCH state:closed)
    close_calls = [
        (a, s) for a, s in calls
        if a[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in a
    ]
    assert len(close_calls) == 1
    assert _json.loads(close_calls[0][1])["state"] == "closed"

    # Operator PR body must reflect the SQUASHED commit, not stale
    # agent SHAs. Regression for the v13 leak the user surfaced.
    open_pr_calls = [
        (a, s) for a, s in calls
        if a[1] == "repos/WolffM/demo/pulls" and "POST" in a
    ]
    assert len(open_pr_calls) == 1
    op_pr_body = _json.loads(open_pr_calls[0][1])["body"]

    # Stale agent SHAs must NOT appear in the operator PR body. The Fix
    # section no longer carries the squashed commit message as prose
    # (that just restated the Summary) — prose now comes from an agent-
    # written `05-fixed/fix_summary.md`, absent in this test. The leak-
    # prevention promise still holds: agent SHAs botA/botB don't appear,
    # and `commits.json` is rewritten to only the new squashed commit.
    assert "botA" not in op_pr_body
    assert "botB" not in op_pr_body
    # Sanity: the file list is still present so the operator can see scope.
    assert "src/x.py" in op_pr_body

    # No internal pipeline language can leak into the upstream-visible body
    body_lower = op_pr_body.lower()
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in body_lower, f"internal term '{forbidden}' leaked into operator PR body"

    # commit_shas.txt is also rewritten so submit_upstream_pr (later)
    # doesn't re-render with stale data
    new_shas = ev.read_text("05-fixed/commit_shas.txt").strip()
    assert new_shas == "NEW_SQUASH_SHA"
    assert ev.exists("05-fixed/agent_original_commit_shas.txt")


def test_replicate_closes_stale_branch_prs_before_opening_new(ev):
    """Audit 2026-05-21 fix: if a prior batch left an open operator preview
    PR on the same head branch, replicate must close it before opening a
    fresh one — otherwise the operator sees two PRs on one branch."""
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 183, "title": "Fix X", "body": "broken"},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["bot1"],
        "files_touched": ["src/x.py"],
        "diff_bytes": 50,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "bot1", "message": "fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "bot1\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix X")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nbroken thing\n")

    closed_prs: list[int] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"copilot/x","head_sha":"H","base_ref":"main"}'}
        if len(args) > 1 and "git/commits/H" in args[1]:
            return {"success": True, "output": "T\n"}
        if args[1] == "repos/WolffM/demo/git/trees/T" and "--jq" in args:
            return {"success": True, "output": '["src/x.py"]'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/crimson-kitty-183" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "POST" in args:
            return {"success": True, "output": '{}'}
        # Stale-PR lookup returns one open PR (#99) on the head branch
        if "pulls?state=open&head=WolffM:crimson-kitty-183" in args[1]:
            return {"success": True, "output": "[99]"}
        # PATCH /pulls/99 — the stale one being closed
        if args[:2] == ["api", "repos/WolffM/demo/pulls/99"] and "PATCH" in args:
            closed_prs.append(99)
            return {"success": True, "output": "{}"}
        if args[1] == "repos/WolffM/demo/pulls" and "POST" in args:
            return {"success": True, "output": '{"number":100,"html_url":"https://github.com/WolffM/demo/pull/100"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        raise AssertionError(f"unexpected gh call: {args}")

    def fake_agg(endpoint):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = replicate_fix_as_operator(
        upstream_slug="upstream/demo",
        fork_slug="WolffM/demo",
        branch_name="crimson-kitty-183",
        evidence=ev,
        run_gh=fake_gh,
        aggregator_get=fake_agg,
    )

    assert result["operator_pr_number"] == 100
    # The stale PR #99 from a prior batch was closed before #100 was opened
    assert closed_prs == [99]


def test_replicate_strips_notes_md_from_squashed_tree(ev):
    """2026-04-30: `notes.md` is a pipeline-internal scratch file the
    agent commits at repo root for the `repro_evidence_present` gate.
    It belongs in evidence (`04-reproduced/notes.md`), NOT in the
    upstream-bound diff. `replicate_fix_as_operator` must build a
    delta tree that strips `notes.md` from the agent's tree before
    creating the operator commit, so the upstream maintainer never
    sees the leak.

    Surfaced after the strapi + gofiber operator preview PRs leaked
    `notes.md` into their diffs.
    """
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 5, "title": "Fix it", "body": "Bug."},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/9",
        "commit_shas": ["botA"],
        "files_touched": ["src/x.py"],
        "diff_bytes": 100,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix it")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))

        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "OLD_TREE\n"}
        # Tree root listing INCLUDES notes.md → must be stripped
        if args[1] == "repos/WolffM/demo/git/trees/OLD_TREE" and "--jq" in args:
            return {"success": True, "output": '["src/x.py", "notes.md", "tests/test_x.py"]'}
        # POST git/trees → return a NEW tree sha that the squash should use
        if args[1] == "repos/WolffM/demo/git/trees" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"STRIPPED_TREE"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/op-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/op-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="op-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    # Assert the strip POST happened with the right payload
    strip_calls = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/trees" and "POST" in a
    ]
    assert len(strip_calls) == 1, "expected exactly one POST git/trees to strip notes.md"
    strip_payload = json.loads(strip_calls[0][1])
    assert strip_payload["base_tree"] == "OLD_TREE"
    assert strip_payload["tree"] == [
        {"path": "notes.md", "mode": "100644", "type": "blob", "sha": None}
    ]

    # Assert the squashed commit was built against the STRIPPED tree
    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    commit_payload = json.loads(create_commit[0][1])
    assert commit_payload["tree"] == "STRIPPED_TREE", (
        "operator commit should reference the stripped tree, not the "
        "agent's original tree containing notes.md"
    )


def test_replicate_no_strip_when_notes_md_absent(ev):
    """If the agent didn't commit notes.md, no POST git/trees should
    happen — we don't want a no-op API call on every replicate. The
    squash commit just uses the original tree directly."""
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 5, "title": "Fix it", "body": "Bug."},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/9",
        "commit_shas": ["botA"], "files_touched": ["src/x.py"],
        "diff_bytes": 100, "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix it")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "CLEAN_TREE\n"}
        # No notes.md in this tree
        if args[1] == "repos/WolffM/demo/git/trees/CLEAN_TREE" and "--jq" in args:
            return {"success": True, "output": '["src/x.py", "tests/test_x.py"]'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/op-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/op-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="op-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    # No POST git/trees should happen
    strip_calls = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/trees" and "POST" in a
    ]
    assert len(strip_calls) == 0, "no notes.md present → no strip POST should happen"

    # Squashed commit uses the original tree
    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    commit_payload = json.loads(create_commit[0][1])
    assert commit_payload["tree"] == "CLEAN_TREE"


def test_replicate_appends_signoff_when_dco_required(ev):
    """Phase 5.3 acceptance: a DCO-required upstream → squash commit
    carries `Signed-off-by: <name> <email>`."""
    from temporal.activities.submission import replicate_fix_as_operator

    # Pre-seed conventions with DCO required so the activity reads from
    # cache rather than calling the aggregator
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(signoff_required=True)["data"])
    # Issue brief for the internal render_pr_body call
    ev.write_json("01-eligible/issue_brief.json",
                  {"issue": {"number": 1, "title": "Fix the bug", "body": "x"}})
    # Standard agent-result + render scaffolding
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["botA"], "files_touched": ["src/x.py"],
        "diff_bytes": 100, "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Initial"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFixes the bug.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))
        if args[:2] == ["api", "user"] and "--jq" in args:
            return {"success": True, "output": json.dumps({
                "name": "Test Operator", "login": "testop", "email": "test@example.com",
            })}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "BOT_TREE\n"}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main":
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/operator-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/operator-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        # render_pr_body still calls pr-template
        if "pr-template" in endpoint:
            return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(signoff_required=True)
        return {"success": True, "data": {}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="operator-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    payload = json.loads(create_commit[0][1])
    assert "Signed-off-by: Test Operator <test@example.com>" in payload["message"]
