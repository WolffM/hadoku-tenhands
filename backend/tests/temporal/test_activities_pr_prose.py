"""The prose helpers behind a PR body: scrubbing, lead-in stitching, summaries.

These exercise `_scrub_internal_language`, `_first_prose_paragraph` and
`_extract_summary` directly rather than through `render_pr_body`, which is
why they are not in test_activities_pr_body.py.
"""

from __future__ import annotations


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
