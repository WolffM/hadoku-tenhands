"""Two-layer upstream-ref sanitizer.

Replaces the jade-hare-era backend.services.oss_firewall._sanitize_upstream_refs
with a sanitizer that operates at both ends of the pipeline:

1. scrub_brief(brief, upstream_slug, issue_number) — input-side
   Strips real upstream URLs, slash-form short refs, bare upstream slugs,
   and identifying issue numbers from the aggregator brief BEFORE it is
   handed to the agent. Runs at the `eligible → forked` transition.
   Output: scrubbed brief text + scrub_report (list of substitutions).

2. scan_outputs(pr_title, pr_body, commit_messages,
                upstream_slug, issue_number) — output-side
   Scans the proposed upstream PR title, body, and every commit message for
   any surviving real upstream ref. Runs at the `submittable → submitted`
   transition. Raises SanitizerError on any leak — blocks the upstream PR
   open. Hallucinated refs (numbers/slugs that don't match the recorded
   upstream identity) are tolerated as cosmetic noise.

See docs/crimson-kitty/cross-ref-isolation.md for the full model.

Reuses:
    backend.services.oss_firewall._sanitize_upstream_refs (the regex set,
        broadened for the two-layer model)
    backend.temporal.evidence.scanner (the leak-detection primitives)

Not yet implemented. Stub for design review — Phase 1B.1.
"""


class SanitizerError(Exception):
    """Raised when scan_outputs finds any real upstream ref in outbound text."""
