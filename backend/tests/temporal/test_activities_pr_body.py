"""PR-body rendering: prose extraction, scrubbing, titles, templates

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

from tests.temporal.conftest import _conventions_envelope


def test_render_pr_body_without_template(ev):
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "Fix the merged-cell bug"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\ntests/test_x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff " * 50)
    ev.write_text("05-fixed/commit_shas.txt", "abc\ndef\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = render_pr_body(
        "microsoft/markitdown", 183, ev, aggregator_get=fake_get,
    )
    assert result["ok"] is True
    title = ev.read_text("09-submittable/pr_title.txt")
    body = ev.read_text("09-submittable/pr_body.md")
    assert "Fix the merged-cell bug" in title
    assert "## Summary" in body
    assert "src/x.py" in body
    # Fixes #N is intentionally NOT in the rendered body — it gets
    # appended at submit_upstream_pr time, after the no_upstream_refs
    # gate has run on the leak-free body. See cross-ref-isolation.md.
    assert "Fixes #" not in body


def test_render_pr_body_scrubs_internal_language_from_verify_notes(ev):
    """User-reported leak after v13: the synthesized verify_notes.md
    contained "the agent's PR diff", "exit_reason was success", and
    "## Commits from this agent session" — all internal pipeline
    vocabulary that must NEVER appear in an upstream-visible PR.

    The render step now strips any line containing internal terms
    (agent, exit_reason, auto-synthesized, orchestrator, harvest,
    copilot, scrubbed) before composing the Verification section.
    """
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    # Old-style verify notes with all the leaks inline
    ev.write_text(
        "06-verified/verify_notes.md",
        "> Auto-synthesized by the orchestrator. The agent's verify phase\n"
        "> completed but did not commit a standalone test output.\n\n"
        "## Files touched in verify phase\n\nsrc/x.py\n\n"
        "## Commits from this agent session\n\n  - abc12345\n\n"
        "## Verification basis\n\n"
        "Evidence of verification lives in the agent's PR diff.\n"
        "The agent's final exit_reason was `success`.\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md").lower()

    # None of the internal pipeline vocabulary survives into the body
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in body, f"'{forbidden}' leaked into PR body"


def test_scrub_internal_language_strips_workspace_paths():
    """2026-05-22 — keycloak#46523 v3: the agent wrote absolute container
    paths into notes.md (`/tmp/workspace/WolffM/keycloak-keycloak/...`).
    `_render_default` then lifted those lines verbatim into the upstream
    PR body, leaking the runtime container path, fork owner, and encoded
    fork slug to upstream reviewers. The scrubber must rewrite each known
    workspace prefix to repo-relative form."""
    from temporal.activities.submission import _scrub_internal_language

    text = (
        "1. From repository root, run `./mvnw test`.\n"
        "2. Inspect `/tmp/workspace/WolffM/keycloak-keycloak/common/src/main/java/Profile.java`.\n"
        "3. Also see `/home/runner/work/keycloak-keycloak/keycloak-keycloak/js/apps/mock.json`.\n"
        "4. Codespace shape: `/workspaces/keycloak-keycloak/common/Profile.java`.\n"
    )
    out = _scrub_internal_language(text)

    # None of the absolute prefixes survive
    assert "/tmp/workspace" not in out
    assert "/home/runner/work" not in out
    assert "/workspaces/" not in out
    # Repo-relative paths preserved
    assert "common/src/main/java/Profile.java" in out
    assert "js/apps/mock.json" in out
    assert "common/Profile.java" in out


def test_render_pr_body_strips_workspace_paths_from_steps(ev):
    """End-to-end: a notes.md whose Steps to reproduce mention absolute
    workspace paths must produce a PR body with only repo-relative refs."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n"
        "1. From repo root, run `./mvnw test`.\n"
        "2. Inspect `/tmp/workspace/WolffM/keycloak-keycloak/common/Profile.java`.\n\n"
        "## Observed\nThe assertion fails.\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("keycloak/keycloak", 46523, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    assert "/tmp/workspace" not in body
    assert "WolffM" not in body  # fork owner must not leak
    assert "common/Profile.java" in body  # repo-relative path preserved


def test_render_pr_body_embeds_screenshot_when_after_url_present(ev):
    """2026-04-30: when the screenshot activity uploaded a verification
    PNG to the fork's release assets and persisted the URL to
    06-verified/after_url.txt, the rendered Verification section embeds
    `![Verification](url)` at the top — visual proof of the test run.

    Updated 2026-05-20: the agent's `verify_notes.md` is now ignored
    (recurring hand-wave phrases were leaking through). The image is
    the only signal coming out of this test fixture; the test-changes
    sentence and the test_output codeblock only fire when their inputs
    are present."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "06-verified/after_url.txt",
        "https://github.com/WolffM/demo/releases/download/crimson-kitty-assets/issue-1-after.png\n",
    )
    # Agent verify_notes is deliberately ignored now — seeded only to
    # prove the renderer no longer reaches for it.
    ev.write_text(
        "06-verified/verify_notes.md",
        "Adds tests covering the corrected behavior:\n\n"
        "- `tests/test_x.py`\n\nThe diff is small enough to read in full.",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    assert (
        "![Verification](https://github.com/WolffM/demo/releases/download/"
        "crimson-kitty-assets/issue-1-after.png)" in body
    )
    # Agent's verify_notes content must NOT appear anywhere.
    assert "diff is small enough to read in full" not in body
    assert "Adds tests covering the corrected behavior" not in body


def test_render_pr_body_embeds_both_screenshot_and_test_output(ev):
    """Updated 2026-05-20: a screenshot does not replace the raw test
    output. The image is at-a-glance proof; the code block is what the
    submission_judge actually reads. Both render."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("06-verified/after_url.txt", "https://example.com/after.png\n")
    ev.write_text(
        "06-verified/test_output.txt",
        "PASS: TestExample (0.01s)\nok      example.com/foo    0.034s\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    assert "![Verification](https://example.com/after.png)" in body
    assert "Test output:" in body
    assert "PASS: TestExample" in body


def test_render_pr_body_falls_back_to_text_when_no_screenshot(ev):
    """No after_url.txt → existing text-only chain still works. Tests
    the absence path so the screenshot feature stays opt-in cleanly."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "06-verified/test_output.txt",
        "PASS: TestExample (0.01s)\nok      example.com/foo    0.034s\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # No image embed
    assert "![Verification]" not in body
    # Test output code block IS present (the fallback path)
    assert "Test output:\n\n```" in body
    assert "PASS: TestExample" in body


def test_render_pr_body_strips_stale_commit_shas_from_repro_section(ev):
    """B26: legacy `_synthesize_repro_notes` runs embedded
    `Commit SHAs:\\n  - abc1234` blocks in the Steps to reproduce
    section. After `replicate_fix_as_operator` squashes, those SHAs
    are stale — they reference commits that no longer exist on the
    submission branch. User flagged this on v15 svelte/cli where the
    body listed `eab5c43` and `f862221`.

    The render-side scrubber strips both the `Commit SHAs:` heading
    and the bullet lines that look like bare hex SHAs. Reviewers
    don't need pre-squash commit history in Steps to reproduce."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Some bug", "body": "There's a bug here."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/foo.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "newsquash\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n\n"
        "1. Run the failing test.\n"
        "2. Observe the crash.\n"
        "Commit SHAs:\n"
        "  - eab5c43\n"
        "  - f862221\n\n"
        "## Observed\n\n"
        "It crashes loudly with " + ("noise " * 30) + "\n\n"
        "## Expected\n\n"
        "No crash.\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # Stale SHAs gone
    assert "eab5c43" not in body
    assert "f862221" not in body
    assert "Commit SHAs:" not in body

    # Real Steps-to-reproduce content survives
    assert "Run the failing test" in body
    assert "Observe the crash" in body


def test_render_pr_body_pulls_rich_content_from_evidence(ev):
    """B21: the default render must produce a reviewable PR body with
    real problem/fix/verify content, not a skeletal checklist. v9
    submission_judge scored an empty-template body at 0.25 and aborted."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Crashes when loading .xlsx with merged cells",
            "body": (
                "When opening a spreadsheet with merged cells in the header "
                "row, the parser crashes with a NullPointerException. This "
                "reproduces consistently on v1.2.3 and later."
            ),
        },
    })
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n"
        "1. Create an xlsx with merged cells in row 1.\n"
        "2. Call parse_xlsx() on it.\n\n"
        "## Observed\n"
        "NullPointerException at XlsxParser.java:142 during cell coalescing "
        "because the merged-cell resolver returns null when row 0 has span > 1.\n\n"
        "## Expected\n"
        "Merged header cells should resolve to their anchor cell's value.\n",
    )
    ev.write_text("05-fixed/files_touched.txt", "src/XlsxParser.java\ntests/XlsxParserTest.java\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\ndef5678\n")
    ev.write_text("05-fixed/diff.patch", "diff --git a/x b/x\n")
    ev.write_text(
        "06-verified/test_output.txt",
        "12 tests passed including merged_header_regression",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("microsoft/markitdown", 183, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # All four main sections present with real content
    assert "## Summary" in body
    assert "NullPointerException" in body  # from the brief
    assert "## Root cause" in body
    assert "cell coalescing" in body  # from the repro notes' Observed section
    assert "## Steps to reproduce" in body
    assert "## Fix" in body
    # 2026-05-20: SHA-listing dropped from the Fix section; file list stays
    # so reviewers can see scope, and the post-replicate commit message
    # (when present in commits.json) supplies the prose.
    assert "src/XlsxParser.java" in body
    assert "## Verification" in body
    assert "12 tests passed" in body

    # Body must have substance — enough words for a human reviewer to
    # evaluate. v9 argo-cd aborted with the earlier skeletal body at 0.25.
    assert len(body.split()) >= 60


def test_render_pr_body_summary_skips_issue_form_heading(ev):
    """2026-05-21: GitHub issue-forms repos (svelte, keycloak) start the
    issue body with a bare template heading (`### Describe the bug`,
    `### Description`). The naive first-paragraph extraction returned just
    that heading, so the PR Summary rendered as an empty `### Describe the
    bug` block. The summary must skip the heading and use real prose."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Promote dynamic client scopes feature to preview",
            "body": (
                "### Description\n\n"
                "Promote dynamic client scopes feature to preview.\n\n"
                "### Value Proposition\n\n"
                "Allows parameterizable scopes.\n\n"
                "### Discussion\n\n_No response_\n"
            ),
        },
    })
    ev.write_text("04-reproduced/notes.md", "## Observed\nFeature stays EXPERIMENTAL.\n")
    ev.write_text("05-fixed/files_touched.txt", "common/src/main/java/Profile.java\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("keycloak/keycloak", 46523, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # The Summary section carries the real description, not the bare heading
    assert "Promote dynamic client scopes feature to preview." in body
    # No orphaned issue-form heading leaked in as the summary content
    assert "### Description" not in body
    assert "_No response_" not in body


def test_first_prose_paragraph_skips_non_prose_blocks():
    """Lower-level guard for the issue-forms summary fix. Block splitting
    must be line-ending- and whitespace-tolerant, and skip every non-prose
    leading block (heading-only, `_No response_`, `<!-- … -->`)."""
    from temporal.activities.submission import _first_prose_paragraph

    prose = "The real prose is here."
    assert _first_prose_paragraph(f"Plain prose first.\n\n{prose}") == "Plain prose first."
    # heading skipped across LF, CRLF, and whitespace-only blank separators
    assert _first_prose_paragraph(f"### Describe the bug\n\n{prose}") == prose
    assert _first_prose_paragraph(f"### Describe the bug\r\n\r\n{prose}") == prose
    assert _first_prose_paragraph(f"### Description\n   \n{prose}") == prose
    # GitHub-forms empty marker + HTML-comment placeholder skipped
    assert _first_prose_paragraph(f"_No response_\n\n{prose}") == prose
    assert _first_prose_paragraph(f"<!-- describe here -->\n\n{prose}") == prose
    # all-junk body yields empty (caller falls back to the title sentence)
    assert _first_prose_paragraph("### Description\n\n_No response_\n\n<!-- x -->") == ""


def test_extract_summary_stitches_lead_in_into_code(ev):
    """2026-05-21 follow-up: svelte#13759's issue body is a narrative where
    every prose block ends in `:` and leads into a code fence. Taking only
    the first block gave a dangling fragment ('…overload:') the judge
    flagged as incomplete. The summary must stitch the lead-in with the
    block it introduces so it carries a complete thought."""
    from temporal.activities.submission import _extract_summary

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Snippet type mismatch",
            "body": (
                "### Describe the bug\r\n\r\n"
                "In a class, I have the following overload:\r\n\r\n"
                "```typescript\r\n    show(content: string | Snippet): void;\r\n```\r\n\r\n"
                "This is a SvelteKit project.\r\n"
            ),
        },
    })
    summary = _extract_summary(ev, "Snippet type mismatch")

    # Not a dangling lead-in: the colon sentence carries its code block
    assert summary.startswith("In a class, I have the following overload:")
    assert "show(content: string | Snippet): void;" in summary
    assert not summary.rstrip().endswith(":")


def test_extract_summary_keeps_self_contained_block(ev):
    """A self-contained first sentence (not a lead-in) must NOT pull in
    following blocks — keycloak#46523 should stay a clean one-liner."""
    from temporal.activities.submission import _extract_summary

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Promote feature",
            "body": (
                "### Description\n\n"
                "Promote dynamic client scopes feature to preview.\n\n"
                "### Value Proposition\n\nAllows parameterizable scopes.\n"
            ),
        },
    })
    summary = _extract_summary(ev, "Promote feature")
    assert summary == "Promote dynamic client scopes feature to preview."


def test_render_pr_body_uses_fix_summary_md_for_fix_prose(ev):
    """2026-05-20: judge complained that the Fix section was always just a
    file list. Agent now writes `05-fixed/fix_summary.md` describing what
    the code change does; the renderer surfaces it as the Fix-section
    prose. When the file is absent, the section falls back to the file
    list only (no hallucinated prose)."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Parser drops merged-cell anchors", "body": "Bug."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/parser.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")
    ev.write_text(
        "05-fixed/fix_summary.md",
        "Clamped the anchor-cell lookup in `parser.py` to "
        "`max(0, anchor_row)` so the walk stays inside the merged range "
        "when row 0 has span > 1.",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    assert "## Fix" in body
    assert "Clamped the anchor-cell lookup" in body
    # File list still appears beneath the prose.
    assert "src/parser.py" in body


def test_render_pr_body_fix_section_omits_prose_when_summary_md_absent(ev):
    """Without `05-fixed/fix_summary.md`, the Fix section is just the
    file list — no fabricated prose. The judge will defer/fail this,
    which is the correct signal: the agent didn't produce a fix
    description."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Bug", "body": "Body."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    # Fix section present but with file list only.
    assert "## Fix" in body
    assert "src/x.py" in body
    # No phantom prose: the Files-changed line is the first content beneath
    # the Fix heading.
    _, fix_and_after = body.split("## Fix", 1)
    fix_section = fix_and_after.split("\n## ", 1)[0]
    assert "Files changed" in fix_section


def test_render_pr_body_filters_notes_md_from_displayed_files(ev):
    """The operator PR tree already strips notes.md; the rendered file
    list must match — otherwise the judge flags notes.md as unexplained
    even though it's not actually in the diff being submitted."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Bug", "body": "Body."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\nnotes.md\ntests/test_x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    _, fix_and_after = body.split("## Fix", 1)
    fix_section = fix_and_after.split("\n## ", 1)[0]
    # Source + test file appear; notes.md does not.
    assert "src/x.py" in fix_section
    assert "tests/test_x.py" in fix_section
    assert "notes.md" not in fix_section


def test_build_title_strips_bracket_prefix_and_word_snaps(ev):
    """2026-05-20: the title renderer was emitting `[Bug] ...`-prefixed
    titles + chopping mid-word at the 80-char cap. Strip prefixes, add
    `fix:`, snap to a word boundary."""
    from temporal.activities.submission import _build_title

    assert _build_title("[Bug] Failed to load source map") == (
        "fix: Failed to load source map"
    )
    assert _build_title("[BUG]: NanoGPT Model Selector overflowing") == (
        "fix: NanoGPT Model Selector overflowing"
    )
    assert _build_title("[question] is it possible to stop parsing") == (
        "fix: is it possible to stop parsing"
    )
    # Already-conventional title is not double-prefixed.
    assert _build_title("feat: add new flag") == "feat: add new flag"
    # Long title word-snaps at the cap, with an ellipsis.
    long_in = (
        "Random sorting in GetSimilarItems (PR #14918) breaks recommendation "
        "accuracy in More Like This panel rendering"
    )
    out = _build_title(long_in)
    assert out.startswith("fix: Random sorting")
    assert out.endswith("…")
    assert len(out) <= 80
    # Title that arrives empty after stripping prefixes still produces a
    # sensible default rather than a bare `fix: `.
    assert _build_title("[Bug]") == "fix: Crimson-kitty fix"


def test_render_pr_body_with_template(ev):
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x"}})
    ev.write_text("05-fixed/files_touched.txt", "a.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {
            "path": ".github/PULL_REQUEST_TEMPLATE.md",
            "raw_text": "## Summary\n\n## Test plan\n",
            "sections": [
                {"heading": "## Summary", "required": True},
                {"heading": "## Test plan", "required": True},
            ],
        }}

    render_pr_body("microsoft/markitdown", 183, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    assert "## Summary" in body
    assert "## Test plan" in body
    # Fixes #N appended at submit time, not render time
    assert "Fixes #" not in body
    assert ev.exists("09-submittable/template.json")


def test_render_pr_body_template_path_uses_rich_default_content(ev):
    """B24: when upstream has a PR template, the rendered body must
    still carry the rich narrative from `_render_default` (real issue
    prose, repro steps, commit SHAs) — not the old skeletal "paste
    fix_summary under every heading" output. Regression for v10
    prettier/mermaid aborts at submission_judge 0.27–0.34 with
    "unfilled template placeholders" feedback.

    Also verifies the template's required headings are still present
    so `pr_template_compliance` passes.
    """
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Angular: add support for comment blocks in elements",
            "body": "Prettier doesn't currently preserve HTML comment "
                    "blocks inside Angular template elements. This "
                    "breaks comment-based developer notes that ship "
                    "in component templates.",
        },
    })
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n1. Format an Angular component with inline comments.\n\n"
        "## Observed\nComments are stripped from the element scope.\n\n"
        "## Expected\nComments preserved verbatim.\n",
    )
    ev.write_text("05-fixed/files_touched.txt", "src/angular/parser.js\n")
    ev.write_text("05-fixed/commit_shas.txt", "abcdef12\n")
    ev.write_text("05-fixed/diff.patch", "diff --git x y")
    ev.write_text("06-verified/test_output.txt", "42 tests passed")

    def fake_get(endpoint: str):
        return {"success": True, "data": {
            "path": ".github/PULL_REQUEST_TEMPLATE.md",
            "raw_text": "## Description\n\n<!-- please describe -->\n\n## Checklist\n- [ ] tests\n",
            "sections": [
                {"heading": "## Description", "required": True},
                {"heading": "## Checklist", "required": True},
            ],
        }}

    render_pr_body("prettier/prettier", 18974, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # Rich content from _render_default is the PRIMARY body
    assert "## Summary" in body
    assert "Prettier doesn't currently preserve" in body  # issue prose
    assert "## Root cause" in body
    assert "Comments are stripped from the element scope" in body  # repro observed
    # 2026-05-20: SHA-listing dropped from Fix section; file list still here.
    assert "src/angular/parser.js" in body
    assert "42 tests passed" in body

    # Template required headings present so pr_template_compliance passes
    assert "## Description" in body
    assert "## Checklist" in body

    # No stale raw template noise — the old code would've left "<!-- please describe -->"
    # and duplicated "Files touched" under every heading
    assert body.count("## Description") == 1
    assert body.count("## Checklist") == 1

    # Body must be substantive (previous template-path output scored 0.25-0.34)
    assert len(body.split()) >= 60


def test_render_pr_body_prepends_conventional_prefix(ev):
    """Phase 5.3 acceptance: a conventional-commits repo gets `fix:`
    prepended to the PR title."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Crashes when loading merged xlsx", "body": "x"},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")

    def fake_get(endpoint: str):
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(commit_style="conventional")
        if "pr-template" in endpoint:
            return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    render_pr_body("microsoft/terminal", 1, ev, aggregator_get=fake_get)
    title = ev.read_text("09-submittable/pr_title.txt")
    assert title.startswith("fix: "), title
    # Conventions persisted to evidence
    assert ev.exists("09-submittable/contribution_conventions.json")
    cached = ev.read_json("09-submittable/contribution_conventions.json")
    assert cached["commit_style"] == "conventional"


def test_render_pr_body_skips_prefix_when_already_present(ev):
    """Idempotent: if the issue title already has a conventional prefix,
    don't double-prefix it."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "feat: add new flag", "body": "x"},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")
    ev.write_text("05-fixed/diff.patch", "diff")

    def fake_get(endpoint: str):
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(commit_style="conventional")
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    title = ev.read_text("09-submittable/pr_title.txt")
    assert title.startswith("feat: "), title
    assert not title.startswith("fix: feat:")
