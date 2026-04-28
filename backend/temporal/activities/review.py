"""Review activity — Phase 1C.7.

Runs a code review pass against the agent's PR. v1 wraps the existing
Copilot Review dispatcher logic via a constructor seam — the activity
itself just translates the dispatcher's output into the structured
comments + severity_summary evidence the orchestrator expects.

The activity does NOT decide pass/fail. The reviewed → remediated /
submittable transition is decided by counting blocker comments in the
result.
"""

from __future__ import annotations

from typing import Any


def _default_review_runner(fork_slug: str, pr_number: int) -> dict:
    """Hook into the existing CopilotReviewDispatcher.

    Returns a dict with `comments: list` matching the schema the
    `comments.json` evidence file uses.
    """
    from services.dispatchers import CopilotReviewDispatcher  # type: ignore

    dispatcher = CopilotReviewDispatcher()
    context = {"my_user": fork_slug.split("/")[0], "repo": fork_slug.split("/", 1)[1], "stage4_pr_number": pr_number}
    result = dispatcher.collect_results(str(pr_number), context)
    if not result.get("success"):
        return {"comments": [], "error": result.get("error", "")}
    outputs = result.get("outputs", {})
    return {"comments": outputs.get("comments") or []}


def run_review(
    fork_slug: str,
    pr_number: int,
    evidence,
    *,
    review_runner=None,
) -> dict:
    """Run a review pass and write comments + severity summary into evidence.

    Writes:
      - 07-reviewed/comments.json
      - 07-reviewed/severity_summary.json
    """
    if review_runner is None:
        review_runner = _default_review_runner

    result = review_runner(fork_slug, pr_number)
    comments = result.get("comments") or []
    if not isinstance(comments, list):
        comments = []

    # Normalize comment shape so downstream gates have a stable schema
    normalized = []
    for i, c in enumerate(comments):
        if not isinstance(c, dict):
            continue
        normalized.append({
            "id": str(c.get("id") or c.get("comment_id") or f"r{i}"),
            "path": c.get("path", ""),
            "line": c.get("line"),
            "severity": (c.get("severity") or "suggested").lower(),
            "body": c.get("body", ""),
        })

    evidence.write_json("07-reviewed/comments.json", normalized)

    summary = {"blocking": 0, "suggested": 0, "nit": 0}
    for c in normalized:
        sev = c["severity"]
        if sev not in summary:
            summary[sev] = 0
        summary[sev] += 1
    evidence.write_json("07-reviewed/severity_summary.json", summary)

    return {"ok": True, "comment_count": len(normalized), "summary": summary}


def read_review_summary(evidence) -> dict:
    """Read the severity counts produced by the most recent run_review.

    Phase 5.2 — the workflow uses this to decide whether to branch into
    `request_remediation` (when blocking > 0) or fall through to
    submission. Returns zeros if the file is missing rather than
    raising; a missing summary is treated as "no blockers" so the
    workflow doesn't abort just because run_review produced a
    degenerate result.
    """
    if not evidence.exists("07-reviewed/severity_summary.json"):
        return {"blocking": 0, "suggested": 0, "nit": 0}
    summary = evidence.read_json("07-reviewed/severity_summary.json")
    if not isinstance(summary, dict):
        return {"blocking": 0, "suggested": 0, "nit": 0}
    return {
        "blocking": int(summary.get("blocking", 0) or 0),
        "suggested": int(summary.get("suggested", 0) or 0),
        "nit": int(summary.get("nit", 0) or 0),
    }
