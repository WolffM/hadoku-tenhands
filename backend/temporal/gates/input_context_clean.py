"""input_context_clean gate — runs after `forked` state.

Scans the scrubbed brief that was written by the fork+scrub activity for
any surviving real upstream ref. This is the input-side leak control —
the primary defense against the cross-reference leak class.

See docs/crimson-kitty/cross-ref-isolation.md and gates.md.
"""

from __future__ import annotations

from ..evidence.scanner import (
    scan_for_bare_slug,
    scan_for_keyword_ref,
    scan_for_short_ref,
    scan_for_url,
)
from . import CRIMSON_KITTY, Fail, GateResult, IssueRef, Pass, gate


@gate(pipeline=CRIMSON_KITTY, after="forked", kind="mechanical")
def input_context_clean(issue: IssueRef, evidence) -> GateResult:
    if not evidence.exists("02-forked/scrubbed_brief.md"):
        return Fail("02-forked/scrubbed_brief.md missing")

    brief = evidence.read_text("02-forked/scrubbed_brief.md")

    # An empty brief means the agent will have zero context about what to
    # fix. Fail early rather than letting it hallucinate.
    if not brief.strip():
        return Fail("scrubbed brief is empty - agent would have no context")

    upstream = issue.upstream_slug
    issue_num = issue.upstream_number

    leaks = []
    leaks += scan_for_url(brief, upstream)
    leaks += scan_for_short_ref(brief, upstream)
    leaks += scan_for_bare_slug(brief, upstream)
    leaks += scan_for_keyword_ref(brief, issue_num, upstream)

    if leaks:
        return Fail(
            f"scrubbed brief still contains {len(leaks)} upstream ref(s)",
            evidence_data={
                "leak_count": len(leaks),
                "leak_kinds": sorted({l.kind for l in leaks}),
                "leak_samples": [l.matched for l in leaks[:5]],
            },
        )
    return Pass()
